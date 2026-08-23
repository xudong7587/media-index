from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.db.database import db


WORKFLOW_STEPS = (
    ("resource_search", "网盘资源查询"),
    ("tmdb_rename", "TMDB 核对和改名"),
    ("transfer", "转存"),
    ("openlist_sync", "OpenList 同步"),
    ("strm_generate", "STRM 生成"),
    ("emby_refresh", "通知 Emby 入库"),
    ("library_notification", "发送入库通知"),
)

_SEARCH_STAGES = {
    "pansou_identifying", "pansou_searching", "searching", "querying_sources",
    "resource_search", "resource_probe", "checking_saved",
}
_TMDB_STAGES = {
    "tmdb_resolving", "matching_files", "preparing_names", "name_resolving",
    "candidate_review", "needs_review",
}
_TRANSFER_STAGES = {
    "provider_submitting", "provider_triggered", "provider_completed",
    "qas_triggered", "qas_transferring", "provider_failed", "already_saved",
}


def initialize_media_workflow(job_id: int) -> None:
    settings = get_settings()
    initial = {
        "resource_search": ("running", "正在准备查询网盘资源"),
        "tmdb_rename": ("pending", "等待资源查询"),
        "transfer": ("pending", "等待名称核对"),
        "openlist_sync": (
            "pending" if settings.openlist_enabled and settings.openlist_auto_sync else "skipped",
            "等待转存完成" if settings.openlist_enabled and settings.openlist_auto_sync else "未启用自动 OpenList 同步",
        ),
        "strm_generate": (
            "pending" if settings.p115_strm_enabled or settings.quark_strm_enabled else "skipped",
            "等待网盘文件就绪" if settings.p115_strm_enabled or settings.quark_strm_enabled else "未启用自动 STRM 生成",
        ),
        "emby_refresh": (
            "pending" if settings.emby_library_refresh_enabled else "skipped",
            "等待 STRM 生成" if settings.emby_library_refresh_enabled else "未启用 Emby 自动入库",
        ),
        "library_notification": (
            "pending" if settings.notification_external_enabled else "skipped",
            "等待 Emby 入库" if settings.notification_external_enabled else "未启用外部入库通知",
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
    if normalized in _SEARCH_STAGES:
        update_media_workflow_step(job_id, "resource_search", "running", message)
        return
    if normalized in _TMDB_STAGES:
        update_media_workflow_step(job_id, "resource_search", "done", "网盘资源查询已完成")
        update_media_workflow_step(job_id, "tmdb_rename", "review" if "review" in normalized else "running", message)
        return
    if normalized in _TRANSFER_STAGES:
        update_media_workflow_step(job_id, "resource_search", "done", "网盘资源查询已完成")
        update_media_workflow_step(job_id, "tmdb_rename", "done", "TMDB 信息与目标文件名已核对")
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


def complete_transfer_workflow_step(job_id: int, status: str, stage: str, message: str) -> None:
    update_media_workflow_progress(job_id, stage, message)
    if status in {"done", "triggered"}:
        update_media_workflow_step(
            job_id,
            "transfer",
            "done" if status == "done" else "running",
            message or ("转存已完成" if status == "done" else "转存已提交，等待网盘确认"),
        )
    elif status == "needs_review":
        update_media_workflow_step(job_id, "tmdb_rename", "review", message or "需要人工核对")
    elif status == "failed":
        step_key = "resource_search" if stage == "no_resource" else "transfer"
        update_media_workflow_step(job_id, step_key, "failed", message or "流程未完成")


def list_media_workflow(tmdb_id: int, media_type: str) -> dict[str, Any]:
    normalized_type = "tv" if str(media_type).lower() == "tv" else "movie"
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
                    {"key": key, "label": label, "status": "pending", "message": "等待开始"}
                    for key, label in WORKFLOW_STEPS
                ],
            }
        rows = conn.execute(
            "SELECT step_key,status,message,updated_at FROM media_workflow_steps WHERE job_id=?",
            (int(job["id"]),),
        ).fetchall()
    if not rows:
        initialize_media_workflow(int(job["id"]))
        complete_transfer_workflow_step(int(job["id"]), str(job["status"]), str(job["stage"]), str(job["message"] or ""))
        with db() as conn:
            rows = conn.execute(
                "SELECT step_key,status,message,updated_at FROM media_workflow_steps WHERE job_id=?",
                (int(job["id"]),),
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
        "job_id": int(job["id"]),
        "status": str(job["status"]),
        "stage": str(job["stage"]),
        "message": str(job["message"] or ""),
        "steps": steps,
    }
