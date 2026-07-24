from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.clients.pansou import PansouClient
from app.clients.qas import QasClient
from app.clients.tmdb import TmdbClient
from app.core.config import get_settings
from app.db.database import db
from app.domain.media import MediaTarget
from app.services.link_resolver import resolve_episode_source
from app.services.episode_naming import adapt_resolution_to_existing_episode_names
from app.services.media_target import resolve_media_target
from app.services.paths import build_save_path
from app.services.saved_episode_scanner import refresh_saved_episodes
from app.services.previous_source import recover_previous_share_urls
from app.services.qas_executor import disable_compatible_qas_schedules
from app.services.review_notification import notify_review_required
from app.providers.base import TransferPlan
from app.providers.registry import get_transfer_provider


RETRY_HOURS = (1, 2, 4, 8, 12)


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
) -> str:
    settings = get_settings()
    zone = ZoneInfo(timezone_name or settings.tracking_timezone)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    local_now = current.astimezone(zone)
    configured_time = _parse_check_time(check_time, settings.tracking_check_hour if check_hour is None else check_hour)

    due_statuses = {"pending", "retry_wait", "failed"}
    future_checks: list[datetime] = []
    has_unconfirmed_air_date = False
    for episode in target.episodes:
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
) -> dict:
    with db() as conn:
        task_row = conn.execute("SELECT * FROM tracking_tasks WHERE id=?", (task_id,)).fetchone()
        if not task_row:
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
            return {"ok": False, "stage": "not_runnable"}

    try:
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
        canonical_save_path = build_save_path(
            task["save_target"],
            target.category or target.media_type,
            target.title,
            target.series_year,
            target.season_number,
            task.get("provider") or "qas",
        )
        if task.get("save_path") != canonical_save_path:
            with db() as conn:
                conn.execute(
                    "UPDATE tracking_tasks SET save_path=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (canonical_save_path, task_id),
                )
            task["save_path"] = canonical_save_path
        disable_compatible_qas_schedules(target, qas_client)
        sync_tracking_episodes(task_id, target, provider=task.get("provider") or "")
        storage = refresh_saved_episodes(task_id, qas=transfer_provider)
        if not storage.get("ok"):
            _finish_task(task_id, "retry_wait", storage.get("message", "读取目标目录失败"), _retry_at(1), retry_count=int(task.get("retry_count") or 0) + 1)
            return {"ok": False, "stage": "storage_check_failed", "message": storage.get("message", "读取目标目录失败")}
        task["save_path"] = storage.get("save_path") or task["save_path"]
        with db() as conn:
            rows = conn.execute(
                "SELECT * FROM tracking_episodes WHERE task_id=? ORDER BY episode_number",
                (task_id,),
            ).fetchall()
            episodes = [dict(row) for row in rows]

        zone = ZoneInfo(get_settings().tracking_timezone)
        local_now = datetime.now(zone)
        configured_time = _parse_check_time(task.get("check_time"), get_settings().tracking_check_hour)
        last_saved_episode = int(storage.get("last_saved_episode") or 0)
        if selected_episode_numbers:
            requested = {int(number) for number in selected_episode_numbers if int(number) > 0}
            # Catch-up is the sole route allowed to work on episodes at or
            # before the destination's current progress.  A regular manual
            # run is still an automatic follow-up run, not a backfill.
            due_numbers = _manual_due_episode_numbers(episodes, requested, local_now)
        else:
            last_saved_episode = max(last_saved_episode, _legacy_qas_progress_floor(task))
            due_numbers = _due_episode_numbers(
                episodes,
                last_saved_episode,
                local_now,
                configured_time,
                force=force or bool(approved_share_url),
            )
        if not due_numbers:
            statuses = {row["episode_number"]: row["status"] for row in episodes}
            next_check = compute_next_check(target, statuses, check_time=task.get("check_time"))
            _finish_task(task_id, "idle", "", next_check, retry_count=0)
            return {
                "ok": True,
                "stage": "not_due",
                "message": "当前没有已播出且尚未保存的新内容",
                "next_check_at": next_check,
            }

        due_target = replace(target, episodes=tuple(ep for ep in target.episodes if ep.episode_number in due_numbers))
        previous_urls = (approved_share_url or task.get("current_share_url") or "",)
        if not previous_urls[0]:
            previous_urls = recover_previous_share_urls(due_target, qas_client)
        resolution = resolve_episode_source(
            due_target,
            previous_urls,
            qas=transfer_provider,
            pansou=pansou,
            refresh=force,
            allow_review_confidence=bool(approved_share_url),
            preferred_source_names=approved_source_names,
            provider_filter=str(task.get("provider") or "qas"),
            excluded_share_urls=_expired_share_urls(task_id),
        )
        if resolution.ok and task.get("provider") == "p115":
            directory_response = transfer_provider.savepath_detail(task["save_path"])
            resolution = adapt_resolution_to_existing_episode_names(
                resolution,
                directory_response,
                target.season_number or 0,
            )
        job_id = _record_tracking_job(task, due_target, resolution)
        _record_candidates(job_id, resolution.reviewed_candidates)
        if not resolution.ok:
            return _handle_resolution_failure(task, due_target, resolution, job_id, qas_client)

        execution = transfer_provider.execute(
            TransferPlan(
                target=due_target,
                resolution=resolution,
                save_path=task["save_path"],
                allow_review_confirmed=bool(approved_share_url),
            )
        )
        _update_tracking_job_execution(job_id, execution)
        if not execution.ok:
            return _handle_execution_failure(task, due_target, execution.message, job_id, qas_client)

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
        next_check = _retry_at(0) if unmatched_numbers else compute_next_check(target, statuses, check_time=task.get("check_time"))
        state = "retry_wait" if execution.confirmed and unmatched_numbers else "idle" if execution.confirmed else "awaiting_confirmation"
        task_message = (
            f"已处理 {len(matched_numbers)} 集，另有 {len(unmatched_numbers)} 集尚无匹配资源，稍后自动重试"
            if execution.confirmed and unmatched_numbers
            else "" if execution.confirmed
            else "QAS 已触发，等待确认转存结果"
        )
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
            "next_check_at": next_check,
        }
    except Exception as exc:
        _finish_task(task_id, "retry_wait", str(exc), _retry_at(task.get("retry_count", 0)), increment_retry=True)
        return {"ok": False, "stage": "internal_error", "message": str(exc)}


def run_due_tracking_tasks(limit: int = 3) -> list[dict]:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db() as conn:
        rows = conn.execute(
            """
            SELECT id FROM tracking_tasks
            WHERE status='active'
              AND decision_state NOT IN ('running','needs_review','awaiting_confirmation')
              AND next_check_at IS NOT NULL AND next_check_at!='' AND next_check_at<=?
            ORDER BY next_check_at LIMIT ?
            """,
            (now, limit),
        ).fetchall()
    return [run_tracking_task(row["id"]) for row in rows]


def _handle_resolution_failure(task: dict, target: MediaTarget, resolution, job_id: int, qas: QasClient) -> dict:
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
    retries = int(task.get("retry_count") or 0) + 1
    max_retries = get_settings().tracking_max_retries
    # Waiting for an upload after TMDB's release date is normal. Recheck later
    # without ever escalating old-episode-only search results to human review.
    source_not_updated = resolution.stage == "source_not_updated"
    needs_review = resolution.stage == "needs_review" or (retries >= max_retries and not source_not_updated)
    state = "needs_review" if needs_review else "retry_wait"
    if source_not_updated:
        # Upload timing can lag TMDB by minutes or hours. Check hourly and do
        # not let earlier manual refreshes stretch this normal wait to 4-12h.
        retries = 0
        next_check = _retry_at(0)
    else:
        next_check = "" if needs_review else _retry_at(retries - 1)
    _finish_task(task["id"], state, resolution.message, next_check, retry_count=retries)
    if needs_review:
        _notify_job_once(job_id, target.title, resolution.message, qas)
    return {
        "ok": False,
        "stage": state,
        "message": resolution.message,
        "next_check_at": next_check,
    }


def _handle_execution_failure(task: dict, target: MediaTarget, message: str, job_id: int, qas: QasClient) -> dict:
    retries = int(task.get("retry_count") or 0) + 1
    needs_review = retries >= get_settings().tracking_max_retries
    state = "needs_review" if needs_review else "retry_wait"
    next_check = "" if needs_review else _retry_at(retries - 1)
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
    if needs_review:
        _notify_job_once(job_id, target.title, message, qas)
    return {
        "ok": False,
        "stage": state,
        "message": message,
        "next_check_at": next_check,
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
                json.dumps([pair.__dict__ for pair in resolution.rename_pairs], ensure_ascii=False),
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


def _update_tracking_job_execution(job_id: int, execution) -> None:
    status = "done" if execution.confirmed else "triggered" if execution.ok else "failed"
    with db() as conn:
        conn.execute(
            """
            UPDATE transfer_jobs SET status=?,stage=?,message=?,
                finished_at=CASE WHEN ? IN ('done','failed') THEN CURRENT_TIMESTAMP ELSE finished_at END
            WHERE id=?
            """,
            (status, execution.stage, execution.message, status, job_id),
        )


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
    hours = RETRY_HOURS[min(max(retry_index, 0), len(RETRY_HOURS) - 1)]
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat(timespec="seconds")


def _parse_air_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def _parse_check_time(value: str | None, fallback_hour: int) -> time:
    try:
        parsed = time.fromisoformat(str(value or ""))
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
        and int(row["episode_number"]) > last_saved_episode
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


def _notify_job_once(job_id: int, title: str, message: str, qas: QasClient) -> None:
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
