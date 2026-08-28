from __future__ import annotations

import io
import json
import re
import sqlite3
import zipfile
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from app.db.database import db


_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(authorization|cookie|token|api[_-]?key|password|passwd|secret)\s*([:=])\s*([^\s,;&]+)"
)
_SECRET_QUERY = re.compile(
    r"(?i)([?&](?:token|access_token|api[_-]?key|password|secret)=)[^&#\s]+"
)


def _safe_text(value: Any, limit: int = 2000) -> str:
    text = str(value or "")[:limit]
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
                      external_job_id,request_source,openlist_fallback_to_p115
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

    tasks = [_safe_context(dict(row)) for row in task_rows]
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
        archive.writestr(
            "diagnostic-events.jsonl",
            b"\n".join(json.dumps(item, ensure_ascii=False, default=str).encode("utf-8") for item in events),
        )
        archive.writestr("tasks.json", _json_bytes(tasks))
        archive.writestr("workflow-steps.json", _json_bytes(workflows))
        archive.writestr("deletion-intents.json", _json_bytes(deletions))
    return buffer.getvalue()
