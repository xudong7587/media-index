import base64
import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException, Request

from app.core.config import get_settings


@dataclass
class SessionUser:
    username: str


_login_failures: dict[str, deque[float]] = defaultdict(deque)


def login_allowed(key: str) -> bool:
    settings = get_settings()
    now = time.time()
    attempts = _login_failures[key]
    while attempts and attempts[0] <= now - settings.login_window_seconds:
        attempts.popleft()
    return len(attempts) < settings.login_max_attempts


def record_login_result(key: str, success: bool) -> None:
    if success:
        _login_failures.pop(key, None)
    else:
        _login_failures[key].append(time.time())


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
        secret_path.write_text(secret, encoding="utf-8")
        return secret
    except Exception:
        return secrets.token_urlsafe(48)


def create_session(username: str) -> str:
    settings = get_settings()
    expires = int(time.time()) + settings.session_ttl_seconds
    payload = f"{username}:{expires}"
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
        username, expires = payload.rsplit(":", 1)
        if int(expires) < int(time.time()):
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
