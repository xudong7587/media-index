from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from app.clients.qas import QasClient
from app.core.config import get_settings
from app.db.database import db
from app.services.qas_executor import qas_saved_files_confirmed
from app.services.review_notification import notify_review_required


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
    with db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM transfer_jobs
            WHERE status='triggered' AND save_path!=''
            ORDER BY created_at LIMIT ?
            """,
            (limit,),
        ).fetchall()
    results: list[dict] = []
    for row in rows:
        job = dict(row)
        expected = _expected_names(job)
        confirmed = qas_saved_files_confirmed(client, job["save_path"], expected)
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
                UPDATE transfer_jobs SET status='done',stage='qas_completed',
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
        results.append({"job_id": job["id"], "confirmed": True})
    return results


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
    retry_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(timespec="seconds")
    notify_title = ""
    needs_review = False
    with db() as conn:
        conn.execute(
            """
            UPDATE transfer_jobs SET status='failed',stage='qas_confirmation_timeout',message=?,
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
