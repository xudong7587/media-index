from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.clients.qas import QasClient
from app.services.link_resolver import resolve_episode_source
from app.services.media_target import resolve_media_target
from app.services.movie_resolver import resolve_movie_source
from app.services.episode_matcher import is_video, match_episode_files
from app.services.cache import FileCache
from app.services.share_inspector import find_season_share_folders, inspect_share


def get_cached_resource_availability(tmdb_id: int, media_type: str, season_number: int | None = None) -> dict | None:
    cached = FileCache("resource-probe").get(
        f"{media_type}:{tmdb_id}:{season_number or 0}",
        get_settings().resource_probe_cache_ttl_seconds,
    )
    return {**cached, "cached": True} if isinstance(cached, dict) else None


def probe_resource_availability(
    tmdb_id: int,
    media_type: str,
    season_number: int | None = None,
    *,
    refresh: bool = False,
) -> dict:
    cache = FileCache("resource-probe")
    cache_key = f"{media_type}:{tmdb_id}:{season_number or 0}"
    if not refresh:
        cached = cache.get(cache_key, get_settings().resource_probe_cache_ttl_seconds)
        if isinstance(cached, dict):
            return {**cached, "cached": True}

    result = _probe_resource_availability(tmdb_id, media_type, season_number)
    root_share_url = str(result.pop("root_share_url", ""))
    # A slower probe may finish after another request has already cached a
    # verified source.  Never let that stale negative result erase the newer
    # positive result (opening a dialog used to trigger exactly this race).
    concurrent = cache.get(cache_key, get_settings().resource_probe_cache_ttl_seconds)
    if not refresh and not result.get("found") and isinstance(concurrent, dict) and concurrent.get("found"):
        result = concurrent
    else:
        cache.set(cache_key, result)
    if media_type == "tv" and result.get("found") and root_share_url:
        _cache_related_season_folders(cache, tmdb_id, root_share_url)
    return {**result, "cached": False}


def _probe_resource_availability(tmdb_id: int, media_type: str, season_number: int | None = None) -> dict:
    target = resolve_media_target(tmdb_id, media_type, season_number)
    if media_type == "movie":
        resolution = resolve_movie_source(target, max_queries=4, max_verify=10, refresh=True)
    else:
        today = datetime.now(ZoneInfo(get_settings().tracking_timezone)).date().isoformat()
        aired = [episode for episode in target.episodes if not episode.air_date or episode.air_date <= today]
        if not aired:
            return {
                "ok": True,
                "found": False,
                "message": "TMDB 标记的首集尚未播出",
                "next_air_date": min((episode.air_date for episode in target.episodes if episode.air_date), default=""),
            }
        latest = max(aired, key=lambda episode: episode.episode_number)
        resolution = resolve_episode_source(replace(target, episodes=(latest,)), max_queries=4, max_verify=10, refresh=True)
    viable_candidate = any(
        not candidate.rejected and any(is_video(name) for name in candidate.files)
        for candidate in resolution.reviewed_candidates
    )
    found = resolution.ok or viable_candidate
    root_share_url = next(
        (
            candidate.share_url
            for candidate in reversed(resolution.reviewed_candidates)
            if not candidate.rejected and candidate.share_url
        ),
        "",
    )
    return {
        "ok": True,
        "found": found,
        "ready": resolution.ok,
        "requires_review": found and not resolution.ok,
        "message": resolution.message,
        "title": target.title,
        "share_url": resolution.share_url if resolution.ok else "",
        "file_count": len(resolution.matches or resolution.rename_pairs) if resolution.ok else 0,
        "stage": resolution.stage,
        "candidate_count": len(resolution.reviewed_candidates),
        "root_share_url": root_share_url,
    }


def _cache_related_season_folders(cache: FileCache, tmdb_id: int, root_share_url: str) -> None:
    qas = QasClient()
    for folder in find_season_share_folders(qas, root_share_url):
        try:
            target = resolve_media_target(tmdb_id, "tv", folder.season_number)
            inspection = inspect_share(qas, folder.share_url)
            if not inspection.valid:
                continue
            today = datetime.now(ZoneInfo(get_settings().tracking_timezone)).date().isoformat()
            aired = [episode for episode in target.episodes if not episode.air_date or episode.air_date <= today]
            if not aired:
                continue
            matches, ambiguities = match_episode_files(target, list(inspection.files))
            covered = {number for match in matches for number in match.episode_numbers}
            latest = max(aired, key=lambda episode: episode.episode_number)
            if latest.episode_number not in covered or ambiguities or any(match.confidence != "high" for match in matches):
                continue
            cache.set(
                f"tv:{tmdb_id}:{folder.season_number}",
                {
                    "ok": True,
                    "found": True,
                    "ready": True,
                    "requires_review": False,
                    "message": f"已从同一分享链接验证 {folder.name}",
                    "title": target.title,
                    "share_url": inspection.share_url,
                    "file_count": len(matches),
                    "stage": "multi_season_folder",
                    "candidate_count": 1,
                },
            )
        except Exception:
            continue
