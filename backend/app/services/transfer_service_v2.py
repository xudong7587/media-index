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
from app.services.standard_resolver import resolve_standard_tv_source
from app.services.paths import build_save_path
from app.providers.base import TransferPlan
from app.providers.registry import get_transfer_provider, resolve_provider_key
from app.services.saved_episode_scanner import resolve_save_path_progress
from app.services.cache import FileCache


def execute_transfer_v2(
    tmdb_id: int,
    media_type: str,
    target_kind: str,
    season_number: int | None = None,
    preferred_share_urls: str | Iterable[str] = "",
    refresh: bool = False,
    user_confirmed: bool = False,
    preferred_source_names: Iterable[str] = (),
    selected_episode_numbers: Iterable[int] = (),
    on_progress: Callable[[str, str], None] | None = None,
    *,
    tmdb: TmdbClient | None = None,
    pansou: PansouClient | None = None,
    qas: QasClient | None = None,
    provider: str | None = None,
    category: str = "",
    simple_matching: bool = False,
    title: str = "",
    year: str = "",
    skip_tmdb: bool = False,
) -> dict:
    if skip_tmdb and (media_type != "movie" or not title.strip() or not year.strip()):
        return {
            "ok": False,
            "stage": "no_resource",
            "message": "直通电影任务缺少已确认的名称或年份",
            "save_path": "",
            "resolution": {},
        }
    _progress(
        on_progress,
        "pansou_identifying" if skip_tmdb else "tmdb_resolving",
        "正在使用 PanSou 确认标准电影名称" if skip_tmdb else "正在匹配 TMDB 媒体信息",
    )
    tmdb_client = tmdb or TmdbClient()
    qas_client = qas or QasClient()
    persisted_provider = resolve_provider_key(target_kind, provider)
    transfer_provider = get_transfer_provider(
        persisted_provider or "qas",
        qas=qas_client,
        target=target_kind,
    )
    if skip_tmdb:
        target = MediaTarget(
            tmdb_id=0,
            media_type="movie",
            title=title.strip(),
            series_year=year.strip(),
            category=category or "movie",
        )
    else:
        target = resolve_media_target(tmdb_id, media_type, season_number, tmdb_client, category)
    save_path = build_save_path(
        target_kind,
        target.category or media_type,
        target.title,
        target.series_year,
        season_number,
        persisted_provider or "qas",
    )

    if persisted_provider == "moviepilot_115":
        if media_type == "movie":
            resolution = resolve_movie_source(
                target,
                preferred_share_urls,
                qas=qas_client,
                pansou=pansou,
                refresh=refresh,
                preferred_source_names=preferred_source_names,
                on_progress=on_progress,
                provider_filter=persisted_provider,
            )
        elif media_type == "tv" and simple_matching:
            resolution = resolve_standard_tv_source(
                target,
                preferred_share_urls,
                qas=qas_client,
                pansou=pansou,
                refresh=refresh,
                preferred_source_names=preferred_source_names,
                on_progress=on_progress,
                provider_filter=persisted_provider,
            )
        else:
            target = replace(target, episodes=_aired_episodes(target))
            resolution = resolve_episode_source(
                target,
                preferred_share_urls,
                qas=qas_client,
                pansou=pansou,
                refresh=refresh,
                preferred_source_names=preferred_source_names,
                on_progress=on_progress,
                provider_filter=persisted_provider,
            )
        return {
            "ok": False,
            "stage": resolution.stage,
            "message": resolution.message,
            "save_path": save_path,
            "target": asdict(target),
            "resolution": asdict(resolution),
            "provider": persisted_provider,
        }

    if media_type == "movie":
        resolution = resolve_movie_source(
            target,
            preferred_share_urls,
            qas=transfer_provider,
            pansou=pansou,
            refresh=refresh,
            preferred_source_names=preferred_source_names,
            on_progress=on_progress,
            provider_filter=persisted_provider,
        )
    elif media_type == "tv" and simple_matching:
        resolution = resolve_standard_tv_source(
            target,
            preferred_share_urls,
            qas=transfer_provider,
            pansou=pansou,
            refresh=refresh,
            on_progress=on_progress,
            provider_filter=persisted_provider,
        )
    else:
        if not preferred_share_urls and not refresh:
            cached_resource = FileCache("resource-probe").get(
                f"{media_type}:{tmdb_id}:{season_number or 0}:{persisted_provider}",
                get_settings().resource_probe_cache_ttl_seconds,
            )
            if isinstance(cached_resource, dict) and cached_resource.get("found") and cached_resource.get("share_url"):
                preferred_share_urls = (str(cached_resource["share_url"]),)
        aired = _aired_episodes(target)
        _progress(on_progress, "checking_saved", "正在读取目标文件夹的已存集数")
        try:
            save_path, last_saved = resolve_save_path_progress(save_path, target.season_number, qas=transfer_provider)
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
        selected_numbers = {int(number) for number in selected_episode_numbers if int(number) > 0}
        if selected_numbers:
            pending = tuple(ep for ep in pending if ep.episode_number in selected_numbers)
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
            qas=transfer_provider,
            pansou=pansou,
            max_queries=8 if len(target.episodes) > 1 else 4,
            refresh=refresh,
            allow_review_confidence=user_confirmed,
            preferred_source_names=preferred_source_names,
            on_progress=on_progress,
            provider_filter=persisted_provider,
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
    _progress(on_progress, "provider_submitting", f"正在提交 {persisted_provider or '本地'} 转存任务")
    execution = transfer_provider.execute(
        TransferPlan(
            target=target,
            resolution=resolution,
            save_path=save_path,
            allow_review_confirmed=user_confirmed,
        )
    )
    return {
        "ok": execution.ok,
        "stage": execution.stage,
        "message": execution.message,
        "save_path": save_path,
        "target": asdict(target),
        "resolution": asdict(resolution),
        "execution": asdict(execution),
        "provider": persisted_provider,
    }


def _progress(callback: Callable[[str, str], None] | None, stage: str, message: str) -> None:
    if callback:
        callback(stage, message)


def _aired_episodes(target: MediaTarget):
    today = datetime.now(ZoneInfo(get_settings().tracking_timezone)).date().isoformat()
    return tuple(episode for episode in target.episodes if not episode.air_date or episode.air_date <= today)
