from __future__ import annotations

from collections.abc import Iterable

from app.db.database import db
from app.services.notifications import add_notification


def refresh_transfer_batch_status(batch_id: int) -> None:
    """Recompute one ordinary transfer batch without crossing into the API layer."""
    with db() as conn:
        batch = conn.execute("SELECT * FROM transfer_batches WHERE id=?", (batch_id,)).fetchone()
        rows = conn.execute(
            """
            SELECT j.id,j.provider,j.season_number,j.status,j.stage,j.message,j.execution_key,j.openlist_fallback_to_p115,
                   COALESCE(w.status,'') AS openlist_status
            FROM transfer_jobs j
            JOIN transfer_batch_jobs bj ON bj.job_id=j.id
            LEFT JOIN media_workflow_steps w ON w.job_id=j.id AND w.step_key='openlist_sync'
            WHERE bj.batch_id=?
            """,
            (batch_id,),
        ).fetchall()
    if not batch:
        return
    # Tracking cycles own a richer terminal state and must not be overwritten
    # by the generic transfer-batch aggregation rules.
    if any(str(row["execution_key"] or "").startswith("tracking-cycle:") for row in rows):
        return
    running = [row for row in rows if row["status"] in {"running", "ready"}]
    successes = [row for row in rows if row["status"] in {"done", "triggered"}]
    reviews = [row for row in rows if row["status"] == "needs_review"]
    failures = [row for row in rows if row["status"] == "failed" and not batch_missing_is_covered(row, rows)]
    if running:
        status = "running"
        message = f"{len(running)} 个网盘子任务仍在执行"
    elif successes and (reviews or failures):
        status = "partial"
        message = f"{len(successes)} 个子任务成功，{len(reviews) + len(failures)} 个需要处理"
    elif successes:
        status = "done"
        message = f"{len(successes)} 个网盘子任务全部完成"
    elif reviews:
        status = "needs_review"
        message = f"{len(reviews)} 个网盘子任务需要确认"
    elif rows and all(row["status"] == "stopped" for row in rows):
        status = "stopped"
        message = "全部子任务已停止"
    else:
        status = "failed"
        message = f"{len(failures)} 个网盘子任务均未完成"
    with db() as conn:
        conn.execute(
            """
            UPDATE transfer_batches SET status=?,message=?,
                finished_at=CASE WHEN ?!='running' THEN CURRENT_TIMESTAMP ELSE finished_at END
            WHERE id=?
            """,
            (status, message, status, batch_id),
        )
    if status not in {"partial", "failed"}:
        return
    details = "；".join(
        f"{row['provider']} S{int(row['season_number'] or 0):02d}: {str(row['message'] or '')[:120]}"
        for row in [*failures, *reviews]
    )
    add_notification(
        f"transfer-batch:{batch_id}:{status}",
        "warning" if status == "partial" else "error",
        f"{batch['display_title'] or '媒体'}多网盘转存{'部分完成' if status == 'partial' else '失败'}",
        details or message,
        action_page="/review" if reviews else "/history",
    )
    # This batch-level warning/error is the sole terminal notice for the user
    # operation; suppress per-child notification backfill.
    with db() as conn:
        conn.execute(
            """
            UPDATE transfer_jobs SET notification_sent_at=COALESCE(notification_sent_at,CURRENT_TIMESTAMP)
            WHERE id IN (SELECT job_id FROM transfer_batch_jobs WHERE batch_id=?)
            """,
            (batch_id,),
        )


def batch_missing_is_covered(row, rows: Iterable) -> bool:
    if str(row["stage"] or "") != "no_resource" or str(row["provider"] or "") != "p115":
        return False
    season_number = int(row["season_number"] or 0)
    for sibling in rows:
        sibling_provider = str(sibling["provider"] or "")
        if int(sibling["season_number"] or 0) != season_number or sibling["status"] not in {"done", "triggered"}:
            continue
        if (
            sibling_provider in {"qas", "quark"}
            and bool(sibling["openlist_fallback_to_p115"])
            and str(sibling["openlist_status"] or "") in {"running", "done"}
        ):
            return True
    return False
