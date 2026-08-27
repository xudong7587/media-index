from __future__ import annotations

from dataclasses import replace
from collections.abc import Callable, Iterable

from app.clients.pansou import PansouClient
from app.clients.pansou import infer_share_provider
from app.clients.qas import QasClient
from app.core.config import get_settings
from app.domain.media import LinkResolution, MediaTarget, ResourceCandidate
from app.services.candidate_ranker import compact, rank_resource_candidates, resource_candidate_sort_key
from app.services.episode_matcher import build_rename_pair, match_episode_files
from app.services.query_planner import build_search_queries
from app.services.share_inspector import ShareInspection, inspect_share
from app.services.provider_compat import candidate_for_provider, provider_accepts_candidate, provider_accepts_share
from app.services.channel_monitor import search_channel_resources


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
    candidate_share_urls: Iterable[str] = (),
    validation_target: MediaTarget | None = None,
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
    existing_candidate_urls = tuple(
        dict.fromkeys(url for url in candidate_share_urls if url and url not in excluded_urls)
    )
    channel_items = search_channel_resources(target, limit=100)

    previous_urls = (previous_share_url,) if isinstance(previous_share_url, str) else tuple(previous_share_url)
    for previous_url in dict.fromkeys(url for url in previous_urls if url):
        if previous_url in excluded_urls:
            errors.append("previous_link_known_expired")
            continue
        _, previous_provider = infer_share_provider(previous_url)
        desired_provider = provider_filter or selected_provider
        if previous_provider and not provider_accepts_share(desired_provider, previous_url):
            errors.append(f"provider_not_executable:{previous_provider}")
            continue
        _progress(on_progress, "validating_link", "正在检查已有网盘链接")
        previous = _inspect_provider_share(qas_client, previous_url)
        previous = _select_inspection_files(previous, selected_names)
        resolution = _complete_resolution(
            target,
            previous,
            "previous_link",
            allow_review_confidence,
            validation_target=validation_target,
        )
        if resolution:
            return resolution
        errors.append(previous.error or "previous_link_missing_target_episodes")

    if existing_candidate_urls:
        best_candidate_resolution: LinkResolution | None = None
        best_candidate_coverage = 0
        reviewed_existing: list[ResourceCandidate] = []
        for candidate_url in existing_candidate_urls:
            _, candidate_provider = infer_share_provider(candidate_url)
            desired_provider = provider_filter or selected_provider
            if candidate_provider and not provider_accepts_share(desired_provider, candidate_url):
                errors.append(f"provider_not_executable:{candidate_provider}")
                continue
            _progress(on_progress, "matching_files", "正在检查已有候选链接中的剩余集数")
            inspection = _inspect_provider_share(qas_client, candidate_url)
            inspection = _select_inspection_files(inspection, selected_names)
            resolution = _complete_resolution(
                target,
                inspection,
                "existing_candidate",
                allow_review_confidence,
                validation_target=validation_target,
            )
            if resolution:
                covered = len({number for match in resolution.matches for number in match.episode_numbers})
                reviewed_existing.append(
                    ResourceCandidate(
                        candidate_url,
                        source="existing_candidate",
                        files=tuple(item.name for item in inspection.files),
                    )
                )
                if covered > best_candidate_coverage:
                    best_candidate_coverage = covered
                    best_candidate_resolution = resolution
                if covered >= len(target.episodes):
                    return replace(resolution, reviewed_candidates=tuple(reviewed_existing))
            errors.append(inspection.error or "existing_candidate_missing_target_episodes")
        if best_candidate_resolution:
            return replace(
                best_candidate_resolution,
                reviewed_candidates=tuple(reviewed_existing),
                errors=tuple(errors),
            )
        return LinkResolution(
            False,
            "no_resource",
            "已检查现有候选链接，仍没有找到剩余集数",
            reviewed_candidates=tuple(reviewed_existing),
            errors=tuple(errors),
        )

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
            [*response.items, *channel_items],
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
    viable = [candidate for candidate in ranked if not candidate.rejected]
    reviewed: list[ResourceCandidate] = []
    best_review: tuple[int, LinkResolution] | None = None
    valid_but_not_updated = False
    title_identity_requires_review = False
    external_provider_requires_confirmation = False
    verification_unavailable = False

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
        inspection = _select_inspection_files(inspection, selected_names)
        matches, ambiguities = _validated_episode_matches(target, inspection, validation_target)
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
            continue
        if (
            target.media_type == "tv"
            and not candidate_title_strong
            and not _matched_files_confirm_title(target, matches)
        ):
            title_identity_requires_review = True
            reviewed.append(
                replace(
                    enriched,
                    rejected=True,
                    reasons=(*enriched.reasons, "title_identity_missing"),
                )
            )
            continue
        reviewed.append(enriched)
        if matches and coverage >= 1 and all(match.confidence == "high" for match in matches) and (not sequence_based or candidate_title_strong):
            pairs = tuple(build_rename_pair(target, match) for match in matches)
            return LinkResolution(
                True,
                "ready",
                "已找到有效链接并完成明确集数匹配" if coverage < 1 else "已找到有效链接并完成全部目标集匹配",
                inspection.share_url,
                candidate.source or "pansou",
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
            candidate.source or "pansou",
            tuple(matches),
            tuple(build_rename_pair(target, match) for match in matches),
            tuple(reviewed),
            tuple(errors),
        )
        if best_review is None or file_score > best_review[0]:
            best_review = (file_score, review_resolution)

    if best_review:
        best_resolution = replace(best_review[1], reviewed_candidates=tuple(reviewed), errors=tuple(errors))
        # TV transfers can safely execute a high-confidence partial pack and
        # then inspect the other links already returned by this same search.
        # Do not do this for variety: its date/issue matching remains strict.
        if (
            target.media_type == "tv"
            and best_resolution.matches
            and all(match.confidence == "high" for match in best_resolution.matches)
        ):
            return replace(
                best_resolution,
                ok=True,
                stage="ready",
                message="已找到电视剧候选链接，先提交已匹配集数，再检查其他已返回链接",
            )
        return best_resolution
    if verification_unavailable:
        return LinkResolution(
            False,
            "needs_review",
            "全局资源源已找到 115 候选，但 115 接口暂时无法读取分享内容，请检查 Cookie、文件接口登录或网络连接后重试",
            reviewed_candidates=tuple(reviewed),
            errors=tuple(errors),
        )
    if external_provider_requires_confirmation:
        return LinkResolution(
            False,
            "needs_review",
            "已找到 115 候选资源，确认后将提交给 MoviePilot",
            reviewed_candidates=tuple(reviewed),
            errors=tuple(errors),
        )
    if title_identity_requires_review:
        return LinkResolution(
            False,
            "needs_review",
            "候选资源的集数可以匹配，但无法确认资源标题，请人工核对后再转存",
            reviewed_candidates=tuple(reviewed),
            errors=tuple(errors),
        )
    if valid_but_not_updated:
        return LinkResolution(
            False,
            "source_not_updated",
            "网盘已追到当前可用最新集，全局资源源尚未出现目标新集，当前无需转存；稍后将自动重试",
            reviewed_candidates=tuple(reviewed),
            errors=tuple(errors),
        )
    return LinkResolution(
        False,
        "no_resource",
        "旧链接不可用或未更新，PanSou 与 TG 频道源都没有找到可安全匹配的资源",
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


def _matched_files_confirm_title(target: MediaTarget, matches) -> bool:
    aliases = tuple(
        compact(title)
        for title in target.search_titles
        if compact(title) and not compact(title).isdigit()
    )
    if not aliases:
        return False
    return any(
        any(alias in compact(match.source.name) for alias in aliases)
        for match in matches
    )


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
    *,
    validation_target: MediaTarget | None = None,
) -> LinkResolution | None:
    if not inspection.valid:
        return None
    matches, ambiguities = _validated_episode_matches(target, inspection, validation_target)
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


def _validated_episode_matches(
    target: MediaTarget,
    inspection: ShareInspection,
    validation_target: MediaTarget | None,
):
    """Match with season context, then retain only the requested due episodes.

    Search planning and candidate ranking continue to use ``target``. The
    broader target is validation-only context for multi-day variety issues.
    """
    context = validation_target or target
    matches, ambiguities = match_episode_files(context, list(inspection.files))
    wanted = {episode.episode_number for episode in target.episodes}
    matches = [match for match in matches if wanted.intersection(match.episode_numbers)]
    ambiguities = [item for item in ambiguities if int(item.get("episode_number") or 0) in wanted]
    return matches, ambiguities
