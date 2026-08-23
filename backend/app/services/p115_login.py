from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any

from app.clients.p115 import P115Error


@dataclass(frozen=True)
class P115LoginSession:
    session_id: str
    qr_url: str
    expires_at: float


@dataclass(frozen=True)
class P115LoginPoll:
    status: str
    access_token: str = ""
    refresh_token: str = ""


@dataclass
class _PendingSession:
    qr_token: dict[str, Any]
    expires_at: float


class P115OpenLoginService:
    """Short-lived bridge for the official 115 Open device-code login."""

    def __init__(self, *, app_id: int = 100195125, ttl_seconds: int = 300) -> None:
        self.app_id = app_id
        self.ttl_seconds = ttl_seconds
        self._sessions: dict[str, _PendingSession] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _sdk():
        try:
            from p115client import P115Client as SdkClient
        except ImportError as exc:  # pragma: no cover - deployment dependency boundary
            raise P115Error("115 文件接口组件不可用") from exc
        return SdkClient

    def start(self) -> P115LoginSession:
        try:
            response = self._sdk().login_qrcode_token_open(self.app_id)
        except Exception as exc:
            raise P115Error("115 文件接口扫码会话创建失败") from exc
        data = _response_data(response, "115 文件接口扫码会话创建")
        if not str(data.get("uid") or "").strip():
            raise P115Error("115 文件接口未返回扫码会话标识")
        token = dict(data)
        qr_url = str(token.get("qrcode") or f"https://115.com/scan/dg-{token['uid']}")
        now = time.monotonic()
        session_id = secrets.token_urlsafe(32)
        expires_at = now + self.ttl_seconds
        with self._lock:
            self._discard_expired(now)
            self._sessions[session_id] = _PendingSession(token, expires_at)
        return P115LoginSession(session_id, qr_url, expires_at)

    def poll(self, session_id: str) -> P115LoginPoll:
        now = time.monotonic()
        with self._lock:
            self._discard_expired(now)
            pending = self._sessions.get(session_id)
        if pending is None:
            return P115LoginPoll("expired")
        try:
            response = self._sdk().login_qrcode_scan_status(pending.qr_token)
            data = _response_data(response, "115 扫码状态读取")
            status = int(data.get("status", 0))
        except Exception as exc:
            if isinstance(exc, P115Error):
                raise
            raise P115Error("115 扫码状态读取失败") from exc
        if status == 0:
            return P115LoginPoll("waiting")
        if status == 1:
            return P115LoginPoll("scanned")
        if status in {-1, -2}:
            with self._lock:
                self._sessions.pop(session_id, None)
            return P115LoginPoll("expired" if status == -1 else "failed")
        if status != 2:
            return P115LoginPoll("waiting")
        try:
            response = self._sdk().login_qrcode_access_token_open(str(pending.qr_token["uid"]))
            token_data = _response_data(response, "115 文件接口授权换取")
            access_token = str(token_data.get("access_token") or "").strip()
            refresh_token = str(token_data.get("refresh_token") or "").strip()
        except Exception as exc:
            if isinstance(exc, P115Error):
                raise
            raise P115Error("115 文件接口授权换取失败") from exc
        if not access_token or not refresh_token:
            raise P115Error("115 文件接口未返回完整授权")
        with self._lock:
            self._sessions.pop(session_id, None)
        return P115LoginPoll("success", access_token, refresh_token)

    def _discard_expired(self, now: float) -> None:
        self._sessions = {key: value for key, value in self._sessions.items() if value.expires_at > now}


def _response_data(response: object, action: str) -> dict[str, Any]:
    """Return Open API data while retaining a short, non-secret failure reason."""
    if not isinstance(response, dict):
        raise P115Error(f"{action}未返回有效响应")
    data = response.get("data")
    failed = response.get("state") is False or str(response.get("code", "0")) not in {"", "0", "None"}
    if failed or not isinstance(data, dict):
        reason = str(response.get("error") or response.get("message") or response.get("msg") or "服务未返回可用数据").strip()
        reason = " ".join(reason.split())[:180]
        raise P115Error(f"{action}失败：{reason}")
    return data
