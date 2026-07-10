import json

from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.security import require_user
from app.clients.qas import QasClient
from app.db.database import db
from app.services.tracking_engine_v2 import run_tracking_task
from app.services.transfer_service_v2 import execute_transfer_v2
from app.services.wishlist_schedule import compute_wishlist_next_check, resolve_wishlist_target
from app.services.share_inspector import inspect_share

router = APIRouter(prefix="/api/review", tags=["review"], dependencies=[Depends(require_user)])


class ConfirmSelection(BaseModel):
    selected_files: list[str] = Field(default_factory=list)


@router.get("")
def list_review_candidates():
    with db() as conn:
        rows = conn.execute(
            """
            SELECT c.*,j.tmdb_id,j.media_type,j.season_number,j.message AS job_message,j.review_state,
                   j.created_at AS job_created_at
            FROM candidates c
            JOIN transfer_jobs j ON j.id=c.job_id
            WHERE j.status='needs_review' AND c.rejected=0 AND COALESCE(c.decision,'pending')='pending'
            ORDER BY j.created_at DESC,c.score DESC,c.created_at DESC
            LIMIT 200
            """
        ).fetchall()
    result = []
    file_cache: dict[str, list[str]] = {}
    file_updates: list[tuple[int, str, int]] = []
    qas = QasClient()
    for row in rows:
        item = dict(row)
        try:
            item["reasons"] = json.loads(item.pop("reasons_json") or "[]")
        except json.JSONDecodeError:
            item["reasons"] = []
        try:
            item["files"] = json.loads(item.pop("files_json") or "[]")
        except json.JSONDecodeError:
            item["files"] = []
        share_url = str(item.get("share_url") or "")
        if not item["files"] and share_url and len(file_cache) < 20:
            if share_url not in file_cache:
                inspection = inspect_share(qas, share_url)
                file_cache[share_url] = [source.name for source in inspection.files] if inspection.valid else []
            item["files"] = file_cache[share_url]
            if item["files"]:
                file_updates.append((len(item["files"]), json.dumps(item["files"], ensure_ascii=False), int(item["id"])))
        result.append(item)
    if file_updates:
        with db() as conn:
            conn.executemany("UPDATE candidates SET file_count=?,files_json=? WHERE id=?", file_updates)
    return result


@router.post("/{candidate_id}/confirm")
def confirm_candidate(
    candidate_id: int,
    background_tasks: BackgroundTasks,
    payload: ConfirmSelection = ConfirmSelection(),
):
    candidate, job = _load_candidate_job(candidate_id)
    if int(candidate.get("rejected") or 0):
        raise HTTPException(status_code=409, detail="失效或冲突候选不能确认执行")
    if candidate.get("decision") != "pending" or job.get("status") != "needs_review":
        raise HTTPException(status_code=409, detail="该候选已经处理或任务状态已改变")
    with db() as conn:
        conn.execute("UPDATE candidates SET decision='approved' WHERE id=?", (candidate_id,))
        conn.execute(
            """
            UPDATE transfer_jobs
            SET review_state='confirmed',status='running',stage='matching_files',
                message='正在按所选文件重新匹配 TMDB 集数',finished_at=NULL
            WHERE id=?
            """,
            (job["id"],),
        )

    background_tasks.add_task(_run_confirmed_candidate, candidate, job, payload.selected_files)
    return {
        "ok": True,
        "id": int(job["id"]),
        "status": "running",
        "stage": "matching_files",
        "message": "正在按所选文件重新匹配 TMDB 集数",
    }


def _run_confirmed_candidate(candidate: dict, job: dict, selected_files: list[str]) -> None:
    def progress(stage: str, message: str) -> None:
        with db() as conn:
            conn.execute(
                "UPDATE transfer_jobs SET stage=?,message=? WHERE id=? AND status='running'",
                (stage, message[:1000], job["id"]),
            )

    if job.get("task_id"):
        with db() as conn:
            conn.execute(
                """
                UPDATE tracking_tasks SET current_share_url=?,decision_state='pending',retry_count=0,
                                          next_check_at=?,last_error='',updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (
                    candidate["share_url"],
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    job["task_id"],
                ),
            )
            conn.execute(
                """
                UPDATE tracking_episodes SET status='pending',last_error='',updated_at=CURRENT_TIMESTAMP
                WHERE task_id=? AND status='needs_review'
                """,
                (job["task_id"],),
            )
        try:
            result = run_tracking_task(
                int(job["task_id"]),
                approved_share_url=candidate["share_url"],
                approved_source_names=selected_files,
            )
        except Exception as exc:
            result = {"ok": False, "stage": "internal_error", "message": f"确认任务执行失败：{exc}"}
        stage = result.get("stage", "unknown")
        status = "done" if stage == "qas_completed" else "triggered" if stage == "qas_triggered" else "needs_review" if stage == "needs_review" else "failed"
        with db() as conn:
            conn.execute(
                """
                UPDATE transfer_jobs SET status=?,stage=?,message=?,review_state=?,finished_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (
                    status,
                    stage,
                    result.get("message", "所选文件已完成重新匹配与转存" if result.get("ok") else "所选文件仍无法安全匹配"),
                    "resolved" if result.get("ok") else "pending",
                    job["id"],
                ),
            )
        return

    try:
        result = execute_transfer_v2(
            int(job["tmdb_id"]),
            str(job["media_type"]),
            str(job["target"]),
            job.get("season_number"),
            preferred_share_urls=(candidate["share_url"],),
            user_confirmed=True,
            preferred_source_names=selected_files,
            on_progress=progress,
        )
    except Exception as exc:
        result = {"ok": False, "stage": "internal_error", "message": f"确认任务执行失败：{exc}"}
    _replace_job_result(int(job["id"]), result)
    return {"ok": result.get("ok", False), "stage": result.get("stage", "unknown"), "message": result.get("message", "")}


@router.delete("/{candidate_id}")
def dismiss_candidate(candidate_id: int):
    candidate, job = _load_candidate_job(candidate_id)
    if candidate.get("decision") != "pending":
        raise HTTPException(status_code=409, detail="该候选已经处理")
    with db() as conn:
        conn.execute("UPDATE candidates SET decision='dismissed' WHERE id=?", (candidate_id,))
        remaining = conn.execute(
            """
            SELECT COUNT(*) FROM candidates
            WHERE job_id=? AND rejected=0 AND COALESCE(decision,'pending')='pending'
            """,
            (job["id"],),
        ).fetchone()[0]
        if not remaining:
            conn.execute(
                """
                UPDATE transfer_jobs SET status='failed',stage='dismissed',review_state='dismissed',
                    message='用户已删除全部待确认候选',finished_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (job["id"],),
            )
    return {"ok": True, "remaining": int(remaining)}


@router.post("/job/{job_id}/research")
def research_job(job_id: int):
    with db() as conn:
        row = conn.execute("SELECT * FROM transfer_jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="review job not found")
    job = dict(row)
    with db() as conn:
        conn.execute("UPDATE candidates SET decision='superseded' WHERE job_id=?", (job_id,))
        conn.execute("UPDATE transfer_jobs SET review_state='researching',status='running' WHERE id=?", (job_id,))

    if job.get("task_id"):
        with db() as conn:
            conn.execute(
                """
                UPDATE tracking_tasks SET current_share_url='',decision_state='pending',retry_count=0,
                                          next_check_at=?,last_error='',updated_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (datetime.now(timezone.utc).isoformat(timespec="seconds"), job["task_id"]),
            )
            conn.execute(
                """
                UPDATE tracking_episodes SET status='pending',last_error='',updated_at=CURRENT_TIMESTAMP
                WHERE task_id=? AND status IN ('needs_review','retry_wait','failed')
                """,
                (job["task_id"],),
            )
        return run_tracking_task(int(job["task_id"]))

    result = execute_transfer_v2(
        int(job["tmdb_id"]),
        str(job["media_type"]),
        str(job["target"]),
        job.get("season_number"),
        refresh=True,
    )
    _replace_job_result(job_id, result)
    return {"ok": result.get("ok", False), "stage": result.get("stage", "unknown"), "message": result.get("message", "")}


def _load_candidate_job(candidate_id: int) -> tuple[dict, dict]:
    with db() as conn:
        row = conn.execute(
            """
            SELECT c.*,j.task_id,j.wishlist_id,j.tmdb_id,j.media_type,j.season_number,j.target,j.status AS job_status
            FROM candidates c JOIN transfer_jobs j ON j.id=c.job_id WHERE c.id=?
            """,
            (candidate_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="review candidate not found")
    merged = dict(row)
    candidate_keys = {
        "id", "job_id", "share_url", "source_title", "search_query", "source", "published_at",
        "file_count", "files_json", "score", "match_stage", "is_fuzzy", "rejected", "reasons_json",
        "decision", "created_at",
    }
    candidate = {key: value for key, value in merged.items() if key in candidate_keys}
    job = {
        "id": candidate["job_id"],
        "task_id": merged.get("task_id"),
        "wishlist_id": merged.get("wishlist_id"),
        "tmdb_id": merged.get("tmdb_id"),
        "media_type": merged.get("media_type"),
        "season_number": merged.get("season_number"),
        "target": merged.get("target"),
        "status": merged.get("job_status"),
    }
    return candidate, job


def _replace_job_result(job_id: int, result: dict) -> None:
    stage = result.get("stage", "unknown")
    status = "done" if stage == "qas_completed" else "triggered" if stage == "qas_triggered" else "needs_review" if stage == "needs_review" else "failed"
    resolution = result.get("resolution") or {}
    pairs = resolution.get("rename_pairs") or []
    first_pair = pairs[0] if pairs else {}
    with db() as conn:
        conn.execute(
            """
            UPDATE transfer_jobs SET status=?,stage=?,message=?,share_url=?,source_file=?,renamed_file=?,
                                     rename_pairs_json=?,save_path=?,review_state=?,finished_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (
                status,
                stage,
                result.get("message", ""),
                resolution.get("share_url", ""),
                first_pair.get("source_name", ""),
                first_pair.get("replacement", ""),
                json.dumps(pairs, ensure_ascii=False),
                result.get("save_path", ""),
                "resolved" if result.get("ok") else "pending",
                job_id,
            ),
        )
        for candidate in resolution.get("reviewed_candidates") or []:
            conn.execute(
                """
                INSERT INTO candidates(job_id,share_url,source_title,search_query,source,published_at,
                                       file_count,files_json,score,rejected,reasons_json)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    job_id,
                    candidate.get("share_url", ""),
                    candidate.get("title", ""),
                    candidate.get("query", ""),
                    candidate.get("source", ""),
                    candidate.get("published_at", ""),
                    len(candidate.get("files") or []),
                    json.dumps(candidate.get("files") or [], ensure_ascii=False),
                    candidate.get("score", 0),
                    1 if candidate.get("rejected") else 0,
                    json.dumps(candidate.get("reasons") or [], ensure_ascii=False),
                ),
            )
    _sync_wishlist_parent(job_id, result)


def _sync_wishlist_parent(job_id: int, result: dict) -> None:
    with db() as conn:
        row = conn.execute(
            """
            SELECT w.* FROM transfer_jobs j JOIN wishlist w ON w.id=j.wishlist_id
            WHERE j.id=?
            """,
            (job_id,),
        ).fetchone()
    if not row:
        return
    item = dict(row)
    stage = result.get("stage", "unknown")
    if stage in {"qas_completed", "qas_triggered"}:
        status = "completed" if stage == "qas_completed" else "triggered"
        with db() as conn:
            conn.execute(
                "UPDATE wishlist SET status=?,next_check_at=NULL,last_error='' WHERE id=?",
                (status, item["id"]),
            )
        return
    if stage == "needs_review":
        with db() as conn:
            conn.execute(
                "UPDATE wishlist SET status='needs_review',next_check_at=NULL,last_error=? WHERE id=?",
                (result.get("message", "")[:1000], item["id"]),
            )
        return
    try:
        target = resolve_wishlist_target(item["tmdb_id"], item["media_type"], item.get("season_number"))
        next_check_at, tmdb_date = compute_wishlist_next_check(target, int(item.get("check_hour") or 9))
    except Exception:
        next_check_at, tmdb_date = item.get("next_check_at"), item.get("tmdb_date") or ""
    with db() as conn:
        conn.execute(
            """
            UPDATE wishlist SET status='retry_wait',next_check_at=?,tmdb_date=?,last_error=? WHERE id=?
            """,
            (next_check_at, tmdb_date, result.get("message", "")[:1000], item["id"]),
        )
