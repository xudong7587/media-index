from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.db.database import db


WORKFLOW_STEPS = (
    ("resource_search", "网盘资源查询"),
    ("tmdb_rename", "TMDB 核对和改名"),
    ("transfer", "提交网盘"),
    ("landing_confirm", "落盘确认"),
    ("openlist_sync", "115 补齐"),
    ("strm_generate", "STRM 生成"),
    ("emby_refresh", "通知 Emby 入库"),
    ("library_notification", "发送入库通知"),
)

_SEARCH_STAGES = {
    "pansou_identifying", "pansou_searching", "searching", "querying_sources",
    "resource_search", "resource_probe", "checking_saved",
}
_TMDB_STAGES = {
    "matching_files", "preparing_names", "name_resolving",
    "candidate_review", "needs_review",
}
_TRANSFER_STAGES = {
    "provider_submitting", "provider_triggered", "provider_completed",
    "provider_submitted", "provider_partial", "provider_confirmation_timeout",
    "qas_triggered", "qas_transferring", "provider_failed", "already_saved",
}


def initialize_media_workflow(job_id: int, *, openlist_fallback_to_p115: bool = False) -> None:
    settings = get_settings()
    with db() as conn:
        job = conn.execute("SELECT provider FROM transfer_jobs WHERE id=?", (int(job_id),)).fetchone()
    provider = str(job["provider"] or "") if job else ""
    strm_enabled = (
        bool(settings.p115_strm_enabled) if provider == "p115"
        else bool(settings.quark_strm_enabled) if provider == "quark"
        else False
    )
    initial = {
        "resource_search": ("running", "正在准备查询网盘资源"),
        "tmdb_rename": ("pending", "等待资源查询"),
        "transfer": ("pending", "等待名称核对"),
        "landing_confirm": ("pending", "等待网盘接收并核对目标目录"),
        "openlist_sync": (
            "pending" if openlist_fallback_to_p115 else "skipped",
            "等待夸克转存完成后补齐到 115" if openlist_fallback_to_p115 else "本次转存不需要 OpenList 跨盘补齐",
        ),
        "strm_generate": (
            "pending" if strm_enabled else "skipped",
            "等待网盘文件就绪" if strm_enabled else "当前网盘未启用自动 STRM 生成",
        ),
        "emby_refresh": (
            "pending" if strm_enabled and settings.emby_library_refresh_enabled else "skipped",
            "等待 STRM 生成" if strm_enabled and settings.emby_library_refresh_enabled else "当前网盘没有自动入库流程",
        ),
        "library_notification": (
            "pending" if strm_enabled and settings.notification_external_enabled else "skipped",
            "等待 Emby 入库" if strm_enabled and settings.notification_external_enabled else "当前网盘在转存完成后结束流程",
        ),
    }
    with db() as conn:
        for key, _label in WORKFLOW_STEPS:
            status, message = initial[key]
            conn.execute(
                """
                INSERT OR IGNORE INTO media_workflow_steps(job_id,step_key,status,message)
                VALUES(?,?,?,?)
                """,
                (int(job_id), key, status, message),
            )


def update_media_workflow_progress(job_id: int, stage: str, message: str) -> None:
    normalized = str(stage or "").strip().lower()
    if normalized == "tmdb_resolving":
        _update_media_workflow_step_if_unfinished(job_id, "tmdb_rename", "running", message)
        return
    if normalized in _SEARCH_STAGES:
        _update_media_workflow_step_if_unfinished(job_id, "resource_search", "running", message)
        return
    if normalized in _TMDB_STAGES:
        update_media_workflow_step(job_id, "resource_search", "done", "网盘资源查询已完成")
        if "review" in normalized:
            update_media_workflow_step(job_id, "tmdb_rename", "review", message)
        else:
            _update_media_workflow_step_if_unfinished(job_id, "tmdb_rename", "running", message)
        return
    if normalized in _TRANSFER_STAGES:
        update_media_workflow_step(job_id, "resource_search", "done", "网盘资源查询已完成")
        update_media_workflow_step(job_id, "tmdb_rename", "done", "TMDB 信息与目标文件名已核对")
        if normalized in {"provider_triggered", "provider_completed", "already_saved"}:
            update_media_workflow_step(job_id, "transfer", "done", "转存请求已提交给网盘")
            update_media_workflow_step(
                job_id,
                "landing_confirm",
                "done" if normalized in {"provider_completed", "already_saved"} else "running",
                message or ("目标目录已经核验" if normalized == "provider_completed" else "等待目标目录出现全部规范文件"),
            )
        elif normalized == "provider_submitted":
            update_media_workflow_step(job_id, "transfer", "done", message or "转存请求已提交给外部执行端")
            update_media_workflow_step(job_id, "landing_confirm", "skipped", "外部执行端未向 MediaIndex 提供落盘确认")
        else:
            update_media_workflow_step(job_id, "transfer", "running", message)


def update_media_workflow_step(job_id: int, step_key: str, status: str, message: str) -> None:
    if step_key not in {key for key, _label in WORKFLOW_STEPS}:
        return
    safe_status = status if status in {"pending", "running", "done", "failed", "review", "skipped"} else "pending"
    with db() as conn:
        conn.execute(
            """
            INSERT INTO media_workflow_steps(job_id,step_key,status,message,updated_at)
            VALUES(?,?,?,?,CURRENT_TIMESTAMP)
            ON CONFLICT(job_id,step_key) DO UPDATE SET
              status=excluded.status,message=excluded.message,updated_at=CURRENT_TIMESTAMP
            """,
            (int(job_id), step_key, safe_status, str(message or "")[:500]),
        )


def _update_media_workflow_step_if_unfinished(
    job_id: int,
    step_key: str,
    status: str,
    message: str,
) -> None:
    """Advance a live step without turning a completed step back into a spinner."""
    with db() as conn:
        row = conn.execute(
            "SELECT status FROM media_workflow_steps WHERE job_id=? AND step_key=?",
            (int(job_id), step_key),
        ).fetchone()
    if row and str(row["status"] or "") not in {"pending", "running"}:
        return
    update_media_workflow_step(job_id, step_key, status, message)


def _settle_unfinished_steps(
    job_id: int,
    steps: tuple[str, ...],
    *,
    status: str = "skipped",
    message: str,
) -> None:
    for step_key in steps:
        _update_media_workflow_step_if_unfinished(job_id, step_key, status, message)


def complete_transfer_workflow_step(job_id: int, status: str, stage: str, message: str) -> None:
    update_media_workflow_progress(job_id, stage, message)
    if stage == "not_due":
        update_media_workflow_step(job_id, "resource_search", "done", message or "已核对网盘现有内容")
        _settle_unfinished_steps(
            job_id,
            ("tmdb_rename", "transfer", "landing_confirm", "openlist_sync", "strm_generate", "emby_refresh", "library_notification"),
            message="当前没有需要继续处理的新内容",
        )
        return
    if status in {"done", "triggered"}:
        _settle_unfinished_steps(
            job_id,
            ("resource_search", "tmdb_rename"),
            status="done",
            message="资源与名称核对已完成",
        )
        update_media_workflow_progress(job_id, stage, message)
    elif status == "needs_review":
        _settle_unfinished_steps(
            job_id,
            ("resource_search",),
            status="done",
            message="网盘资源查询已完成",
        )
        update_media_workflow_step(job_id, "tmdb_rename", "review", message or "需要人工核对")
        _settle_unfinished_steps(
            job_id,
            ("transfer", "landing_confirm", "openlist_sync", "strm_generate", "emby_refresh", "library_notification"),
            message="等待人工确认后继续",
        )
    elif status == "failed":
        search_failure = stage in {
            "no_resource", "source_not_updated", "storage_check_failed", "search_failed",
            "not_found", "not_runnable",
        }
        landing_failure = stage in {"provider_partial", "provider_confirmation_timeout"}
        step_key = "resource_search" if search_failure else "landing_confirm" if landing_failure else "transfer"
        update_media_workflow_step(job_id, step_key, "failed", message or "流程未完成")
        if step_key == "resource_search":
            _settle_unfinished_steps(
                job_id,
                ("tmdb_rename", "transfer", "landing_confirm"),
                message="资源查询未完成，未继续处理",
            )
        elif step_key == "landing_confirm":
            _settle_unfinished_steps(
                job_id,
                ("resource_search", "tmdb_rename", "transfer"),
                status="done",
                message="转存请求已经提交",
            )
        else:
            _settle_unfinished_steps(
                job_id,
                ("resource_search", "tmdb_rename", "landing_confirm"),
                message="流程已终止，未继续处理",
            )
        with db() as conn:
            job = conn.execute(
                "SELECT provider,openlist_fallback_to_p115 FROM transfer_jobs WHERE id=?",
                (int(job_id),),
            ).fetchone()
        keep_fallback_pending = bool(
            stage == "no_resource"
            and job
            and str(job["provider"] or "") == "p115"
            and bool(job["openlist_fallback_to_p115"])
        )
        downstream = ["strm_generate", "emby_refresh", "library_notification"]
        if not keep_fallback_pending:
            downstream.insert(0, "openlist_sync")
        _settle_unfinished_steps(
            job_id,
            tuple(downstream),
            message="前序流程未完成，已停止后续处理",
        )


def list_media_workflow(tmdb_id: int, media_type: str) -> dict[str, Any]:
    requested_type = str(media_type or "").lower()
    normalized_type = requested_type if requested_type in {"movie", "tv", "variety"} else "movie"
    with db() as conn:
        job = conn.execute(
            """
            SELECT * FROM transfer_jobs
            WHERE tmdb_id=? AND media_type=? AND provider NOT IN ('openlist','strm')
            ORDER BY id DESC LIMIT 1
            """,
            (int(tmdb_id), normalized_type),
        ).fetchone()
        if not job:
            return {
                "job_id": None,
                "status": "idle",
                "message": "尚未开始自动流程",
                "steps": [
                    {
                        "key": key,
                        "label": label,
                        "status": "skipped" if key == "openlist_sync" else "pending",
                        "message": "未启用本季跨盘补齐" if key == "openlist_sync" else "等待开始",
                    }
                    for key, label in WORKFLOW_STEPS
                ],
                "providers": [],
            }
        association = conn.execute(
            "SELECT batch_id FROM transfer_batch_jobs WHERE job_id=? ORDER BY batch_id DESC LIMIT 1",
            (int(job["id"]),),
        ).fetchone()
        batch_id = int(association["batch_id"]) if association else int(job["batch_id"] or 0)
        siblings = []
        if batch_id:
            siblings = conn.execute(
                """
                SELECT j.* FROM transfer_jobs j
                JOIN transfer_batch_jobs bj ON bj.job_id=j.id
                WHERE bj.batch_id=? AND j.provider NOT IN ('openlist','strm')
                ORDER BY j.provider,j.season_number,j.id
                """,
                (batch_id,),
            ).fetchall()
    primary = _workflow_for_job(dict(job), associated_batch_id=batch_id or None)
    lanes = [_workflow_for_job(dict(row), associated_batch_id=batch_id) for row in siblings]
    return {**primary, "providers": lanes}


def _workflow_for_job(job: dict[str, Any], *, associated_batch_id: int | None = None) -> dict[str, Any]:
    job_id = int(job["id"])
    with db() as conn:
        rows = conn.execute(
            "SELECT step_key,status,message,updated_at FROM media_workflow_steps WHERE job_id=?",
            (job_id,),
        ).fetchall()
    if not rows:
        initialize_media_workflow(
            job_id,
            openlist_fallback_to_p115=bool(job["openlist_fallback_to_p115"]),
        )
        complete_transfer_workflow_step(job_id, str(job["status"]), str(job["stage"]), str(job["message"] or ""))
        with db() as conn:
            rows = conn.execute(
                "SELECT step_key,status,message,updated_at FROM media_workflow_steps WHERE job_id=?",
                (job_id,),
            ).fetchall()
    by_key = {str(row["step_key"]): dict(row) for row in rows}
    steps = []
    for key, label in WORKFLOW_STEPS:
        row = by_key.get(key, {})
        steps.append({
            "key": key,
            "label": label,
            "status": row.get("status", "pending"),
            "message": row.get("message", "等待开始"),
            "updated_at": row.get("updated_at"),
        })
    return {
        "job_id": job_id,
        "batch_id": associated_batch_id or int(job.get("batch_id") or 0) or None,
        "provider": str(job.get("provider") or ""),
        "season_number": int(job.get("season_number") or 0),
        "status": str(job["status"]),
        "stage": str(job["stage"]),
        "message": str(job["message"] or ""),
        "steps": steps,
    }
