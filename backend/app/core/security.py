import base64
import hashlib
import hmac
import os
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException, Request

from app.core.config import get_settings


@dataclass
class SessionUser:
    username: str


_login_failures: dict[str, deque[float]] = {}
_login_failures_lock = threading.Lock()
_MAX_LOGIN_FAILURE_KEYS = 10_000


def login_allowed(key: str) -> bool:
    settings = get_settings()
    now = time.time()
    with _login_failures_lock:
        attempts = _login_failures.get(key)
        if attempts is None:
            return True
        while attempts and attempts[0] <= now - settings.login_window_seconds:
            attempts.popleft()
        if not attempts:
            _login_failures.pop(key, None)
            return True
        return len(attempts) < settings.login_max_attempts


def record_login_result(key: str, success: bool) -> None:
    with _login_failures_lock:
        if success:
            _login_failures.pop(key, None)
            return
        if key not in _login_failures and len(_login_failures) >= _MAX_LOGIN_FAILURE_KEYS:
            _login_failures.pop(next(iter(_login_failures)), None)
        _login_failures.setdefault(key, deque()).append(time.time())


def _secret() -> bytes:
    settings = get_settings()
    secret = settings.auth_secret or load_or_create_auth_secret(settings.db_path)
    return secret.encode("utf-8")


@lru_cache(maxsize=4)
def load_or_create_auth_secret(db_path: str) -> str:
    secret_path = Path(db_path).parent / "auth_secret"
    try:
        if secret_path.exists():
            secret = secret_path.read_text(encoding="utf-8").strip()
            if secret:
                return secret
        secret_path.parent.mkdir(parents=True, exist_ok=True)
        secret = secrets.token_urlsafe(48)
        try:
            descriptor = os.open(secret_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            persisted = secret_path.read_text(encoding="utf-8").strip()
            return persisted or secret
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(secret)
            handle.flush()
            os.fsync(handle.fileno())
        return secret
    except Exception:
        return secrets.token_urlsafe(48)


def create_session(username: str) -> str:
    settings = get_settings()
    expires = int(time.time()) + settings.session_ttl_seconds
    payload = f"{username}:{expires}:{_credential_version(settings.media_user, settings.media_pass)}"
    sig = hmac.new(_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}:{sig}".encode("utf-8")).decode("ascii")


def verify_session(token: str | None) -> SessionUser | None:
    if not token:
        return None
    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
        payload, sig = raw.rsplit(":", 1)
        expected = hmac.new(_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        username, expires, credential_version = payload.rsplit(":", 2)
        if int(expires) < int(time.time()):
            return None
        settings = get_settings()
        if not hmac.compare_digest(
            credential_version,
            _credential_version(settings.media_user, settings.media_pass),
        ):
            return None
        if not hmac.compare_digest(username, settings.media_user):
            return None
        return SessionUser(username=username)
    except Exception:
        return None


def require_user(request: Request) -> SessionUser:
    settings = get_settings()
    token = request.cookies.get(settings.cookie_name)
    user = verify_session(token)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def check_password(username: str, password: str) -> bool:
    settings = get_settings()
    if not settings.media_user or not settings.media_pass or settings.media_pass == "admin":
        return False
    return hmac.compare_digest(username, settings.media_user) and hmac.compare_digest(password, settings.media_pass)


def _credential_version(username: str, password: str) -> str:
    value = f"{username}\0{password}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()[:24]
