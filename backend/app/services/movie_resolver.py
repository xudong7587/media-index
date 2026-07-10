from __future__ import annotations

from dataclasses import replace

from app.clients.pansou import PansouClient
from app.clients.qas import QasClient
from app.domain.media import LinkResolution, MediaTarget, ResourceCandidate
from app.services.candidate_ranker import rank_resource_candidates
from app.services.movie_matcher import build_movie_rename_pair, choose_movie_file
from app.services.query_planner import build_search_queries
from app.services.share_inspector import inspect_share


def resolve_movie_source(
    target: MediaTarget,
    *,
    qas: QasClient | None = None,
    pansou: PansouClient | None = None,
    max_queries: int = 4,
    max_verify: int = 5,
) -> LinkResolution:
    qas_client = qas or QasClient()
    pansou_client = pansou or PansouClient()
    errors: list[str] = []
    merged: dict[str, ResourceCandidate] = {}

    for query in build_search_queries(target, max_queries=max_queries):
        response = pansou_client.search_detailed(
            query.keyword,
            limit=50,
            timeout=12,
            title_en=target.original_title,
            result_mode="all",
        )
        if response.error:
            errors.append(f"pansou:{query.keyword}:{response.error}")
        for candidate in rank_resource_candidates(target, response.items, query.keyword):
            if not candidate.share_url:
                continue
            existing = merged.get(candidate.share_url)
            if existing is None or candidate.score > existing.score:
                merged[candidate.share_url] = candidate

    ranked = sorted(merged.values(), key=lambda item: (item.rejected, -item.score))
    reviewed: list[ResourceCandidate] = []
    for candidate in [item for item in ranked if not item.rejected][:max_verify]:
        inspection = inspect_share(qas_client, candidate.share_url)
        if not inspection.valid:
            reviewed.append(replace(candidate, rejected=True, reasons=(*candidate.reasons, inspection.error)))
            continue
        source, file_score, reasons, ambiguous = choose_movie_file(target, list(inspection.files), candidate.title)
        enriched = replace(candidate, score=candidate.score + file_score, reasons=(*candidate.reasons, *reasons))
        reviewed.append(enriched)
        if source and not ambiguous and file_score >= 35:
            return LinkResolution(
                True,
                "ready",
                "已找到有效电影文件并完成重命名预演",
                inspection.share_url,
                "pansou",
                rename_pairs=(build_movie_rename_pair(target, source, reasons),),
                reviewed_candidates=tuple(reviewed),
                errors=tuple(errors),
            )

    if reviewed:
        return LinkResolution(
            False,
            "needs_review",
            "候选链接有效，但电影主文件选择存在歧义",
            reviewed_candidates=tuple(reviewed),
            errors=tuple(errors),
        )
    return LinkResolution(
        False,
        "no_resource",
        "PanSou 没有找到可安全匹配的电影资源",
        errors=tuple(errors),
    )

