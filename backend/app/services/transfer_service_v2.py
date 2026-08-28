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
from app.services.paths import build_cloud_download_staging_path, build_save_path
from app.providers.base import TransferPlan
from app.providers.registry import get_transfer_provider, resolve_provider_key
from app.services.saved_episode_scanner import resolve_save_path_progress
from app.services.cache import FileCache
from app.services.openlist_sync import automatic_sync_allowed


def execute_transfer_v2(
    tmdb_id: int,
    media_type: str,
    target_kind: str,
    season_number: int | None = None,
    preferred_share_urls: str | Iterable[str] = "",
    preferred_share_only: bool = False,
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
    interaction_cloud_download_child: str = "",
    request_source: str = "",
) -> dict:
    preferred_share_urls = tuple(
        dict.fromkeys(
            value.strip()
            for value in (
                (preferred_share_urls,) if isinstance(preferred_share_urls, str) else preferred_share_urls
            )
            if isinstance(value, str) and value.strip()
        )
    )
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
    cloud_download_child = str(interaction_cloud_download_child or "").strip()
    if cloud_download_child:
        if (
            target_kind != "cloud"
            or persisted_provider not in {"p115", "quark"}
            or str(request_source or "").strip().lower() not in {"wecom", "telegram"}
        ):
            raise ValueError("互动云下载目录只允许企业微信或 Telegram 的原生网盘任务使用")
        save_path = build_cloud_download_staging_path(
            persisted_provider,
            cloud_download_child,
            target.media_type,
            target.title,
            target.series_year,
            season_number,
        )
    else:
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
                max_queries=0 if preferred_share_only and preferred_share_urls else 4,
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
                max_queries=0 if preferred_share_only and preferred_share_urls else 3,
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
                max_queries=0 if preferred_share_only and preferred_share_urls else 4,
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
            max_queries=0 if preferred_share_only and preferred_share_urls else 4,
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
            max_queries=0 if preferred_share_only and preferred_share_urls else 3,
            qas=transfer_provider,
            pansou=pansou,
            refresh=refresh,
            on_progress=on_progress,
            provider_filter=persisted_provider,
        )
    else:
        if not preferred_share_urls and not refresh:
            cached_resource = FileCache("resource-probe").get(
                f"v5:{media_type}:{tmdb_id}:{season_number or 0}:{persisted_provider}",
                get_settings().resource_probe_cache_ttl_seconds,
            )
            if (
                isinstance(cached_resource, dict)
                and cached_resource.get("found")
                and (cached_resource.get("transfer_share_urls") or cached_resource.get("share_url"))
            ):
                preferred_share_urls = tuple(
                    dict.fromkeys(
                        str(value).strip()
                        for value in (
                            cached_resource.get("transfer_share_urls")
                            or (cached_resource.get("share_url"),)
                        )
                        if str(value or "").strip()
                    )
                )
        aired = _aired_episodes(target)
        _progress(on_progress, "checking_saved", "正在读取目标文件夹的已存集数")
        try:
            storage_progress = resolve_save_path_progress(save_path, target.season_number, qas=transfer_provider)
            save_path, last_saved = storage_progress
        except Exception as exc:
            return {
                "ok": False,
                "stage": "storage_check_failed",
                "message": f"无法可靠读取目标文件夹，已停止转存：{type(exc).__name__}",
                "save_path": save_path,
                "target": asdict(target),
                "resolution": {},
            }
        exact_saved = (
            set(storage_progress.episodes)
            if bool(getattr(storage_progress, "episodes_reliable", False))
            else None
        )
        pending = (
            tuple(episode for episode in aired if episode.episode_number not in exact_saved)
            if exact_saved is not None
            else tuple(episode for episode in aired if episode.episode_number > last_saved)
        )
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
                "message": (
                    "目标文件夹已包含所有已播出的所选集，没有需要转存的内容"
                    if exact_saved is not None
                    else f"目标文件夹已存至 S{target.season_number:02d}E{last_saved:02d}，没有需要转存的新集"
                ),
                "save_path": save_path,
                "target": asdict(target),
                "resolution": {},
            }
        resolution = resolve_episode_source(
            target,
            preferred_share_urls,
            qas=transfer_provider,
            pansou=pansou,
            max_queries=0 if preferred_share_only and preferred_share_urls else (8 if len(target.episodes) > 1 else 4),
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
            destination_scope="cloud_download" if cloud_download_child else "",
            cloud_download_child=cloud_download_child,
        )
    )
    executions = [execution]
    resolutions = [resolution]
    if target.media_type == "tv" and (
        execution.ok or (persisted_provider == "p115" and _retryable_p115_candidate_error(execution.message))
    ):
        executions, resolutions = _continue_missing_episode_transfers(
            target,
            resolution,
            execution,
            save_path=save_path,
            transfer_provider=transfer_provider,
            persisted_provider=persisted_provider,
            pansou=pansou,
            refresh=refresh,
            user_confirmed=user_confirmed,
            preferred_source_names=preferred_source_names,
            on_progress=on_progress,
            cloud_download_child=cloud_download_child,
            preferred_share_urls=preferred_share_urls,
            allow_search_fallback=not preferred_share_only,
        )
    combined_resolution = _combine_resolutions(resolutions, target)
    combined_execution = _combine_executions(
        executions,
        resolutions,
        combined_resolution,
        target,
        provider=persisted_provider,
    )
    return {
        "ok": combined_execution["ok"],
        "stage": combined_execution["stage"],
        "message": combined_execution["message"],
        "save_path": save_path,
        "target": asdict(target),
        "resolution": asdict(combined_resolution),
        "execution": combined_execution,
        "provider": persisted_provider,
    }


def _continue_missing_episode_transfers(
    target: MediaTarget,
    first_resolution,
    first_execution,
    *,
    save_path: str,
    transfer_provider,
    persisted_provider: str,
    pansou: PansouClient | None,
    refresh: bool,
    user_confirmed: bool,
    preferred_source_names: Iterable[str],
    on_progress: Callable[[str, str], None] | None,
    cloud_download_child: str = "",
    preferred_share_urls: Iterable[str] = (),
    allow_search_fallback: bool = True,
):
    retry_failed_candidates = persisted_provider == "p115"
    executions = [first_execution] if first_execution.ok else []
    resolutions = [first_resolution] if first_execution.ok else []
    fallback_execution = first_execution
    fallback_resolution = first_resolution
    covered = _resolution_episode_numbers(first_resolution) if first_execution.ok else set()
    used_urls = {first_resolution.share_url} if first_resolution.share_url else set()
    candidate_urls = list(
        dict.fromkeys(
            [
                str(url).strip()
                for url in preferred_share_urls
                if str(url or "").strip() and str(url).strip() not in used_urls
            ]
            + [
                str(candidate.share_url)
                for candidate in first_resolution.reviewed_candidates
                if candidate.share_url and candidate.share_url not in used_urls
            ]
        )
    )
    fresh_searches = 0
    max_attempts = max(20, min(200, len(target.episodes) * 4))
    # PanSou verification is capped upstream.  Walk candidates one link at a
    # time so a season made up of individual shares can be completed without
    # re-inspecting the whole remaining list on every pass.  Once that page is
    # exhausted, a few bounded title-only searches can expose later links.
    for _ in range(max_attempts):
        missing = {
            episode.episode_number
            for episode in target.episodes
            if episode.episode_number not in covered
        }
        if not missing:
            break
        _progress(on_progress, "matching_files", f"已有链接已覆盖 {len(covered)} 集，检查剩余 {len(missing)} 集")
        remaining_target = replace(
            target,
            episodes=tuple(episode for episode in target.episodes if episode.episode_number in missing),
        )
        available_candidates = [url for url in candidate_urls if url not in used_urls]
        # A PanSou pass verifies at most 20 shares.  Repeat only its first,
        # broad TV-title query after those candidates are exhausted, excluding
        # every attempted URL.  This also handles seasons published as more
        # than 20 per-episode 115 links, not only duplicate-reception failures.
        refresh_candidate_search = (
            allow_search_fallback
            and retry_failed_candidates
            and not available_candidates
            and fresh_searches < 5
        )
        if not available_candidates and not refresh_candidate_search:
            break
        selected_candidates = (available_candidates[0],) if available_candidates else ()
        next_resolution = resolve_episode_source(
            remaining_target,
            "",
            qas=transfer_provider,
            pansou=pansou,
            max_queries=1 if refresh_candidate_search else 0,
            refresh=refresh,
            allow_review_confidence=user_confirmed,
            preferred_source_names=preferred_source_names,
            provider_filter=persisted_provider,
            excluded_share_urls=used_urls,
            candidate_share_urls=selected_candidates,
            on_progress=on_progress,
        )
        # A rejected or irrelevant candidate must not be inspected again on
        # the next pass.  Fresh PanSou searches already respect ``used_urls``.
        used_urls.update(selected_candidates)
        if refresh_candidate_search:
            fresh_searches += 1
        if not next_resolution.ok:
            if selected_candidates:
                continue
            break
        for candidate in next_resolution.reviewed_candidates:
            candidate_url = str(candidate.share_url or "")
            if candidate_url and candidate_url not in candidate_urls:
                candidate_urls.append(candidate_url)
        next_execution = transfer_provider.execute(
            TransferPlan(
                target=remaining_target,
                resolution=next_resolution,
                save_path=save_path,
                allow_review_confirmed=user_confirmed,
                destination_scope="cloud_download" if cloud_download_child else "",
                cloud_download_child=cloud_download_child,
            )
        )
        if next_resolution.share_url:
            used_urls.add(next_resolution.share_url)
        if not next_execution.ok:
            if retry_failed_candidates and _retryable_p115_candidate_error(next_execution.message):
                fallback_execution = next_execution
                fallback_resolution = next_resolution
                continue
            resolutions.append(next_resolution)
            executions.append(next_execution)
            break
        resolutions.append(next_resolution)
        executions.append(next_execution)
        new_covered = _resolution_episode_numbers(next_resolution) - covered
        covered.update(new_covered)
        if not new_covered:
            break
    if not executions:
        return [fallback_execution], [fallback_resolution]
    return executions, resolutions


def _retryable_p115_candidate_error(message: str) -> bool:
    normalized = str(message or "").casefold()
    return "4200045" in normalized or "已接收过" in normalized or "已经转存过" in normalized


def _resolution_episode_numbers(resolution) -> set[int]:
    numbers: set[int] = set()
    for pair in resolution.rename_pairs:
        numbers.update(int(number) for number in (pair.episode_numbers or ()) if int(number) > 0)
        if pair.episode_number:
            numbers.add(int(pair.episode_number))
    return numbers


def _restrict_resolution_to_target(resolution, target):
    """Keep a full-season inspection limited to the episodes being caught up."""
    selected = {int(episode.episode_number) for episode in target.episodes}
    if not selected:
        return replace(resolution, matches=(), rename_pairs=())

    def pair_numbers(pair) -> set[int]:
        numbers = {int(number) for number in (pair.episode_numbers or ()) if int(number) > 0}
        if pair.episode_number:
            numbers.add(int(pair.episode_number))
        return numbers

    return replace(
        resolution,
        matches=tuple(
            match for match in resolution.matches
            if set(match.episode_numbers) & selected
        ),
        rename_pairs=tuple(pair for pair in resolution.rename_pairs if pair_numbers(pair) & selected),
    )


def _combine_resolutions(resolutions, target):
    if len(resolutions) == 1:
        return resolutions[0]
    first = resolutions[0]
    matches = []
    pairs = []
    candidates = []
    seen_matches: set[str] = set()
    seen_pairs: set[tuple[str, str]] = set()
    seen_candidates: set[str] = set()
    for resolution in resolutions:
        for match in resolution.matches:
            key = f"{match.source.name}:{','.join(str(number) for number in match.episode_numbers)}"
            if key not in seen_matches:
                matches.append(match)
                seen_matches.add(key)
        for pair in resolution.rename_pairs:
            key = (pair.source_name, pair.replacement)
            if key not in seen_pairs:
                pairs.append(pair)
                seen_pairs.add(key)
        for candidate in resolution.reviewed_candidates:
            if candidate.share_url not in seen_candidates:
                candidates.append(candidate)
                seen_candidates.add(candidate.share_url)
    return replace(
        first,
        message=f"已从 {len(resolutions)} 个链接完成集数匹配",
        matches=tuple(matches),
        rename_pairs=tuple(pairs),
        reviewed_candidates=tuple(candidates),
    )


def _combine_executions(executions, resolutions, resolution, target, *, provider: str = "qas") -> dict:
    total = len(_resolution_episode_numbers(resolution))
    ok = all(bool(execution.ok) for execution in executions)
    confirmed = all(bool(execution.confirmed) for execution in executions)
    if not ok:
        failures = [
            f"链接 {index}：{execution.message}"
            for index, execution in enumerate(executions, start=1)
            if not execution.ok
        ]
        return {
            "ok": False,
            "stage": next((execution.stage for execution in reversed(executions) if not execution.ok), "provider_failed"),
            "message": "；".join(failures) or "网盘转存失败",
            "external_job_id": "",
            "executed_items": sum(int(execution.executed_items or 0) for execution in executions),
            "confirmed": False,
            "outputs": [output for execution in executions for output in execution.outputs],
        }
    if getattr(target, "media_type", "") == "movie":
        executed_items = sum(int(execution.executed_items or 0) for execution in executions)
        return {
            "ok": True,
            "stage": "provider_completed" if confirmed else "provider_triggered",
            "message": (
                f"已完成转存并确认 {executed_items or len(resolution.rename_pairs)} 个电影文件"
                if confirmed
                else f"已提交 {executed_items or len(resolution.rename_pairs)} 个电影文件，等待网盘确认"
            ),
            "external_job_id": "",
            "executed_items": executed_items,
            "confirmed": confirmed,
            "outputs": [output for execution in executions for output in execution.outputs],
        }
    covered = len(_resolution_episode_numbers(resolution))
    expected = len(target.episodes)
    missing = max(0, expected - covered)
    stage = "provider_completed" if ok and confirmed else "provider_triggered" if ok else executions[-1].stage
    link_parts = [
        f"链接 {index} 一次性提交 {len(_resolution_episode_numbers(item))} 集"
        for index, item in enumerate(resolutions, start=1)
    ]
    message = "；".join(link_parts) + f"。目标共 {expected} 集，已覆盖 {covered} 集"
    if missing:
        message += f"，仍缺失 {missing} 集"
    elif confirmed:
        message += "，已完成转存"
    else:
        message += "，已提交转存任务，等待网盘确认"
        settings = get_settings()
        opposite_provider = "p115" if provider == "qas" else "qas"
        if (
            settings.openlist_enabled
            and settings.openlist_auto_sync
            and automatic_sync_allowed(settings, provider, opposite_provider)
        ):
            message += "；确认后将发起 OpenList 复制"
    if len(executions) > 1:
        message += f"；共提交 {total} 集"
    return {
        "ok": ok,
        "stage": stage,
        "message": message,
        "external_job_id": "",
        "executed_items": total,
        "confirmed": confirmed,
        "outputs": [output for execution in executions for output in execution.outputs],
    }


def _progress(callback: Callable[[str, str], None] | None, stage: str, message: str) -> None:
    if callback:
        callback(stage, message)


def _aired_episodes(target: MediaTarget):
    today = datetime.now(ZoneInfo(get_settings().tracking_timezone)).date().isoformat()
    return tuple(episode for episode in target.episodes if not episode.air_date or episode.air_date <= today)
