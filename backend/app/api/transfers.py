from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.security import require_user
from app.db.database import db
from app.services.paths import build_save_path
from app.services.transfer_executor import execute_cloud_transfer

router = APIRouter(prefix="/api/transfers", tags=["transfers"], dependencies=[Depends(require_user)])


class TransferCreate(BaseModel):
    tmdb_id: int
    media_type: str
    title: str
    year: str = ""
    poster_url: str = ""
    overview: str = ""
    target: str = "cloud"
    season_number: int | None = None


@router.get("")
def list_transfers():
    with db() as conn:
        rows = conn.execute("SELECT * FROM transfer_jobs ORDER BY created_at DESC LIMIT 100").fetchall()
        return [dict(row) for row in rows]


@router.post("")
def create_transfer(payload: TransferCreate):
    save_path = build_save_path(payload.target, payload.media_type, payload.title, payload.year, payload.season_number)
    with db() as conn:
        cur = conn.execute(
            """
            INSERT INTO transfer_jobs(target, status, stage, message, save_path)
            VALUES(?,?,?,?,?)
            """,
            (
                payload.target,
                "queued",
                "created",
                "转存任务已创建，等待执行",
                save_path,
            ),
        )
        job_id = cur.lastrowid

    if payload.target != "cloud":
        return {"ok": True, "id": job_id, "save_path": save_path, "message": "本地任务已记录"}

    result = execute_cloud_transfer(payload.title, payload.year, payload.media_type, save_path, payload.season_number)
    status = "done" if result.get("ok") else "failed"
    stage = result.get("stage", "unknown")
    message = result.get("message", "")
    with db() as conn:
        conn.execute(
            """
            UPDATE transfer_jobs
            SET status=?, stage=?, message=?, share_url=?, source_file=?, renamed_file=?
            WHERE id=?
            """,
            (
                status,
                stage,
                message,
                result.get("share_url", ""),
                result.get("pattern", ""),
                result.get("replace", ""),
                job_id,
            ),
        )
        if not result.get("ok") and stage in {"no_resource", "needs_review"}:
            conn.execute(
                """
                INSERT INTO wishlist(tmdb_id, media_type, title, year, poster_url, overview, status)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(tmdb_id, media_type) DO UPDATE SET status='pending'
                """,
                (
                    payload.tmdb_id,
                    payload.media_type,
                    payload.title,
                    payload.year,
                    payload.poster_url,
                    payload.overview,
                    "pending",
                ),
            )
    return {"ok": result.get("ok", False), "id": job_id, "save_path": save_path, "message": message, "stage": stage}
