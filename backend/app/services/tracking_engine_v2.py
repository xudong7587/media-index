from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from collections.abc import Callable
from zoneinfo import ZoneInfo

from app.clients.pansou import PansouClient
from app.clients.qas import QasClient
from app.clients.tmdb import TmdbClient
from app.core.config import get_settings
from app.db.database import db
from app.domain.media import MediaTarget, ProviderExecutionResult
from app.services.link_resolver import resolve_episode_source
from app.services.episode_naming import adapt_resolution_to_existing_episode_names
from app.services.media_workflow import (
    complete_transfer_workflow_step,
    initialize_media_workflow,
    update_media_workflow_progress,
    update_media_workflow_step,
)
from app.services.media_target import resolve_media_target
from app.services.notifications import add_notification
from app.services.saved_episode_scanner import refresh_saved_episodes
from app.services.tracking_save_path import resolve_tracking_save_path
from app.services.previous_source import recover_previous_share_urls
from app.services.post_transfer_pipeline import run_confirmed_native_transfer_post_processing
from app.services.qas_executor import disable_compatible_qas_schedules
from app.services.review_notification import notify_review_required
from app.services.openlist_sync import sync_tracking_fallback_to_p115
from app.services.transfer_service_v2 import (
    _combine_executions,
    _combine_resolutions,
    _continue_missing_episode_transfers,
    _retryable_p115_candidate_error,
    _restrict_resolution_to_target,
)
from app.providers.base import TransferPlan
from app.providers.registry import get_transfer_provider


_POST_PROCESSING_PENDING = "post_processing_pending"
_POST_PROCESSING_RUNNING = "post_processing_running"
_POST_PROCESSING_COMPLETED = "post_processing_completed"
_POST_PROCESSING_FAILED = "post_processing_failed"
_POST_PROCESSING_SKIPPED = "post_processing_skipped"
_POST_PROCESSING_SUCCESS = {_POST_PROCESSING_COMPLETED, _POST_PROCESSING_SKIPPED}
_POST_PROCESSING_MAX_ATTEMPTS = 2


def sync_tracking_episodes(task_id: int, target: MediaTarget, *, provider: str | None = None) -> None:
    with db() as conn:
        if provider is None:
            row = conn.execute("SELECT provider FROM tracking_tasks WHERE id=?", (task_id,)).fetchone()
            provider = str(row["provider"] or "") if row else ""
        for episode in target.episodes:
            conn.execute(
                """
                INSERT INTO tracking_episodes(
                    task_id, season_number, episode_number, air_date, title, provider,
                    match_tokens_json, desc_hint
                ) VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(task_id, season_number, episode_number) DO UPDATE SET
                    air_date=excluded.air_date,
                    title=excluded.title,
                    provider=excluded.provider,
                    match_tokens_json=excluded.match_tokens_json,
                    desc_hint=excluded.desc_hint,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    task_id,
                    episode.season_number,
                    episode.episode_number,
                    episode.air_date,
                    episode.title,
                    provider,
                    json.dumps(episode.match_tokens, ensure_ascii=False),
                    episode.desc_hint,
                ),
            )


def compute_next_check(
    target: MediaTarget,
    statuses: dict[int, str],
    now: datetime | None = None,
    *,
    check_hour: int | None = None,
    check_time: str | None = None,
    timezone_name: str | None = None,
    progress_floor: int = 0,
) -> str:
    settings = get_settings()
    zone = ZoneInfo(timezone_name or settings.tracking_timezone)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    local_now = current.astimezone(zone)
    configured_time = _parse_check_time(check_time, settings.tracking_check_time if check_hour is None else check_hour)

    due_statuses = {"pending", "retry_wait", "failed"}
    future_checks: list[datetime] = []
    has_unconfirmed_air_date = False
    for episode in target.episodes:
        if episode.episode_number <= progress_floor:
            continue
        state = statuses.get(episode.episode_number, "pending")
        if state not in due_statuses:
            continue
        parsed_air_date = _parse_air_date(episode.air_date)
        # An empty or malformed TMDB air date is not proof that a new episode
        # has been released. Wait for TMDB to provide a real date instead of
        # creating speculative searches and review tasks.
        if parsed_air_date is None:
            has_unconfirmed_air_date = True
            continue
        local_check = datetime.combine(parsed_air_date, configured_time, tzinfo=zone)
        if local_check <= local_now:
            return current.astimezone(timezone.utc).isoformat(timespec="seconds")
        future_checks.append(local_check)
    if has_unconfirmed_air_date:
        metadata_check = datetime.combine(local_now.date(), configured_time, tzinfo=zone)
        if metadata_check <= local_now:
            metadata_check += timedelta(days=1)
        future_checks.append(metadata_check)
    if not future_checks:
        return ""
    return min(future_checks).astimezone(timezone.utc).isoformat(timespec="seconds")


def compute_auto_start_episode(
    target: MediaTarget,
    statuses: dict[int, str],
    now: datetime | None = None,
    *,
    check_time: str | None = None,
    timezone_name: str | None = None,
) -> int:
    if any(status in {"saved", "triggered"} for status in statuses.values()):
        return 0
    settings = get_settings()
    zone = ZoneInfo(timezone_name or settings.tracking_timezone)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    local_now = current.astimezone(zone)
    configured_time = _parse_check_time(check_time, settings.tracking_check_time)
    dated_checks: list[tuple[int, datetime]] = []
    for episode in target.episodes:
        air_date = _parse_air_date(episode.air_date)
        if air_date is not None:
            dated_checks.append((episode.episode_number, datetime.combine(air_date, configured_time, tzinfo=zone)))
    future_checks = [check_at for _, check_at in dated_checks if check_at > local_now]
    if not future_checks:
        return 0
    next_check = min(future_checks)
    return max((episode_number for episode_number, check_at in dated_checks if check_at < next_check), default=0)


def run_tracking_task(
    task_id: int,
    *,
    tmdb: TmdbClient | None = None,
    pansou: PansouClient | None = None,
    qas: QasClient | None = None,
    approved_share_url: str = "",
    approved_source_names: tuple[str, ...] | list[str] = (),
    force: bool = False,
    selected_episode_numbers: tuple[int, ...] | list[int] = (),
    job_id: int | None = None,
    on_progress: Callable[[str, str], None] | None = None,
    defer_notification: bool = False,
) -> dict:
    with db() as conn:
        task_row = conn.execute("SELECT * FROM tracking_tasks WHERE id=?", (task_id,)).fetchone()
        if not task_row:
            _finish_tracking_run_job(job_id, "failed", "not_found", "追更任务不存在")
            return {"ok": False, "stage": "not_found"}
        task = dict(task_row)
        locked = conn.execute(
            """
            UPDATE tracking_tasks SET decision_state='running', updated_at=CURRENT_TIMESTAMP
            WHERE id=? AND status='active' AND decision_state!='running'
            """,
            (task_id,),
        ).rowcount
        if not locked:
            _finish_tracking_run_job(job_id, "failed", "not_runnable", "追更任务正在运行、已暂停或等待人工确认")
            return {"ok": False, "stage": "not_runnable"}

    def progress(stage: str, message: str) -> None:
        if job_id is not None:
            with db() as conn:
                conn.execute(
                    "UPDATE transfer_jobs SET stage=?,message=? WHERE id=? AND status='running'",
                    (stage, message[:1000], job_id),
                )
            update_media_workflow_progress(int(job_id), stage, message)
        if on_progress:
            on_progress(stage, message)

    try:
        progress("tmdb_resolving", "正在读取 TMDB 媒体信息")
        tmdb_client = tmdb or TmdbClient()
        qas_client = qas or QasClient()
        transfer_provider = get_transfer_provider(task.get("provider") or "qas", qas=qas_client)
        target = resolve_media_target(
            task["tmdb_id"],
            task["media_type"],
            task["season_number"],
            tmdb_client,
            task.get("category") or "",
        )
        resolved_save_path = resolve_tracking_save_path(
            str(task.get("save_path") or ""),
            save_target=task["save_target"],
            media_type=target.category or target.media_type,
            title=target.title,
            year=target.series_year,
            season_number=int(target.season_number or task["season_number"] or 0),
            provider=task.get("provider") or "qas",
        )
        if task.get("save_path") != resolved_save_path:
            with db() as conn:
                conn.execute(
                    "UPDATE tracking_tasks SET save_path=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (resolved_save_path, task_id),
                )
            task["save_path"] = resolved_save_path
        _disable_qas_schedules_if_configured(target, qas_client)
        sync_tracking_episodes(task_id, target, provider=task.get("provider") or "")
        progress("checking_saved", "正在读取目标网盘目录")
        storage = refresh_saved_episodes(task_id, qas=transfer_provider)
        if not storage.get("ok"):
            message = storage.get("message", "读取目标目录失败")
            retries = int(task.get("retry_count") or 0) + 1
            state, next_check = _execution_retry_state(retries)
            _finish_task(task_id, state, message, next_check, retry_count=retries)
            if state == "needs_review" and job_id is not None and not defer_notification:
                _notify_job_once(job_id, target.title, message, qas_client)
            _finish_tracking_run_job(job_id, "failed", "storage_check_failed", message)
            return {"ok": False, "stage": "storage_check_failed", "message": message}
        task["save_path"] = storage.get("save_path") or task["save_path"]
        with db() as conn:
            rows = conn.execute(
                "SELECT * FROM tracking_episodes WHERE task_id=? ORDER BY episode_number",
                (task_id,),
            ).fetchall()
            episodes = [dict(row) for row in rows]

        zone = ZoneInfo(get_settings().tracking_timezone)
        local_now = datetime.now(zone)
        configured_time = _parse_check_time(task.get("check_time"), get_settings().tracking_check_time)
        last_saved_episode = int(storage.get("last_saved_episode") or 0)
        exact_saved_episode_numbers = (
            {
                int(number)
                for number in storage.get("drive_episodes") or ()
                if int(number) > 0
            }
            if storage.get("drive_episodes_reliable") is True
            else None
        )
        progress_floor = max(
            int(task.get("auto_start_episode") or 0),
            _legacy_qas_progress_floor(task),
            0 if exact_saved_episode_numbers is not None else last_saved_episode,
        )
        if selected_episode_numbers:
            requested = {int(number) for number in selected_episode_numbers if int(number) > 0}
            # Catch-up is the sole route allowed to work on episodes at or
            # before the destination's current progress.  A regular manual
            # run is still an automatic follow-up run, not a backfill.
            due_numbers = _manual_due_episode_numbers(episodes, requested, local_now)
        else:
            due_numbers = _due_episode_numbers(
                episodes,
                progress_floor,
                local_now,
                configured_time,
                force=force or bool(approved_share_url),
                exact_saved_episode_numbers=exact_saved_episode_numbers,
            )
        if not due_numbers:
            statuses = {row["episode_number"]: row["status"] for row in episodes}
            next_check = compute_next_check(target, statuses, check_time=task.get("check_time"), progress_floor=progress_floor)
            _finish_task(task_id, "idle", "", next_check, retry_count=0)
            _finish_tracking_run_job(job_id, "done", "not_due", "当前没有已播出且尚未保存的新内容")
            return {
                "ok": True,
                "stage": "not_due",
                "message": "当前没有已播出且尚未保存的新内容",
                "next_check_at": next_check,
                "job_id": job_id,
                "provider": str(task.get("provider") or ""),
                "episode_numbers": [],
            }

        due_target = replace(target, episodes=tuple(ep for ep in target.episodes if ep.episode_number in due_numbers))
        previous_urls = (approved_share_url or task.get("current_share_url") or "",)
        if not previous_urls[0]:
            previous_urls = recover_previous_share_urls(due_target, qas_client)
        search_target = due_target
        # Catch-up from the card must inspect complete season packs first.  A
        # one-episode target would make the search planner add SxxExx and
        # hide the full-share candidates the user asked us to reuse.
        if selected_episode_numbers and task["media_type"] == "tv":
            search_target = replace(target, episodes=target.episodes)
        progress("searching_sources", "正在通过 PanSou 搜索可用资源")
        resolution = resolve_episode_source(
            search_target,
            previous_urls,
            qas=transfer_provider,
            pansou=pansou,
            refresh=force,
            allow_review_confidence=bool(approved_share_url),
            preferred_source_names=approved_source_names,
            provider_filter=str(task.get("provider") or "qas"),
            excluded_share_urls=_expired_share_urls(task_id),
            on_progress=progress,
            validation_target=replace(
                target,
                episodes=tuple(
                    episode
                    for episode in target.episodes
                    if (_parse_air_date(episode.air_date) or date.max) <= local_now.date()
                ),
            ),
        )
        if search_target is not due_target and resolution.ok:
            resolution = _restrict_resolution_to_target(resolution, due_target)
        if resolution.ok and task.get("provider") == "p115":
            directory_response = transfer_provider.savepath_detail(task["save_path"])
            resolution = adapt_resolution_to_existing_episode_names(
                resolution,
                directory_response,
                target.season_number or 0,
            )
        if job_id is None:
            job_id = _record_tracking_job(task, due_target, resolution)
        else:
            _update_tracking_run_resolution(job_id, task, due_target, resolution)
        _record_candidates(job_id, resolution.reviewed_candidates)
        if not resolution.ok:
            return _handle_resolution_failure(
                task,
                due_target,
                resolution,
                job_id,
                qas_client,
                notify=not defer_notification,
            )

        progress("provider_submitting", "正在提交网盘转存任务")
        execution = transfer_provider.execute(
            TransferPlan(
                target=due_target,
                resolution=resolution,
                save_path=task["save_path"],
                allow_review_confirmed=bool(approved_share_url),
            )
        )
        executions = [execution]
        resolutions = [resolution]
        provider_key = str(task.get("provider") or "qas")
        if due_target.media_type == "tv" and (
            execution.ok or (provider_key == "p115" and _retryable_p115_candidate_error(execution.message))
        ):
            executions, resolutions = _continue_missing_episode_transfers(
                due_target,
                resolution,
                execution,
                save_path=task["save_path"],
                transfer_provider=transfer_provider,
                persisted_provider=provider_key,
                pansou=pansou,
                refresh=force,
                user_confirmed=bool(approved_share_url),
                preferred_source_names=approved_source_names,
                on_progress=progress,
            )
        partial_failure_messages: list[str] = []
        # A 115 season is frequently assembled from one share per episode.  A
        # later link can fail after earlier links have already been confirmed.
        # Keep the confirmed subset as durable progress instead of routing the
        # whole run through the all-or-nothing failure handler.  Only confirmed
        # resolutions are allowed to mark episodes saved or enter STRM/Emby.
        if provider_key == "p115":
            confirmed_pairs = [
                (item, item_resolution)
                for item, item_resolution in zip(executions, resolutions, strict=False)
                if item.ok and item.confirmed
            ]
            partial_failure_messages = [
                str(item.message or "115 转存失败")
                for item in executions
                if not item.ok
            ]
            if confirmed_pairs and partial_failure_messages:
                executions = [item for item, _item_resolution in confirmed_pairs]
                resolutions = [item_resolution for _item, item_resolution in confirmed_pairs]

        resolution = _combine_resolutions(resolutions, due_target)
        aggregate = _combine_executions(
            executions,
            resolutions,
            resolution,
            due_target,
            provider=provider_key,
        )
        if partial_failure_messages and aggregate["ok"]:
            aggregate["stage"] = "provider_partial"
            aggregate["message"] = (
                f"{aggregate['message']}；其余链接转存失败："
                + "；".join(partial_failure_messages)
                + "，已成功集数保持完成并将自动重试缺失集"
            )
        execution = ProviderExecutionResult(
            ok=bool(aggregate["ok"]),
            stage=str(aggregate["stage"]),
            message=str(aggregate["message"]),
            executed_items=int(aggregate["executed_items"] or 0),
            confirmed=bool(aggregate["confirmed"]),
            outputs=tuple(aggregate["outputs"] or ()),
        )
        with db() as conn:
            conn.execute(
                """
                UPDATE transfer_jobs SET share_url=?,source_file=?,renamed_file=?,rename_pairs_json=?
                WHERE id=?
                """,
                (
                    resolution.share_url,
                    resolution.rename_pairs[0].source_name if resolution.rename_pairs else "",
                    resolution.rename_pairs[0].replacement if resolution.rename_pairs else "",
                    _tracking_pairs_json(resolution.rename_pairs, due_target),
                    job_id,
                ),
            )
        source_provider = str(task.get("provider") or "qas")
        post_processing_required = bool(
            execution.confirmed
            and str(task.get("save_target") or "cloud") == "cloud"
            and source_provider in {"p115", "quark"}
            and execution.outputs
        )
        _update_tracking_job_execution(
            job_id,
            execution,
            post_processing_state=(
                _POST_PROCESSING_PENDING
                if post_processing_required
                else _POST_PROCESSING_SKIPPED
                if execution.confirmed
                else ""
            ),
        )
        if execution.ok and not execution.confirmed and str(task.get("provider") or "qas") == "qas":
            from app.services.qas_reconciler import request_qas_reconciliation

            request_qas_reconciliation()
        if not execution.ok:
            return _handle_execution_failure(
                task,
                due_target,
                execution.message,
                job_id,
                qas_client,
                notify=not defer_notification,
            )

        post_processing_ok: bool | None = True if execution.confirmed and not post_processing_required else None
        if post_processing_required:
            post_processing_ok = run_pending_tracking_post_processing(
                int(job_id),
                outputs=execution.outputs,
                title=str(target.title or task.get("title") or ""),
                poster_url=str(task.get("poster_url") or target.poster_url or ""),
                media_year=str(target.series_year or task.get("year") or ""),
                defer_library_notification=defer_notification,
            )
        episode_status = "saved" if execution.confirmed else "triggered"
        pairs = {
            episode_number: pair
            for pair in resolution.rename_pairs
            for episode_number in (pair.episode_numbers or ((pair.episode_number,) if pair.episode_number is not None else ()))
        }
        matches = {episode_number: match for match in resolution.matches for episode_number in match.episode_numbers}
        matched_numbers = set(matches) & set(pairs)
        unmatched_numbers = {episode.episode_number for episode in due_target.episodes} - matched_numbers
        with db() as conn:
            for episode in due_target.episodes:
                if episode.episode_number in unmatched_numbers:
                    conn.execute(
                        """
                        UPDATE tracking_episodes
                        SET status='retry_wait',matched_file='',source_file='',rename_to='',confidence='',share_url='',
                            last_error='本批资源尚未包含该集，稍后自动重试',updated_at=CURRENT_TIMESTAMP
                        WHERE task_id=? AND episode_number=?
                        """,
                        (task_id, episode.episode_number),
                    )
                    continue
                pair = pairs.get(episode.episode_number)
                match = matches.get(episode.episode_number)
                conn.execute(
                    """
                    UPDATE tracking_episodes
                    SET status=?, matched_file=?, source_file=?, rename_to=?, confidence=?, share_url=?,
                        last_error='', saved_at=CASE WHEN ?='saved' THEN CURRENT_TIMESTAMP ELSE saved_at END,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE task_id=? AND episode_number=?
                    """,
                    (
                        episode_status,
                        match.source.name if match else "",
                        match.source.name if match else "",
                        pair.replacement if pair else "",
                        match.confidence if match else "",
                        resolution.share_url,
                        episode_status,
                        task_id,
                        episode.episode_number,
                    ),
                )
            rows = conn.execute(
                "SELECT episode_number,status FROM tracking_episodes WHERE task_id=?",
                (task_id,),
            ).fetchall()
            statuses = {row["episode_number"]: row["status"] for row in rows}
        next_check = _retry_at(0) if unmatched_numbers else compute_next_check(target, statuses, check_time=task.get("check_time"), progress_floor=progress_floor)
        state = "retry_wait" if execution.confirmed and unmatched_numbers else "idle" if execution.confirmed else "awaiting_confirmation"
        task_message = execution.message
        if unmatched_numbers:
            task_message += f"；当前仍缺失 {len(unmatched_numbers)} 集，现有候选链接已检查完毕"
        _finish_task(
            task_id,
            state,
            task_message,
            next_check,
            retry_count=0 if execution.confirmed else int(task.get("retry_count") or 0),
            current_share_url=resolution.share_url,
        )
        return {
            "ok": True,
            "stage": execution.stage,
            "confirmed": execution.confirmed,
            "matched_episode_count": len(matched_numbers),
            "unmatched_episode_count": len(unmatched_numbers),
            "message": task_message or f"已处理 {len(matched_numbers)} 集",
            "next_check_at": next_check,
            "job_id": int(job_id),
            "provider": source_provider,
            "episode_numbers": sorted(due_numbers),
            "output_filenames": [
                str(pair.replacement or "").strip()
                for pair in resolution.rename_pairs
                if str(pair.replacement or "").strip()
            ],
            "post_processing_ok": post_processing_ok,
        }
    except Exception as exc:
        retries = int(task.get("retry_count") or 0) + 1
        state, next_check = _execution_retry_state(retries)
        _finish_task(task_id, state, str(exc), next_check, retry_count=retries)
        if state == "needs_review" and job_id is not None and not defer_notification:
            _notify_job_once(job_id, str(task.get("title") or "追更任务"), str(exc), None)
        _finish_tracking_run_job(job_id, "failed", "internal_error", "追更执行失败")
        return {"ok": False, "stage": "internal_error", "message": str(exc)}


def prepare_tracking_cycle(task_id: int, *, request_source: str) -> dict:
    """Persist one same-season native-provider cycle before background work."""
    with db() as conn:
        seed = conn.execute("SELECT * FROM tracking_tasks WHERE id=?", (int(task_id),)).fetchone()
        if not seed:
            return {"ok": False, "message": "追更任务不存在"}
        task = dict(seed)
        rows = conn.execute(
            """
            SELECT * FROM tracking_tasks
            WHERE tmdb_id=? AND media_type=? AND season_number=? AND status='active'
              AND provider IN ('quark','qas','p115')
            ORDER BY CASE provider WHEN 'quark' THEN 0 WHEN 'qas' THEN 1 ELSE 2 END
            """,
            (task["tmdb_id"], task["media_type"], task["season_number"]),
        ).fetchall()
        tasks = [dict(row) for row in rows]
        native_quark = next((item for item in tasks if item["provider"] == "quark"), None)
        legacy_quark = next((item for item in tasks if item["provider"] == "qas"), None)
        p115 = next((item for item in tasks if item["provider"] == "p115"), None)
        tasks = [item for item in (native_quark or legacy_quark, p115) if item]
        if not tasks:
            return {"ok": False, "message": "本季没有可执行的网盘追更链路"}
        provider_text = "与".join(_tracking_provider_label(str(item["provider"] or "")) for item in tasks)
        running_message = (
            f"正在并行执行本季{provider_text}原生追更"
            if len(tasks) > 1
            else f"正在执行本季{provider_text}原生追更"
        )
        task_ids = tuple(int(item["id"]) for item in tasks)
        placeholders = ",".join("?" for _ in task_ids)
        active = conn.execute(
            f"""
            SELECT j.id,j.execution_key,COALESCE(j.batch_id,bj.batch_id) AS batch_id
            FROM transfer_jobs j
            LEFT JOIN transfer_batch_jobs bj ON bj.job_id=j.id
            WHERE j.task_id IN ({placeholders})
              AND j.status IN ('running','ready','triggered')
            ORDER BY j.id DESC LIMIT 1
            """,
            task_ids,
        ).fetchone()
        if active:
            tracking_cycle = str(active["execution_key"] or "").startswith("tracking-cycle:")
            return {
                "ok": True,
                "duplicate": True,
                "blocked": not tracking_cycle,
                "batch_id": int(active["batch_id"] or 0),
                "message": "同季首次转存仍在执行，追更巡检将在其完成后继续" if not tracking_cycle else "同季追更链路已在执行",
            }
        batch_id = int(
            conn.execute(
                """
                INSERT INTO transfer_batches(
                    tmdb_id,media_type,display_title,target,status,message,providers_json,seasons_json
                ) VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    task["tmdb_id"],
                    task["media_type"],
                    task.get("title") or "",
                    "cloud",
                    "running",
                    running_message,
                    json.dumps([item["provider"] for item in tasks], ensure_ascii=False),
                    json.dumps([int(task["season_number"] or 0)]),
                ),
            ).lastrowid
        )
        jobs = []
        for item in tasks:
            try:
                job_id = int(
                    conn.execute(
                        """
                        INSERT INTO transfer_jobs(
                            task_id,tmdb_id,media_type,display_title,season_number,target,provider,status,stage,message,
                            save_path,execution_key,request_source,batch_id
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            item["id"],
                            item["tmdb_id"],
                            item["media_type"],
                            item.get("title") or "",
                            item["season_number"],
                            item["save_target"],
                            item["provider"],
                            "running",
                            "checking_saved",
                            "正在准备同季原生追更",
                            item.get("save_path") or "",
                            f"tracking-cycle:{int(item['id'])}",
                            str(request_source or "tracking_scheduler"),
                            batch_id,
                        ),
                    ).lastrowid
                )
            except sqlite3.IntegrityError:
                # The active execution key is stable per tracking task.  If
                # two requests race after the read-side duplicate check, the
                # partial unique index admits exactly one and this transaction
                # must discard its just-created batch instead of leaving an
                # orphan behind.
                conn.rollback()
                existing = conn.execute(
                    f"""
                    SELECT j.id,bj.batch_id FROM transfer_jobs j
                    LEFT JOIN transfer_batch_jobs bj ON bj.job_id=j.id
                    WHERE j.task_id IN ({placeholders}) AND j.status IN ('running','ready','triggered')
                    ORDER BY j.id DESC LIMIT 1
                    """,
                    task_ids,
                ).fetchone()
                if not existing:
                    raise
                return {
                    "ok": True,
                    "duplicate": True,
                    "batch_id": int(existing["batch_id"] or 0),
                    "message": "同季追更链路已在执行",
                }
            conn.execute(
                "INSERT INTO transfer_batch_jobs(batch_id,job_id) VALUES(?,?)",
                (batch_id, job_id),
            )
            jobs.append({
                "task_id": int(item["id"]),
                "job_id": job_id,
                "provider": item["provider"],
                "openlist_fallback_to_p115": bool(item.get("openlist_fallback_to_p115")),
            })
    for item in jobs:
        initialize_media_workflow(
            int(item["job_id"]),
            openlist_fallback_to_p115=bool(item["openlist_fallback_to_p115"]),
        )
    return {
        "ok": True,
        "duplicate": False,
        "batch_id": batch_id,
        "status": "running",
        "message": f"已开始本季{provider_text}原生追更",
        "jobs": jobs,
    }


def run_tracking_cycle(batch_id: int, *, force: bool = False) -> list[dict]:
    """Finish all native lanes, then evaluate the explicit one-way fallback."""
    with db() as conn:
        rows = conn.execute(
            """
            SELECT j.id AS job_id,j.task_id,j.provider,j.status
            FROM transfer_batch_jobs bj
            JOIN transfer_jobs j ON j.id=bj.job_id
            WHERE bj.batch_id=? AND j.task_id IS NOT NULL AND j.provider IN ('quark','qas','p115')
              AND j.execution_key LIKE 'tracking-cycle:%'
            ORDER BY j.id
            """,
            (int(batch_id),),
        ).fetchall()
    jobs = [dict(row) for row in rows]
    if not jobs:
        return []
    # Reconciliation/restart callers may encounter a persisted cycle after its
    # in-process native runners have already exited.  Never submit those lanes
    # again; advance the durable state machine instead.
    if any(str(item.get("status") or "") != "running" for item in jobs):
        return resume_tracking_cycle(batch_id)
    results_by_provider: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=min(2, len(jobs))) as pool:
        future_jobs = {
            pool.submit(
                run_tracking_task,
                int(item["task_id"]),
                force=force,
                job_id=int(item["job_id"]),
                defer_notification=True,
            ): item
            for item in jobs
        }
        for future in as_completed(future_jobs):
            item = future_jobs[future]
            try:
                result = dict(future.result() or {})
            except Exception as exc:
                result = {"ok": False, "stage": "internal_error", "message": type(exc).__name__}
                _finish_tracking_run_job(int(item["job_id"]), "failed", "internal_error", "追更执行失败")
            result.setdefault("job_id", int(item["job_id"]))
            result.setdefault("provider", str(item["provider"] or ""))
            results_by_provider[str(item["provider"] or "")] = result

    # A legacy QAS lane can be confirmed by its background reconciler while a
    # slower P115 future is still running.  The in-memory QAS result is then a
    # stale `confirmed=False` snapshot.  Reload every lane from durable state
    # after all futures exit before deciding fallback or terminal status.
    return resume_tracking_cycle(int(batch_id))


def resume_tracking_cycle(batch_id: int) -> list[dict]:
    """Advance a persisted cycle after provider confirmation or a restart."""
    _resume_pending_tracking_post_processing(int(batch_id))
    results_by_provider = _load_tracking_cycle_results(int(batch_id))
    if not results_by_provider:
        return []
    active = [
        result
        for result in results_by_provider.values()
        if str(result.get("job_status") or "") in {"running", "ready", "triggered"}
        or str(result.get("post_processing_state") or "") in {_POST_PROCESSING_PENDING, _POST_PROCESSING_RUNNING}
        or bool(result.get("post_processing_retryable"))
        or (
            str(result.get("job_status") or "") == "done"
            and result.get("post_processing_ok") is None
        )
    ]
    if active:
        # Reconciliation may race another native lane.  An active child is a
        # hard barrier: keep the batch open and never infer failure, notify, or
        # run fallback until every native child has reached durable terminal
        # state.  Triggered OpenList/P115 confirmation is also handled here.
        with db() as conn:
            conn.execute(
                "UPDATE transfer_batches SET status='running',finished_at=NULL WHERE id=?",
                (int(batch_id),),
            )
        return list(results_by_provider.values())
    fallback = _finish_tracking_cycle_fallback(int(batch_id), results_by_provider)
    results = list(results_by_provider.values())
    if fallback:
        results.append({"provider": "openlist", **fallback})
    _finish_tracking_cycle_batch(int(batch_id), results_by_provider, fallback)
    return results


def resume_tracking_cycle_for_job(job_id: int) -> list[dict]:
    """Advance only when the confirmed/expired job belongs to a tracking cycle."""
    with db() as conn:
        row = conn.execute(
            """
            SELECT bj.batch_id FROM transfer_batch_jobs bj
            JOIN transfer_batches b ON b.id=bj.batch_id
            JOIN transfer_jobs j ON j.id=bj.job_id
            WHERE bj.job_id=? AND b.status='running'
              AND j.execution_key LIKE 'tracking-cycle:%'
            ORDER BY bj.batch_id DESC LIMIT 1
            """,
            (int(job_id),),
        ).fetchone()
    return resume_tracking_cycle(int(row["batch_id"])) if row else []


def run_pending_tracking_post_processing(
    job_id: int,
    *,
    outputs=(),
    title: str = "",
    poster_url: str = "",
    media_year: str = "",
    defer_library_notification: bool = True,
) -> bool | None:
    """Atomically claim and finish one durable tracking post-processing step."""
    supplied_outputs = tuple(dict(item) for item in outputs if isinstance(item, dict))
    exact_outputs: tuple[dict, ...] = ()
    with db() as conn:
        row = conn.execute("SELECT * FROM transfer_jobs WHERE id=?", (int(job_id),)).fetchone()
        claimed = 0
        if row and str(row["external_provider_status"] or "") == _POST_PROCESSING_PENDING:
            job_data = dict(row)
            metadata = _tracking_job_metadata(job_data, "_post_processing")
            has_metadata = _tracking_job_has_metadata(job_data, "_post_processing")
            metadata_outputs = metadata.get("outputs")
            persisted_outputs = tuple(
                dict(item)
                for item in metadata_outputs if isinstance(item, dict)
            ) if isinstance(metadata_outputs, list) else ()
            exact_outputs = supplied_outputs or persisted_outputs
            if not exact_outputs and not has_metadata:
                exact_outputs = tuple({"file_name": name} for name in _expected_tracking_filenames(job_data))
            try:
                attempts = max(0, int(metadata.get("attempts") or 0)) + 1
            except (TypeError, ValueError):
                attempts = 1
            durable_metadata = {
                **metadata,
                "outputs": list(exact_outputs),
                "attempts": attempts,
            }
            claimed = conn.execute(
                """
                UPDATE transfer_jobs
                SET external_provider_status=?,rename_pairs_json=?
                WHERE id=? AND external_provider_status=?
                """,
                (
                    _POST_PROCESSING_RUNNING,
                    _replace_tracking_job_metadata(job_data, "_post_processing", durable_metadata),
                    int(job_id),
                    _POST_PROCESSING_PENDING,
                ),
            ).rowcount
            row = conn.execute("SELECT * FROM transfer_jobs WHERE id=?", (int(job_id),)).fetchone()
        task = (
            conn.execute("SELECT title,poster_url,year FROM tracking_tasks WHERE id=?", (int(row["task_id"]),)).fetchone()
            if row and row["task_id"]
            else None
        )
    if not row:
        return False
    state = str(row["external_provider_status"] or "")
    if not claimed:
        if state in _POST_PROCESSING_SUCCESS:
            return True
        if state == _POST_PROCESSING_FAILED:
            return False
        return None
    provider = str(row["provider"] or "")
    settings = get_settings()
    enabled = bool(getattr(settings, f"{provider}_strm_enabled", False)) if provider in {"p115", "quark"} else False
    try:
        ok = bool(
            run_confirmed_native_transfer_post_processing(
                int(job_id),
                provider=provider,
                save_path=str(row["save_path"] or ""),
                outputs=exact_outputs,
                title=str(title or (task["title"] if task else None) or row["display_title"] or ""),
                poster_url=str(poster_url or (task["poster_url"] if task else None) or ""),
                media_year=str(media_year or (task["year"] if task else None) or ""),
                defer_library_notification=defer_library_notification,
            )
        )
    except Exception:
        ok = False
    final_state = _POST_PROCESSING_SKIPPED if ok and not enabled else _POST_PROCESSING_COMPLETED if ok else _POST_PROCESSING_FAILED
    with db() as conn:
        conn.execute(
            "UPDATE transfer_jobs SET external_provider_status=? WHERE id=? AND external_provider_status=?",
            (final_state, int(job_id), _POST_PROCESSING_RUNNING),
        )
    return ok


def _resume_pending_tracking_post_processing(batch_id: int) -> None:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT j.id FROM transfer_batch_jobs bj
            JOIN transfer_jobs j ON j.id=bj.job_id
            WHERE bj.batch_id=? AND j.execution_key LIKE 'tracking-cycle:%'
              AND j.status='done' AND j.external_provider_status=?
            ORDER BY j.id
            """,
            (int(batch_id), _POST_PROCESSING_PENDING),
        ).fetchall()
    for row in rows:
        run_pending_tracking_post_processing(int(row["id"]), defer_library_notification=True)


def _finish_tracking_cycle_fallback(batch_id: int, results: dict[str, dict]) -> dict | None:
    source_provider = "quark" if "quark" in results else "qas" if "qas" in results else ""
    source_result = results.get(source_provider) or {}
    p115_result = results.get("p115") or {}
    source_job_id = int(source_result.get("job_id") or 0)
    p115_job_id = int(p115_result.get("job_id") or 0)
    p115_requested_numbers = sorted({
        int(number)
        for number in p115_result.get("episode_numbers") or ()
        if int(number) > 0
    })
    if (
        not source_provider
        or not source_result.get("ok")
        or not source_job_id
        or not p115_job_id
        or not p115_requested_numbers
    ):
        return None
    with db() as conn:
        source_job = conn.execute("SELECT * FROM transfer_jobs WHERE id=?", (source_job_id,)).fetchone()
        p115_job = conn.execute("SELECT * FROM transfer_jobs WHERE id=?", (p115_job_id,)).fetchone()
        target_task = conn.execute(
            """
            SELECT * FROM tracking_tasks
            WHERE id=? AND provider='p115' AND openlist_fallback_to_p115=1
            """,
            (int(p115_job["task_id"]) if p115_job else 0,),
        ).fetchone()
    if not source_job or not p115_job or not target_task:
        return None
    fallback_meta = _tracking_job_metadata(dict(p115_job), "_tracking_openlist_fallback")
    if fallback_meta:
        requested = _positive_numbers(fallback_meta.get("requested") or ())
        submitted = _positive_numbers(fallback_meta.get("submitted") or ())
        missing = _positive_numbers(fallback_meta.get("missing") or ())
        status = str(p115_job["status"] or "")
        post_processing_state = str(p115_job["external_provider_status"] or "")
        post_processing_ok = (
            True
            if post_processing_state in _POST_PROCESSING_SUCCESS
            else False
            if post_processing_state == _POST_PROCESSING_FAILED
            else None
        )
        if fallback_meta.get("native_post_processing_failed"):
            post_processing_ok = False
        if status == "triggered":
            return {
                "ok": True,
                "submitted": True,
                "running": True,
                "complete": False,
                "partial": bool(missing),
                "confirmed": False,
                "requested": requested,
                "copied": submitted,
                "skipped": [],
                "missing": missing,
                "message": str(p115_job["message"] or "已提交 OpenList 自动补齐，等待 115 目标目录确认"),
            }
        if status == "done":
            return {
                "ok": True,
                "submitted": True,
                "running": False,
                "complete": not missing and post_processing_ok is True,
                "partial": bool(missing) or post_processing_ok is False,
                "confirmed": True,
                "post_processing_ok": post_processing_ok,
                "requested": requested,
                "copied": submitted,
                "skipped": [],
                "missing": missing,
                "message": str(p115_job["message"] or "115 已确认 OpenList 自动补齐文件"),
            }
        return {
            "ok": False,
            "submitted": bool(submitted),
            "running": False,
            "complete": False,
            "partial": bool(submitted),
            "confirmed": False,
            "requested": requested,
            "copied": submitted,
            "skipped": [],
            "missing": sorted(set(requested) - set(submitted) | set(missing)),
            "message": str(p115_job["message"] or "115 未确认 OpenList 自动补齐文件"),
        }
    confirmed_native_numbers = {
        int(number)
        for number in p115_result.get("matched_episode_numbers") or ()
        if int(number) > 0
    }
    requested_numbers = sorted(set(p115_requested_numbers) - confirmed_native_numbers)
    p115_status = str(p115_job["status"] or "")
    p115_stage = str(p115_job["stage"] or "")
    fallback_eligible = (
        p115_stage in {"no_resource", "source_not_updated"}
        or (
            p115_status == "done"
            and p115_stage in {"provider_completed", "provider_partial"}
            and bool(requested_numbers)
        )
    )
    # A legacy QAS submission is not evidence that the source files exist yet.
    # Storage/provider failures remain hard stops.  Native 115 no-resource,
    # stale-source, and confirmed partial runs may copy only their exact gap.
    if (
        str(source_job["status"] or "") != "done"
        or not requested_numbers
        or not fallback_eligible
    ):
        return None
    result = sync_tracking_fallback_to_p115(
        target_task_id=int(target_task["id"]),
        episode_numbers=requested_numbers,
    )
    copied = set(_positive_numbers(result.get("copied") or ()))
    skipped = set(_positive_numbers(result.get("skipped") or ()))
    handled = (copied | skipped) & set(requested_numbers)
    files_by_episode = {
        int(item.get("episode_number") or 0): str(item.get("file_name") or "").strip()
        for item in result.get("files") or ()
        if isinstance(item, dict) and int(item.get("episode_number") or 0) > 0 and str(item.get("file_name") or "").strip()
    }
    # Exact filenames are mandatory evidence for a bounded P115 reconcile.
    # A copy response without them cannot be promoted to a submitted transfer.
    handled &= set(files_by_episode)
    unresolved = set(requested_numbers) - handled
    result["requested"] = requested_numbers
    result["copied"] = sorted(copied & handled)
    result["skipped"] = sorted(skipped & handled)
    result["missing"] = sorted(unresolved)
    result["complete"] = False
    result["partial"] = bool(handled) and bool(unresolved)
    result["submitted"] = bool(handled)
    result["confirmed"] = False
    result["running"] = bool(handled)
    workflow_status = (
        "running"
        if result.get("running")
        else "review"
        if result["partial"]
        else "failed"
    )
    update_media_workflow_step(
        p115_job_id,
        "openlist_sync",
        workflow_status,
        str(result.get("message") or "OpenList 自动补齐未完成"),
    )
    fallback_job_id = int(result.get("job_id") or 0)
    if fallback_job_id:
        with db() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO transfer_batch_jobs(batch_id,job_id) VALUES(?,?)",
                (int(batch_id), fallback_job_id),
            )
    if handled:
        fallback_metadata = {
            "requested": requested_numbers,
            "submitted": sorted(handled),
            "missing": sorted(unresolved),
            "submitted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "native_post_processing_failed": bool(
                confirmed_native_numbers and p115_result.get("post_processing_ok") is False
            ),
        }
        rename_pairs = [
            {
                "source_name": files_by_episode[number],
                "replacement": files_by_episode[number],
                "episode_number": number,
                "episode_numbers": [number],
            }
            for number in sorted(handled)
        ]
        rename_pairs.append({"_tracking_openlist_fallback": fallback_metadata, "expected_count": len(handled)})
        waiting_message = (
            f"OpenList 已提交 {len(handled)} 集，等待 115 目标目录逐集确认"
            + (f"；另有 {len(unresolved)} 集等待后续重试" if unresolved else "")
        )
        with db() as conn:
            conn.execute(
                """
                UPDATE transfer_jobs
                SET status='triggered',stage='openlist_sync_submitted',message=?,rename_pairs_json=?,
                    external_provider_status='awaiting_confirmation',finished_at=NULL
                WHERE id=?
                """,
                (waiting_message, json.dumps(rename_pairs, ensure_ascii=False), p115_job_id),
            )
        result["message"] = waiting_message
        update_media_workflow_step(p115_job_id, "openlist_sync", "running", waiting_message)
    _apply_tracking_fallback_result(dict(target_task), requested_numbers, result)
    if handled:
        from app.services.qas_reconciler import request_qas_reconciliation

        request_qas_reconciliation()
    return result


def _apply_tracking_fallback_result(target_task: dict, requested_numbers: list[int], result: dict) -> None:
    copied = {int(number) for number in result.get("copied") or () if int(number) > 0}
    skipped = {int(number) for number in result.get("skipped") or () if int(number) > 0}
    handled = (copied | skipped) & set(requested_numbers)
    unresolved = set(requested_numbers) - handled
    filenames = {
        int(item.get("episode_number") or 0): str(item.get("file_name") or "").strip()
        for item in result.get("files") or ()
        if isinstance(item, dict) and int(item.get("episode_number") or 0) > 0 and str(item.get("file_name") or "").strip()
    }
    retry_message = str(result.get("message") or "OpenList 自动补齐未完成")
    with db() as conn:
        for episode_number in handled:
            conn.execute(
                """
                UPDATE tracking_episodes
                SET status='triggered',rename_to=?,source_file=?,last_error='',updated_at=CURRENT_TIMESTAMP
                WHERE task_id=? AND episode_number=?
                """,
                (filenames.get(episode_number, ""), filenames.get(episode_number, ""), int(target_task["id"]), int(episode_number)),
            )
        for episode_number in unresolved:
            conn.execute(
                """
                UPDATE tracking_episodes
                SET status='retry_wait',last_error=?,updated_at=CURRENT_TIMESTAMP
                WHERE task_id=? AND episode_number=?
                """,
                (retry_message[:1000], int(target_task["id"]), int(episode_number)),
            )
        current = conn.execute(
            "SELECT retry_count FROM tracking_tasks WHERE id=?",
            (int(target_task["id"]),),
        ).fetchone()
    _finish_task(
        int(target_task["id"]),
        "awaiting_confirmation" if handled else "retry_wait",
        "" if handled and not unresolved else retry_message,
        "" if handled else _retry_at(0),
        retry_count=0 if handled else int(current["retry_count"] or 0) if current else 0,
    )


def _finish_tracking_cycle_batch(batch_id: int, results: dict[str, dict], fallback: dict | None) -> None:
    lanes = list(results.values())
    waiting_lane = next(
        (
            result
            for result in lanes
            if result.get("ok") and result.get("confirmed") is False
        ),
        None,
    )
    if waiting_lane or (fallback and fallback.get("running")):
        message = (
            str(fallback.get("message") or "正在等待 115 确认 OpenList 自动补齐文件")
            if fallback and fallback.get("running")
            else f"正在等待 {_tracking_provider_label(str((waiting_lane or {}).get('provider') or ''))} 目标目录确认"
        )
        with db() as conn:
            conn.execute(
                "UPDATE transfer_batches SET status='running',message=?,finished_at=NULL WHERE id=?",
                (message, int(batch_id)),
            )
        return
    complete_lanes = [
        result
        for result in lanes
        if result.get("ok")
        and result.get("confirmed") is not False
        and result.get("post_processing_ok") is True
        and int(result.get("unmatched_episode_count") or 0) == 0
    ]
    source = results.get("quark") or results.get("qas") or {}
    source_complete = (
        bool(source.get("ok"))
        and source.get("confirmed") is not False
        and source.get("post_processing_ok") is True
        and int(source.get("unmatched_episode_count") or 0) == 0
    )
    post_processing_failed = any(result.get("post_processing_ok") is False for result in lanes) or bool(
        fallback and fallback.get("post_processing_ok") is False
    )
    if post_processing_failed:
        status = "partial"
        message = "转存完成但 STRM/Emby 后处理未完成"
    elif fallback and fallback.get("complete") and source_complete:
        status = "done"
        message = "夸克已有对应集；115 原生无资源，OpenList 自动补齐已确认并完成后处理"
    elif fallback:
        status = "partial" if complete_lanes or fallback.get("complete") or fallback.get("partial") or fallback.get("running") else "failed"
        message = (
            "已提交 115 OpenList 自动补齐，但夸克原生链路仍有未覆盖集"
            if fallback.get("complete") and not source_complete
            else str(fallback.get("message") or "OpenList 自动补齐未完成")
        )
    elif lanes and len(complete_lanes) == len(lanes):
        status = "done"
        providers = [str(result.get("provider") or "") for result in complete_lanes]
        if len(providers) == 1:
            message = f"{_tracking_provider_label(providers[0])}原生追更已完成"
        else:
            message = "夸克与 115 原生追更均已完成"
    elif any(str(result.get("stage") or "") == "needs_review" for result in lanes):
        status = "needs_review"
        message = "本季追更需要人工确认"
    elif str((results.get("p115") or {}).get("resolution_stage") or "") == "no_resource":
        status = "partial" if complete_lanes else "failed"
        message = "115 原生未找到资源，且本轮未满足 OpenList 自动补齐条件"
    else:
        status = "partial" if any(result.get("ok") for result in lanes) else "failed"
        message = "本季追更部分完成" if status == "partial" else "本季追更未完成"
    if not fallback:
        p115_job_id = int((results.get("p115") or {}).get("job_id") or 0)
        if p115_job_id:
            update_media_workflow_step(
                p115_job_id,
                "openlist_sync",
                "skipped",
                "本轮未满足夸克已有且 115 原生无资源的自动补齐条件",
            )
    with db() as conn:
        conn.execute(
            """
            UPDATE transfer_batches SET status=?,message=?,finished_at=CURRENT_TIMESTAMP WHERE id=?
            """,
            (status, message, int(batch_id)),
        )
        batch = conn.execute(
            "SELECT display_title FROM transfer_batches WHERE id=?",
            (int(batch_id),),
        ).fetchone()
        conn.execute(
            """
            UPDATE transfer_jobs SET notification_sent_at=COALESCE(notification_sent_at,CURRENT_TIMESTAMP)
            WHERE id IN (SELECT job_id FROM transfer_batch_jobs WHERE batch_id=?)
            """,
            (int(batch_id),),
        )
    material_activity = any(_tracking_result_has_transfer(result) for result in lanes) or bool(
        fallback and fallback.get("confirmed") and fallback.get("submitted")
    )
    needs_attention = status == "needs_review" or post_processing_failed
    if material_activity or needs_attention:
        notification_type = "success" if status == "done" else "warning" if status in {"partial", "needs_review"} else "error"
        title_suffix = "已完成" if status == "done" else "需要确认" if status == "needs_review" else "部分完成" if status == "partial" else "未完成"
        add_notification(
            f"tracking-cycle:{int(batch_id)}:terminal",
            notification_type,
            f"{str(batch['display_title'] or '媒体') if batch else '媒体'} 本季追更{title_suffix}",
            message,
            action_page="review" if status == "needs_review" else "tracking",
        )


def _load_tracking_cycle_results(batch_id: int) -> dict[str, dict]:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT j.* FROM transfer_batch_jobs bj
            JOIN transfer_jobs j ON j.id=bj.job_id
            WHERE bj.batch_id=? AND j.task_id IS NOT NULL
              AND j.provider IN ('quark','qas','p115')
              AND j.execution_key LIKE 'tracking-cycle:%'
            ORDER BY j.id
            """,
            (int(batch_id),),
        ).fetchall()
    results: dict[str, dict] = {}
    for raw in rows:
        job = dict(raw)
        provider = str(job.get("provider") or "")
        metadata = _tracking_job_metadata(job, "_tracking_cycle")
        requested = set(_positive_numbers(metadata.get("requested") or ()))
        matched: set[int] = set()
        try:
            pairs = json.loads(job.get("rename_pairs_json") or "[]")
        except (json.JSONDecodeError, TypeError):
            pairs = []
        for pair in pairs if isinstance(pairs, list) else ():
            if not isinstance(pair, dict) or "_tracking_openlist_fallback" in pair:
                continue
            matched.update(_positive_numbers(pair.get("episode_numbers") or ()))
            if pair.get("episode_number") is not None:
                matched.update(_positive_numbers((pair.get("episode_number"),)))
        fallback_meta = _tracking_job_metadata(job, "_tracking_openlist_fallback")
        if fallback_meta:
            requested = set(_positive_numbers(fallback_meta.get("requested") or ()))
            matched = set(_positive_numbers(fallback_meta.get("submitted") or ()))
        status = str(job.get("status") or "")
        stage = str(job.get("stage") or "")
        post_processing_state = str(job.get("external_provider_status") or "")
        result = {
            "ok": status in {"done", "triggered"},
            "stage": stage,
            "resolution_stage": stage,
            "confirmed": status == "done",
            "matched_episode_count": len(matched),
            "unmatched_episode_count": len(requested - matched),
            "message": str(job.get("message") or ""),
            "job_id": int(job["id"]),
            "provider": provider,
            "job_status": status,
            "post_processing_state": post_processing_state,
            "post_processing_retryable": _post_processing_retryable_job(job),
            "episode_numbers": sorted(requested),
            "matched_episode_numbers": sorted(matched),
            "output_filenames": _expected_tracking_filenames(job),
            "post_processing_ok": (
                True
                if post_processing_state in _POST_PROCESSING_SUCCESS
                else False
                if post_processing_state == _POST_PROCESSING_FAILED
                else None
            ),
        }
        results[provider] = result
    return results


def _tracking_pairs_json(rename_pairs, target: MediaTarget) -> str:
    values = [dict(pair.__dict__) for pair in rename_pairs]
    values.append(
        {
            "_tracking_cycle": {
                "requested": sorted({int(episode.episode_number) for episode in target.episodes if int(episode.episode_number) > 0})
            }
        }
    )
    return json.dumps(values, ensure_ascii=False)


def _tracking_job_metadata(job: dict, key: str) -> dict:
    try:
        pairs = json.loads(job.get("rename_pairs_json") or "[]")
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(pairs, list):
        return {}
    for item in pairs:
        if isinstance(item, dict) and isinstance(item.get(key), dict):
            return dict(item[key])
    return {}


def _tracking_job_has_metadata(job: dict, key: str) -> bool:
    try:
        pairs = json.loads(job.get("rename_pairs_json") or "[]")
    except (json.JSONDecodeError, TypeError):
        return False
    return bool(
        isinstance(pairs, list)
        and any(isinstance(item, dict) and key in item for item in pairs)
    )


def _replace_tracking_job_metadata(job: dict, key: str, value: dict) -> str:
    try:
        raw_pairs = json.loads(job.get("rename_pairs_json") or "[]")
    except (json.JSONDecodeError, TypeError):
        raw_pairs = []
    pairs = list(raw_pairs) if isinstance(raw_pairs, list) else []
    for index, item in enumerate(pairs):
        if isinstance(item, dict) and key in item:
            pairs[index] = {**item, key: dict(value)}
            break
    else:
        pairs.append({key: dict(value)})
    return json.dumps(pairs, ensure_ascii=False)


def _post_processing_retryable_job(job: dict) -> bool:
    if str(job.get("external_provider_status") or "") != _POST_PROCESSING_FAILED:
        return False
    metadata = _tracking_job_metadata(job, "_post_processing")
    outputs = metadata.get("outputs")
    try:
        attempts = max(0, int(metadata.get("attempts") or 0))
    except (TypeError, ValueError):
        attempts = 0
    return bool(isinstance(outputs, list) and any(isinstance(item, dict) for item in outputs)) and attempts < _POST_PROCESSING_MAX_ATTEMPTS


def post_processing_retryable(job_id: int) -> bool:
    """Return whether a failed exact-output post step owns one durable retry."""
    with db() as conn:
        row = conn.execute("SELECT * FROM transfer_jobs WHERE id=?", (int(job_id),)).fetchone()
    return _post_processing_retryable_job(dict(row)) if row else False


def _expected_tracking_filenames(job: dict) -> list[str]:
    try:
        pairs = json.loads(job.get("rename_pairs_json") or "[]")
    except (json.JSONDecodeError, TypeError):
        return []
    return list(
        dict.fromkeys(
            str(item.get("replacement") or "").strip()
            for item in pairs if isinstance(item, dict) and str(item.get("replacement") or "").strip()
        )
    )


def _positive_numbers(values) -> list[int]:
    numbers: set[int] = set()
    for value in values:
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number > 0:
            numbers.add(number)
    return sorted(numbers)


def _tracking_result_has_transfer(result: dict) -> bool:
    if result.get("confirmed") is not True:
        return False
    if str(result.get("stage") or "") in {"not_due", "no_resource", "source_not_updated", "retry_wait"}:
        return False
    return bool(
        int(result.get("matched_episode_count") or 0) > 0
        or result.get("output_filenames")
    )


def _tracking_provider_label(provider: str) -> str:
    return "115" if provider == "p115" else "夸克" if provider in {"quark", "qas"} else "网盘"


def run_due_tracking_tasks(limit: int = 3) -> list[dict]:
    refresh_tracking_metadata()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db() as conn:
        rows = conn.execute(
            """
            SELECT id,tmdb_id,media_type,season_number FROM tracking_tasks
            WHERE status='active'
              AND decision_state NOT IN ('running','needs_review','awaiting_confirmation')
              AND next_check_at IS NOT NULL AND next_check_at!='' AND next_check_at<=?
            ORDER BY next_check_at LIMIT ?
            """,
            (now, limit),
        ).fetchall()
    results: list[dict] = []
    handled_groups: set[tuple[int, str, int]] = set()
    for raw in rows:
        row = dict(raw)
        group = (int(row["tmdb_id"]), str(row["media_type"]), int(row["season_number"] or 0))
        if group in handled_groups:
            continue
        handled_groups.add(group)
        active_executions = _active_tracking_group_executions(group)
        # Discovery/detail first-transfer children may already be moving the
        # same season after registration.  They are not tracking-cycle jobs,
        # so neither prepare_tracking_cycle nor its stable execution key can
        # deduplicate them.  Let that user-requested transfer finish before a
        # scheduled patrol is allowed to inspect or submit the season again.
        if active_executions["ordinary"]:
            continue
        with db() as conn:
            enabled_fallback = conn.execute(
                """
                SELECT id FROM tracking_tasks
                WHERE tmdb_id=? AND media_type=? AND season_number=? AND provider='p115'
                  AND status='active' AND openlist_fallback_to_p115=1
                LIMIT 1
                """,
                group,
            ).fetchone()
        if active_executions["tracking"] and not enabled_fallback:
            continue
        if enabled_fallback:
            cycle = prepare_tracking_cycle(int(row["id"]), request_source="tracking_scheduler")
            if cycle.get("ok"):
                if cycle.get("duplicate"):
                    if cycle.get("blocked"):
                        results.append(cycle)
                    else:
                        results.extend(resume_tracking_cycle(int(cycle["batch_id"])))
                else:
                    results.extend(run_tracking_cycle(int(cycle["batch_id"]), force=False))
            else:
                results.append(cycle)
            continue
        group_rows = [
            candidate
            for candidate in rows
            if (
                int(candidate["tmdb_id"]),
                str(candidate["media_type"]),
                int(candidate["season_number"] or 0),
            ) == group
        ]
        results.extend(run_tracking_task(int(candidate["id"])) for candidate in group_rows)
    return results


def _active_tracking_group_executions(group: tuple[int, str, int]) -> dict[str, bool]:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT j.execution_key FROM tracking_tasks t
            JOIN transfer_jobs j ON j.task_id=t.id
            LEFT JOIN transfer_batch_jobs bj ON bj.job_id=j.id
            LEFT JOIN transfer_batches b ON b.id=bj.batch_id
            WHERE t.tmdb_id=? AND t.media_type=? AND t.season_number=?
              AND j.status IN ('running','ready','triggered')
            """,
            group,
        ).fetchall()
    tracking = False
    ordinary = False
    for row in rows:
        if str(row["execution_key"] or "").startswith("tracking-cycle:"):
            tracking = True
        else:
            ordinary = True
    return {"tracking": tracking, "ordinary": ordinary}


def refresh_tracking_task_metadata(task_id: int, target: MediaTarget | None = None) -> dict:
    """Refresh TMDB episodes and wake a task only when new episodes appeared."""
    with db() as conn:
        task_row = conn.execute("SELECT * FROM tracking_tasks WHERE id=?", (task_id,)).fetchone()
        previous_rows = conn.execute(
            "SELECT episode_number,status FROM tracking_episodes WHERE task_id=?",
            (task_id,),
        ).fetchall()
    if not task_row:
        return {"ok": False, "task_id": task_id, "message": "追更任务不存在"}
    task = dict(task_row)
    resolved = target or resolve_media_target(
        task["tmdb_id"],
        task["media_type"],
        task["season_number"],
        category=task.get("category") or "",
    )
    previous_numbers = {int(row["episode_number"]) for row in previous_rows}
    sync_tracking_episodes(task_id, resolved, provider=task.get("provider") or "")
    current_numbers = {episode.episode_number for episode in resolved.episodes}
    added_numbers = sorted(current_numbers - previous_numbers)
    next_check = task.get("next_check_at") or ""
    if added_numbers and task.get("decision_state") not in {"running", "needs_review", "awaiting_confirmation", "paused"}:
        with db() as conn:
            rows = conn.execute(
                "SELECT episode_number,status FROM tracking_episodes WHERE task_id=?",
                (task_id,),
            ).fetchall()
            statuses = {int(row["episode_number"]): str(row["status"]) for row in rows}
        progress_floor = max(
            int(task.get("auto_start_episode") or 0),
            int(task.get("last_saved_episode") or 0),
        )
        next_check = compute_next_check(
            resolved,
            statuses,
            check_time=task.get("check_time"),
            progress_floor=progress_floor,
        )
        with db() as conn:
            conn.execute(
                "UPDATE tracking_tasks SET next_check_at=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (next_check or None, task_id),
            )
    return {
        "ok": True,
        "task_id": task_id,
        "added_episode_numbers": added_numbers,
        "next_check_at": next_check,
    }


def refresh_tracking_metadata() -> list[dict]:
    """Refresh active TMDB seasons before deciding which tracking tasks are due."""
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM tracking_tasks WHERE status='active' ORDER BY id"
        ).fetchall()
    target_cache: dict[tuple[int, str, int, str], MediaTarget] = {}
    results: list[dict] = []
    for raw in rows:
        task = dict(raw)
        key = (
            int(task["tmdb_id"]),
            str(task["media_type"]),
            int(task["season_number"] or 0),
            str(task.get("category") or ""),
        )
        try:
            target = target_cache.get(key)
            if target is None:
                target = resolve_media_target(key[0], key[1], key[2], category=key[3])
                target_cache[key] = target
            results.append(refresh_tracking_task_metadata(int(task["id"]), target))
        except Exception as exc:
            results.append({"ok": False, "task_id": int(task["id"]), "message": type(exc).__name__})
    return results


def _handle_resolution_failure(
    task: dict,
    target: MediaTarget,
    resolution,
    job_id: int,
    qas: QasClient,
    *,
    notify: bool = True,
) -> dict:
    with db() as conn:
        episode_state = "needs_review" if resolution.stage == "needs_review" else "retry_wait"
        for episode in target.episodes:
            conn.execute(
                """
                UPDATE tracking_episodes SET status=?, retry_count=retry_count+1, last_error=?, updated_at=CURRENT_TIMESTAMP
                WHERE task_id=? AND episode_number=?
                """,
                (episode_state, resolution.message, task["id"], episode.episode_number),
            )
        conn.execute(
            "UPDATE transfer_jobs SET status=?, stage=?, message=?, finished_at=CURRENT_TIMESTAMP WHERE id=?",
            (episode_state, resolution.stage, resolution.message, job_id),
        )
    complete_transfer_workflow_step(
        int(job_id),
        "needs_review" if episode_state == "needs_review" else "failed",
        str(resolution.stage or ""),
        str(resolution.message or ""),
    )
    retries = int(task.get("retry_count") or 0) + 1
    # Waiting for an upload after TMDB's release date is normal. It obeys the
    # configured interval, but never becomes an artificial review task.
    source_not_updated = resolution.stage == "source_not_updated"
    # An inspected share that only contains older files is a normal publication
    # delay, not an ambiguity for the user to resolve. Keep retrying quietly no
    # matter how many checks have already happened; a later search result will
    # be validated again against the due TMDB episodes.
    needs_review = _resolution_needs_review(resolution.stage)
    state = "needs_review" if needs_review else "retry_wait"
    if source_not_updated:
        # Upload timing can lag TMDB by minutes or hours; use the same fixed
        # interval as other retryable tracking failures.
        next_check = "" if needs_review else _retry_at(retries - 1)
    else:
        next_check = "" if needs_review else _retry_at(retries - 1)
    _finish_task(task["id"], state, resolution.message, next_check, retry_count=retries)
    if needs_review and notify:
        _notify_job_once(job_id, target.title, resolution.message, qas)
    return {
        "ok": False,
        "stage": state,
        "resolution_stage": str(resolution.stage or ""),
        "message": resolution.message,
        "next_check_at": next_check,
        "job_id": int(job_id),
        "provider": str(task.get("provider") or ""),
        "episode_numbers": sorted(episode.episode_number for episode in target.episodes),
    }


def _handle_execution_failure(
    task: dict,
    target: MediaTarget,
    message: str,
    job_id: int,
    qas: QasClient,
    *,
    notify: bool = True,
) -> dict:
    retries = int(task.get("retry_count") or 0) + 1
    state, next_check = _execution_retry_state(retries)
    with db() as conn:
        for episode in target.episodes:
            conn.execute(
                """
                UPDATE tracking_episodes SET status=?, retry_count=retry_count+1, last_error=?, updated_at=CURRENT_TIMESTAMP
                WHERE task_id=? AND episode_number=?
                """,
                (state, message, task["id"], episode.episode_number),
            )
    _finish_task(task["id"], state, message, next_check, retry_count=retries)
    if state == "needs_review" and notify:
        _notify_job_once(job_id, target.title, message, qas)
    return {
        "ok": False,
        "stage": state,
        "message": message,
        "next_check_at": next_check,
        "job_id": int(job_id),
        "provider": str(task.get("provider") or ""),
        "episode_numbers": sorted(episode.episode_number for episode in target.episodes),
    }


def _record_tracking_job(task: dict, target: MediaTarget, resolution) -> int:
    episode_key = ",".join(str(ep.episode_number) for ep in target.episodes)
    provider = str(task.get("provider") or "")
    legacy_execution_key = f"tracking:{task['id']}:{target.season_number or 0}:{episode_key}:{task['save_target']}"
    execution_key = (
        f"{legacy_execution_key}:{provider}"
    )
    with db() as conn:
        existing = conn.execute(
            "SELECT id,status FROM transfer_jobs WHERE execution_key IN (?,?) ORDER BY id DESC LIMIT 1",
            (execution_key, legacy_execution_key),
        ).fetchone()
        if existing:
            if existing["status"] in {"running", "triggered", "done"}:
                raise RuntimeError("同一批追更任务正在处理或已经完成")
            conn.execute(
                """
                UPDATE candidates SET decision='superseded'
                WHERE job_id=? AND COALESCE(decision,'pending')='pending'
                """,
                (existing["id"],),
            )
            conn.execute(
                """
                UPDATE transfer_jobs
                SET execution_key=?,status='failed',stage='superseded',review_state='resolved',
                    message='已由同批次的重新搜索替代',finished_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (f"{execution_key}:archived:{existing['id']}", existing["id"]),
            )
        cur = conn.execute(
            """
            INSERT INTO transfer_jobs(task_id,tmdb_id,media_type,season_number,target,provider,status,stage,message,
                                      share_url,source_file,renamed_file,rename_pairs_json,save_path,execution_key)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                task["id"],
                target.tmdb_id,
                target.media_type,
                target.season_number,
                task["save_target"],
                provider,
                "ready" if resolution.ok else "failed",
                resolution.stage,
                resolution.message,
                resolution.share_url,
                resolution.rename_pairs[0].source_name if resolution.rename_pairs else "",
                resolution.rename_pairs[0].replacement if resolution.rename_pairs else "",
                _tracking_pairs_json(resolution.rename_pairs, target),
                task["save_path"],
                # Tracking may legitimately catch up later episodes while an
                # older QAS job is still being reconciled.  Scope idempotency
                # to this task and exact episode batch so an old E01 job does
                # not block E02-E04, while a retry of the same batch is still
                # deduplicated by the unique index.
                execution_key,
            ),
        )
        return int(cur.lastrowid)


def _update_tracking_run_resolution(job_id: int, task: dict, target: MediaTarget, resolution) -> None:
    """Attach resolution evidence to the run record created before slow work."""
    with db() as conn:
        conn.execute(
            """
            UPDATE transfer_jobs
            SET tmdb_id=?,media_type=?,display_title=?,season_number=?,target=?,provider=?,
                stage=?,message=?,share_url=?,source_file=?,renamed_file=?,rename_pairs_json=?,save_path=?
            WHERE id=? AND status='running'
            """,
            (
                target.tmdb_id,
                target.media_type,
                target.title,
                target.season_number,
                task["save_target"],
                str(task.get("provider") or ""),
                resolution.stage,
                resolution.message,
                resolution.share_url,
                resolution.rename_pairs[0].source_name if resolution.rename_pairs else "",
                resolution.rename_pairs[0].replacement if resolution.rename_pairs else "",
                _tracking_pairs_json(resolution.rename_pairs, target),
                task["save_path"],
                job_id,
            ),
        )
    update_media_workflow_progress(int(job_id), str(resolution.stage or ""), str(resolution.message or ""))


def _finish_tracking_run_job(job_id: int | None, status: str, stage: str, message: str) -> None:
    if job_id is None:
        return
    with db() as conn:
        conn.execute(
            """
            UPDATE transfer_jobs
            SET status=?,stage=?,message=?,
                external_provider_status=CASE
                    WHEN ?='done' AND COALESCE(external_provider_status,'')='' THEN ?
                    ELSE external_provider_status
                END,
                finished_at=CASE WHEN ? IN ('done','failed','needs_review') THEN CURRENT_TIMESTAMP ELSE finished_at END
            WHERE id=? AND status='running'
            """,
            (status, stage, message[:1000], status, _POST_PROCESSING_SKIPPED, status, job_id),
        )
    complete_transfer_workflow_step(int(job_id), status, stage, message)


def _record_candidates(job_id: int, candidates) -> None:
    if not candidates:
        return
    with db() as conn:
        conn.executemany(
            """
            INSERT INTO candidates(job_id,share_url,source_title,search_query,source,cloud_type,provider,published_at,
                                   file_count,files_json,score,rejected,reasons_json)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            [
                (
                    job_id,
                    candidate.share_url,
                    candidate.title,
                    candidate.query,
                    candidate.source,
                    candidate.cloud_type or "quark",
                    candidate.provider or "qas",
                    candidate.published_at,
                    len(candidate.files),
                    json.dumps(candidate.files, ensure_ascii=False),
                    candidate.score,
                    1 if candidate.rejected else 0,
                    json.dumps(candidate.reasons, ensure_ascii=False),
                )
                for candidate in candidates
            ],
        )


def _update_tracking_job_execution(job_id: int, execution, *, post_processing_state: str = "") -> None:
    status = "done" if execution.confirmed else "triggered" if execution.ok else "failed"
    with db() as conn:
        conn.execute(
            """
            UPDATE transfer_jobs SET status=?,stage=?,message=?,external_provider_status=?,
                finished_at=CASE WHEN ? IN ('done','failed') THEN CURRENT_TIMESTAMP ELSE finished_at END
            WHERE id=?
            """,
            (status, execution.stage, execution.message, post_processing_state, status, job_id),
        )
    complete_transfer_workflow_step(int(job_id), status, str(execution.stage or ""), str(execution.message or ""))


def _finish_task(
    task_id: int,
    state: str,
    error: str,
    next_check_at: str,
    *,
    retry_count: int | None = None,
    increment_retry: bool = False,
    current_share_url: str | None = None,
) -> None:
    with db() as conn:
        current = conn.execute("SELECT retry_count,current_share_url FROM tracking_tasks WHERE id=?", (task_id,)).fetchone()
        retries = int(current["retry_count"] or 0) if current else 0
        if retry_count is not None:
            retries = retry_count
        elif increment_retry:
            retries += 1
        share_url = current_share_url if current_share_url is not None else (current["current_share_url"] if current else "")
        conn.execute(
            """
            UPDATE tracking_tasks SET decision_state=?,last_error=?,next_check_at=?,retry_count=?,
                                      current_share_url=?,last_checked_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (state, error[:1000], next_check_at or None, retries, share_url, task_id),
        )


def _retry_at(retry_index: int) -> str:
    interval_minutes = max(1, int(get_settings().tracking_retry_interval_minutes))
    return (datetime.now(timezone.utc) + timedelta(minutes=interval_minutes)).isoformat(timespec="seconds")


def _execution_retry_state(retries: int) -> tuple[str, str]:
    """Apply the configured cap to real execution failures, not publication delays."""
    if retries >= max(1, int(get_settings().tracking_max_retries)):
        return "needs_review", ""
    return "retry_wait", _retry_at(retries - 1)


def _disable_qas_schedules_if_configured(target: MediaTarget, qas_client: object) -> None:
    if bool(getattr(qas_client, "configured", lambda: False)()):
        disable_compatible_qas_schedules(target, qas_client)


def _uses_legacy_openlist_auto_sync(provider: str) -> bool:
    """Compatibility predicate retained for extensions; tracking no longer calls it."""
    return str(provider or "").strip().lower() in {"qas", "p115"}


def _parse_air_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def _parse_check_time(value: str | None, fallback_hour: int | str) -> time:
    try:
        parsed = time.fromisoformat(str(value or ""))
        return time(hour=parsed.hour, minute=parsed.minute)
    except (TypeError, ValueError):
        try:
            parsed = time.fromisoformat(str(fallback_hour))
            return time(hour=parsed.hour, minute=parsed.minute)
        except (TypeError, ValueError):
            return time(hour=max(0, min(int(fallback_hour), 23)))


def _air_date_has_reached_check_time(value: str, local_now: datetime, configured_time: time) -> bool:
    air_date = _parse_air_date(value)
    if air_date is None:
        return False
    return datetime.combine(air_date, configured_time, tzinfo=local_now.tzinfo) <= local_now


def _due_episode_numbers(
    episodes: list[dict],
    last_saved_episode: int,
    local_now: datetime,
    configured_time: time,
    *,
    force: bool = False,
    exact_saved_episode_numbers: set[int] | None = None,
) -> set[int]:
    due_statuses = {"pending", "retry_wait", "failed"}
    if force:
        # A user-triggered check is also an explicit request to retry stale or
        # dismissed review items. Automatic schedules still leave active
        # review work untouched.
        due_statuses.add("needs_review")
    return {
        int(row["episode_number"])
        for row in episodes
        if row["status"] in due_statuses
        and (
            int(row["episode_number"]) not in exact_saved_episode_numbers
            if exact_saved_episode_numbers is not None
            else int(row["episode_number"]) > last_saved_episode
        )
        # A manual run may bypass today's configured release time, but it must
        # never turn a future TMDB air date into a released episode.  Otherwise
        # a variety-show file such as "第4期上" gets compared with several
        # future episode ordinals and is incorrectly sent to review as 0/N.
        and (air_date := _parse_air_date(row.get("air_date", ""))) is not None
        and air_date <= local_now.date()
        and (force or _air_date_has_reached_check_time(row["air_date"], local_now, configured_time))
    }


def _manual_due_episode_numbers(episodes: list[dict], requested: set[int], local_now: datetime) -> set[int]:
    """Return explicitly selected, aired episodes without applying auto-follow thresholds."""
    return {
        int(row["episode_number"])
        for row in episodes
        if int(row["episode_number"]) in requested
        and row["status"] != "saved"
        and (air_date := _parse_air_date(row.get("air_date", ""))) is not None
        and air_date <= local_now.date()
    }


def _resolution_needs_review(stage: str) -> bool:
    # Search availability is not something a user can resolve. A review is
    # created only when validation found real, current files but could not map
    # them safely. Empty or stale search results remain scheduled retries.
    return stage == "needs_review"


def _expired_share_urls(task_id: int) -> tuple[str, ...]:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT share_url FROM transfer_jobs
            WHERE task_id=? AND status='failed' AND message LIKE '%4100018%' AND COALESCE(share_url,'')!=''
            ORDER BY id DESC LIMIT 20
            """,
            (task_id,),
        ).fetchall()
    return tuple(str(row["share_url"]) for row in rows)


def _legacy_qas_progress_floor(task: dict) -> int:
    """Keep a provider migration from replaying an old local QAS tracking task.

    Older installations represented QAS tracking as a ``local`` target with
    no provider value.  When the new QAS provider row has just been enabled,
    its configured cloud folder can be empty even though that legacy task has
    already advanced.  That legacy high-water mark is a safety floor only: it
    prevents automatic replay; a user can still choose earlier episodes via
    manual catch-up.
    """
    if task.get("provider") != "qas" or task.get("save_target") != "cloud":
        return 0
    with db() as conn:
        row = conn.execute(
            """
            SELECT MAX(last_saved_episode) AS value
            FROM tracking_tasks
            WHERE tmdb_id=? AND media_type=? AND season_number=?
              AND save_target='local' AND COALESCE(provider,'')=''
            """,
            (task["tmdb_id"], task["media_type"], task["season_number"]),
        ).fetchone()
    return int(row["value"] or 0) if row else 0


def _notify_job_once(job_id: int, title: str, message: str, qas: QasClient | None) -> None:
    with db() as conn:
        row = conn.execute("SELECT notification_sent_at FROM transfer_jobs WHERE id=?", (job_id,)).fetchone()
    if row and row["notification_sent_at"]:
        return
    result = notify_review_required(title, message, job_id, qas=qas)
    with db() as conn:
        conn.execute(
            """
            UPDATE transfer_jobs SET review_state=?,
                notification_sent_at=CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE notification_sent_at END
            WHERE id=?
            """,
            ("notified" if result.sent else "notification_failed", 1 if result.sent else 0, job_id),
        )
