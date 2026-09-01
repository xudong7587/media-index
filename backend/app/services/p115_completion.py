from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from app.clients.pansou import PansouClient
from app.clients.tmdb import TmdbClient
from app.core.config import get_settings
from app.domain.media import EpisodeTarget, MediaTarget
from app.providers.base import TransferPlan
from app.providers.registry import get_transfer_provider
from app.services.episode_matcher import episode_numbers_from_name
from app.services.link_resolver import resolve_episode_source
from app.services.media_target import resolve_media_target
from app.services.movie_resolver import resolve_movie_source
from app.services.openlist_sync import automatic_sync_allowed, sync_transfer_outputs
from app.services.post_transfer_pipeline import run_confirmed_native_transfer_post_processing
from app.services.provider_path_mapping import map_provider_save_path


@dataclass(frozen=True)
class P115CompletionResult:
    requested: bool
    native_attempted: bool
    native_completed: bool
    remaining_filenames: tuple[str, ...]
    openlist_results: tuple[dict[str, Any], ...]
    message: str
    workflow_status: str


def complete_quark_to_p115(
    *,
    job_id: int,
    save_path: str,
    filenames: list[str] | tuple[str, ...],
    tmdb_id: int | None = None,
    media_type: str = "",
    season_number: int | None = None,
    title: str = "",
    year: str = "",
    category: str = "",
    poster_url: str = "",
) -> P115CompletionResult:
    """Prefer a verified native 115 share, then copy only the exact remainder through OpenList."""
    settings = get_settings()
    exact_names = tuple(dict.fromkeys(str(name or "").strip() for name in filenames if str(name or "").strip()))
    if not (
        settings.openlist_enabled
        and settings.openlist_auto_sync
        and automatic_sync_allowed(settings, "quark", "p115")
        and save_path
        and exact_names
    ):
        return P115CompletionResult(False, False, False, exact_names, (), "", "skipped")

    target_path = map_provider_save_path(save_path, "quark", "p115", settings)
    native_attempted = False
    native_completed = False
    remaining = exact_names
    native_note = ""
    try:
        provider = get_transfer_provider("p115", target="cloud")
        if provider.configured() and provider.reconcile(target_path, list(exact_names)):
            return P115CompletionResult(
                True,
                False,
                True,
                (),
                (),
                f"115 目标目录已包含全部 {len(exact_names)} 个精确文件",
                "done",
            )
        target = _native_search_target(
            tmdb_id=tmdb_id,
            media_type=media_type,
            season_number=season_number,
            title=title,
            year=year,
            category=category,
            filenames=exact_names,
        )
        if target is not None and provider.configured():
            native_attempted = True
            resolution = (
                resolve_movie_source(
                    target,
                    qas=provider,
                    pansou=PansouClient(),
                    provider_filter="p115",
                    max_queries=4,
                )
                if target.media_type == "movie"
                else resolve_episode_source(
                    target,
                    qas=provider,
                    pansou=PansouClient(),
                    provider_filter="p115",
                    max_queries=4,
                )
            )
            if resolution.ok:
                execution = provider.execute(TransferPlan(target, resolution, target_path))
                confirmed_outputs = tuple(dict(item) for item in execution.outputs)
                if execution.ok and execution.confirmed and confirmed_outputs:
                    remaining = _remaining_after_native(
                        exact_names,
                        resolution.rename_pairs,
                        confirmed_outputs,
                        season_number,
                        target.media_type,
                    )
                    native_completed = not remaining
                    native_note = (
                        f"PanSou 找到 115 资源，原生 115 已确认 {len(confirmed_outputs)} 个文件"
                    )
                    if job_id > 0:
                        run_confirmed_native_transfer_post_processing(
                            job_id,
                            provider="p115",
                            save_path=target_path,
                            outputs=confirmed_outputs,
                            title=target.title,
                            poster_url=poster_url,
                            media_year=target.series_year,
                        )
                else:
                    native_note = f"115 原生转存未确认：{execution.message}"
            else:
                native_note = "PanSou 未找到可安全验真的 115 资源"
        elif target is None:
            native_note = "媒体身份不足，已跳过 PanSou 猜测"
        else:
            native_note = "115 原生转存未配置"
    except Exception as exc:
        native_note = f"115 原生优先检查已跳过（{type(exc).__name__}）"

    if not remaining:
        return P115CompletionResult(True, native_attempted, True, (), (), native_note, "done")

    try:
        openlist_results = tuple(
            sync_transfer_outputs(
                "quark",
                save_path,
                list(remaining),
                tmdb_id=tmdb_id,
                media_type=media_type,
                season_number=season_number,
                display_title=title,
                target_providers=("p115",),
            )
        )
    except Exception as exc:
        message = f"{native_note}；OpenList 补齐未完成（{type(exc).__name__}）".strip("；")
        return P115CompletionResult(True, native_attempted, native_completed, remaining, (), message, "failed")

    landed = any(bool(item.get("ok")) and item.get("landed") is not None for item in openlist_results)
    submitted = any(bool(item.get("ok")) for item in openlist_results)
    job_ids = "、".join(str(item.get("job_id")) for item in openlist_results if item.get("job_id"))
    if landed:
        suffix = f"OpenList 已完成剩余 {len(remaining)} 个文件的 115 落盘确认"
        status = "done"
    elif submitted:
        suffix = f"OpenList 已提交剩余 {len(remaining)} 个文件的补齐任务{f' #{job_ids}' if job_ids else ''}"
        status = "running"
    else:
        detail = str((openlist_results[0] if openlist_results else {}).get("message") or "未产生可核验的结果")
        suffix = f"OpenList 补齐未完成：{detail[:100]}"
        status = "failed"
    return P115CompletionResult(
        True,
        native_attempted,
        native_completed,
        remaining,
        openlist_results,
        f"{native_note}；{suffix}".strip("；"),
        status,
    )


def _native_search_target(
    *,
    tmdb_id: int | None,
    media_type: str,
    season_number: int | None,
    title: str,
    year: str,
    category: str,
    filenames: tuple[str, ...],
) -> MediaTarget | None:
    normalized_type = str(media_type or category or "").strip().lower()
    episodic = normalized_type in {"tv", "variety", "anime"}
    if int(tmdb_id or 0) > 0 and normalized_type in {"movie", "tv", "variety"}:
        target = resolve_media_target(int(tmdb_id), normalized_type, season_number, TmdbClient(), category)
        if episodic:
            numbers = _episode_numbers(filenames, int(season_number or target.season_number or 1))
            if not numbers:
                return None
            target = replace(target, episodes=tuple(ep for ep in target.episodes if ep.episode_number in numbers))
            if not target.episodes:
                return None
        return target
    normalized_title = str(title or "").strip()
    if not normalized_title:
        return None
    if not episodic:
        if not str(year or "").strip():
            return None
        return MediaTarget(0, "movie", normalized_title, category=category or "movie", series_year=str(year).strip())
    season = int(season_number or _single_season_number(filenames) or 1)
    numbers = _episode_numbers(filenames, season)
    if not numbers:
        return None
    return MediaTarget(
        0,
        "tv",
        normalized_title,
        category=category or "tv",
        series_year=str(year or "").strip(),
        season_number=season,
        episodes=tuple(EpisodeTarget(season, number) for number in sorted(numbers)),
    )


def _episode_numbers(filenames: tuple[str, ...], season_number: int) -> set[int]:
    return {number for name in filenames for number in episode_numbers_from_name(name, season_number)}


def _single_season_number(filenames: tuple[str, ...]) -> int | None:
    import re

    seasons = {int(match.group(1)) for name in filenames if (match := re.search(r"(?i)(?:^|[^a-z0-9])S0*(\d{1,2})E", name))}
    return next(iter(seasons)) if len(seasons) == 1 else None


def _remaining_after_native(
    exact_names,
    rename_pairs,
    outputs,
    season_number: int | None,
    media_type: str,
) -> tuple[str, ...]:
    if str(media_type or "").strip().lower() == "movie" and outputs:
        return ()
    confirmed_names = {str(item.get("file_name") or item.get("name") or "").strip().casefold() for item in outputs}
    covered_episodes = {
        int(number)
        for pair in rename_pairs
        for number in getattr(pair, "episode_numbers", ())
        if int(number) > 0
    }
    for pair in rename_pairs:
        if getattr(pair, "episode_number", None):
            covered_episodes.add(int(pair.episode_number))
    season = int(season_number or _single_season_number(tuple(exact_names)) or 1)
    remaining = []
    for name in exact_names:
        if name.casefold() in confirmed_names:
            continue
        numbers = episode_numbers_from_name(name, season)
        if numbers and numbers.issubset(covered_episodes):
            continue
        remaining.append(name)
    return tuple(remaining)
