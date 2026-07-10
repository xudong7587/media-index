from __future__ import annotations

import json
from datetime import datetime, timezone

from app.clients.qas import QasClient
from app.db.database import db
from app.services.qas_executor import qas_saved_files_confirmed


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
            results.append({"job_id": job["id"], "confirmed": False})
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
