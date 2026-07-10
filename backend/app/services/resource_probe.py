from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.services.link_resolver import resolve_episode_source
from app.services.media_target import resolve_media_target
from app.services.movie_resolver import resolve_movie_source


def probe_resource_availability(tmdb_id: int, media_type: str, season_number: int | None = None) -> dict:
    target = resolve_media_target(tmdb_id, media_type, season_number)
    if media_type == "movie":
        resolution = resolve_movie_source(target, max_queries=3, max_verify=8)
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
        resolution = resolve_episode_source(replace(target, episodes=(latest,)), max_queries=3, max_verify=8)
    return {
        "ok": True,
        "found": resolution.ok,
        "message": resolution.message,
        "title": target.title,
        "share_url": resolution.share_url if resolution.ok else "",
        "file_count": len(resolution.matches) if resolution.ok else 0,
        "stage": resolution.stage,
        "candidate_count": len(resolution.reviewed_candidates),
    }
