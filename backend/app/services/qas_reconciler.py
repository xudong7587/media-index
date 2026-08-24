from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta, timezone

from app.clients.qas import QasClient
from app.core.config import get_settings
from app.db.database import db
from app.providers.registry import get_transfer_provider
from app.services.notifications import sync_transfer_notifications
from app.services.openlist_sync import sync_transfer_outputs
from app.services.review_notification import notify_review_required


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
            WHERE status='triggered' AND provider='qas' AND save_path!=''
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
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db() as conn:
        rows = conn.execute("SELECT id,task_id,wishlist_id FROM transfer_jobs WHERE status='running'").fetchall()
        conn.execute(
            """
            UPDATE transfer_jobs SET status='failed',stage='interrupted',
                message='服务重启中断了任务，未将其视为成功',finished_at=CURRENT_TIMESTAMP
            WHERE status='running'
            """
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
    return len(rows)


def reconcile_triggered_jobs(limit: int = 20, *, qas: QasClient | None = None) -> list[dict]:
    client = qas or QasClient()
    provider = get_transfer_provider("qas", qas=client)
    with db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM transfer_jobs
            WHERE status='triggered' AND save_path!=''
              AND (provider='qas' OR (COALESCE(provider,'')='' AND target='cloud'))
            ORDER BY created_at LIMIT ?
            """,
            (limit,),
        ).fetchall()
    results: list[dict] = []
    for row in rows:
        job = dict(row)
        expected = _expected_names(job)
        expected_count = _expected_count(job)
        confirmed = provider.reconcile(job["save_path"], expected, expected_count=expected_count)
        if not confirmed:
            if _confirmation_expired(job):
                _expire_job(job, expected, client)
                results.append({"job_id": job["id"], "confirmed": False, "expired": True})
            else:
                results.append({"job_id": job["id"], "confirmed": False, "expired": False})
            continue
        with db() as conn:
            conn.execute(
                """
                UPDATE transfer_jobs SET status='done',stage='provider_completed',
                                         message='QAS 目标目录已确认全部文件存在',
                                         finished_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (job["id"],),
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
                    UPDATE tracking_tasks SET decision_state='pending',last_error='',next_check_at=?,
                                              updated_at=CURRENT_TIMESTAMP
                    WHERE id=?
                    """,
                    (datetime.now(timezone.utc).isoformat(timespec="seconds"), job["task_id"]),
                )
            if job.get("wishlist_id"):
                conn.execute(
                    """
                    UPDATE wishlist SET status='completed',next_check_at=NULL,last_error='',retry_count=0
                    WHERE id=?
                    """,
                    (job["wishlist_id"],),
                )
        _sync_confirmed_qas_job(job, expected)
        results.append({"job_id": job["id"], "confirmed": True})
    if results and get_settings().notification_external_enabled and any(
        result.get("confirmed") or result.get("expired") for result in results
    ):
        sync_transfer_notifications()
    return results


def _sync_confirmed_qas_job(job: dict, filenames: list[str]) -> None:
    if not job.get("openlist_fallback_to_p115"):
        return
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
            return
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
    raw = str(job.get("created_at") or "").strip()
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
    message = "QAS 接受任务后长时间未在目标目录发现文件，已转入自动重试"
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
    if needs_review and notify_title:
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
