from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable
from dataclasses import replace

from app.clients.pansou import PansouClient, infer_share_provider
from app.clients.qas import QasClient
from app.core.config import get_settings
from app.domain.media import LinkResolution, MediaTarget, RenamePair, ResourceCandidate, SourceFile
from app.services.candidate_ranker import DERIVATIVE_WORDS, compact, rank_resource_candidates, resource_candidate_sort_key
from app.services.episode_matcher import is_source_video, quality_score, sanitize_filename_component
from app.services.share_inspector import ShareInspection, inspect_share


_SEASON_EPISODE = re.compile(r"(?i)(?<![a-z0-9])s(\d{1,2})[ ._-]*e(?:p|x)?(\d{1,4})(?!\d)")
_EPISODE = re.compile(r"(?i)(?<![a-z0-9])e(?:p|x)?(\d{1,4})(?!\d)")
_YEAR = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")


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
    selected_names = {name for name in preferred_source_names if name}
    previous_urls = (previous_share_urls,) if isinstance(previous_share_urls, str) else tuple(previous_share_urls)

    for share_url in dict.fromkeys(url for url in previous_urls if url):
        _, share_provider = infer_share_provider(share_url)
        desired_provider = provider_filter or selected_provider
        if share_provider and share_provider != desired_provider:
            errors.append(f"provider_not_executable:{share_provider}")
            continue
        _progress(on_progress, "validating_link", "正在检查已有网盘链接")
        inspection = _inspect_provider_share(qas_client, share_url)
        resolution = _resolve_inspection(target, inspection, "pansou_first", reviewed, selected_names=selected_names)
        if resolution:
            return replace(resolution, errors=tuple(errors))
        errors.append(inspection.error or "standard_tv_files_not_found")

    merged: dict[tuple[str, str], ResourceCandidate] = {}
    queries = _search_queries(target, max_queries)
    for query in queries:
        _progress(on_progress, "searching_sources", f"正在搜索资源：{query}")
        response = pansou_client.search_detailed(
            query,
            limit=100,
            timeout=timeout,
            title_en=target.original_title,
            result_mode="all",
            refresh=refresh,
        )
        if response.error:
            errors.append(f"pansou:{query}:{response.error}")
        for candidate in rank_resource_candidates(target, response.items, query, 90):
            if not candidate.share_url:
                continue
            key = (candidate.cloud_type, candidate.share_url)
            if key not in merged or candidate.score > merged[key].score:
                merged[key] = candidate

    ranked = sorted(merged.values(), key=resource_candidate_sort_key)
    if provider_filter:
        ranked = [candidate for candidate in ranked if candidate.provider == provider_filter]
    external_provider_requires_confirmation = False
    for candidate in [item for item in ranked if not item.rejected][:max_verify]:
        if candidate.provider != selected_provider:
            external_provider_requires_confirmation = True
            reviewed.append(replace(candidate, reasons=(*candidate.reasons, "external_organize_requires_confirmation")))
            continue
        _progress(on_progress, "matching_files", "正在按名称、年份和季集标记核对电视剧文件")
        inspection = _inspect_provider_share(qas_client, candidate.share_url)
        if not inspection.valid:
            reviewed.append(replace(candidate, rejected=True, reasons=(*candidate.reasons, inspection.error)))
            continue
        resolution = _resolve_inspection(target, inspection, "pansou", reviewed, candidate, selected_names=selected_names)
        if resolution:
            return replace(resolution, errors=tuple(errors))

    if external_provider_requires_confirmation:
        return LinkResolution(
            False,
            "needs_review",
            "已找到 115 候选资源，确认后将提交给 MoviePilot",
            reviewed_candidates=tuple(reviewed),
            errors=tuple(errors),
        )
    return LinkResolution(False, "no_resource", "没有找到可按名称、年份和季集标记确认的电视剧资源", reviewed_candidates=tuple(reviewed), errors=tuple(errors))


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
    files = _choose_tv_files(target, list(inspection.files), candidate.title if candidate else "", selected_names or set())
    if not files:
        return None
    pairs = tuple(_build_tv_rename_pair(target, item) for item in files)
    enriched = replace(
        candidate or ResourceCandidate(inspection.share_url, source=source),
        share_url=inspection.share_url,
        source=source,
        files=tuple(item.name for item in files),
        reasons=(*(candidate.reasons if candidate else ()), "standard_tv_name_year_match"),
    )
    reviewed.append(enriched)
    return LinkResolution(True, "ready", "已按电视剧名称、年份和季集标记完成重命名预演", inspection.share_url, source, rename_pairs=pairs, reviewed_candidates=tuple(reviewed))


def _choose_tv_files(target: MediaTarget, files: list[SourceFile], source_title: str, selected_names: set[str]) -> tuple[SourceFile, ...]:
    aliases = [compact(title) for title in target.search_titles if len(compact(title)) >= 2 and not compact(title).isdigit()]
    accepted_years = {year for year in (target.series_year, target.season_year) if year}
    selected: dict[str, SourceFile] = {}
    for source in files:
        if not is_source_video(source):
            continue
        if selected_names and source.name not in selected_names:
            continue
        raw = f"{source.name} {source_title}"
        haystack = compact(raw)
        if not any(alias in haystack for alias in aliases):
            continue
        found_years = set(_YEAR.findall(raw))
        if accepted_years and found_years and not found_years.intersection(accepted_years):
            continue
        season_match = _SEASON_EPISODE.search(source.name)
        if target.season_number and season_match and int(season_match.group(1)) != target.season_number:
            continue
        episode_match = season_match or _EPISODE.search(source.name)
        if target.season_number and not episode_match:
            continue
        if any(word in haystack for word in DERIVATIVE_WORDS):
            continue
        identity = _episode_identity(source.name) or source.name.casefold()
        current = selected.get(identity)
        if current is None or quality_score(source) > quality_score(current):
            selected[identity] = source
    return tuple(sorted(selected.values(), key=lambda item: item.name.casefold()))


def _build_tv_rename_pair(target: MediaTarget, source: SourceFile) -> RenamePair:
    extension = os.path.splitext(source.name)[1].lower() or ".mp4"
    stem = os.path.splitext(source.name)[0]
    match = _SEASON_EPISODE.search(stem)
    episode_number = 0
    if match:
        episode_token = f"S{int(match.group(1)):02d}E{int(match.group(2)):02d}"
        episode_number = int(match.group(2))
        suffix = stem[match.end() :].strip(" ._- ")
        suffix = f".{suffix}" if suffix else ""
        normalized_stem = f"{episode_token}{suffix}"
    else:
        match = _EPISODE.search(stem)
        episode_token = f"E{int(match.group(1)):02d}" if match else ""
        episode_number = int(match.group(1)) if match else 0
        suffix = stem[match.end() :].strip(" ._- ") if match else ""
        normalized_stem = f"{episode_token}{f'.{suffix}' if suffix else ''}"
    title = sanitize_filename_component(target.title)
    year = sanitize_filename_component(target.series_year or target.season_year)
    replacement = ".".join(part for part in (title, year, normalized_stem) if part) + extension
    return RenamePair(
        source_name=source.name,
        pattern=f"^{re.escape(source.name)}$",
        replacement=replacement,
        episode_number=episode_number or None,
        confidence="high",
        reasons=("title", "year", "season_episode_marker", "standard_tv_name_year_match"),
        source_id=source.provider_file_id,
        source_path=source.path,
        source_size=source.size,
        episode_numbers=(episode_number,) if episode_number else (),
    )


def _episode_identity(name: str) -> str:
    match = _SEASON_EPISODE.search(name)
    if match:
        return f"s{int(match.group(1)):02d}e{int(match.group(2)):04d}"
    match = _EPISODE.search(name)
    return f"e{int(match.group(1)):04d}" if match else ""


def _search_queries(target: MediaTarget, max_queries: int) -> tuple[str, ...]:
    values = []
    if target.title and target.series_year:
        values.append(f"{target.title} {target.series_year}")
    if target.title:
        values.append(target.title)
    if target.original_title:
        values.append(target.original_title)
    return tuple(dict.fromkeys(values))[:max_queries]


def _inspect_provider_share(provider, share_url: str) -> ShareInspection:
    method = getattr(provider, "inspect_share", None)
    return method(share_url) if callable(method) else inspect_share(provider, share_url)


def _progress(callback: Callable[[str, str], None] | None, stage: str, message: str) -> None:
    if callback:
        callback(stage, message)
