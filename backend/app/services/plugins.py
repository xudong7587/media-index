"""Allowlisted plugin management. No downloaded Python code runs in the host."""
import json
import os
import tempfile
from pathlib import Path
from threading import RLock

from app.core.config import get_settings

_lock = RLock()
PLUGIN_ID = "playback-optimizer"


def state_path() -> Path:
    return Path(get_settings().db_path).parent / "plugins" / "state.json"


def enabled() -> bool:
    path = state_path()
    if not path.exists():
        # Preserve existing explicitly configured worker deployments.
        return bool(os.environ.get("TRANSCODE_WORKER_URL", ""))
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        return state.get(PLUGIN_ID, {}).get("enabled") is True
    except (OSError, ValueError, AttributeError):
        return False


def set_enabled(value: bool) -> None:
    with _lock:
        path = state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        # This first registry owns only its own entry; malformed data is never overwritten.
        state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if not isinstance(state, dict):
            raise ValueError("插件状态格式无效")
        state[PLUGIN_ID] = {"enabled": value}
        fd, temporary = tempfile.mkstemp(prefix="state-", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(state, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def catalog() -> list[dict]:
    return [{"id": PLUGIN_ID, "name": "播放优化", "enabled": enabled(),
             "runtime": "external-worker", "configurationRequired": not bool(os.environ.get("TRANSCODE_WORKER_URL")),
             "description": "独立容器提供 HLS 转码；关闭后拒绝新会话，已有会话自然结束。原画 302 不受影响。",
             "features": ["HLS 转码", "硬件适配", "分辨率与码率", "可选原片分块缓存", "暂停预读与网络估算"],
             "plannedFeatures": ["端到端 NAS 与电视验证"]}]
