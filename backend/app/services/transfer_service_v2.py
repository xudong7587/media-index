from __future__ import annotations

from dataclasses import asdict, replace
from datetime import date

from app.clients.pansou import PansouClient
from app.clients.qas import QasClient
from app.clients.tmdb import TmdbClient
from app.domain.media import MediaTarget
from app.services.link_resolver import resolve_episode_source
from app.services.media_target import resolve_media_target
from app.services.movie_resolver import resolve_movie_source
from app.services.paths import build_save_path
from app.services.qas_executor import execute_qas_plan


def execute_transfer_v2(
    tmdb_id: int,
    media_type: str,
    target_kind: str,
    season_number: int | None = None,
    *,
    tmdb: TmdbClient | None = None,
    pansou: PansouClient | None = None,
    qas: QasClient | None = None,
) -> dict:
    tmdb_client = tmdb or TmdbClient()
    qas_client = qas or QasClient()
    target = resolve_media_target(tmdb_id, media_type, season_number, tmdb_client)
    save_path = build_save_path(target_kind, media_type, target.title, target.series_year, season_number)

    if media_type == "movie":
        resolution = resolve_movie_source(target, qas=qas_client, pansou=pansou)
    else:
        target = replace(target, episodes=_aired_episodes(target))
        resolution = resolve_episode_source(target, qas=qas_client, pansou=pansou)

    if not resolution.ok:
        return {
            "ok": False,
            "stage": resolution.stage,
            "message": resolution.message,
            "save_path": save_path,
            "target": asdict(target),
            "resolution": asdict(resolution),
        }

    execution = execute_qas_plan(target, resolution, save_path, qas=qas_client)
    return {
        "ok": execution.ok,
        "stage": execution.stage,
        "message": execution.message,
        "save_path": save_path,
        "target": asdict(target),
        "resolution": asdict(resolution),
        "execution": asdict(execution),
    }


def _aired_episodes(target: MediaTarget):
    today = date.today().isoformat()
    return tuple(episode for episode in target.episodes if not episode.air_date or episode.air_date <= today)

