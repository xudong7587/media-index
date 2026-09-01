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
        if not isinstance(payload, dict) or str(payload.get("state") or "") == "done":
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
        )
        state = "done" if result.workflow_status in {"done", "skipped"} else "failed" if result.workflow_status == "failed" else "submitted"
        _write_completion_state(job_id, state=state, message=result.message, workflow_status=result.workflow_status)
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
        _write_completion_state(job_id, state="failed", message=message)
        update_media_workflow_step(job_id, "openlist_sync", "failed", message)
        record_diagnostic_event(
            "transfer", "p115_completion_failed", job_id=job_id, level="warning", status="failed", message=message
        )
    finally:
        with _workers_lock:
            _workers.discard(int(job_id))


def recover_organized_quark_completions() -> int:
    with db() as conn:
        rows = conn.execute(
            """SELECT id,external_provider_status FROM transfer_jobs
               WHERE provider='quark' AND status='done' AND stage='organizer_completed'
                 AND external_provider_status LIKE '%\"p115_completion\"%'
               ORDER BY id DESC LIMIT 100"""
        ).fetchall()
    pending = []
    for row in rows:
        value = _decode(row["external_provider_status"]).get("p115_completion")
        if isinstance(value, dict) and str(value.get("state") or "") in {"queued", "working"}:
            pending.append(int(row["id"]))
    return sum(1 for job_id in pending if request_organized_quark_completion(job_id))
