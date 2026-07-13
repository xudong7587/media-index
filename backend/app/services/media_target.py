from __future__ import annotations

from app.clients.tmdb import TmdbClient
from app.domain.media import MediaTarget
from app.services.episode_tokens import build_episode_targets
from app.services.resource_aliases import merge_resource_aliases


def resolve_media_target(
    tmdb_id: int,
    media_type: str,
    season_number: int | None = None,
    client: TmdbClient | None = None,
) -> MediaTarget:
    tmdb = client or TmdbClient()
    detail = tmdb.details(media_type, tmdb_id)
    if detail.get("error"):
        raise RuntimeError(f"TMDB details failed: {detail['error']}")
    if not detail.get("title"):
        raise ValueError(f"TMDB media not found: {media_type}/{tmdb_id}")

    episodes = ()
    season_year = ""
    if media_type in {"tv", "variety"} and season_number is not None:
        season = tmdb.season(tmdb_id, season_number)
        if season.get("error"):
            raise RuntimeError(f"TMDB season failed: {season['error']}")
        raw_episodes = season.get("episodes") or []
        episodes = build_episode_targets(
            season_number,
            raw_episodes,
            exclude_derivatives=media_type == "variety",
            include_issue_tokens=media_type == "variety",
        )
        season_date = str(season.get("air_date") or "")
        if not season_date and episodes:
            season_date = next((ep.air_date for ep in episodes if ep.air_date), "")
        season_year = season_date[:4]

    return MediaTarget(
        tmdb_id=tmdb_id,
        media_type=media_type,
        title=str(detail.get("title") or "").strip(),
        original_title=str(detail.get("original_title") or "").strip(),
        aliases=merge_resource_aliases(tmdb_id, media_type, detail.get("aliases") or ()),
        series_year=str(detail.get("year") or ""),
        season_number=season_number,
        season_year=season_year,
        status=str(detail.get("status") or ""),
        poster_url=str(detail.get("poster_url") or ""),
        overview=str(detail.get("overview") or ""),
        release_date=str(detail.get("release_date") or ""),
        episodes=episodes,
    )
