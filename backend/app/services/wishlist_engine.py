from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from app.clients.qas import QasClient
from app.core.config import get_settings
from app.db.database import db
from app.services.media_workflow import complete_transfer_workflow_step, initialize_media_workflow, update_media_workflow_step
from app.services.notifications import sync_transfer_notifications
from app.services.openlist_sync import automatic_sync_allowed, sync_transfer_outputs
from app.services.review_notification import notify_review_required
from app.services.post_transfer_pipeline import run_confirmed_native_transfer_post_processing
from app.services.transfer_service_v2 import execute_transfer_v2
from app.services.wishlist_schedule import compute_wishlist_next_check, resolve_wishlist_target
from app.providers.status import normalize_provider_stage, transfer_status_for_stage


def run_due_wishlist_items(limit: int = 3) -> list[dict]:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db() as conn:
        rows = conn.execute(
            """
            SELECT id FROM wishlist
            WHERE status IN ('pending','retry_wait')
              AND COALESCE(enabled,1)=1
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
        provider = str(row["provider"] or "")
        execution_key = (
            f"{row['tmdb_id']}:{row['media_type']}:{row['season_number'] or 0}:"
            f"{row['save_target'] or 'cloud'}:{provider}"
        )
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
        openlist_fallback_to_p115 = _wishlist_openlist_fallback_enabled(provider)
        cur = conn.execute(
            """
            INSERT INTO transfer_jobs(
                wishlist_id,tmdb_id,media_type,season_number,target,provider,status,stage,message,execution_key,
                openlist_fallback_to_p115
            ) VALUES(?,?,?,?,?,?,'running','provider_resolving','愿望单正在按 TMDB 日期检查资源',?,?)
            """,
            (
                item_id,
                item["tmdb_id"],
                item["media_type"],
                item.get("season_number"),
                item.get("save_target") or "cloud",
                provider,
                execution_key,
                1 if openlist_fallback_to_p115 else 0,
            ),
        )
        job_id = int(cur.lastrowid)
    initialize_media_workflow(job_id, openlist_fallback_to_p115=openlist_fallback_to_p115)

    qas_client = qas or QasClient()
    try:
        result = execute_transfer_v2(
            int(item["tmdb_id"]),
            str(item["media_type"]),
            str(item.get("save_target") or "cloud"),
            item.get("season_number"),
            refresh=refresh,
            qas=qas_client,
            provider=item.get("provider") or None,
            category=item.get("category") or "",
        )
    except Exception as exc:
        result = {"ok": False, "stage": "internal_error", "message": f"愿望单检查失败：{type(exc).__name__}", "resolution": {}}

    _persist_job_result(job_id, result)
    stage = normalize_provider_stage(result.get("stage", "unknown"))
    complete_transfer_workflow_step(
        job_id,
        transfer_status_for_stage(stage),
        stage,
        str(result.get("message") or ""),
    )
    if stage in {"provider_completed", "provider_triggered"}:
        status = "completed" if stage == "provider_completed" else "triggered"
        retry_count = 0 if stage == "provider_completed" else int(item.get("retry_count") or 0)
        with db() as conn:
            conn.execute(
                """
                UPDATE wishlist SET status=?,next_check_at=NULL,last_error='',retry_count=?,
                                    last_checked_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (status, retry_count, item_id),
            )
        native_provider = str(result.get("provider") or item.get("provider") or "").strip().lower()
        execution = result.get("execution") or {}
        exact_outputs = execution.get("outputs") or ()
        confirmed_native_transfer = (
            bool(result.get("ok"))
            and stage == "provider_completed"
            and bool(execution.get("confirmed"))
            and str(item.get("save_target") or "cloud") == "cloud"
            and native_provider in {"p115", "quark"}
            and exact_outputs
        )
        if confirmed_native_transfer:
            run_confirmed_native_transfer_post_processing(
                job_id,
                provider=native_provider,
                save_path=str(result.get("save_path") or ""),
                outputs=exact_outputs,
                title=str((result.get("target") or {}).get("title") or item.get("title") or ""),
                poster_url=str(
                    item.get("poster_url")
                    or (result.get("target") or {}).get("poster_url")
                    or ""
                ),
            )
        if confirmed_native_transfer and native_provider == "quark" and openlist_fallback_to_p115:
            sync_results = _sync_wishlist_quark_to_p115(item, result, exact_outputs)
            sync_message = _openlist_results_message(sync_results)
            update_media_workflow_step(
                job_id,
                "openlist_sync",
                "done" if _openlist_post_processing_completed(sync_results) else "failed",
                sync_message,
            )
            with db() as conn:
                conn.execute(
                    "UPDATE transfer_jobs SET message=? WHERE id=?",
                    (f"{result.get('message') or ''}；{sync_message}".strip("；")[:1000], job_id),
                )
            if _openlist_post_processing_completed(sync_results):
                _remove_wishlist_media(item, source_job_id=job_id)
            sync_transfer_notifications()
        if status == "triggered":
            from app.services.qas_reconciler import request_qas_reconciliation

            request_qas_reconciliation()
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


def _wishlist_openlist_fallback_enabled(provider: str) -> bool:
    settings = get_settings()
    return bool(
        str(provider or "").strip().lower() in {"qas", "quark"}
        and settings.openlist_enabled
        and settings.openlist_auto_sync
        and automatic_sync_allowed(settings, provider, "p115")
    )


def _sync_wishlist_quark_to_p115(item: dict, result: dict, outputs) -> list[dict]:
    filenames = [
        str(output.get("file_name") or output.get("name") or "").strip()
        for output in outputs
        if isinstance(output, dict)
    ]
    try:
        return sync_transfer_outputs(
            "quark",
            str(result.get("save_path") or ""),
            filenames,
            tmdb_id=item.get("tmdb_id"),
            media_type=str(item.get("media_type") or ""),
            season_number=item.get("season_number"),
            display_title=str((result.get("target") or {}).get("title") or item.get("title") or ""),
            target_providers=("p115",),
        )
    except Exception:
        return []


def _openlist_post_processing_completed(results: list[dict]) -> bool:
    return any(bool(result.get("ok")) and result.get("landed") is not None for result in results)


def _openlist_results_message(results: list[dict]) -> str:
    if not results:
        return "OpenList 同步未完成：未产生可核验的补齐结果"
    completed = _openlist_post_processing_completed(results)
    job_ids = [str(result.get("job_id")) for result in results if result.get("job_id")]
    if completed:
        return f"OpenList 已完成复制与后处理 #{'、'.join(job_ids)}" if job_ids else "OpenList 已完成复制与后处理"
    detail = str(results[0].get("message") or "未知错误")[:120]
    return f"OpenList 同步未完成：{detail}"


def _remove_wishlist_media(item: dict, *, source_job_id: int) -> None:
    with db() as conn:
        conn.execute(
            "UPDATE transfer_jobs SET notification_sent_at=COALESCE(notification_sent_at,CURRENT_TIMESTAMP) WHERE id=?",
            (int(source_job_id),),
        )
        conn.execute(
            """
            DELETE FROM wishlist
            WHERE tmdb_id=? AND media_type=? AND COALESCE(season_number,0)=?
            """,
            (item.get("tmdb_id"), item.get("media_type"), int(item.get("season_number") or 0)),
        )


def _persist_job_result(job_id: int, result: dict) -> None:
    stage = result.get("stage", "unknown")
    stage = normalize_provider_stage(stage)
    status = transfer_status_for_stage(stage)
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
                    candidate.get("cloud_type") or "quark",
                    candidate.get("provider") or "qas",
                    candidate.get("published_at", ""),
                    len(candidate.get("files") or []),
                    json.dumps(candidate.get("files") or [], ensure_ascii=False),
                    candidate.get("score", 0),
                    1 if candidate.get("rejected") else 0,
                    json.dumps(candidate.get("reasons") or [], ensure_ascii=False),
                ),
            )
