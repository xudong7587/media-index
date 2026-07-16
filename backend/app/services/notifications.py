from datetime import datetime, timezone
from app.db.database import db
from app.core.config import get_settings
from app.services.notification_channels import send_configured_channels


def add_notification(
    source_key: str,
    notification_type: str,
    title: str,
    message: str = "",
    action_page: str = "",
    *,
    created_at: str | None = None,
) -> bool:
    """Create a notification once for a stable business event key."""
    with db() as conn:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO notifications(
                source_key,type,title,message,action_page,created_at
            ) VALUES(?,?,?,?,?,COALESCE(?,CURRENT_TIMESTAMP))
            """,
            (source_key, notification_type, title[:160], message[:1000], action_page, created_at),
        )
        return cursor.rowcount > 0


def sync_transfer_notifications() -> int:
    """Backfill terminal transfer events, including jobs completed by the scheduler."""
    inserted_ids: list[int] = []
    with db() as conn:
        rows = conn.execute(
            """
            SELECT j.id,j.status,j.stage,j.message,j.created_at,j.finished_at,
                   COALESCE(NULLIF(j.display_title,''),t.title,w.title,m.title,'') AS media_title
            FROM transfer_jobs j
            LEFT JOIN tracking_tasks t ON t.id=j.task_id
            LEFT JOIN wishlist w ON w.id=j.wishlist_id
            LEFT JOIN media m ON m.tmdb_id=j.tmdb_id AND m.media_type=j.media_type
            WHERE j.status IN ('done','triggered','needs_review','failed')
              AND j.stage NOT IN ('superseded','dismissed')
            ORDER BY j.id DESC
            LIMIT 100
            """,
        ).fetchall()
        for row in rows:
            notification_type, title, action_page = _transfer_presentation(dict(row))
            source_key = f"transfer:{row['id']}:{row['status']}:{row['stage']}"
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO notifications(
                    source_key,type,title,message,action_page,created_at
                ) VALUES(?,?,?,?,?,COALESCE(?,?,CURRENT_TIMESTAMP))
                """,
                (
                    source_key,
                    notification_type,
                    title,
                    (row["message"] or "")[:1000],
                    action_page,
                    row["finished_at"],
                    row["created_at"],
                ),
            )
            if cursor.rowcount > 0:
                inserted_ids.append(int(cursor.lastrowid))
    for notification_id in inserted_ids:
        deliver_notification(notification_id)
    return len(inserted_ids)


def deliver_notification(notification_id: int) -> None:
    settings = get_settings()
    if not settings.notification_external_enabled:
        return
    with db() as conn:
        row = conn.execute(
            """
            SELECT id,type,title,message,action_page,created_at,external_status
            FROM notifications WHERE id=?
            """,
            (notification_id,),
        ).fetchone()
        if not row or row["external_status"]:
            return
        if not _is_after_enabled_at(row["created_at"], settings.notification_enabled_at):
            conn.execute(
                "UPDATE notifications SET external_status='skipped' WHERE id=?",
                (notification_id,),
            )
            return

    results = send_configured_channels(row["title"], row["message"], row["action_page"])
    failures = [result for result in results if not result.ok]
    status = "sent" if results and not failures else "failed"
    error = "; ".join(f"{result.provider}: {result.message}" for result in failures)
    if not results:
        status, error = "failed", "未启用任何推送渠道"
    with db() as conn:
        conn.execute(
            """
            UPDATE notifications
            SET external_status=?,external_attempted_at=CURRENT_TIMESTAMP,external_error=?
            WHERE id=?
            """,
            (status, error[:1000], notification_id),
        )


def _is_after_enabled_at(created_at: str, enabled_at: str) -> bool:
    if not enabled_at.strip():
        return False
    try:
        created = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
        enabled = datetime.fromisoformat(enabled_at.replace("Z", "+00:00"))
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if enabled.tzinfo is None:
            enabled = enabled.replace(tzinfo=timezone.utc)
        return created >= enabled
    except ValueError:
        return False


def _transfer_presentation(job: dict) -> tuple[str, str, str]:
    subject = job.get("media_title") or f"任务 #{job['id']}"
    status = job.get("status")
    stage = job.get("stage")
    if status == "needs_review":
        return "warning", f"{subject} 需要确认", "review"
    if stage == "no_resource":
        return "info", f"{subject} 暂无可用资源", "wishlist"
    if status == "done":
        return "success", f"{subject} 转存已完成", "tracking"
    if status == "triggered":
        return "success", f"{subject} 转存任务已提交", "tracking"
    return "error", f"{subject} 处理失败", "tracking"
