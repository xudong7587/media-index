from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
import threading
import time

from fastapi import Header, HTTPException, Request

from app.core.config import get_settings
from app.db.database import db
from app.services.diagnostics import record_diagnostic_event


_RATE_LIMIT = 60
_RATE_WINDOW_SECONDS = 60.0
_rate_lock = threading.Lock()
_rate_hits: dict[str, deque[float]] = defaultdict(deque)


def _db_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def support_status() -> dict[str, object]:
    enabled = bool(getattr(get_settings(), "developer_remote_diagnostics_enabled", False))
    with db() as conn:
        conn.execute(
            "DELETE FROM diagnostic_support_tokens WHERE expires_at<=datetime('now','-1 day') OR revoked_at IS NOT NULL"
        )
        row = conn.execute(
            """SELECT COUNT(*) AS count,MIN(expires_at) AS next_expiry
               FROM diagnostic_support_tokens
               WHERE revoked_at IS NULL AND expires_at>datetime('now')"""
        ).fetchone()
    return {
        "enabled": enabled,
        "active_token_count": int(row["count"] if row else 0),
        "next_expiry": str(row["next_expiry"] or "") if row else "",
        "scope": "diagnostics:read",
        "maximum_ttl_minutes": 120,
    }


def create_support_token(ttl_minutes: int) -> dict[str, object]:
    if not bool(getattr(get_settings(), "developer_remote_diagnostics_enabled", False)):
        raise HTTPException(status_code=409, detail="请先启用远程只读诊断")
    ttl = max(5, min(int(ttl_minutes), 120))
    token = f"mi_diag_{secrets.token_urlsafe(32)}"
    expires = datetime.now(timezone.utc) + timedelta(minutes=ttl)
    prefix = token[:16]
    with db() as conn:
        conn.execute(
            """INSERT INTO diagnostic_support_tokens(token_hash,token_prefix,expires_at)
               VALUES(?,?,?)""",
            (_digest(token), prefix, _db_time(expires)),
        )
    record_diagnostic_event(
        "diagnostics",
        "support_token_created",
        message="已创建短时只读诊断令牌",
        context={"ttl_minutes": ttl, "token_prefix": prefix},
    )
    return {
        "token": token,
        "expires_at": expires.isoformat(),
        "scope": "diagnostics:read",
    }


def revoke_support_tokens() -> int:
    with db() as conn:
        cursor = conn.execute(
            """UPDATE diagnostic_support_tokens SET revoked_at=CURRENT_TIMESTAMP
               WHERE revoked_at IS NULL AND expires_at>datetime('now')"""
        )
    count = int(cursor.rowcount)
    record_diagnostic_event(
        "diagnostics",
        "support_tokens_revoked",
        message="已撤销全部远程诊断令牌",
        context={"count": count},
    )
    return count


def _rate_limit(token_id: int, request: Request) -> None:
    peer = request.client.host if request.client else "unknown"
    key = f"{token_id}:{peer}"
    now = time.monotonic()
    with _rate_lock:
        hits = _rate_hits[key]
        while hits and now - hits[0] >= _RATE_WINDOW_SECONDS:
            hits.popleft()
        if len(hits) >= _RATE_LIMIT:
            raise HTTPException(status_code=429, detail="诊断读取过于频繁，请稍后重试")
        hits.append(now)
        if len(_rate_hits) > 2048:
            stale = [item for item, values in _rate_hits.items() if not values or now - values[-1] >= _RATE_WINDOW_SECONDS]
            for item in stale[:1024]:
                _rate_hits.pop(item, None)


def require_support_token(request: Request, authorization: str = Header(default="")) -> int:
    if not bool(getattr(get_settings(), "developer_remote_diagnostics_enabled", False)):
        raise HTTPException(status_code=403, detail="远程诊断未启用")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.startswith("mi_diag_") or len(token) > 160:
        raise HTTPException(status_code=401, detail="诊断令牌无效")
    with db() as conn:
        row = conn.execute(
            """SELECT id FROM diagnostic_support_tokens
               WHERE token_hash=? AND revoked_at IS NULL AND expires_at>datetime('now')""",
            (_digest(token),),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="诊断令牌无效或已过期")
        token_id = int(row["id"])
        conn.execute(
            "UPDATE diagnostic_support_tokens SET last_used_at=CURRENT_TIMESTAMP WHERE id=?",
            (token_id,),
        )
    _rate_limit(token_id, request)
    return token_id
