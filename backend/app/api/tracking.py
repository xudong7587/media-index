from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.security import require_user
from app.db.database import db
from app.services.media_target import resolve_media_target
from app.services.paths import build_save_path
from app.services.saved_episode_scanner import refresh_saved_episodes
from app.services.tracking_engine_v2 import compute_next_check, run_tracking_task, sync_tracking_episodes

router = APIRouter(prefix="/api/tracking", tags=["tracking"], dependencies=[Depends(require_user)])


class TrackingCreate(BaseModel):
    tmdb_id: int
    media_type: str
    title: str = ""
    year: str = ""
    poster_url: str = ""
    overview: str = ""
    season_number: int = 1
    save_target: str = "cloud"


@router.get("")
def list_tracking():
    with db() as conn:
        rows = conn.execute(
            """
            SELECT t.*,
                   SUM(CASE WHEN e.status='saved' THEN 1 ELSE 0 END) AS saved_count,
                   SUM(CASE WHEN e.status='triggered' THEN 1 ELSE 0 END) AS triggered_count,
                   COUNT(e.id) AS episode_count
            FROM tracking_tasks t
            LEFT JOIN tracking_episodes e ON e.task_id=t.id
            GROUP BY t.id
            ORDER BY t.created_at DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]


@router.post("")
def create_tracking(payload: TrackingCreate):
    try:
        target = resolve_media_target(payload.tmdb_id, payload.media_type, payload.season_number)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"TMDB target resolution failed: {exc}") from exc
    save_path = build_save_path(
        payload.save_target,
        payload.media_type,
        target.title,
        target.series_year,
        payload.season_number,
    )
    with db() as conn:
        existing = conn.execute(
            "SELECT * FROM tracking_tasks WHERE tmdb_id=? AND media_type=? AND season_number=?",
            (payload.tmdb_id, payload.media_type, payload.season_number),
        ).fetchone()
        if existing:
            task_id = int(existing["id"])
            conn.execute(
                """
                UPDATE tracking_tasks SET title=?,year=?,poster_url=?,overview=?,save_target=?,save_path=?,
                                          status='active',decision_state='pending',updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (
                    target.title,
                    target.series_year,
                    target.poster_url,
                    target.overview,
                    payload.save_target,
                    save_path,
                    task_id,
                ),
            )
        else:
            cur = conn.execute(
                """
                INSERT INTO tracking_tasks(
                    tmdb_id,media_type,title,year,poster_url,overview,season_number,
                    save_target,save_path,status,decision_state
                ) VALUES(?,?,?,?,?,?,?,?,?,'active','pending')
                """,
                (
                    payload.tmdb_id,
                    payload.media_type,
                    target.title,
                    target.series_year,
                    target.poster_url,
                    target.overview,
                    payload.season_number,
                    payload.save_target,
                    save_path,
                ),
            )
            task_id = int(cur.lastrowid)
    sync_tracking_episodes(task_id, target)
    refresh_saved_episodes(task_id)
    with db() as conn:
        rows = conn.execute(
            "SELECT episode_number,status FROM tracking_episodes WHERE task_id=?",
            (task_id,),
        ).fetchall()
        statuses = {row["episode_number"]: row["status"] for row in rows}
        next_check = compute_next_check(target, statuses)
        conn.execute(
            "UPDATE tracking_tasks SET next_check_at=? WHERE id=?",
            (next_check or None, task_id),
        )
    return {"ok": True, "id": task_id, "next_check_at": next_check}


@router.post("/{task_id}/run")
def run_now(task_id: int):
    with db() as conn:
        conn.execute(
            "UPDATE tracking_tasks SET decision_state='pending',next_check_at=? WHERE id=?",
            (datetime.now(timezone.utc).isoformat(timespec="seconds"), task_id),
        )
    return run_tracking_task(task_id)


@router.post("/{task_id}/refresh-storage")
def refresh_storage(task_id: int):
    result = refresh_saved_episodes(task_id)
    if not result.get("ok"):
        status_code = 404 if result.get("message") == "追更任务不存在" else 503
        raise HTTPException(status_code=status_code, detail=result.get("message", "storage check failed"))
    return result


@router.post("/{task_id}/pause")
def pause_tracking(task_id: int):
    with db() as conn:
        conn.execute(
            "UPDATE tracking_tasks SET status='paused',decision_state='paused',updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (task_id,),
        )
    return {"ok": True}


@router.post("/{task_id}/resume")
def resume_tracking(task_id: int):
    with db() as conn:
        conn.execute(
            """
            UPDATE tracking_tasks SET status='active',decision_state='pending',next_check_at=?,updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (datetime.now(timezone.utc).isoformat(timespec="seconds"), task_id),
        )
    return {"ok": True}


@router.delete("/{task_id}")
def delete_tracking(task_id: int):
    with db() as conn:
        conn.execute("DELETE FROM tracking_episodes WHERE task_id=?", (task_id,))
        conn.execute("DELETE FROM tracking_tasks WHERE id=?", (task_id,))
    return {"ok": True}
