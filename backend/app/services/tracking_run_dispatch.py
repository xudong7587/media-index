from __future__ import annotations

import sqlite3

from app.db.database import db


def enqueue_tracking_run(
    task_id: int,
    *,
    selected_episode_numbers: tuple[int, ...] = (),
    request_source: str,
) -> dict:
    """Persist one exact tracking execution before any background work."""
    episode_key = ",".join(str(number) for number in selected_episode_numbers) or "due"
    execution_key = f"tracking-run:{task_id}:{episode_key}"
    with db() as conn:
        task = conn.execute("SELECT * FROM tracking_tasks WHERE id=?", (task_id,)).fetchone()
        if not task:
            raise LookupError("追更任务不存在")
        existing = conn.execute(
            "SELECT * FROM transfer_jobs WHERE execution_key=? AND status='running' ORDER BY id DESC LIMIT 1",
            (execution_key,),
        ).fetchone()
        if existing:
            return {
                "ok": True,
                "id": int(existing["id"]),
                "status": "running",
                "stage": existing["stage"],
                "message": existing["message"],
                "duplicate": True,
            }
        try:
            job_id = conn.execute(
                """
                INSERT INTO transfer_jobs(
                    task_id,tmdb_id,media_type,display_title,season_number,target,provider,status,stage,message,
                    save_path,execution_key,request_source
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    task["id"],
                    task["tmdb_id"],
                    task["media_type"],
                    task["title"],
                    task["season_number"],
                    task["save_target"],
                    task["provider"],
                    "running",
                    "checking_saved",
                    "正在准备追更任务",
                    task["save_path"],
                    execution_key,
                    request_source,
                ),
            ).lastrowid
        except sqlite3.IntegrityError:
            existing = conn.execute(
                "SELECT * FROM transfer_jobs WHERE execution_key=? AND status='running' ORDER BY id DESC LIMIT 1",
                (execution_key,),
            ).fetchone()
            if existing:
                return {
                    "ok": True,
                    "id": int(existing["id"]),
                    "status": "running",
                    "stage": existing["stage"],
                    "message": existing["message"],
                    "duplicate": True,
                }
            raise
    return {
        "ok": True,
        "id": int(job_id),
        "status": "running",
        "stage": "checking_saved",
        "message": "正在准备追更任务",
        "duplicate": False,
    }
