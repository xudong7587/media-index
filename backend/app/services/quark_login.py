from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass

from app.clients.quark import QuarkClient, QuarkQrLogin, QuarkQrPoll


@dataclass(frozen=True)
class QuarkLoginSession:
    session_id: str
    qr_url: str
    expires_at: float


@dataclass
class _PendingSession:
    upstream_token: str
    expires_at: float
    upstream_cookie: str = ""


class QuarkLoginService:
    """In-memory, short-lived bridge between a browser QR session and Quark."""

    def __init__(self, client: QuarkClient | None = None, *, ttl_seconds: int = 300) -> None:
        self.client = client or QuarkClient()
        self.ttl_seconds = ttl_seconds
        self._sessions: dict[str, _PendingSession] = {}
        self._lock = threading.Lock()

    def start(self) -> QuarkLoginSession:
        login: QuarkQrLogin = self.client.start_qr_login()
        now = time.monotonic()
        session_id = secrets.token_urlsafe(32)
        expires_at = now + self.ttl_seconds
        with self._lock:
            self._discard_expired(now)
            self._sessions[session_id] = _PendingSession(login.token, expires_at, login.cookie)
        return QuarkLoginSession(session_id=session_id, qr_url=login.qr_url, expires_at=expires_at)

    def poll(self, session_id: str) -> QuarkQrPoll:
        now = time.monotonic()
        with self._lock:
            self._discard_expired(now)
            session = self._sessions.get(session_id)
        if session is None:
            return QuarkQrPoll(status="expired")
        result = self.client.poll_qr_login(session.upstream_token, session.upstream_cookie)
        if result.status == "waiting" and result.cookie:
            with self._lock:
                current = self._sessions.get(session_id)
                if current is not None:
                    current.upstream_cookie = result.cookie
        if result.status in {"success", "expired", "failed"}:
            with self._lock:
                self._sessions.pop(session_id, None)
        return result

    def _discard_expired(self, now: float) -> None:
        self._sessions = {key: value for key, value in self._sessions.items() if value.expires_at > now}
