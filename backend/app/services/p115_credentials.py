from __future__ import annotations

import os
from pathlib import Path

from app.clients.p115 import P115Error, normalize_p115_cookie, valid_p115_cookie
from app.core.config import get_settings
from app.core.env_file import atomic_write_env, env_file_lock, read_env_file


def p115_config_path() -> Path:
    """The runtime settings file every 115 credential write must land in."""
    return Path(os.getenv("MEDIA_CONFIG_PATH", "/app/.env"))


def mask_p115_cookie(cookie: str) -> str:
    """Describe a saved Cookie without exposing its value to the browser."""
    fields: dict[str, str] = {}
    for chunk in normalize_p115_cookie(cookie).split(";"):
        name, separator, value = chunk.strip().partition("=")
        if separator and name:
            fields[name] = value
    uid = fields.get("UID", "")
    masked_uid = f"UID=…{uid[-4:]}" if len(uid) > 4 else "UID=已保存"
    present = tuple(name for name in ("UID", "CID", "SEID", "KID") if fields.get(name))
    return f"{masked_uid} · 字段 {'、'.join(present)}" if present else "Cookie 已保存"


def apply_p115_cookie(values: dict[str, str], cookie: str) -> str:
    """Merge a normalized, validated Cookie into a pending settings mapping.

    Callers that already own an atomic settings write (the settings API) use
    this form so a later validation failure still leaves the file untouched.
    """
    normalized = normalize_p115_cookie(cookie)
    if not valid_p115_cookie(normalized):
        raise P115Error("115 Cookie 缺少 UID、CID 或 SEID")
    values["P115_COOKIE"] = normalized
    values["P115_AUTH_MODE"] = "cookie"
    return normalized


def save_p115_cookie(cookie: str) -> str:
    """Normalize, validate and persist ``P115_COOKIE`` to the runtime env file.

    A Cookie can reach MediaIndex through the settings page, a container
    environment variable or the 115 scan login.  All of them must end up in the
    same file, otherwise the next container start silently loses the login and
    playback falls back to a blank Cookie.
    """
    env_path = p115_config_path()
    with env_file_lock():
        values = read_env_file(env_path)
        normalized = apply_p115_cookie(values, cookie)
        atomic_write_env(env_path, values)
        os.environ["P115_COOKIE"] = normalized
        os.environ["P115_AUTH_MODE"] = "cookie"
        get_settings.cache_clear()
    return normalized


def reconcile_p115_cookie_from_environment() -> bool:
    """Persist a valid Cookie that only exists in the process environment.

    Compose and upgrade instructions can inject ``P115_COOKIE`` outside the
    settings file.  Writing that copy once at startup keeps one authoritative
    credential instead of two copies that drift apart.
    """
    injected = normalize_p115_cookie(os.environ.get("P115_COOKIE", ""))
    if not valid_p115_cookie(injected):
        return False
    stored = normalize_p115_cookie(read_env_file(p115_config_path()).get("P115_COOKIE", ""))
    if valid_p115_cookie(stored):
        return False
    save_p115_cookie(injected)
    return True
