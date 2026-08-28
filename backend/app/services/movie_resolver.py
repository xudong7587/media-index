from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import replace

from app.clients.pansou import PansouClient, infer_share_provider
from app.clients.qas import QasClient
from app.core.config import get_settings
from app.domain.media import LinkResolution, MediaTarget, ResourceCandidate
from app.services.candidate_ranker import rank_resource_candidates, resource_candidate_sort_key
from app.services.movie_matcher import build_movie_rename_pair, choose_movie_file, choose_movie_files
from app.services.query_planner import build_search_queries
from app.services.share_inspector import ShareInspection, inspect_share
from app.services.provider_compat import candidate_for_provider, provider_accepts_candidate, provider_accepts_share


def resolve_movie_source(
    target: MediaTarget,
    previous_share_urls: str | Iterable[str] = "",
    *,
    qas: QasClient | None = None,
    pansou: PansouClient | None = None,
    max_queries: int = 4,
    max_verify: int = 20,
    search_timeout: int | None = None,
    refresh: bool = False,
    preferred_source_names: Iterable[str] = (),
    on_progress: Callable[[str, str], None] | None = None,
    provider_filter: str | None = None,
) -> LinkResolution:
    qas_client = qas or QasClient()
    selected_provider = str(getattr(qas_client, "key", "qas"))
    pansou_client = pansou or PansouClient()
    errors: list[str] = []
    merged: dict[tuple[str, str], ResourceCandidate] = {}
    timeout = search_timeout or get_settings().pansou_search_timeout_seconds
    selected_names = {name for name in preferred_source_names if name}

    previous_urls = (previous_share_urls,) if isinstance(previous_share_urls, str) else tuple(previous_share_urls)
    for previous_url in dict.fromkeys(url for url in previous_urls if url):
        previous_cloud_type, previous_provider = infer_share_provider(previous_url)
        desired_provider = provider_filter or selected_provider
        if previous_provider and not provider_accepts_share(desired_provider, previous_url):
            errors.append(f"provider_not_executable:{previous_provider}")
            continue
        if on_progress:
            on_progress("validating_link", "正在检查已有网盘链接")
        inspection = _inspect_provider_share(qas_client, previous_url)
        if inspection.valid and selected_names:
            inspection = replace(inspection, files=tuple(source for source in inspection.files if source.name in selected_names))
        resolution = _movie_resolution_from_inspection(target, inspection, "user_candidate")
        if resolution:
            return resolution
        errors.append(inspection.error or "preferred_movie_candidate_ambiguous")
        if max_queries <= 0:
            candidate = ResourceCandidate(
                previous_url,
                source="user_candidate",
                rejected=not inspection.verification_unavailable,
                reasons=(
                    "provider_inspection_unavailable" if inspection.verification_unavailable else "selected_share_not_matched",
                    inspection.error or "preferred_movie_candidate_ambiguous",
                ),
                files=tuple(source.name for source in inspection.files),
                cloud_type=previous_cloud_type,
                provider=previous_provider,
            )
            if inspection.verification_unavailable:
                return LinkResolution(
                    False,
                    "provider_failed",
                    f"所选 {previous_cloud_type or '网盘'} 链接验证失败：{inspection.error or '暂时无法读取分享内容'}",
                    previous_url,
                    "user_candidate",
                    reviewed_candidates=(candidate,),
                    errors=tuple(errors),
                )
            return LinkResolution(
                False,
                "no_resource",
                "所选分享链接中没有找到可安全匹配的电影正片",
                previous_url,
                "user_candidate",
                reviewed_candidates=(candidate,),
                errors=tuple(errors),
            )

    for query in build_search_queries(target, max_queries=max_queries):
        if on_progress:
            on_progress("searching_sources", f"正在搜索资源：{query.keyword}")
        response = pansou_client.search_detailed(
            query.keyword,
            limit=50,
            timeout=timeout,
            title_en=target.original_title,
            result_mode="all",
            refresh=refresh,
        )
        if response.error:
            errors.append(f"pansou:{query.keyword}:{response.error}")
        for candidate in rank_resource_candidates(target, response.items, query.keyword, query.priority):
            if not candidate.share_url:
                continue
            candidate_key = (candidate.cloud_type, candidate.share_url)
            existing = merged.get(candidate_key)
            if existing is None or candidate.score > existing.score:
                merged[candidate_key] = candidate

    ranked = sorted(merged.values(), key=resource_candidate_sort_key)
    if provider_filter:
        ranked = [
            candidate_for_provider(provider_filter, candidate)
            for candidate in ranked
            if provider_accepts_candidate(provider_filter, candidate)
        ]
    else:
        ranked = [
            candidate_for_provider(selected_provider, candidate)
            if provider_accepts_candidate(selected_provider, candidate)
            else candidate
            for candidate in ranked
        ]
    reviewed: list[ResourceCandidate] = []
    external_provider_requires_confirmation = False
    verification_unavailable = False
    for candidate in [item for item in ranked if not item.rejected][:max_verify]:
        if candidate.provider != selected_provider:
            external_provider_requires_confirmation = True
            reviewed.append(
                replace(candidate, reasons=(*candidate.reasons, "external_organize_requires_confirmation"))
            )
            continue
        if on_progress:
            on_progress("matching_files", "正在读取文件并选择正片")
        inspection = _inspect_provider_share(qas_client, candidate.share_url)
        if not inspection.valid:
            if inspection.verification_unavailable:
                verification_unavailable = True
                reviewed.append(
                    replace(
                        candidate,
                        reasons=(*candidate.reasons, "provider_inspection_unavailable", inspection.error),
                    )
                )
                continue
            reviewed.append(replace(candidate, rejected=True, reasons=(*candidate.reasons, inspection.error)))
            continue
        if selected_names:
            inspection = replace(inspection, files=tuple(source for source in inspection.files if source.name in selected_names))
        source, file_score, reasons, ambiguous = choose_movie_file(target, list(inspection.files), candidate.title)
        enriched = replace(
            candidate,
            score=candidate.score + file_score,
            reasons=(*candidate.reasons, *reasons),
            files=tuple(item.name for item in inspection.files),
        )
        # PanSou's listing title is untrusted metadata. It can be copied from
        # a search query while the share actually contains another movie, so
        # only the inspected filename may establish the movie identity.
        strong_file_title = any(
            reason in {
                "title",
                "title_fuzzy",
                "path_title",
                "path_title_fuzzy",
                "source_title_context",
            }
            for reason in reasons
        )
        likely_feature = source is not None and (
            source.size <= 0 or "feature_length_size" in reasons
        )
        # Generic daily collections remain searchable, but unrelated files must never become review cards.
        if not source or not strong_file_title or not likely_feature:
            continue
        reviewed.append(enriched)
        high_confidence_candidate = candidate.score >= 80 and strong_file_title
        if source and (not ambiguous or high_confidence_candidate) and file_score >= 35 and strong_file_title:
            selected_files, _, _ = choose_movie_files(target, list(inspection.files), candidate.title)
            pairs = tuple(
                build_movie_rename_pair(
                    target,
                    item,
                    reasons,
                    index if len(selected_files) > 1 else None,
                )
                for index, item in enumerate(selected_files, start=1)
            )
            return LinkResolution(
                True,
                "ready",
                "已找到有效电影文件并完成重命名预演",
                inspection.share_url,
                candidate.source or "pansou",
                rename_pairs=pairs,
                reviewed_candidates=tuple(reviewed),
                errors=tuple(errors),
            )

    if any(not candidate.rejected for candidate in reviewed):
        return LinkResolution(
            False,
            "needs_review",
            "全局资源源已找到 115 候选，但 115 接口暂时无法读取分享内容，请检查 Cookie、文件接口登录或网络连接后重试"
            if verification_unavailable
            else "已找到 115 候选资源，确认后将提交给 MoviePilot"
            if external_provider_requires_confirmation and all(candidate.provider != "qas" for candidate in reviewed)
            else "候选链接有效，但电影主文件选择存在歧义",
            reviewed_candidates=tuple(reviewed),
            errors=tuple(errors),
        )
    return LinkResolution(
        False,
        "no_resource",
        "PanSou 没有找到可安全匹配的电影资源",
        errors=tuple(errors),
    )


def _inspect_provider_share(provider, share_url: str) -> ShareInspection:
    method = getattr(provider, "inspect_share", None)
    return method(share_url) if callable(method) else inspect_share(provider, share_url)


def _movie_resolution_from_inspection(target: MediaTarget, inspection, source_name: str) -> LinkResolution | None:
    if not inspection.valid:
        return None
    source, file_score, reasons, ambiguous = choose_movie_file(target, list(inspection.files), "")
    if not source or ambiguous or file_score < 35:
        return None
    return LinkResolution(
        True,
        "ready",
        "用户选择的电影资源已重新验证并完成重命名预演",
        inspection.share_url,
        source_name,
        rename_pairs=(build_movie_rename_pair(target, source, reasons),),
    )
