from __future__ import annotations

import json
import queue
import threading
from typing import Any, Iterable, Mapping

from app.core.config import get_settings
from app.db.database import db
from app.services.diagnostics import record_diagnostic_event
from app.services.media_workflow import update_media_workflow_step
from app.services.openlist_sync import automatic_sync_allowed
from app.services.p115_completion import complete_quark_to_p115


_workers: set[int] = set()
_workers_lock = threading.Lock()
_work_queue: queue.Queue[int] = queue.Queue()
_worker_threads_started = False


def _decode(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _write_completion_state(job_id: int, **updates: Any) -> bool:
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT external_provider_status FROM transfer_jobs WHERE id=?",
            (int(job_id),),
        ).fetchone()
        if not row:
            return False
        state = _decode(row["external_provider_status"])
        completion = state.get("p115_completion")
        if not isinstance(completion, dict):
            completion = {}
        completion.update(updates)
        state["p115_completion"] = completion
        conn.execute(
            "UPDATE transfer_jobs SET external_provider_status=? WHERE id=?",
            (json.dumps(state, ensure_ascii=False, separators=(",", ":")), int(job_id)),
        )
    return True


def _mark_completion_review(job_id: int, message: str) -> None:
    _write_completion_state(job_id, state="needs_review", workflow_status="review", message=message)
    update_media_workflow_step(job_id, "openlist_sync", "review", message)


def enqueue_organized_quark_completion(
    job_id: int,
    *,
    save_path: str,
    target_files: Iterable[Mapping[str, Any]],
    tmdb_id: int | None,
    media_type: str,
    season_number: int | None,
    title: str,
    year: str = "",
    category: str = "",
    poster_url: str = "",
) -> bool:
    """Queue 115 completion only after an organizer has verified final targets."""
    prepared = prepare_organized_quark_completion(
        job_id,
        save_path=save_path,
        target_files=target_files,
        tmdb_id=tmdb_id,
        media_type=media_type,
        season_number=season_number,
        title=title,
        year=year,
        category=category,
        poster_url=poster_url,
    )
    if not prepared:
        return False
    with db() as conn:
        row = conn.execute("SELECT status,stage FROM transfer_jobs WHERE id=?", (int(job_id),)).fetchone()
    if not row or str(row["status"] or "") != "done" or str(row["stage"] or "") != "organizer_completed":
        return False
    return request_organized_quark_completion(job_id)


def prepare_organized_quark_completion(
    job_id: int,
    *,
    save_path: str,
    target_files: Iterable[Mapping[str, Any]],
    tmdb_id: int | None,
    media_type: str,
    season_number: int | None,
    title: str,
    year: str = "",
    category: str = "",
    poster_url: str = "",
) -> bool:
    """Persist the queued hand-off before the organizer is marked complete."""
    settings = get_settings()
    if not (
        settings.openlist_enabled
        and settings.openlist_auto_sync
        and automatic_sync_allowed(settings, "quark", "p115")
    ):
        return False
    filenames = tuple(
        dict.fromkeys(
            str(item.get("file_name") or item.get("name") or "").strip()
            for item in target_files
            if str(item.get("file_name") or item.get("name") or "").strip()
        )
    )
    if not save_path or not filenames:
        update_media_workflow_step(job_id, "openlist_sync", "failed", "标准落盘目标不完整，未启动 115 补齐")
        return False
    with db() as conn:
        row = conn.execute(
            "SELECT status,stage,provider,external_provider_status FROM transfer_jobs WHERE id=?",
            (int(job_id),),
        ).fetchone()
    if not row or str(row["provider"] or "") != "quark" or str(row["status"] or "") == "stopped":
        return False
    existing = _decode(row["external_provider_status"]).get("p115_completion")
    if isinstance(existing, dict) and existing.get("state") == "needs_review":
        return False
    if isinstance(existing, dict) and str(existing.get("state") or "") in {"queued", "working", "submitted", "done"}:
        return True
    payload = {
        "state": "queued",
        "save_path": save_path,
        "filenames": list(filenames),
        "tmdb_id": tmdb_id,
        "media_type": media_type,
        "season_number": season_number,
        "title": title,
        "year": year,
        "category": category,
        "poster_url": poster_url,
    }
    _write_completion_state(job_id, **payload)
    update_media_workflow_step(job_id, "openlist_sync", "pending", "标准命名与目录落盘已核验，115 补齐已排队")
    record_diagnostic_event(
        "transfer",
        "p115_completion_queued",
        job_id=job_id,
        status="queued",
        stage="organized_landing_verified",
        message="标准落盘已核验，115 补齐已排队",
        context={"file_count": len(filenames), "save_path": save_path},
    )
    return True


def request_organized_quark_completion(job_id: int) -> bool:
    global _worker_threads_started
    with _workers_lock:
        if int(job_id) in _workers:
            return True
        if not _worker_threads_started:
            for index in range(2):
                threading.Thread(
                    target=_completion_worker,
                    name=f"media-index-organized-p115-{index + 1}",
                    daemon=True,
                ).start()
            _worker_threads_started = True
        _workers.add(int(job_id))
    _work_queue.put(int(job_id))
    return True


def _completion_worker() -> None:
    while True:
        job_id = _work_queue.get()
        try:
            _run_completion(job_id)
        finally:
            _work_queue.task_done()


def _run_completion(job_id: int) -> None:
    try:
        with db() as conn:
            row = conn.execute(
                "SELECT status,stage,external_provider_status FROM transfer_jobs WHERE id=?",
                (int(job_id),),
            ).fetchone()
        if not row or str(row["status"] or "") != "done" or str(row["stage"] or "") != "organizer_completed":
            return
        payload = _decode(row["external_provider_status"]).get("p115_completion")
        if not isinstance(payload, dict) or str(payload.get("state") or "") in {"done", "needs_review"}:
            return
        if payload.get("state") == "submitted":
            reconcile_submitted_organized_quark_completions()
            return
        if payload.get("state") == "working":
            # A previous process may have submitted a native write without
            # recording its receipt. Recovery must not repeat that write.
            _mark_completion_review(job_id, "115 补齐上次执行中断，提交结果尚未确认；请核对 115 目标和跨盘任务，本次不会重复转存")
            return
        _write_completion_state(job_id, state="working")
        update_media_workflow_step(job_id, "openlist_sync", "running", "正在优先搜索并核验原生 115 资源，缺失项才使用 OpenList")
        record_diagnostic_event(
            "transfer", "p115_completion_started", job_id=job_id, status="running", stage="p115_native_search"
        )
        result = complete_quark_to_p115(
            job_id=job_id,
            save_path=str(payload.get("save_path") or ""),
            filenames=tuple(str(value) for value in payload.get("filenames") or ()),
            tmdb_id=payload.get("tmdb_id"),
            media_type=str(payload.get("media_type") or ""),
            season_number=payload.get("season_number"),
            title=str(payload.get("title") or ""),
            year=str(payload.get("year") or ""),
            category=str(payload.get("category") or ""),
            poster_url=str(payload.get("poster_url") or ""),
            # This lane is independent from the user's Quark backfill choice:
            # a complete native 115 season may fill its own aired gaps now;
            # OpenList still copies only exact files proven in Quark.
            supplement_missing_episodes=True,
        )
        state = (
            "done" if result.workflow_status in {"done", "skipped"}
            else "needs_review" if result.workflow_status == "review"
            else "failed" if result.workflow_status == "failed"
            else "submitted"
        )
        copy_job_ids = sorted({int(item["job_id"]) for item in result.openlist_results if item.get("job_id")})
        _write_completion_state(job_id, state=state, message=result.message, workflow_status=result.workflow_status,
                                copy_job_ids=copy_job_ids)
        update_media_workflow_step(job_id, "openlist_sync", result.workflow_status, result.message or "本次无需 115 补齐")
        record_diagnostic_event(
            "transfer",
            "p115_completion_completed",
            job_id=job_id,
            status=state,
            stage="p115_completion",
            message=result.message,
            context={"native_attempted": result.native_attempted, "native_completed": result.native_completed},
        )
    except Exception as exc:
        message = f"115 补齐未完成（{type(exc).__name__}）"
        _mark_completion_review(job_id, message + "；执行结果需核验，不会自动重新转存")
        record_diagnostic_event(
            "transfer", "p115_completion_failed", job_id=job_id, level="warning", status="failed", message=message
        )
    finally:
        with _workers_lock:
            _workers.discard(int(job_id))


def recover_organized_quark_completions() -> int:
    reconcile_submitted_organized_quark_completions()
    with db() as conn:
        rows = conn.execute(
            """SELECT id,external_provider_status FROM transfer_jobs
               WHERE provider='quark' AND status='done' AND stage='organizer_completed'
                 AND external_provider_status LIKE '%\"p115_completion\"%'
                 AND (external_provider_status LIKE '%\"queued\"%' OR external_provider_status LIKE '%\"working\"%')
               ORDER BY id"""
        ).fetchall()
    pending = []
    for row in rows:
        value = _decode(row["external_provider_status"]).get("p115_completion")
        if isinstance(value, dict) and str(value.get("state") or "") in {"queued", "working"}:
            pending.append(int(row["id"]))
    return sum(1 for job_id in pending if request_organized_quark_completion(job_id))


def reconcile_submitted_organized_quark_completions() -> int:
    """Reflect child copy outcomes without re-submitting a transfer.

    A parent organizer is already done; its completion lane must independently
    follow the copy job through landing and downstream post-processing.
    """
    with db() as conn:
        rows = conn.execute(
            """SELECT id,external_provider_status FROM transfer_jobs
               WHERE provider='quark' AND status='done' AND stage='organizer_completed'
                 AND external_provider_status LIKE '%"p115_completion"%'
                 AND external_provider_status LIKE '%"submitted"%'"""
        ).fetchall()
    updated = 0
    for row in rows:
        payload = _decode(row["external_provider_status"]).get("p115_completion")
        if not isinstance(payload, dict) or payload.get("state") != "submitted":
            continue
        raw_ids = payload.get("copy_job_ids")
        if not isinstance(raw_ids, list) or not raw_ids or any(type(value) is not int or value <= 0 for value in raw_ids):
            # Surface the missing evidence instead of leaving a legacy parent
            # "running" forever. Never guess by title or repeat cloud writes.
            _mark_completion_review(int(row["id"]), "历史 115 补齐记录缺少可验证的子任务编号；请在跨盘任务中核对实际结果，本条记录不会自动重试")
            updated += 1
            continue
        ids = sorted(set(raw_ids))
        with db() as conn:
            children = conn.execute(
                f"SELECT status,stage FROM transfer_jobs WHERE provider='openlist' AND id IN ({','.join('?' for _ in ids)})",
                ids,
            ).fetchall()
        if len(children) != len(ids):
            state, workflow, message = "failed", "failed", "115 补齐子任务记录不完整，请人工核验"
        elif any(child["status"] in {"failed", "stopped", "needs_review"} for child in children):
            state, workflow, message = "failed", "failed", "115 补齐或后处理未完成，请查看跨盘子任务"
        elif all(child["status"] == "done" and child["stage"] == "openlist_post_processing_done" for child in children):
            state, workflow, message = "done", "done", "115 补齐已确认落盘，后处理已完成"
        else:
            continue
        _write_completion_state(int(row["id"]), state=state, workflow_status=workflow, message=message)
        update_media_workflow_step(int(row["id"]), "openlist_sync", workflow, message)
        updated += 1
    return updated
