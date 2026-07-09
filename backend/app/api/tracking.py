from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.clients.tmdb import TmdbClient
from app.core.security import require_user
from app.db.database import db
from app.services.paths import build_save_path

router = APIRouter(prefix="/api/tracking", tags=["tracking"], dependencies=[Depends(require_user)])


class TrackingCreate(BaseModel):
    tmdb_id: int
    media_type: str
    title: str
    year: str = ""
    poster_url: str = ""
    overview: str = ""
    season_number: int = 1
    save_target: str = "cloud"


@router.get("")
def list_tracking():
    with db() as conn:
        rows = conn.execute("SELECT * FROM tracking_tasks ORDER BY created_at DESC").fetchall()
        tasks = [dict(row) for row in rows]
    return [enrich_tracking_task(task) for task in tasks]


def enrich_tracking_task(task: dict) -> dict:
    if task.get("poster_url") and task.get("overview"):
        return task
    try:
        detail = TmdbClient().details(task["media_type"], task["tmdb_id"])
    except Exception:
        return task
    updates = {}
    if not task.get("poster_url") and detail.get("poster_url"):
        task["poster_url"] = detail["poster_url"]
        updates["poster_url"] = detail["poster_url"]
    if not task.get("overview") and detail.get("overview"):
        task["overview"] = detail["overview"]
        updates["overview"] = detail["overview"]
    if updates:
        with db() as conn:
            conn.execute(
                "UPDATE tracking_tasks SET poster_url=?, overview=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (task.get("poster_url", ""), task.get("overview", ""), task["id"]),
            )
    return task


@router.post("")
def create_tracking(payload: TrackingCreate):
    save_path = build_save_path(
        payload.save_target,
        payload.media_type,
        payload.title,
        payload.year,
        payload.season_number,
    )
    with db() as conn:
        existing = conn.execute(
            "SELECT * FROM tracking_tasks WHERE tmdb_id=? AND media_type=? AND season_number=?",
            (payload.tmdb_id, payload.media_type, payload.season_number),
        ).fetchone()
        if existing:
            return {"ok": True, "id": existing["id"], "message": "already exists"}
        cur = conn.execute(
            """
            INSERT INTO tracking_tasks(tmdb_id, media_type, title, year, poster_url, overview, season_number, save_target, save_path)
            VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (
                payload.tmdb_id,
                payload.media_type,
                payload.title,
                payload.year,
                payload.poster_url,
                payload.overview,
                payload.season_number,
                payload.save_target,
                save_path,
            ),
        )
        return {"ok": True, "id": cur.lastrowid}


@router.post("/{task_id}/pause")
def pause_tracking(task_id: int):
    with db() as conn:
        conn.execute("UPDATE tracking_tasks SET status='paused', updated_at=CURRENT_TIMESTAMP WHERE id=?", (task_id,))
    return {"ok": True}


@router.post("/{task_id}/resume")
def resume_tracking(task_id: int):
    with db() as conn:
        conn.execute("UPDATE tracking_tasks SET status='active', updated_at=CURRENT_TIMESTAMP WHERE id=?", (task_id,))
    return {"ok": True}


@router.delete("/{task_id}")
def delete_tracking(task_id: int):
    with db() as conn:
        conn.execute("DELETE FROM tracking_tasks WHERE id=?", (task_id,))
    return {"ok": True}
