from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from app.clients.qas import QasClient
from app.db.database import db
from app.services.review_notification import notify_review_required
from app.services.transfer_service_v2 import execute_transfer_v2
from app.services.wishlist_schedule import compute_wishlist_next_check, resolve_wishlist_target


def run_due_wishlist_items(limit: int = 3) -> list[dict]:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db() as conn:
        rows = conn.execute(
            """
            SELECT id FROM wishlist
            WHERE status IN ('pending','retry_wait')
              AND next_check_at IS NOT NULL AND next_check_at!='' AND next_check_at<=?
            ORDER BY next_check_at LIMIT ?
            """,
            (now, limit),
        ).fetchall()
    return [run_wishlist_item(int(row["id"])) for row in rows]


def run_wishlist_item(item_id: int, *, refresh: bool = False, qas: QasClient | None = None) -> dict:
    with db() as conn:
        row = conn.execute("SELECT * FROM wishlist WHERE id=?", (item_id,)).fetchone()
        if not row:
            return {"ok": False, "stage": "not_found"}
        execution_key = f"{row['tmdb_id']}:{row['media_type']}:{row['season_number'] or 0}:{row['save_target'] or 'cloud'}"
        active = conn.execute(
            "SELECT id FROM transfer_jobs WHERE execution_key=? AND status IN ('running','ready','triggered') LIMIT 1",
            (execution_key,),
        ).fetchone()
        if active:
            return {"ok": False, "stage": "duplicate_active", "job_id": int(active["id"])}
        locked = conn.execute(
            """
            UPDATE wishlist SET status='checking',last_checked_at=CURRENT_TIMESTAMP
            WHERE id=? AND status IN ('pending','retry_wait','needs_review')
            """,
            (item_id,),
        ).rowcount
        if not locked:
            return {"ok": False, "stage": "not_runnable"}
        item = dict(row)
        cur = conn.execute(
            """
            INSERT INTO transfer_jobs(wishlist_id,tmdb_id,media_type,season_number,target,status,stage,message,execution_key)
            VALUES(?,?,?,?,?,'running','resolving','愿望单正在按 TMDB 日期检查资源',?)
            """,
            (
                item_id,
                item["tmdb_id"],
                item["media_type"],
                item.get("season_number"),
                item.get("save_target") or "cloud",
                execution_key,
            ),
        )
        job_id = int(cur.lastrowid)

    qas_client = qas or QasClient()
    try:
        result = execute_transfer_v2(
            int(item["tmdb_id"]),
            str(item["media_type"]),
            str(item.get("save_target") or "cloud"),
            item.get("season_number"),
            refresh=refresh,
            qas=qas_client,
        )
    except Exception as exc:
        result = {"ok": False, "stage": "internal_error", "message": f"愿望单检查失败：{type(exc).__name__}", "resolution": {}}

    _persist_job_result(job_id, result)
    stage = result.get("stage", "unknown")
    if stage in {"qas_completed", "qas_triggered"}:
        status = "completed" if stage == "qas_completed" else "triggered"
        retry_count = 0 if stage == "qas_completed" else int(item.get("retry_count") or 0)
        with db() as conn:
            conn.execute(
                """
                UPDATE wishlist SET status=?,next_check_at=NULL,last_error='',retry_count=?,
                                    last_checked_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (status, retry_count, item_id),
            )
        return {"ok": True, "stage": stage, "job_id": job_id}

    if stage == "needs_review":
        with db() as conn:
            conn.execute(
                """
                UPDATE wishlist SET status='needs_review',next_check_at=NULL,last_error=?,
                                    last_checked_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (result.get("message", "")[:1000], item_id),
            )
        notification = notify_review_required(item["title"], result.get("message", ""), job_id, qas=qas_client)
        with db() as conn:
            conn.execute(
                """
                UPDATE transfer_jobs SET review_state=?,
                    notification_sent_at=CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE notification_sent_at END
                WHERE id=?
                """,
                ("notified" if notification.sent else "notification_failed", 1 if notification.sent else 0, job_id),
            )
            if notification.sent:
                conn.execute("UPDATE wishlist SET notification_sent_at=CURRENT_TIMESTAMP WHERE id=?", (item_id,))
        return {"ok": False, "stage": "needs_review", "job_id": job_id}

    try:
        target = resolve_wishlist_target(item["tmdb_id"], item["media_type"], item.get("season_number"))
        next_check_at, tmdb_date = compute_wishlist_next_check(target, int(item.get("check_hour") or 9))
    except Exception:
        next_check_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(timespec="seconds")
        tmdb_date = item.get("tmdb_date") or ""
    with db() as conn:
        conn.execute(
            """
            UPDATE wishlist SET status='retry_wait',next_check_at=?,tmdb_date=?,last_error=?,
                                retry_count=retry_count+1,last_checked_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (next_check_at, tmdb_date, result.get("message", "")[:1000], item_id),
        )
    return {"ok": False, "stage": stage, "job_id": job_id, "next_check_at": next_check_at}


def _persist_job_result(job_id: int, result: dict) -> None:
    stage = result.get("stage", "unknown")
    status = "done" if stage == "qas_completed" else "triggered" if stage == "qas_triggered" else "needs_review" if stage == "needs_review" else "failed"
    resolution = result.get("resolution") or {}
    pairs = resolution.get("rename_pairs") or []
    first_pair = pairs[0] if pairs else {}
    with db() as conn:
        conn.execute(
            """
            UPDATE transfer_jobs SET status=?,stage=?,message=?,share_url=?,source_file=?,renamed_file=?,
                                     rename_pairs_json=?,save_path=?,finished_at=CURRENT_TIMESTAMP
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
