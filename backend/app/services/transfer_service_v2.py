from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime
from zoneinfo import ZoneInfo
from collections.abc import Iterable
from collections.abc import Callable

from app.clients.pansou import PansouClient
from app.clients.qas import QasClient
from app.clients.tmdb import TmdbClient
from app.core.config import get_settings
from app.domain.media import MediaTarget
from app.services.link_resolver import resolve_episode_source
from app.services.media_target import resolve_media_target
from app.services.movie_resolver import resolve_movie_source
from app.services.paths import build_save_path
from app.services.qas_executor import execute_qas_plan
from app.services.saved_episode_scanner import resolve_save_path_progress


def execute_transfer_v2(
    tmdb_id: int,
    media_type: str,
    target_kind: str,
    season_number: int | None = None,
    preferred_share_urls: str | Iterable[str] = "",
    refresh: bool = False,
    user_confirmed: bool = False,
    preferred_source_names: Iterable[str] = (),
    on_progress: Callable[[str, str], None] | None = None,
    *,
    tmdb: TmdbClient | None = None,
    pansou: PansouClient | None = None,
    qas: QasClient | None = None,
) -> dict:
    _progress(on_progress, "tmdb_resolving", "正在匹配 TMDB 媒体信息")
    tmdb_client = tmdb or TmdbClient()
    qas_client = qas or QasClient()
    target = resolve_media_target(tmdb_id, media_type, season_number, tmdb_client)
    save_path = build_save_path(target_kind, media_type, target.title, target.series_year, season_number)

    if media_type == "movie":
        resolution = resolve_movie_source(
            target,
            preferred_share_urls,
            qas=qas_client,
            pansou=pansou,
            refresh=refresh,
            preferred_source_names=preferred_source_names,
            on_progress=on_progress,
        )
    else:
        aired = _aired_episodes(target)
        _progress(on_progress, "checking_saved", "正在读取目标文件夹的已存集数")
        try:
            save_path, last_saved = resolve_save_path_progress(save_path, target.season_number, qas=qas_client)
        except Exception as exc:
            return {
                "ok": False,
                "stage": "storage_check_failed",
                "message": f"无法可靠读取目标文件夹，已停止转存：{type(exc).__name__}",
                "save_path": save_path,
                "target": asdict(target),
                "resolution": {},
            }
        pending = tuple(ep for ep in aired if ep.episode_number > last_saved)
        # A manual save is a catch-up operation: transfer every aired episode
        # missing from the destination, not only the first one.  When the
        # destination is already at E181 and only E182 has aired, ``pending``
        # naturally still contains just E182.
        target = replace(target, episodes=pending)
        if not target.episodes:
            return {
                "ok": True,
                "stage": "already_saved",
                "message": f"目标文件夹已存至 S{target.season_number:02d}E{last_saved:02d}，没有需要转存的新集",
                "save_path": save_path,
                "target": asdict(target),
                "resolution": {},
            }
        resolution = resolve_episode_source(
            target,
            preferred_share_urls,
            qas=qas_client,
            pansou=pansou,
            refresh=refresh,
            allow_review_confidence=user_confirmed,
            preferred_source_names=preferred_source_names,
            on_progress=on_progress,
        )

    if not resolution.ok:
        return {
            "ok": False,
            "stage": resolution.stage,
            "message": resolution.message,
            "save_path": save_path,
            "target": asdict(target),
            "resolution": asdict(resolution),
        }

    _progress(on_progress, "preparing_names", "正在生成规范文件名")
    _progress(on_progress, "qas_transferring", "正在提交 QAS 转存任务")
    execution = execute_qas_plan(
        target,
        resolution,
        save_path,
        qas=qas_client,
        allow_review_confirmed=user_confirmed,
    )
    return {
        "ok": execution.ok,
        "stage": execution.stage,
        "message": execution.message,
        "save_path": save_path,
        "target": asdict(target),
        "resolution": asdict(resolution),
        "execution": asdict(execution),
    }


def _progress(callback: Callable[[str, str], None] | None, stage: str, message: str) -> None:
    if callback:
        callback(stage, message)


def _aired_episodes(target: MediaTarget):
    today = datetime.now(ZoneInfo(get_settings().tracking_timezone)).date().isoformat()
    return tuple(episode for episode in target.episodes if not episode.air_date or episode.air_date <= today)
