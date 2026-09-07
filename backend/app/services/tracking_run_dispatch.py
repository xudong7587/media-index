from __future__ import annotations

import sqlite3
import hashlib

from app.db.database import db


def enqueue_tracking_run(
    task_id: int,
    *,
    selected_episode_numbers: tuple[int, ...] = (),
    request_source: str,
    approved_share_url: str = "",
) -> dict:
    """Persist one exact tracking execution before any background work."""
    selected_episode_numbers = tuple(sorted(set(selected_episode_numbers)))
    episode_key = ",".join(str(number) for number in selected_episode_numbers) or "due"
    execution_key = f"tracking-run:{task_id}:{episode_key}"
    if approved_share_url:
        execution_key += ":share:" + hashlib.sha256(approved_share_url.strip().encode()).hexdigest()[:24]
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        task = conn.execute("SELECT * FROM tracking_tasks WHERE id=?", (task_id,)).fetchone()
        if not task:
            raise LookupError("追更任务不存在")
        existing = conn.execute(
            "SELECT * FROM transfer_jobs WHERE task_id=? AND status IN ('running','ready','triggered') ORDER BY id DESC LIMIT 1",
            (task_id,),
        ).fetchone()
        if existing:
            same = existing["execution_key"] == execution_key
            return {
                "ok": same, "id": int(existing["id"]), "status": existing["status"],
                "stage": existing["stage"], "message": "相同补齐任务已在执行" if same else "该网盘追更已有任务正在执行，请完成后再提交其他选集",
                "duplicate": True, "blocked": not same,
            }
        if task["status"] != "active" or task["decision_state"] == "running":
            return {"ok": False, "duplicate": True, "blocked": True, "message": "请先恢复追更或等待当前执行完成"}
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
                "SELECT * FROM transfer_jobs WHERE task_id=? AND status IN ('running','ready','triggered') ORDER BY id DESC LIMIT 1",
                (task_id,),
            ).fetchone()
            if existing:
                same = existing["execution_key"] == execution_key
                return {
                    "ok": same, "id": int(existing["id"]), "status": existing["status"],
                    "stage": existing["stage"], "message": "相同补齐任务已在执行" if same else "该网盘追更已有任务正在执行",
                    "duplicate": True, "blocked": not same,
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
