from __future__ import annotations

import base64
import json
import secrets
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from io import BytesIO
from typing import Any

import qrcode

from app.clients.p115 import P115Error, valid_p115_cookie
from app.core.config import Settings, get_settings
from app.services.p115_credentials import mask_p115_cookie, save_p115_cookie


QRCODE_TOKEN_API = "https://qrcodeapi.115.com/api/1.0/web/1.0/token/"
QRCODE_STATUS_API = "https://qrcodeapi.115.com/get/status/"
PASSPORT_QRCODE_API = "https://passportapi.115.com/app/1.0/{app}/1.0/login/qrcode/"

# Binding an app kicks the same app's already signed-in device.  The mini-app
# channel is the least surprising default because it does not replace the
# user's common web or mobile 115 session.
P115_COOKIE_LOGIN_APPS = (
    "web",
    "android",
    "ios",
    "linux",
    "mac",
    "windows",
    "tv",
    "alipaymini",
    "wechatmini",
    "qandroid",
)
DEFAULT_P115_COOKIE_LOGIN_APP = "alipaymini"


class P115LoginTimeout(P115Error):
    """A transient scan-endpoint timeout; polling must simply continue."""


@dataclass(frozen=True)
class P115CookieLoginSession:
    session_id: str
    app: str
    qr_image: str
    expires_at: float


@dataclass(frozen=True)
class P115CookieLoginPoll:
    status: str
    message: str = ""
    masked_cookie: str = ""


@dataclass
class _PendingSession:
    uid: str
    time: str
    sign: str
    app: str
    expires_at: float


class P115CookieLoginService:
    """Short-lived bridge between a browser QR session and the 115 Cookie login.

    The flow keeps the classic three-step 115 endpoint contract and then binds
    a device through ``passportapi`` so the result is a Cookie the playback
    gateway can actually use.  Cookies never leave this service in plain text.
    """

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        ttl_seconds: int = 300,
        timeout_seconds: int = 15,
        status_timeout_seconds: int = 30,
        opener: Any | None = None,
    ) -> None:
        self._settings = settings
        self.ttl_seconds = ttl_seconds
        self.timeout_seconds = timeout_seconds
        self.status_timeout_seconds = status_timeout_seconds
        self._opener = opener
        self._sessions: dict[str, _PendingSession] = {}
        self._lock = threading.Lock()

    @staticmethod
    def supported_apps() -> tuple[str, ...]:
        return P115_COOKIE_LOGIN_APPS

    def normalize_app(self, app: str | None) -> str:
        selected = str(app or "").strip().lower() or DEFAULT_P115_COOKIE_LOGIN_APP
        if selected not in P115_COOKIE_LOGIN_APPS:
            raise P115Error("115 扫码登录设备类型无效")
        return selected

    def start(self, app: str | None = None) -> P115CookieLoginSession:
        selected = self.normalize_app(app)
        token = _response_data(self._request_json(QRCODE_TOKEN_API), "115 扫码会话创建")
        uid = str(token.get("uid") or "").strip()
        if not uid:
            raise P115Error("115 未返回扫码会话标识")
        qr_content = str(token.get("qrcode") or f"https://115.com/scan/dg-{uid}").strip()
        image_buffer = BytesIO()
        qrcode.make(qr_content).save(image_buffer, format="PNG")
        image = image_buffer.getvalue()
        now = time.monotonic()
        session_id = secrets.token_urlsafe(32)
        expires_at = now + self.ttl_seconds
        with self._lock:
            self._discard_expired(now)
            self._sessions[session_id] = _PendingSession(
                uid=uid,
                time=str(token.get("time") or ""),
                sign=str(token.get("sign") or ""),
                app=selected,
                expires_at=expires_at,
            )
        return P115CookieLoginSession(
            session_id=session_id,
            app=selected,
            qr_image="data:image/png;base64," + base64.b64encode(image).decode("ascii"),
            expires_at=expires_at,
        )

    def poll(self, session_id: str) -> P115CookieLoginPoll:
        now = time.monotonic()
        with self._lock:
            self._discard_expired(now)
            pending = self._sessions.get(session_id)
        if pending is None:
            return P115CookieLoginPoll("expired", "扫码会话已过期，请重新获取二维码")
        params = urllib.parse.urlencode({"uid": pending.uid, "time": pending.time, "sign": pending.sign})
        try:
            response = self._request_json(f"{QRCODE_STATUS_API}?{params}", timeout=self.status_timeout_seconds)
        except P115LoginTimeout:
            # 115 answers this endpoint slowly on some networks; a timeout is not
            # a failed scan, so keep the session alive and let the UI retry.
            return P115CookieLoginPoll("waiting", "等待 115 返回扫码状态（网络较慢，仍在重试）")
        data = _response_data(response, "115 扫码状态读取")
        status = _status_code(data.get("status"))
        if status == 0:
            return P115CookieLoginPoll("waiting", "等待扫码")
        if status == 1:
            return P115CookieLoginPoll("scanned", "已扫码，请在手机上确认登录")
        if status in {-1, -2}:
            self._forget(session_id)
            if status == -2:
                return P115CookieLoginPoll("canceled", "手机端已取消登录")
            return P115CookieLoginPoll("expired", "二维码已过期，请重新获取")
        if status != 2:
            return P115CookieLoginPoll("waiting", "等待扫码")
        cookie = self._exchange(pending)
        self._forget(session_id)
        try:
            save_p115_cookie(cookie)
        except P115Error:
            raise
        except (OSError, RuntimeError) as exc:
            raise P115Error("115 登录凭据写入失败，请检查数据目录权限后重试") from exc
        return P115CookieLoginPoll("done", "115 扫码登录已保存", mask_p115_cookie(cookie))

    def _exchange(self, pending: _PendingSession) -> str:
        """Bind the scanned device and render the returned Cookie dictionary."""
        body = urllib.parse.urlencode({"app": pending.app, "account": pending.uid}).encode("utf-8")
        data = _response_data(
            self._request_json(PASSPORT_QRCODE_API.format(app=pending.app), data=body),
            "115 扫码登录换票",
        )
        cookie = data.get("cookie")
        if not isinstance(cookie, dict) or not cookie:
            raise P115Error("115 扫码登录未返回 Cookie")
        rendered = "; ".join(f"{name}={value}" for name, value in cookie.items())
        if not valid_p115_cookie(rendered):
            raise P115Error("115 扫码登录返回的 Cookie 缺少 UID、CID 或 SEID")
        return rendered

    def _forget(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def _discard_expired(self, now: float) -> None:
        self._sessions = {key: value for key, value in self._sessions.items() if value.expires_at > now}

    def _open(self, request: urllib.request.Request, timeout: int | None = None):
        opener = self._opener or self._build_opener()
        return opener.open(request, timeout=self.timeout_seconds if timeout is None else timeout)

    def _build_opener(self) -> Any:
        settings = self._settings or get_settings()
        handlers: list[Any] = [_NoRedirectHandler()]
        proxy = settings.proxy_url.strip()
        if proxy:
            handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
        return urllib.request.build_opener(*handlers)

    def _request(self, url: str, *, data: bytes | None = None, timeout: int | None = None) -> bytes:
        headers = {
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 MediaIndex/P115",
        }
        if data is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
        try:
            with self._open(request, timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code in {301, 302, 303, 307, 308}:
                raise P115Error("115 扫码接口返回了不安全的重定向") from exc
            raise P115Error(f"115 扫码接口请求失败（HTTP {exc.code}）") from exc
        except (TimeoutError, socket.timeout) as exc:
            raise P115LoginTimeout("115 扫码接口响应超时") from exc
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", None)
            if isinstance(reason, (TimeoutError, socket.timeout)):
                raise P115LoginTimeout("115 扫码接口响应超时") from exc
            if isinstance(reason, ssl.SSLError) or isinstance(exc, ssl.SSLError):
                raise P115Error("115 扫码接口 HTTPS 握手被中断，请检查网络、代理或网关策略") from exc
            raise P115Error(f"115 扫码接口连接失败（{type(exc).__name__}）") from exc

    def _request_json(self, url: str, *, data: bytes | None = None, timeout: int | None = None) -> dict[str, Any]:
        raw = self._request(url, data=data, timeout=timeout).decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise P115Error("115 扫码接口返回了非 JSON 响应") from exc
        if not isinstance(payload, dict):
            raise P115Error("115 扫码接口返回格式不兼容")
        return payload

class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _status_code(value: object) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def _response_data(response: object, action: str) -> dict[str, Any]:
    """Return the ``data`` object of a 115 response, or fail with a safe reason."""
    if not isinstance(response, dict):
        raise P115Error(f"{action}未返回有效响应")
    data = response.get("data")
    code = str(response.get("code") if response.get("code") is not None else "0").strip()
    if _looks_false(response.get("state")) or code not in {"", "0"} or not isinstance(data, dict):
        reason = response.get("error") or response.get("message") or response.get("msg")
        if not reason and isinstance(data, dict):
            reason = data.get("msg")
        reason = " ".join(str(reason or "服务未返回可用数据").split())[:180]
        raise P115Error(f"{action}失败：{reason}")
    return data


def _looks_false(value: object) -> bool:
    if isinstance(value, bool):
        return not value
    if value is None:
        return False
    return str(value).strip().lower() in {"0", "false"}
