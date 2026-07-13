from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.services.link_resolver import resolve_episode_source
from app.services.media_target import resolve_media_target
from app.services.movie_resolver import resolve_movie_source
from app.services.episode_matcher import is_video
from app.services.cache import FileCache


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
    cache.set(cache_key, result)
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
    }
