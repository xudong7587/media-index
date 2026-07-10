from __future__ import annotations

from dataclasses import replace
from collections.abc import Iterable

from app.clients.pansou import PansouClient
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
) -> LinkResolution:
    if not target.episodes:
        return LinkResolution(False, "no_target_episodes", "TMDB 没有可匹配的目标集")
    qas_client = qas or QasClient()
    pansou_client = pansou or PansouClient()
    errors: list[str] = []
    timeout = search_timeout or get_settings().pansou_search_timeout_seconds

    previous_urls = (previous_share_url,) if isinstance(previous_share_url, str) else tuple(previous_share_url)
    for previous_url in dict.fromkeys(url for url in previous_urls if url):
        previous = inspect_share(qas_client, previous_url)
        resolution = _complete_resolution(target, previous, "previous_link", allow_review_confidence)
        if resolution:
            return resolution
        errors.append(previous.error or "previous_link_missing_target_episodes")

    merged: dict[str, ResourceCandidate] = {}
    for query in build_search_queries(target, max_queries=max_queries):
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
        for candidate in rank_resource_candidates(target, response.items, query.keyword):
            if not candidate.share_url:
                continue
            existing = merged.get(candidate.share_url)
            if existing is None or candidate.score > existing.score:
                merged[candidate.share_url] = candidate

    ranked = sorted(merged.values(), key=resource_candidate_sort_key)
    viable = [candidate for candidate in ranked if not candidate.rejected]
    reviewed: list[ResourceCandidate] = []
    best_review: tuple[int, LinkResolution] | None = None

    for candidate in viable[:max_verify]:
        inspection = inspect_share(qas_client, candidate.share_url)
        if not inspection.valid:
            errors.append(f"share_inspection:{inspection.error or 'invalid_share'}")
            reviewed.append(replace(candidate, rejected=True, reasons=(*candidate.reasons, inspection.error)))
            continue
        matches, ambiguities = match_episode_files(target, list(inspection.files))
        coverage = len(matches) / len(target.episodes)
        file_score = candidate.score + int(coverage * 60) - len(ambiguities) * 20
        enriched = replace(
            candidate,
            score=file_score,
            reasons=(*candidate.reasons, f"episode_coverage:{len(matches)}/{len(target.episodes)}"),
        )
        reviewed.append(enriched)
        if coverage == 1 and not ambiguities and all(match.confidence == "high" for match in matches):
            pairs = tuple(build_rename_pair(target, match) for match in matches)
            return LinkResolution(
                True,
                "ready",
                "已找到有效链接并完成全部目标集匹配",
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
    return LinkResolution(
        False,
        "no_resource",
        "旧链接不可用或未更新，PanSou 也没有找到可安全匹配的资源",
        reviewed_candidates=tuple(reviewed),
        errors=tuple(errors),
    )


def _complete_resolution(
    target: MediaTarget,
    inspection: ShareInspection,
    source: str,
    allow_review_confidence: bool = False,
) -> LinkResolution | None:
    if not inspection.valid:
        return None
    matches, ambiguities = match_episode_files(target, list(inspection.files))
    if len(matches) != len(target.episodes) or ambiguities:
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
    )
