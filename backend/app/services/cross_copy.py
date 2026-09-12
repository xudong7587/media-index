"""Exclusive cross-cloud transport selection, retaining legacy OpenList contracts."""
from __future__ import annotations

from contextlib import contextmanager
from functools import wraps
import os
from pathlib import Path

from app.clients.openlist import OpenListClient, OpenListError
from app.core.config import get_settings
from app.core.env_file import atomic_write_env, env_file_lock
from app.db.database import db

_active_operations = 0


def transport_name(settings=None) -> str:
    value = str(getattr(settings or get_settings(), "cross_copy_transport", "openlist") or "openlist")
    if value not in {"openlist", "cd2"}:
        raise OpenListError("跨盘通路配置无效，请选择 OpenList 或 CD2")
    return value


class _CopySettings:
    def __init__(self, settings):
        self.original = settings

    def __getattr__(self, key):
        if transport_name(self.original) == "cd2" and key in {
            "openlist_url", "openlist_token", "openlist_qas_library_path", "openlist_p115_library_path"
        }:
            key = key.replace("openlist_", "cd2_", 1)
        return getattr(self.original, key)


def copy_settings(settings):
    return _CopySettings(settings) if transport_name(settings) == "cd2" else settings


def copy_client(settings=None, *, openlist_factory=OpenListClient):
    settings = settings or get_settings()
    if transport_name(settings) == "cd2":
        from app.clients.cd2 import Cd2Client
        return Cd2Client(settings.cd2_url, settings.cd2_token)
    return openlist_factory()


@contextmanager
def copy_operation():
    global _active_operations
    with env_file_lock():
        _active_operations += 1
    try:
        yield
    finally:
        with env_file_lock():
            _active_operations -= 1


def serialized_copy_operation(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with copy_operation():
            return function(*args, **kwargs)
    return wrapped


def pending_copy_jobs() -> bool:
    with db() as conn:
        return conn.execute(
            """SELECT 1 FROM transfer_jobs WHERE status IN ('running','triggered')
               AND (provider='openlist' OR (provider='p115' AND stage='openlist_sync_submitted')) LIMIT 1"""
        ).fetchone() is not None


def validate_imported_transport(values: dict[str, str]) -> None:
    """The settings backup API must enforce the same route switch boundary."""
    next_route = values.get("CROSS_COPY_TRANSPORT", "openlist")
    if next_route not in {"openlist", "cd2"}:
        raise ValueError("跨盘通路配置无效")
    settings = get_settings()
    # Imports replace all portable values, including the selected route's mounts.
    relevant = {key: value for key, value in values.items()
                if key.startswith(("CD2_", "OPENLIST_")) or key == "CROSS_COPY_TRANSPORT"}
    changed = next_route != transport_name(settings) or any(
        str(getattr(settings, key.lower(), "")) != value for key, value in relevant.items()
    )
    if changed and (_active_operations or pending_copy_jobs()):
        raise RuntimeError("仍有跨盘复制或待落盘任务，暂不能导入会改变通路的配置")
    effective = copy_settings(settings)
    if changed and effective.openlist_enabled and effective.openlist_url and effective.openlist_token:
        if any(task["state"] == "running" for task in copy_client(settings).copy_tasks()):
            raise RuntimeError("当前通路仍有远端复制任务，暂不能导入配置")


def config_status() -> dict:
    settings = get_settings()
    effective = copy_settings(settings)
    result = {key: getattr(settings, key) for key in (
        "cross_copy_transport", "cd2_url", "cd2_qas_library_path", "cd2_p115_library_path",
        "openlist_enabled", "openlist_auto_sync", "openlist_url", "openlist_qas_library_path", "openlist_p115_library_path"
    )}
    result.update(has_cd2_token=bool(settings.cd2_token), has_openlist_token=bool(settings.openlist_token),
                  ready=bool(effective.openlist_enabled and effective.openlist_url and effective.openlist_token
                             and effective.openlist_qas_library_path and effective.openlist_p115_library_path),
                  source_mount=effective.openlist_qas_library_path, target_mount=effective.openlist_p115_library_path)
    return result


def save_config(values: dict) -> dict:
    with env_file_lock():
        settings = get_settings()
        updates = {}
        for key, value in values.items():
            if value is None or (key.endswith("_token") and not str(value).strip()):
                continue
            normalized = str(value).strip() if not isinstance(value, bool) else str(value).lower()
            if any(ord(c) < 32 for c in normalized) or "\n" in str(value) or "\r" in str(value):
                raise ValueError("跨盘配置不能包含换行或控制字符")
            if key.endswith("_library_path"):
                from app.clients.cd2 import normalize_path
                normalized = normalize_path(normalized)
                if normalized == "/":
                    raise ValueError("请选择具体网盘挂载目录，不能使用服务根目录")
            if key in {"cd2_url", "openlist_url"} and normalized:
                from app.clients.cd2 import validate_endpoint
                normalized = validate_endpoint(normalized)
            previous = getattr(settings, key)
            previous = str(previous).lower() if isinstance(previous, bool) else str(previous)
            if previous != normalized:
                updates[key.upper()] = normalized
        if not updates:
            return config_status()
        if _active_operations or pending_copy_jobs():
            raise RuntimeError("仍有跨盘复制或待落盘任务，请处理完成后再修改通路配置")
        # Local jobs can finish before an old remote library copy. Do not mix routes
        # while the selected service still has active remote work.
        effective = copy_settings(settings)
        token_only = set(updates) <= {"CD2_TOKEN", "OPENLIST_TOKEN"}
        if not token_only and effective.openlist_enabled and effective.openlist_url and effective.openlist_token:
            if any(task["state"] == "running" for task in copy_client(settings).copy_tasks()):
                raise RuntimeError("当前通路仍有远端复制任务，请等待完成后再修改配置")
        path = Path(os.getenv("MEDIA_CONFIG_PATH", ".env"))
        existing = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    key, value = line.split("=", 1)
                    existing[key.strip()] = value.strip()
        updates["OPENLIST_AUTO_SYNC_DIRECTION"] = "qas_to_p115"
        atomic_write_env(path, {**existing, **updates})
        os.environ.update(updates)
        get_settings.cache_clear()
        return config_status()
