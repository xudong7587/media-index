from __future__ import annotations

from dataclasses import replace
from collections.abc import Callable, Iterable

from app.clients.pansou import PansouClient
from app.clients.pansou import infer_share_provider
from app.clients.qas import QasClient
from app.core.config import get_settings
from app.domain.media import LinkResolution, MediaTarget, ResourceCandidate
from app.services.candidate_ranker import rank_resource_candidates, resource_candidate_sort_key
from app.services.episode_matcher import build_rename_pair, match_episode_files
from app.services.query_planner import build_search_queries
from app.services.share_inspector import ShareInspection, inspect_share


def resolve_episode_source(
    target: MediaTarget,
    previous_share_url: str | Iterable[str] = "",
    *,
    qas: QasClient | None = None,
    pansou: PansouClient | None = None,
    max_queries: int = 4,
    max_verify: int = 20,
    search_timeout: int | None = None,
    refresh: bool = False,
    allow_review_confidence: bool = False,
    preferred_source_names: Iterable[str] = (),
    on_progress: Callable[[str, str], None] | None = None,
    provider_filter: str | None = None,
    excluded_share_urls: Iterable[str] = (),
) -> LinkResolution:
    if not target.episodes:
        return LinkResolution(False, "no_target_episodes", "TMDB 没有可匹配的目标集")
    qas_client = qas or QasClient()
    selected_provider = str(getattr(qas_client, "key", "qas"))
    pansou_client = pansou or PansouClient()
    errors: list[str] = []
    timeout = search_timeout or get_settings().pansou_search_timeout_seconds
    selected_names = {name for name in preferred_source_names if name}
    excluded_urls = {url for url in excluded_share_urls if url}

    previous_urls = (previous_share_url,) if isinstance(previous_share_url, str) else tuple(previous_share_url)
    for previous_url in dict.fromkeys(url for url in previous_urls if url):
        if previous_url in excluded_urls:
            errors.append("previous_link_known_expired")
            continue
        _, previous_provider = infer_share_provider(previous_url)
        desired_provider = provider_filter or selected_provider
        if previous_provider and previous_provider != desired_provider:
            errors.append(f"provider_not_executable:{previous_provider}")
            continue
        _progress(on_progress, "validating_link", "正在检查已有网盘链接")
        previous = _inspect_provider_share(qas_client, previous_url)
        previous = _select_inspection_files(previous, selected_names)
        resolution = _complete_resolution(target, previous, "previous_link", allow_review_confidence)
        if resolution:
            return resolution
        errors.append(previous.error or "previous_link_missing_target_episodes")

    merged: dict[tuple[str, str], ResourceCandidate] = {}
    for query in build_search_queries(target, max_queries=max_queries):
        _progress(on_progress, "searching_sources", f"正在搜索资源：{query.keyword}")
        response = pansou_client.search_detailed(
            query.keyword,
            limit=100,
            timeout=timeout,
            title_en=target.original_title,
            result_mode="all",
            refresh=refresh,
        )
        if response.error:
            errors.append(f"pansou:{query.keyword}:{response.error}")
        for candidate in rank_resource_candidates(
            target,
            response.items,
            query.keyword,
            query.priority,
        ):
            if not candidate.share_url:
                continue
            if candidate.share_url in excluded_urls:
                continue
            candidate_key = (candidate.cloud_type, candidate.share_url)
            existing = merged.get(candidate_key)
            if existing is None or candidate.score > existing.score:
                merged[candidate_key] = candidate

    ranked = sorted(merged.values(), key=resource_candidate_sort_key)
    if provider_filter:
        ranked = [candidate for candidate in ranked if candidate.provider == provider_filter]
    viable = [candidate for candidate in ranked if not candidate.rejected]
    reviewed: list[ResourceCandidate] = []
    best_review: tuple[int, LinkResolution] | None = None
    valid_but_not_updated = False
    external_provider_requires_confirmation = False

    for candidate in viable[:max_verify]:
        if candidate.provider != selected_provider:
            external_provider_requires_confirmation = True
            reviewed.append(
                replace(candidate, reasons=(*candidate.reasons, "external_organize_requires_confirmation"))
            )
            continue
        _progress(on_progress, "matching_files", "正在读取文件并匹配 TMDB 集数")
        inspection = _inspect_provider_share(qas_client, candidate.share_url)
        if not inspection.valid:
            errors.append(f"share_inspection:{inspection.error or 'invalid_share'}")
            reviewed.append(replace(candidate, rejected=True, reasons=(*candidate.reasons, inspection.error)))
            continue
        inspection = _select_inspection_files(inspection, selected_names)
        matches, ambiguities = match_episode_files(target, list(inspection.files))
        covered_numbers = {number for match in matches for number in match.episode_numbers}
        coverage = len(covered_numbers) / len(target.episodes)
        file_score = candidate.score + int(coverage * 60) - len(ambiguities) * 20
        enriched = replace(
            candidate,
            score=file_score,
            reasons=(*candidate.reasons, f"episode_coverage:{len(covered_numbers)}/{len(target.episodes)}"),
            files=tuple(source.name for source in inspection.files),
        )
        # A valid share containing only older episodes is not ambiguous. For
        # example, E01-E06 cannot help a user who already has E06 and is
        # waiting for E07, so it must not become a review candidate.
        if not matches and not ambiguities:
            valid_but_not_updated = True
            reviewed.append(
                replace(
                    enriched,
                    rejected=True,
                    reasons=(*enriched.reasons, "no_target_episode_files"),
                )
            )
            continue
        sequence_based = any("numeric_episode_sequence" in match.reasons for match in matches)
        candidate_title_strong = "title_exact_or_contained" in candidate.reasons
        if sequence_based and not candidate_title_strong:
            reviewed.append(
                replace(
                    enriched,
                    rejected=True,
                    reasons=(*enriched.reasons, "unsafe_numeric_sequence_with_weak_title"),
                )
            )
            continue
        reviewed.append(enriched)
        if matches and all(match.confidence == "high" for match in matches) and (not sequence_based or candidate_title_strong):
            pairs = tuple(build_rename_pair(target, match) for match in matches)
            return LinkResolution(
                True,
                "ready",
                "已找到有效链接并完成明确集数匹配" if coverage < 1 else "已找到有效链接并完成全部目标集匹配",
                inspection.share_url,
                "pansou",
                tuple(matches),
                pairs,
                tuple(reviewed),
                tuple(errors),
            )
        review_resolution = LinkResolution(
            False,
            "needs_review",
            "候选链接有效，但集数匹配不完整或存在歧义",
            inspection.share_url,
            "pansou",
            tuple(matches),
            tuple(build_rename_pair(target, match) for match in matches),
            tuple(reviewed),
            tuple(errors),
        )
        if best_review is None or file_score > best_review[0]:
            best_review = (file_score, review_resolution)

    if best_review:
        return replace(best_review[1], reviewed_candidates=tuple(reviewed), errors=tuple(errors))
    if external_provider_requires_confirmation:
        return LinkResolution(
            False,
            "needs_review",
            "已找到 115 候选资源，确认后将提交给 MoviePilot",
            reviewed_candidates=tuple(reviewed),
            errors=tuple(errors),
        )
    if valid_but_not_updated:
        return LinkResolution(
            False,
            "source_not_updated",
            "网盘已追到当前可用最新集，PanSou 搜索结果尚未出现目标新集，当前无需转存；稍后将自动重试",
            reviewed_candidates=tuple(reviewed),
            errors=tuple(errors),
        )
    return LinkResolution(
        False,
        "no_resource",
        "旧链接不可用或未更新，PanSou 也没有找到可安全匹配的资源",
        reviewed_candidates=tuple(reviewed),
        errors=tuple(errors),
    )


def _select_inspection_files(inspection: ShareInspection, selected_names: set[str]) -> ShareInspection:
    if not inspection.valid or not selected_names:
        return inspection
    files = tuple(source for source in inspection.files if source.name in selected_names)
    if not files:
        return ShareInspection(False, inspection.share_url, error="selected_files_not_found")
    return replace(inspection, files=files)


def _progress(callback: Callable[[str, str], None] | None, stage: str, message: str) -> None:
    if callback:
        callback(stage, message)


def _inspect_provider_share(provider, share_url: str) -> ShareInspection:
    method = getattr(provider, "inspect_share", None)
    return method(share_url) if callable(method) else inspect_share(provider, share_url)


def _complete_resolution(
    target: MediaTarget,
    inspection: ShareInspection,
    source: str,
    allow_review_confidence: bool = False,
) -> LinkResolution | None:
    if not inspection.valid:
        return None
    matches, ambiguities = match_episode_files(target, list(inspection.files))
    covered_numbers = {number for match in matches for number in match.episode_numbers}
    if not covered_numbers:
        return None
    if not allow_review_confidence and not all(match.confidence == "high" for match in matches):
        return None
    if allow_review_confidence and any(match.confidence == "low" for match in matches):
        return None
    return LinkResolution(
        True,
        "ready",
        "用户确认的分享链接已完成一对一重命名预演" if allow_review_confidence else "上一次分享链接仍有效且已包含全部目标集",
        inspection.share_url,
        source,
        tuple(matches),
        tuple(build_rename_pair(target, match) for match in matches),
        (
            ResourceCandidate(
                inspection.share_url,
                source=source,
                files=tuple(item.name for item in inspection.files),
            ),
        ),
    )
