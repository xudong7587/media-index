import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.security import require_user
from app.db.database import db
from app.services.transfer_service_v2 import execute_transfer_v2

router = APIRouter(prefix="/api/transfers", tags=["transfers"], dependencies=[Depends(require_user)])


class TransferCreate(BaseModel):
    tmdb_id: int
    media_type: str
    title: str = ""
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
    with db() as conn:
        cur = conn.execute(
            """
            INSERT INTO transfer_jobs(tmdb_id, media_type, season_number, target, status, stage, message)
            VALUES(?,?,?,?,?,?,?)
            """,
            (
                payload.tmdb_id,
                payload.media_type,
                payload.season_number,
                payload.target,
                "running",
                "resolving",
                "正在根据 TMDB 信息验证链接和匹配文件",
            ),
        )
        job_id = cur.lastrowid

    try:
        result = execute_transfer_v2(
            payload.tmdb_id,
            payload.media_type,
            payload.target,
            payload.season_number,
        )
    except Exception as exc:
        result = {"ok": False, "stage": "internal_error", "message": f"转存决策失败：{exc}", "save_path": ""}

    stage = result.get("stage", "unknown")
    status = (
        "done"
        if stage == "qas_completed"
        else "triggered"
        if stage == "qas_triggered"
        else "needs_review"
        if stage == "needs_review"
        else "failed"
    )
    message = result.get("message", "")
    resolution = result.get("resolution") or {}
    pairs = resolution.get("rename_pairs") or []
    first_pair = pairs[0] if pairs else {}
    save_path = result.get("save_path", "")
    with db() as conn:
        conn.execute(
            """
            UPDATE transfer_jobs
            SET status=?, stage=?, message=?, share_url=?, source_file=?, renamed_file=?, save_path=?,
                finished_at=CASE WHEN ? IN ('done','failed','needs_review') THEN CURRENT_TIMESTAMP ELSE finished_at END
            WHERE id=?
            """,
            (
                status,
                stage,
                message,
                resolution.get("share_url", ""),
                first_pair.get("source_name", ""),
                first_pair.get("replacement", ""),
                save_path,
                status,
                job_id,
            ),
        )
        for candidate in resolution.get("reviewed_candidates") or []:
            conn.execute(
                """
                INSERT INTO candidates(job_id, share_url, source_title, search_query, source, published_at,
                                       score, rejected, reasons_json)
                VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (
                    job_id,
                    candidate.get("share_url", ""),
                    candidate.get("title", ""),
                    candidate.get("query", ""),
                    candidate.get("source", ""),
                    candidate.get("published_at", ""),
                    candidate.get("score", 0),
                    1 if candidate.get("rejected") else 0,
                    json.dumps(candidate.get("reasons") or [], ensure_ascii=False),
                ),
            )
        if not result.get("ok") and stage == "no_resource":
            target = result.get("target") or {}
            conn.execute(
                """
                INSERT INTO wishlist(tmdb_id, media_type, title, year, poster_url, overview, status)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(tmdb_id, media_type) DO UPDATE SET status='pending'
                """,
                (
                    payload.tmdb_id,
                    payload.media_type,
                    target.get("title") or payload.title,
                    target.get("series_year") or payload.year,
                    payload.poster_url,
                    payload.overview,
                    "pending",
                ),
            )
    return {
        "ok": result.get("ok", False),
        "id": job_id,
        "save_path": save_path,
        "message": message,
        "stage": stage,
        "status": status,
    }
