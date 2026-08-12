from __future__ import annotations

from app.db.database import db


def recover_untracked_provider_submissions() -> int:
    """Close accepted external-provider jobs that MediaIndex cannot poll.

    Older releases left 115 and MoviePilot submissions in ``triggered``
    forever.  The external service may still be working, but MediaIndex has no
    in-process work left, so these records must be terminal without claiming
    that the destination file has been confirmed.
    """
    with db() as conn:
        rows = conn.execute(
            """
            SELECT id,message FROM transfer_jobs
            WHERE status='triggered'
              AND provider IN ('p115','moviepilot_115')
              AND stage IN ('provider_submitting','provider_triggered')
            """
        ).fetchall()
        for row in rows:
            message = str(row["message"] or "").strip()
            suffix = "任务已交给网盘后台处理，MediaIndex 不再持续跟踪；请在对应网盘中查看最终进度"
            if suffix not in message:
                message = f"{message}；{suffix}" if message else suffix
            conn.execute(
                """
                UPDATE transfer_jobs
                SET status='done',stage='provider_submitted',message=?,finished_at=CURRENT_TIMESTAMP
                WHERE id=? AND status='triggered'
                """,
                (message[:1000], int(row["id"])),
            )
    return len(rows)
