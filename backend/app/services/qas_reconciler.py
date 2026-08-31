from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta, timezone

from app.clients.qas import QasClient
from app.core.config import get_settings
from app.db.database import db
from app.providers.registry import get_transfer_provider
from app.services.media_workflow import complete_transfer_workflow_step, update_media_workflow_step
from app.services.notifications import sync_transfer_notifications
from app.services.openlist_sync import sync_transfer_outputs
from app.services.review_notification import notify_review_required
from app.services.saved_episode_scanner import record_confirmed_tracking_outputs


_reconcile_worker: threading.Thread | None = None
_reconcile_worker_lock = threading.Lock()
_RECONCILE_INTERVAL_SECONDS = 10


def request_qas_reconciliation() -> bool:
    """Start a bounded confirmation worker only when QAS has pending jobs."""
    global _reconcile_worker
    if not _has_pending_qas_jobs():
        return False
    with _reconcile_worker_lock:
        if _reconcile_worker and _reconcile_worker.is_alive():
            return False
        _reconcile_worker = threading.Thread(
            target=_reconcile_until_idle,
            name="media-index-qas-reconcile",
            daemon=True,
        )
        _reconcile_worker.start()
    return True


def _has_pending_qas_jobs() -> bool:
    with db() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM transfer_jobs
            WHERE status='triggered' AND save_path!=''
              AND (
                provider='qas'
                OR (provider='p115' AND stage='openlist_sync_submitted')
              )
            LIMIT 1
            """
        ).fetchone()
    return bool(row)


def _reconcile_until_idle() -> None:
    global _reconcile_worker
    try:
        # QAS normally finishes the rename/transfer in about ten seconds.
        time.sleep(_RECONCILE_INTERVAL_SECONDS)
        while _has_pending_qas_jobs():
            reconcile_triggered_jobs()
            if _has_pending_qas_jobs():
                time.sleep(_RECONCILE_INTERVAL_SECONDS)
    finally:
        with _reconcile_worker_lock:
            _reconcile_worker = None
        # Cover a new QAS job submitted just as the previous worker exits.
        request_qas_reconciliation()


def recover_interrupted_jobs() -> int:
    """A process restart proves in-process workers no longer exist; make them retryable."""
    from app.services.tracking_engine_v2 import post_processing_retryable

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db() as conn:
        raw_post_rows = conn.execute(
            """
            SELECT j.*,bj.batch_id AS linked_batch_id
            FROM transfer_jobs j
            LEFT JOIN transfer_batch_jobs bj ON bj.job_id=j.id
            WHERE j.provider IN ('p115','quark')
              AND COALESCE(j.execution_key,'') NOT LIKE 'tracking-cycle:%'
              AND (
                j.status='running'
                OR j.external_provider_status IN (
                  'post_processing_pending','post_processing_running','post_processing_failed'
                )
              )
              AND j.external_provider_status IN (
                'post_processing_pending','post_processing_running',
                'post_processing_completed','post_processing_failed',
                'post_processing_skipped'
                  )
            """
        ).fetchall()
        ordinary_post_by_id: dict[int, dict] = {}
        for raw in raw_post_rows:
            job = dict(raw)
            if not _job_has_metadata(job, "_post_processing"):
                continue
            job_id = int(job["id"])
            if (
                str(job.get("external_provider_status") or "") == "post_processing_failed"
                and not post_processing_retryable(job_id)
            ):
                continue
            current = ordinary_post_by_id.setdefault(job_id, job)
            parent_ids = set(current.get("recovery_batch_ids") or ())
            parent_ids.update(
                int(value)
                for value in (job.get("batch_id"), job.get("linked_batch_id"))
                if value
            )
            current["recovery_batch_ids"] = sorted(parent_ids)
        ordinary_post_rows = list(ordinary_post_by_id.values())
        ordinary_post_ids = {int(row["id"]) for row in ordinary_post_rows}
        if ordinary_post_ids:
            placeholders = ",".join("?" for _ in ordinary_post_ids)
            conn.execute(
                f"""
                UPDATE transfer_jobs SET external_provider_status='post_processing_pending'
                WHERE id IN ({placeholders})
                  AND external_provider_status IN ('post_processing_running','post_processing_failed')
                """,
                tuple(sorted(ordinary_post_ids)),
            )
            for job in ordinary_post_rows:
                if str(job.get("external_provider_status") or "") in {
                    "post_processing_running",
                    "post_processing_failed",
                }:
                    job["external_provider_status"] = "post_processing_pending"
        rows = [
            row
            for row in conn.execute(
                """
                SELECT j.id,j.task_id,j.wishlist_id,j.execution_key,COALESCE(j.batch_id,bj.batch_id) AS batch_id
                FROM transfer_jobs j
                LEFT JOIN transfer_batch_jobs bj ON bj.job_id=j.id
                WHERE j.status='running'
                """
            ).fetchall()
            if int(row["id"]) not in ordinary_post_ids
        ]
        tracking_batches = [
            int(row["batch_id"])
            for row in conn.execute(
                """
                SELECT DISTINCT bj.batch_id FROM transfer_batch_jobs bj
                JOIN transfer_batches b ON b.id=bj.batch_id
                JOIN transfer_jobs j ON j.id=bj.job_id
                WHERE b.status='running' AND j.execution_key LIKE 'tracking-cycle:%'
                """
            ).fetchall()
        ]
        for batch_id in tracking_batches:
            # A process restart proves no in-process post-processing claim is
            # still alive.  Requeue durable pending/running native work, and
            # make lanes that never require STRM explicit successes.
            conn.execute(
                """
                UPDATE transfer_jobs SET external_provider_status='post_processing_pending'
                WHERE id IN (SELECT job_id FROM transfer_batch_jobs WHERE batch_id=?)
                  AND status='done' AND provider IN ('p115','quark')
                  AND (
                    external_provider_status IN ('post_processing_running','post_processing_failed')
                    OR (COALESCE(external_provider_status,'')='' AND stage!='not_due')
                  )
                """,
                (batch_id,),
            )
            conn.execute(
                """
                UPDATE transfer_jobs SET external_provider_status='post_processing_skipped'
                WHERE id IN (SELECT job_id FROM transfer_batch_jobs WHERE batch_id=?)
                  AND status='done' AND COALESCE(external_provider_status,'')=''
                  AND (provider='qas' OR stage='not_due')
                """,
                (batch_id,),
            )
        conn.executemany(
            """
            UPDATE transfer_jobs SET status='failed',stage='interrupted',
                message='服务重启中断了任务，未将其视为成功',finished_at=CURRENT_TIMESTAMP
            WHERE id=? AND status='running'
            """,
            [(int(row["id"]),) for row in rows],
        )
        ordinary_batches = {
            int(row["batch_id"])
            for row in rows
            if row["batch_id"] and int(row["batch_id"]) not in set(tracking_batches)
        }
        for batch_id in ordinary_batches:
            active = int(conn.execute(
                """
                SELECT COUNT(*) FROM transfer_batch_jobs bj
                JOIN transfer_jobs j ON j.id=bj.job_id
                WHERE bj.batch_id=? AND j.status IN ('running','ready','triggered')
                """,
                (batch_id,),
            ).fetchone()[0])
            if active:
                continue
            completed = int(conn.execute(
                """
                SELECT COUNT(*) FROM transfer_batch_jobs bj
                JOIN transfer_jobs j ON j.id=bj.job_id
                WHERE bj.batch_id=? AND j.status='done'
                """,
                (batch_id,),
            ).fetchone()[0])
            conn.execute(
                """
                UPDATE transfer_batches SET status=?,message=?,finished_at=CURRENT_TIMESTAMP
                WHERE id=? AND status='running'
                """,
                (
                    "partial" if completed else "failed",
                    "服务重启中断了首次转存批次；已完成部分保持不变，请按需重试" if completed else "服务重启中断了首次转存批次，请重试",
                    batch_id,
                ),
            )
        for row in rows:
            if row["task_id"]:
                conn.execute(
                    "UPDATE tracking_tasks SET decision_state='pending',next_check_at=?,last_error='任务被服务重启中断' WHERE id=?",
                    (now, row["task_id"]),
                )
            if row["wishlist_id"]:
                conn.execute(
                    "UPDATE wishlist SET status='pending',next_check_at=?,last_error='任务被服务重启中断' WHERE id=?",
                    (now, row["wishlist_id"]),
                )
    if tracking_batches:
        from app.services.tracking_engine_v2 import resume_tracking_cycle

        for batch_id in tracking_batches:
            resume_tracking_cycle(batch_id)
    recovered_post_jobs = _resume_ordinary_post_processing(ordinary_post_rows)
    if recovered_post_jobs:
        sync_transfer_notifications()
    request_qas_reconciliation()
    return len(rows) + recovered_post_jobs


def _resume_ordinary_post_processing(rows: list[dict]) -> int:
    """Resume the exact-output barrier used by first-transfer native jobs."""
    if not rows:
        return 0
    from app.services.tracking_engine_v2 import post_processing_retryable, run_pending_tracking_post_processing

    terminal_jobs = 0
    batch_ids: set[int] = set()
    for job in rows:
        metadata = _job_metadata(job, "_post_processing")
        terminal_status = str(metadata.get("terminal_status") or "done")
        if terminal_status not in {"done", "failed"}:
            terminal_status = "done"
        current_stage = str(job.get("stage") or "")
        fallback_stage = (
            "provider_completed"
            if current_stage in {"post_processing_retry_wait", "post_processing_failed"}
            else current_stage or "provider_completed"
        )
        terminal_stage = str(metadata.get("terminal_stage") or fallback_stage)
        terminal_message = str(metadata.get("terminal_message") or job.get("message") or "")
        state = str(job.get("external_provider_status") or "")
        if state in {"post_processing_completed", "post_processing_skipped"}:
            post_processing_ok: bool | None = True
        elif state == "post_processing_failed":
            post_processing_ok = False
        else:
            outputs = metadata.get("outputs")
            exact_outputs = tuple(
                dict(item)
                for item in outputs if isinstance(item, dict)
            ) if isinstance(outputs, list) else ()
            post_processing_ok = run_pending_tracking_post_processing(
                int(job["id"]),
                outputs=exact_outputs,
                defer_library_notification=True,
            )
        if post_processing_ok is None:
            continue
        if post_processing_ok is False and post_processing_retryable(int(job["id"])):
            with db() as conn:
                conn.execute(
                    """
                    UPDATE transfer_jobs
                    SET status='running',stage='post_processing_retry_wait',finished_at=NULL
                    WHERE id=?
                    """,
                    (int(job["id"]),),
                )
            continue
        failure_message = "STRM 或 Emby 后处理失败"
        with db() as conn:
            current = conn.execute(
                "SELECT stage,message FROM transfer_jobs WHERE id=?",
                (int(job["id"]),),
            ).fetchone()
            if not current:
                continue
            if post_processing_ok:
                conn.execute(
                    """
                    UPDATE transfer_jobs
                    SET status=?,stage=?,message=?,finished_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (terminal_status, terminal_stage, terminal_message[:1000], int(job["id"])),
                )
            elif terminal_status == "failed":
                message = str(current["message"] or "")
                if failure_message not in message:
                    message = f"{message}；{failure_message}".strip("；")
                conn.execute(
                    """
                    UPDATE transfer_jobs
                    SET status='failed',stage=?,message=?,finished_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (terminal_stage, message[:1000], int(job["id"])),
                )
            else:
                message = str(current["message"] or "")
                if failure_message not in message:
                    message = f"{message}；{failure_message}".strip("；")
                conn.execute(
                    """
                    UPDATE transfer_jobs SET status='failed',stage='post_processing_failed',
                        message=?,finished_at=CURRENT_TIMESTAMP WHERE id=?
                    """,
                    (message[:1000], int(job["id"])),
                )
        with db() as conn:
            terminal = conn.execute(
                "SELECT status,stage,message FROM transfer_jobs WHERE id=?",
                (int(job["id"]),),
            ).fetchone()
        if terminal:
            complete_transfer_workflow_step(
                int(job["id"]),
                str(terminal["status"] or "failed"),
                str(terminal["stage"] or ""),
                str(terminal["message"] or ""),
            )
        task_id = int(job.get("task_id") or 0)
        if task_id:
            outputs = metadata.get("outputs")
            if isinstance(outputs, list):
                record_confirmed_tracking_outputs(task_id, outputs)
        batch_ids.update(int(value) for value in job.get("recovery_batch_ids") or () if value)
        terminal_jobs += 1
    if batch_ids:
        from app.services.transfer_batches import refresh_transfer_batch_status

        for batch_id in sorted(batch_ids):
            refresh_transfer_batch_status(batch_id)
    return terminal_jobs


def retry_failed_post_processing() -> int:
    """Reclaim one persisted exact-output retry without resubmitting providers."""
    from app.services.tracking_engine_v2 import post_processing_retryable, resume_tracking_cycle

    with db() as conn:
        raw_rows = conn.execute(
            """
            SELECT j.*,bj.batch_id AS linked_batch_id
            FROM transfer_jobs j
            LEFT JOIN transfer_batch_jobs bj ON bj.job_id=j.id
            WHERE j.provider IN ('p115','quark')
              AND j.external_provider_status='post_processing_failed'
            ORDER BY j.id
            """
        ).fetchall()
    jobs_by_id: dict[int, dict] = {}
    for raw in raw_rows:
        job = dict(raw)
        job_id = int(job["id"])
        if not post_processing_retryable(job_id):
            continue
        current = jobs_by_id.setdefault(job_id, job)
        parent_ids = set(current.get("recovery_batch_ids") or ())
        parent_ids.update(
            int(value)
            for value in (job.get("batch_id"), job.get("linked_batch_id"))
            if value
        )
        current["recovery_batch_ids"] = sorted(parent_ids)

    claimed: list[dict] = []
    with db() as conn:
        for job in jobs_by_id.values():
            changed = conn.execute(
                """
                UPDATE transfer_jobs SET external_provider_status='post_processing_pending'
                WHERE id=? AND external_provider_status='post_processing_failed'
                """,
                (int(job["id"]),),
            ).rowcount
            if changed:
                job["external_provider_status"] = "post_processing_pending"
                claimed.append(job)

    ordinary = [
        job
        for job in claimed
        if not str(job.get("execution_key") or "").startswith("tracking-cycle:")
    ]
    tracking_batch_ids = {
        int(batch_id)
        for job in claimed
        if str(job.get("execution_key") or "").startswith("tracking-cycle:")
        for batch_id in job.get("recovery_batch_ids") or ()
    }
    _resume_ordinary_post_processing(ordinary)
    for batch_id in sorted(tracking_batch_ids):
        with db() as conn:
            conn.execute(
                "UPDATE transfer_batches SET status='running',finished_at=NULL WHERE id=?",
                (batch_id,),
            )
        resume_tracking_cycle(batch_id)
    if claimed:
        sync_transfer_notifications()
    return len(claimed)


def reconcile_triggered_jobs(limit: int = 20, *, qas: QasClient | None = None, p115: object | None = None) -> list[dict]:
    client = qas or QasClient()
    with db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM transfer_jobs
            WHERE status='triggered' AND save_path!=''
              AND (
                provider='qas'
                OR (COALESCE(provider,'')='' AND target='cloud')
                OR (provider='p115' AND stage='openlist_sync_submitted')
              )
            ORDER BY created_at LIMIT ?
            """,
            (limit,),
        ).fetchall()
    results: list[dict] = []
    for row in rows:
        job = dict(row)
        provider_key = "p115" if str(job.get("provider") or "") == "p115" else "qas"
        fallback_meta = _job_metadata(job, "_tracking_openlist_fallback")
        fallback_missing = [int(number) for number in fallback_meta.get("missing") or () if int(number) > 0]
        provider = (
            get_transfer_provider("p115", p115=p115)
            if provider_key == "p115"
            else get_transfer_provider("qas", qas=client)
        )
        expected = _expected_names(job)
        expected_count = _expected_count(job)
        confirmed = (
            provider.reconcile(job["save_path"], expected)
            if provider_key == "p115"
            else provider.reconcile(job["save_path"], expected, expected_count=expected_count)
        )
        if not confirmed:
            if _confirmation_expired(job):
                _expire_job(job, expected, client)
                _resume_tracking_cycle(job)
                results.append({"job_id": job["id"], "confirmed": False, "expired": True})
            else:
                results.append({"job_id": job["id"], "confirmed": False, "expired": False})
            continue
        completed_message = (
            "115 目标目录已确认 OpenList 补齐文件全部存在"
            if provider_key == "p115"
            else "QAS 目标目录已确认全部文件存在"
        )
        with db() as conn:
            conn.execute(
                """
                UPDATE transfer_jobs SET status='done',stage='provider_completed',
                                         message=?,external_provider_status=?,
                                         finished_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (
                    completed_message,
                    "post_processing_pending" if provider_key == "p115" else "post_processing_skipped",
                    job["id"],
                ),
            )
            if job.get("task_id"):
                placeholders = ",".join("?" for _ in expected)
                if placeholders:
                    conn.execute(
                        f"""
                        UPDATE tracking_episodes SET status='saved',saved_at=CURRENT_TIMESTAMP,last_error=''
                        WHERE task_id=? AND rename_to IN ({placeholders})
                        """,
                        (job["task_id"], *expected),
                    )
                conn.execute(
                    """
                    UPDATE tracking_tasks SET decision_state=?,last_error=?,next_check_at=?,
                                              updated_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (
                        "retry_wait" if fallback_missing else "pending",
                        f"OpenList 自动补齐后仍有 {len(fallback_missing)} 集等待重试" if fallback_missing else "",
                        datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        job["task_id"],
                    ),
                )
            if job.get("wishlist_id"):
                conn.execute(
                    """
                    UPDATE wishlist SET status='completed',next_check_at=NULL,last_error='',retry_count=0
                    WHERE id=?
                    """,
                    (job["wishlist_id"],),
                )
        complete_transfer_workflow_step(
            int(job["id"]),
            "done",
            "provider_completed",
            completed_message,
        )
        if job.get("task_id"):
            record_confirmed_tracking_outputs(int(job["task_id"]), expected)
        if provider_key == "p115":
            from app.services.tracking_engine_v2 import run_pending_tracking_post_processing

            run_pending_tracking_post_processing(
                int(job["id"]),
                outputs=tuple({"file_name": name} for name in expected),
                defer_library_notification=True,
            )
            update_media_workflow_step(
                int(job["id"]),
                "openlist_sync",
                "done",
                "115 目标目录已确认 OpenList 补齐文件全部存在",
            )
        else:
            openlist_completed = _sync_confirmed_qas_job(job, expected)
            if openlist_completed and job.get("wishlist_id"):
                _remove_wishlist_media(job)
        _resume_tracking_cycle(job)
        results.append({"job_id": job["id"], "confirmed": True})
    if results and any(
        result.get("confirmed") or result.get("expired") for result in results
    ):
        sync_transfer_notifications()
    return results


def _sync_confirmed_qas_job(job: dict, filenames: list[str]) -> bool:
    if not job.get("openlist_fallback_to_p115"):
        return False
    sync_results: list[dict] = []
    try:
        sync_results = sync_transfer_outputs(
            "qas",
            str(job.get("save_path") or ""),
            filenames,
            tmdb_id=job.get("tmdb_id"),
            media_type=str(job.get("media_type") or ""),
            season_number=job.get("season_number"),
            display_title=str(job.get("display_title") or ""),
            target_providers=("p115",),
        )
    except Exception as exc:
        message = f"QAS 目标目录已确认全部文件存在；OpenList 同步未完成：{type(exc).__name__}"
    else:
        if not sync_results:
            return False
        successful = sum(1 for result in sync_results if result.get("ok"))
        job_ids = [str(result.get("job_id")) for result in sync_results if result.get("job_id")]
        if successful:
            message = (
                f"QAS 目标目录已确认全部文件存在；OpenList 已提交后台复制任务 #{'、'.join(job_ids)}"
                if job_ids
                else f"QAS 目标目录已确认全部文件存在；OpenList 已同步 {successful} 个文件"
            )
        else:
            detail = str(sync_results[0].get("message") or "未知错误")[:80]
            message = f"QAS 目标目录已确认全部文件存在；OpenList 同步未完成：{detail}"
    with db() as conn:
        conn.execute("UPDATE transfer_jobs SET message=? WHERE id=?", (message, job["id"]))
    completed = any(bool(result.get("ok")) and result.get("landed") is not None for result in sync_results)
    update_media_workflow_step(
        int(job["id"]),
        "openlist_sync",
        "done" if completed else "failed",
        message,
    )
    return completed


def _remove_wishlist_media(job: dict) -> None:
    with db() as conn:
        conn.execute(
            "UPDATE transfer_jobs SET notification_sent_at=COALESCE(notification_sent_at,CURRENT_TIMESTAMP) WHERE id=?",
            (int(job["id"]),),
        )
        conn.execute(
            """
            DELETE FROM wishlist
            WHERE tmdb_id=? AND media_type=? AND COALESCE(season_number,0)=?
            """,
            (job.get("tmdb_id"), job.get("media_type"), int(job.get("season_number") or 0)),
        )


def _resume_tracking_cycle(job: dict) -> None:
    if not str(job.get("execution_key") or "").startswith("tracking-cycle:"):
        return
    from app.services.tracking_engine_v2 import resume_tracking_cycle_for_job

    resume_tracking_cycle_for_job(int(job["id"]))


def _job_metadata(job: dict, key: str) -> dict:
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


def _job_has_metadata(job: dict, key: str) -> bool:
    try:
        pairs = json.loads(job.get("rename_pairs_json") or "[]")
    except (json.JSONDecodeError, TypeError):
        return False
    return bool(
        isinstance(pairs, list)
        and any(isinstance(item, dict) and key in item for item in pairs)
    )


def _expected_names(job: dict) -> list[str]:
    try:
        pairs = json.loads(job.get("rename_pairs_json") or "[]")
    except json.JSONDecodeError:
        pairs = []
    names = [
        str(pair.get("replacement") or "")
        for pair in pairs
        if isinstance(pair, dict) and pair.get("replacement")
    ]
    if not names and job.get("renamed_file"):
        names.append(str(job["renamed_file"]))
    return list(dict.fromkeys(names))


def _expected_count(job: dict) -> int:
    try:
        pairs = json.loads(job.get("rename_pairs_json") or "[]")
    except json.JSONDecodeError:
        pairs = []
    if not isinstance(pairs, list):
        return 0
    for pair in pairs:
        if isinstance(pair, dict) and pair.get("expected_count"):
            try:
                return max(0, int(pair["expected_count"]))
            except (TypeError, ValueError):
                return 0
    return 0


def _confirmation_expired(job: dict, now: datetime | None = None) -> bool:
    fallback_meta = _job_metadata(job, "_tracking_openlist_fallback")
    raw = str(fallback_meta.get("submitted_at") or job.get("created_at") or "").strip()
    if not raw:
        return False
    try:
        created = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    timeout = max(5, get_settings().qas_confirmation_timeout_minutes)
    return current.astimezone(timezone.utc) - created.astimezone(timezone.utc) >= timedelta(minutes=timeout)


def _expire_job(job: dict, expected: list[str], client: QasClient) -> None:
    provider_label = "115" if str(job.get("provider") or "") == "p115" else "QAS"
    message = f"{provider_label} 接受任务后长时间未在目标目录发现文件，已转入自动重试"
    tracking_cycle = str(job.get("execution_key") or "").startswith("tracking-cycle:")
    retry_at = (datetime.now(timezone.utc) + timedelta(minutes=max(1, get_settings().tracking_retry_interval_minutes))).isoformat(timespec="seconds")
    notify_title = ""
    needs_review = False
    with db() as conn:
        conn.execute(
            """
            UPDATE transfer_jobs SET status='failed',stage='provider_confirmation_timeout',message=?,
                                     finished_at=CURRENT_TIMESTAMP
            WHERE id=? AND status='triggered'
            """,
            (message, job["id"]),
        )
        if job.get("task_id"):
            task = conn.execute(
                "SELECT title,retry_count FROM tracking_tasks WHERE id=?",
                (job["task_id"],),
            ).fetchone()
            retries = int(task["retry_count"] or 0) + 1 if task else 1
            needs_review = retries >= get_settings().tracking_max_retries
            state = "needs_review" if needs_review else "retry_wait"
            placeholders = ",".join("?" for _ in expected)
            if placeholders:
                conn.execute(
                    f"""
                    UPDATE tracking_episodes SET status=?,last_error=?,retry_count=retry_count+1,
                                                 updated_at=CURRENT_TIMESTAMP
                    WHERE task_id=? AND rename_to IN ({placeholders})
                    """,
                    (state, message, job["task_id"], *expected),
                )
            conn.execute(
                """
                UPDATE tracking_tasks SET decision_state=?,last_error=?,next_check_at=?,
                                          retry_count=?,updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (state, message, "" if needs_review else retry_at, retries, job["task_id"]),
            )
            if needs_review and tracking_cycle:
                conn.execute(
                    "UPDATE transfer_jobs SET status='needs_review',stage='needs_review' WHERE id=?",
                    (int(job["id"]),),
                )
            if needs_review and task:
                notify_title = str(task["title"] or "追更任务")
        if job.get("wishlist_id"):
            wishlist = conn.execute(
                "SELECT title,retry_count FROM wishlist WHERE id=?",
                (job["wishlist_id"],),
            ).fetchone()
            retries = int(wishlist["retry_count"] or 0) + 1 if wishlist else 1
            wishlist_needs_review = retries >= get_settings().tracking_max_retries
            wishlist_state = "needs_review" if wishlist_needs_review else "retry_wait"
            conn.execute(
                """
                UPDATE wishlist SET status=?,last_error=?,next_check_at=?,retry_count=?
                WHERE id=?
                """,
                (
                    wishlist_state,
                    message,
                    "" if wishlist_needs_review else retry_at,
                    retries,
                    job["wishlist_id"],
                ),
            )
            if wishlist_needs_review and wishlist and not notify_title:
                needs_review = True
                notify_title = str(wishlist["title"] or "愿望单任务")
    if str(job.get("provider") or "") == "p115":
        update_media_workflow_step(int(job["id"]), "openlist_sync", "failed", message)
    if needs_review and notify_title and not tracking_cycle:
        notification = notify_review_required(notify_title, message, int(job["id"]), qas=client)
        with db() as conn:
            conn.execute(
                """
                UPDATE transfer_jobs SET review_state=?,
                    notification_sent_at=CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE notification_sent_at END
                WHERE id=?
                """,
                ("notified" if notification.sent else "notification_failed", 1 if notification.sent else 0, job["id"]),
            )
