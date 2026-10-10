from __future__ import annotations

import os
import re
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import replace

from app.clients.pansou import PansouClient, infer_share_provider
from app.clients.qas import QasClient
from app.core.config import get_settings
from app.domain.media import EpisodeMatch, LinkResolution, MediaTarget, RenamePair, ResourceCandidate, SourceFile
from app.services.candidate_ranker import DERIVATIVE_WORDS, compact, extract_seasons, rank_resource_candidates, resource_candidate_sort_key
from app.services.episode_matcher import is_source_video, match_episode_files, sanitize_filename_component
from app.services.episode_markers import bare_episode_number, named_part, parse_episode_markers
from app.services.query_planner import build_search_queries, has_usable_search_candidates
from app.services.share_inspector import ShareInspection, inspect_share
from app.services.provider_compat import candidate_for_provider, provider_accepts_candidate, provider_accepts_share


def resolve_standard_tv_source(
    target: MediaTarget,
    previous_share_urls: str | Iterable[str] = "",
    *,
    qas: QasClient | None = None,
    pansou: PansouClient | None = None,
    max_queries: int = 3,
    max_verify: int = 10,
    search_timeout: int | None = None,
    refresh: bool = False,
    preferred_source_names: Iterable[str] = (),
    on_progress: Callable[[str, str], None] | None = None,
    provider_filter: str | None = None,
) -> LinkResolution:
    qas_client = qas or QasClient()
    pansou_client = pansou or PansouClient()
    selected_provider = str(getattr(qas_client, "key", "qas"))
    timeout = search_timeout or get_settings().pansou_search_timeout_seconds
    errors: list[str] = []
    reviewed: list[ResourceCandidate] = []
    uncertain_resolution: LinkResolution | None = None
    selected_names = {name for name in preferred_source_names if name}
    previous_urls = (previous_share_urls,) if isinstance(previous_share_urls, str) else tuple(previous_share_urls)

    for share_url in dict.fromkeys(url for url in previous_urls if url):
        _, share_provider = infer_share_provider(share_url)
        desired_provider = provider_filter or selected_provider
        if share_provider and not provider_accepts_share(desired_provider, share_url):
            errors.append(f"provider_not_executable:{share_provider}")
            continue
        _progress(on_progress, "validating_link", "正在检查已有网盘链接")
        inspection = _inspect_provider_share(qas_client, share_url)
        resolution = _resolve_inspection(target, inspection, "pansou_first", reviewed, selected_names=selected_names)
        if resolution and resolution.ok:
            return replace(resolution, errors=tuple(errors))
        if resolution:
            uncertain_resolution = resolution
        errors.append(inspection.error or "standard_tv_files_not_found")

    merged: dict[tuple[str, str], ResourceCandidate] = {}
    queries = _search_queries(target, max_queries)
    for query in queries:
        _progress(on_progress, "searching_sources", f"正在搜索资源：{query.keyword}")
        response = pansou_client.search_detailed(
            query.keyword,
            limit=100,
            timeout=timeout,
            title_en=target.english_title,
            result_mode="all",
            refresh=refresh,
        )
        if response.error:
            errors.append(f"pansou:{query}:{response.error}")
        for candidate in rank_resource_candidates(target, response.items, query.keyword, query.priority):
            if not candidate.share_url:
                continue
            key = (candidate.cloud_type, candidate.share_url)
            if key not in merged or candidate.score > merged[key].score:
                merged[key] = candidate
        if has_usable_search_candidates(target, response.items, provider_filter or selected_provider):
            break

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
    external_provider_requires_confirmation = False
    verification_unavailable = False
    for candidate in [item for item in ranked if not item.rejected][:max_verify]:
        if candidate.provider != selected_provider:
            external_provider_requires_confirmation = True
            reviewed.append(replace(candidate, reasons=(*candidate.reasons, "external_organize_requires_confirmation")))
            continue
        _progress(on_progress, "matching_files", "正在按名称和季集标记核对电视剧文件")
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
        resolution = _resolve_inspection(target, inspection, candidate.source or "pansou", reviewed, candidate, selected_names=selected_names)
        if resolution and resolution.ok:
            return replace(resolution, errors=tuple(errors))
        if resolution:
            uncertain_resolution = resolution

    if uncertain_resolution:
        return replace(uncertain_resolution, reviewed_candidates=tuple(reviewed), errors=tuple(errors))
    if verification_unavailable:
        return LinkResolution(
            False,
            "needs_review",
            "已找到候选资源，但所选网盘暂时无法读取分享内容，请检查 Cookie、登录状态或网络后重试",
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
    return LinkResolution(False, "no_resource", "PanSou 没有找到可按名称和季集标记确认的电视剧资源", reviewed_candidates=tuple(reviewed), errors=tuple(errors))


def _resolve_inspection(
    target: MediaTarget,
    inspection: ShareInspection,
    source: str,
    reviewed: list[ResourceCandidate],
    candidate: ResourceCandidate | None = None,
    selected_names: set[str] | None = None,
) -> LinkResolution | None:
    if not inspection.valid:
        return None
    matches = _choose_tv_matches(
        target,
        list(inspection.files),
        candidate.title if candidate else "",
        selected_names or set(),
        trust_search_identity=candidate is not None and "title_exact_or_contained" in candidate.reasons,
    )
    if not matches:
        wanted = {item.episode_number for item in target.episodes}
        aliases = [compact(value) for value in target.search_titles if len(compact(value)) >= 2]
        uncertain = tuple(item.name for item in inspection.files
                          if is_source_video(item) and (not selected_names or item.name in selected_names)
                          and (named_part(item.name) or bare_episode_number(item.name) in wanted)
                          and not any(word in compact(item.name) for word in DERIVATIVE_WORDS)
                          and ((candidate is not None and "title_exact_or_contained" in candidate.reasons)
                               or any(alias in compact(f"{item.name} {item.path}") for alias in aliases)))
        if uncertain:
            enriched = replace(candidate or ResourceCandidate(inspection.share_url, source=source),
                               files=uncertain, reasons=(*(candidate.reasons if candidate else ()), "episode_identity_uncertain"))
            reviewed.append(enriched)
            return LinkResolution(False, "needs_review", "分享有效，但文件集数或上下篇无法与 TMDB 唯一对应，请确认", inspection.share_url,
                                  source, reviewed_candidates=tuple(reviewed))
        return None
    files = tuple(item.source for item in matches)
    pairs = tuple(_build_tv_rename_pair(target, item.source, item) for item in matches)
    enriched = replace(
        candidate or ResourceCandidate(inspection.share_url, source=source),
        share_url=inspection.share_url,
        source=source,
        files=tuple(item.name for item in files),
        reasons=(*(candidate.reasons if candidate else ()), "standard_tv_name_season_match"),
    )
    reviewed.append(enriched)
    return LinkResolution(True, "ready", "已按电视剧名称和季集标记完成重命名预演", inspection.share_url, source, rename_pairs=pairs, reviewed_candidates=tuple(reviewed))


def _choose_tv_matches(
    target: MediaTarget,
    files: list[SourceFile],
    source_title: str,
    selected_names: set[str],
    *,
    trust_search_identity: bool = False,
) -> tuple[EpisodeMatch, ...]:
    aliases = [compact(title) for title in target.search_titles if len(compact(title)) >= 2 and not compact(title).isdigit()]
    eligible = []
    for source in files:
        if not is_source_video(source) or (selected_names and source.name not in selected_names):
            continue
        raw = f"{source.name} {source.path} {source_title}"
        haystack = compact(raw)
        if not trust_search_identity and not any(alias in haystack for alias in aliases):
            continue
        if any(word in haystack for word in DERIVATIVE_WORDS):
            continue
        seasons = extract_seasons(raw.casefold()) | set(parse_episode_markers(raw).seasons)
        if seasons and seasons != {target.season_number}:
            continue
        parsed = parse_episode_markers(source.name, target.season_number)
        if parsed.invalid:
            continue
        # Later seasons need explicit season context for generic names.
        if target.season_number not in {0, 1} and not seasons:
            continue
        eligible.append(source)
    # Supply only a verified identity as context; never rewrite the source path
    # carried by a transfer plan.
    title_seasons = extract_seasons(source_title.casefold()) | set(parse_episode_markers(source_title).seasons)
    matches, _ = match_episode_files(target, eligible, trust_search_identity=True,
                                    search_season=target.season_number if title_seasons == {target.season_number} else None)
    return tuple(item for item in matches if item.confidence == "high")


def _choose_tv_files(target, files, source_title, selected_names, *, trust_search_identity=False):
    return tuple(item.source for item in _choose_tv_matches(
        target, files, source_title, selected_names, trust_search_identity=trust_search_identity))


def _build_tv_rename_pair(target: MediaTarget, source: SourceFile, match: EpisodeMatch | None = None) -> RenamePair:
    parsed = parse_episode_markers(source.name, target.season_number)
    numbers = match.episode_numbers if match else parsed.numbers
    episode_number = numbers[0] if numbers else 0
    extension = os.path.splitext(unicodedata.normalize("NFKC", source.name))[1].lower() or ".mp4"
    normalized = unicodedata.normalize("NFKC", os.path.splitext(source.name)[0])
    # Keep release/quality suffixes for explicit episode markers.
    suffix = normalized[parsed.end:].strip(" ._- ") if parsed.numbers else ""
    token = f"S{target.season_number or 0:02d}E{episode_number:02d}"
    if len(numbers) > 1:
        token += f"-E{numbers[-1]:02d}"
    title = sanitize_filename_component(target.title)
    year = sanitize_filename_component(target.series_year or target.season_year) if target.series_year or target.season_year else ""
    replacement = ".".join(part for part in (title, year, token, suffix) if part) + extension
    return RenamePair(
        source_name=source.name, pattern=f"^{re.escape(source.name)}$", replacement=replacement,
        episode_number=episode_number or None, confidence="high",
        reasons=(*(match.reasons if match else ()), "standard_tv_name_season_match"),
        source_id=source.provider_file_id, source_path=source.path, source_size=source.size,
        episode_numbers=numbers,
    )


def _search_queries(target: MediaTarget, max_queries: int):
    return build_search_queries(target, max_queries=max_queries)


def _inspect_provider_share(provider, share_url: str) -> ShareInspection:
    method = getattr(provider, "inspect_share", None)
    return method(share_url) if callable(method) else inspect_share(provider, share_url)


def _progress(callback: Callable[[str, str], None] | None, stage: str, message: str) -> None:
    if callback:
        callback(stage, message)
