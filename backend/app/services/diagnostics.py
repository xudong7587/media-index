from __future__ import annotations

import io
import json
import re
import sqlite3
import zipfile
import os
import platform
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from app.db.database import db

_STARTED = time.monotonic()
_PROBE_LOCK = threading.Lock()
_LAST_PROBE: dict[int, float] = {}
_PROVIDER_FIELDS = {"tmdb_id", "kind", "info_hash", "task_id", "save_path", "title", "year", "last_poll_at",
                    "poll_count", "last_error", "last_result", "status", "message", "target_cid",
                    "file_id", "name", "file_name", "percentDone", "percent_done", "display_percent",
                    "display_status", "status_text", "size", "cid", "pid"}


def safe_provider_state(raw: Any) -> dict:
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return {"state": _safe_text(raw, 120)}
    if not isinstance(value, dict):
        return {}
    return {key: safe_provider_state(item) if isinstance(item, dict) else _safe_context(item)
            for key, item in value.items() if key in _PROVIDER_FIELDS}


def diagnostic_runtime() -> dict:
    from app.core.config import get_settings
    settings = get_settings()
    with db() as conn:
        counts = conn.execute("SELECT status,COUNT(*) AS count FROM transfer_jobs GROUP BY status").fetchall()
        latest = conn.execute("SELECT COALESCE(MAX(id),0) AS id FROM diagnostic_events").fetchone()
    return {"captured_at": datetime.now(timezone.utc).isoformat(), "pid": os.getpid(),
            "python": platform.python_version(), "platform": platform.system(),
            "diagnostics_uptime_seconds": int(time.monotonic() - _STARTED),
            "thread_count": threading.active_count(), "latest_event_id": int(latest["id"]),
            "tasks_by_status": {row["status"]: row["count"] for row in counts},
            "enabled_providers": settings.enabled_provider_keys(),
            "probes": ["p115_cloud_download"], "probe_cooldown_seconds": 30}


def diagnostic_tasks(*, before_id: int = 0, query: str = "", status: str = "", limit: int = 30) -> dict:
    clauses, values = [], []
    if before_id:
        clauses.append("id<?")
        values.append(before_id)
    if query:
        clauses.append("display_title LIKE ? ESCAPE '\\'")
        escaped = query[:120].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        values.append(f"%{escaped}%")
    if status:
        clauses.append("status=?")
        values.append(status[:40])
    values.append(max(1, min(limit, 100)))
    with db() as conn:
        rows = conn.execute("SELECT id,display_title,provider,status,stage,message,save_path,created_at,finished_at "
                            "FROM transfer_jobs " + ("WHERE " + " AND ".join(clauses) if clauses else "")
                            + " ORDER BY id DESC LIMIT ?", values).fetchall()
    return {"tasks": [_safe_context(dict(row)) for row in rows], "next_before_id": rows[-1]["id"] if rows else None}


def diagnostic_probe_download(job_id: int) -> dict | None:
    """Fixed read-only probe derived from a persisted job, with no supplied path/command."""
    from app.clients.p115 import P115Client
    from app.services.paths import cloud_download_direct_child_scope
    with db() as conn:
        row = conn.execute("SELECT provider,save_path,external_provider_status FROM transfer_jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        return None
    state = safe_provider_state(row["external_provider_status"])
    if row["provider"] != "p115" or state.get("kind") != "p115_cloud_download_target":
        return {"supported": False, "message": "该任务没有可核验的 115 云下载记录"}
    if not (state.get("info_hash") or state.get("task_id")):
        return {"supported": False, "message": "该任务缺少精确下载标识，未读取其他下载记录"}
    if not _PROBE_LOCK.acquire(blocking=False):
        return {"supported": True, "busy": True, "retry_after_seconds": 30}
    try:
        now = time.monotonic()
        if now - _LAST_PROBE.get(job_id, -100) < 30:
            return {"supported": True, "busy": True, "retry_after_seconds": 30}
        if len(_LAST_PROBE) > 1000:
            _LAST_PROBE.clear()
        _LAST_PROBE[job_id] = now
        client = P115Client()
        result = client.cloud_download_task_status(str(state.get("info_hash") or ""), str(state.get("task_id") or ""))
        output = {"supported": True, "captured_at": datetime.now(timezone.utc).isoformat(),
                  "status": result.status, "message": _safe_text(result.message),
                  "provider_task": safe_provider_state(result.task), "target_entries": []}
        path = str(row["save_path"] or "")
        if cloud_download_direct_child_scope("p115", path):
            cid = client.directory_id(path)
            output["target_exists"] = bool(cid and str(cid) != "0")
            if output["target_exists"]:
                entries = client.list_directory(cid)
                output["target_entries"] = [{"file_id": item.file_id, "parent_id": item.parent_id,
                                             "name": _safe_text(item.name), "size": item.size, "is_dir": item.is_dir}
                                            for item in entries[:100]]
                output["listing_scope"] = "first_page_max_100"
        record_diagnostic_event("diagnostics", "download_probed", job_id=job_id, context=output)
        return output
    except Exception as exc:
        return {"supported": True, "error": type(exc).__name__, "message": _safe_text(str(exc), 300)}
    finally:
        _PROBE_LOCK.release()


_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(authorization|cookie|token|api[_-]?key|password|passwd|secret)\s*([:=])\s*([^\s,;&]+)"
)
_SECRET_QUERY = re.compile(
    r"(?i)([?&](?:token|access_token|api[_-]?key|password|secret)=)[^&#\s]+"
)


def _safe_text(value: Any, limit: int = 2000) -> str:
    text = str(value or "")[:limit]
    text = re.sub(r"(?im)\b(cookie|authorization)\s*[:=][^\r\n]*", r"\1=[REDACTED]", text)
    text = re.sub(r"(?i)(?:https?://|magnet:\?)[^\s<>\"']+", "[URL REDACTED]", text)
    text = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", text)
    return _SECRET_QUERY.sub(lambda match: f"{match.group(1)}[REDACTED]", text)


def _safe_context(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            safe_key = str(key)[:80]
            if re.search(r"(?i)(authorization|cookie|token|api.?key|password|passwd|secret)", safe_key):
                result[safe_key] = "[REDACTED]"
            else:
                result[safe_key] = _safe_context(item)
        return result
    if isinstance(value, list):
        return [_safe_context(item) for item in value[:100]]
    if isinstance(value, str):
        return _safe_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _safe_text(value)


def record_diagnostic_event(
    component: str,
    event: str,
    *,
    level: str = "info",
    job_id: int | None = None,
    correlation_id: str = "",
    status: str = "",
    stage: str = "",
    message: str = "",
    context: dict[str, Any] | None = None,
) -> None:
    """Record a bounded, redacted developer event without exposing credentials."""
    safe_context = _safe_context(context or {})
    try:
        with db() as conn:
            conn.execute(
                """INSERT INTO diagnostic_events
                   (level,component,event,job_id,correlation_id,status,stage,message_safe,context_json)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    _safe_text(level, 16) or "info",
                    _safe_text(component, 80),
                    _safe_text(event, 120),
                    job_id,
                    _safe_text(correlation_id, 180),
                    _safe_text(status, 80),
                    _safe_text(stage, 120),
                    _safe_text(message),
                    json.dumps(safe_context, ensure_ascii=False, separators=(",", ":")),
                ),
            )
    except (sqlite3.Error, OSError):
        # Diagnostics must never break the workflow it is observing.
        return


def recent_diagnostic_events(*, after_id: int = 0, job_id: int | None = None, limit: int = 200) -> list[dict[str, Any]]:
    """Return a bounded, redacted event stream for the support API."""
    safe_limit = max(1, min(int(limit), 500))
    clauses = ["id>?"]
    values: list[Any] = [max(0, int(after_id))]
    if job_id is not None:
        clauses.append("job_id=?")
        values.append(int(job_id))
    values.append(safe_limit)
    with db() as conn:
        rows = conn.execute(
            f"SELECT * FROM diagnostic_events WHERE {' AND '.join(clauses)} ORDER BY id {'ASC' if after_id else 'DESC'} LIMIT ?",
            tuple(values),
        ).fetchall()
    events: list[dict[str, Any]] = []
    for row in (rows if after_id else reversed(rows)):
        item = dict(row)
        try:
            item["context"] = _safe_context(json.loads(item.pop("context_json") or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            item["context"] = {}
            item.pop("context_json", None)
        item["message_safe"] = _safe_text(item.get("message_safe"))
        events.append(item)
    return events


def diagnostic_task_timeline(job_id: int) -> dict[str, Any] | None:
    """Expose one task and its redacted workflow timeline, never provider payloads."""
    with db() as conn:
        task = conn.execute(
            """SELECT id,batch_id,tmdb_id,media_type,display_title,season_number,target,provider,
                      status,stage,message,save_path,created_at,finished_at,review_state,
                      execution_key,external_job_id,request_source,openlist_fallback_to_p115,external_provider_status
               FROM transfer_jobs WHERE id=?""",
            (int(job_id),),
        ).fetchone()
        if not task:
            return None
        workflows = conn.execute(
            "SELECT step_key,status,message,updated_at FROM media_workflow_steps WHERE job_id=? ORDER BY updated_at,step_key",
            (int(job_id),),
        ).fetchall()
    safe_task = dict(task)
    safe_task["external_provider_status"] = safe_provider_state(safe_task.get("external_provider_status"))
    return {
        "task": _safe_context(safe_task),
        "workflow_steps": [_safe_context(dict(row)) for row in workflows],
        "events": recent_diagnostic_events(job_id=int(job_id), limit=500),
    }


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str).encode("utf-8")


def export_diagnostic_bundle(limit: int = 50000) -> bytes:
    """Export a support bundle containing safe state and an append-only timeline."""
    safe_limit = max(1, min(int(limit), 50000))
    with db() as conn:
        event_rows = conn.execute(
            "SELECT * FROM diagnostic_events ORDER BY id DESC LIMIT ?", (safe_limit,)
        ).fetchall()
        task_rows = conn.execute(
            """SELECT id,batch_id,tmdb_id,media_type,display_title,season_number,target,provider,
                      status,stage,message,save_path,created_at,finished_at,review_state,execution_key,
                      external_job_id,request_source,openlist_fallback_to_p115,external_provider_status
               FROM transfer_jobs ORDER BY id DESC LIMIT 5000"""
        ).fetchall()
        workflow_rows = conn.execute(
            "SELECT job_id,step_key,status,message,updated_at FROM media_workflow_steps ORDER BY updated_at DESC LIMIT 20000"
        ).fetchall()
        deletion_rows = conn.execute(
            """SELECT id,asset_id,trigger_source,state,references_at_request,message_safe,
                      requested_at,confirmed_at,completed_at,updated_at
               FROM deletion_intents ORDER BY id DESC LIMIT 5000"""
        ).fetchall()

    events: list[dict[str, Any]] = []
    for row in reversed(event_rows):
        item = dict(row)
        try:
            item["context"] = _safe_context(json.loads(item.pop("context_json") or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            item["context"] = {}
            item.pop("context_json", None)
        item["message_safe"] = _safe_text(item.get("message_safe"))
        events.append(item)

    tasks = [_safe_context({**dict(row), "external_provider_status": safe_provider_state(row["external_provider_status"])}) for row in task_rows]
    workflows = [_safe_context(dict(row)) for row in workflow_rows]
    deletions = [_safe_context(dict(row)) for row in deletion_rows]
    summary = {
        "event_count": len(events),
        "task_count": len(tasks),
        "events_by_level": dict(Counter(str(item.get("level") or "") for item in events)),
        "events_by_component": dict(Counter(str(item.get("component") or "") for item in events)),
        "tasks_by_status": dict(Counter(str(item.get("status") or "") for item in tasks)),
    }
    manifest = {
        "format": "mediaindex-diagnostics/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "retention": {"days": 30, "maximum_events": 50000},
        "privacy": "credentials, cookies, share URLs and raw provider payloads are excluded or redacted",
    }

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", _json_bytes(manifest))
        archive.writestr("summary.json", _json_bytes(summary))
        archive.writestr("runtime.json", _json_bytes(diagnostic_runtime()))
        archive.writestr(
            "diagnostic-events.jsonl",
            b"\n".join(json.dumps(item, ensure_ascii=False, default=str).encode("utf-8") for item in events),
        )
        archive.writestr("tasks.json", _json_bytes(tasks))
        archive.writestr("workflow-steps.json", _json_bytes(workflows))
        archive.writestr("deletion-intents.json", _json_bytes(deletions))
    return buffer.getvalue()
