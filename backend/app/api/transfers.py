import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from app.core.security import require_user
from app.db.database import db
from app.services.transfer_service_v2 import execute_transfer_v2
from app.services.review_notification import notify_review_required
from app.services.wishlist_schedule import compute_wishlist_next_check, resolve_wishlist_target
from app.core.config import get_settings
from app.providers.registry import resolve_provider_key
from app.providers.status import normalize_provider_record, transfer_status_for_stage

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
    provider: str | None = None


@router.get("")
def list_transfers():
    with db() as conn:
        rows = conn.execute("SELECT * FROM transfer_jobs ORDER BY created_at DESC LIMIT 100").fetchall()
        return [normalize_provider_record(dict(row)) for row in rows]


@router.get("/{job_id}")
def get_transfer(job_id: int):
    with db() as conn:
        row = conn.execute("SELECT * FROM transfer_jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="transfer job not found")
    return normalize_provider_record(dict(row))


@router.post("")
def create_transfer(payload: TransferCreate, background_tasks: BackgroundTasks):
    response = enqueue_transfer(payload)
    if not response.get("duplicate"):
        background_tasks.add_task(_run_transfer_job, payload, int(response["id"]))
    return response


def enqueue_transfer(payload: TransferCreate) -> dict:
    try:
        provider = resolve_provider_key(payload.target, payload.provider)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    execution_key = f"{payload.tmdb_id}:{payload.media_type}:{payload.season_number or 0}:{payload.target}:{provider}"
    with db() as conn:
        existing = conn.execute(
            "SELECT * FROM transfer_jobs WHERE execution_key=? AND status IN ('running','ready','triggered') ORDER BY id DESC LIMIT 1",
            (execution_key,),
        ).fetchone()
        if existing:
            return {"ok": True, **normalize_provider_record(dict(existing)), "duplicate": True}
        cur = conn.execute(
            """
            INSERT INTO transfer_jobs(
                tmdb_id,media_type,display_title,season_number,target,provider,status,stage,message,execution_key
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                payload.tmdb_id,
                payload.media_type,
                payload.title,
                payload.season_number,
                payload.target,
                provider,
                "running",
                "tmdb_resolving",
                "正在匹配 TMDB 媒体信息",
                execution_key,
            ),
        )
        job_id = cur.lastrowid

    return {
        "ok": True,
        "id": int(job_id),
        "save_path": "",
        "message": "正在匹配 TMDB 媒体信息",
        "stage": "tmdb_resolving",
        "status": "running",
        "provider": provider,
    }


def _run_transfer_job(payload: TransferCreate, job_id: int) -> None:
    def progress(stage: str, message: str) -> None:
        with db() as conn:
            conn.execute(
                "UPDATE transfer_jobs SET stage=?,message=? WHERE id=? AND status='running'",
                (stage, message[:1000], job_id),
            )

    try:
        result = execute_transfer_v2(
            payload.tmdb_id,
            payload.media_type,
            payload.target,
            payload.season_number,
            on_progress=progress,
            provider=payload.provider,
        )
    except Exception as exc:
        result = {"ok": False, "stage": "internal_error", "message": f"转存决策失败：{exc}", "save_path": ""}

    stage = result.get("stage", "unknown")
    status = transfer_status_for_stage(stage)
    message = result.get("message", "")
    resolution = result.get("resolution") or {}
    pairs = resolution.get("rename_pairs") or []
    first_pair = pairs[0] if pairs else {}
    save_path = result.get("save_path", "")
    wishlist_schedule = None
    if not result.get("ok") and stage == "no_resource":
        try:
            wishlist_target = resolve_wishlist_target(payload.tmdb_id, payload.media_type, payload.season_number)
            check_hour = get_settings().wishlist_default_check_hour
            next_check_at, tmdb_date = compute_wishlist_next_check(wishlist_target, check_hour)
            wishlist_schedule = (wishlist_target, check_hour, next_check_at, tmdb_date)
        except Exception:
            wishlist_schedule = None
    with db() as conn:
        conn.execute(
            """
            UPDATE transfer_jobs
            SET status=?, stage=?, message=?, share_url=?, source_file=?, renamed_file=?, rename_pairs_json=?, save_path=?,
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
                json.dumps(pairs, ensure_ascii=False),
                save_path,
                status,
                job_id,
            ),
        )
        for candidate in resolution.get("reviewed_candidates") or []:
            conn.execute(
                """
                INSERT INTO candidates(job_id,share_url,source_title,search_query,source,cloud_type,provider,published_at,
                                       file_count,files_json,score,rejected,reasons_json)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    job_id,
                    candidate.get("share_url", ""),
                    candidate.get("title", ""),
                    candidate.get("query", ""),
                    candidate.get("source", ""),
                    "quark",
                    "qas",
                    candidate.get("published_at", ""),
                    len(candidate.get("files") or []),
                    json.dumps(candidate.get("files") or [], ensure_ascii=False),
                    candidate.get("score", 0),
                    1 if candidate.get("rejected") else 0,
                    json.dumps(candidate.get("reasons") or [], ensure_ascii=False),
                ),
            )
        if not result.get("ok") and stage == "no_resource":
            target = result.get("target") or {}
            scheduled_target = wishlist_schedule[0] if wishlist_schedule else None
            check_hour = wishlist_schedule[1] if wishlist_schedule else get_settings().wishlist_default_check_hour
            next_check_at = wishlist_schedule[2] if wishlist_schedule else None
            tmdb_date = wishlist_schedule[3] if wishlist_schedule else ""
            conn.execute(
                """
                INSERT INTO wishlist(
                    tmdb_id,media_type,title,year,poster_url,overview,season_number,save_target,provider,
                    check_hour,tmdb_date,next_check_at,status
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,'pending')
                ON CONFLICT(tmdb_id, media_type) DO UPDATE SET
                    season_number=excluded.season_number,
                    save_target=excluded.save_target,
                    provider=excluded.provider,
                    check_hour=excluded.check_hour,
                    tmdb_date=excluded.tmdb_date,
                    next_check_at=excluded.next_check_at,
                    status='pending',last_error='',retry_count=0
                """,
                (
                    payload.tmdb_id,
                    payload.media_type,
                    target.get("title") or payload.title,
                    target.get("series_year") or payload.year,
                    payload.poster_url,
                    payload.overview,
                    scheduled_target.season_number if scheduled_target else payload.season_number,
                    payload.target,
                    resolve_provider_key(payload.target, payload.provider),
                    check_hour,
                    tmdb_date,
                    next_check_at,
                ),
            )
    if status == "needs_review":
        target = result.get("target") or {}
        notification = notify_review_required(target.get("title") or payload.title or "未命名媒体", message, job_id)
        with db() as conn:
            conn.execute(
                """
                UPDATE transfer_jobs SET review_state=?,
                    notification_sent_at=CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE notification_sent_at END
                WHERE id=?
                """,
                ("notified" if notification.sent else "notification_failed", 1 if notification.sent else 0, job_id),
            )
