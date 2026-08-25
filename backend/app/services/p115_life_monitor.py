from __future__ import annotations

from hashlib import sha256
import json
import threading

from app.clients.p115 import P115Client, P115Error
from app.core.config import get_settings
from app.services.notifications import add_notification
from app.services.strm_jobs import create_strm_job, run_strm_job


_lock = threading.Lock()
_last_signature = ""


def poll_p115_life_events(*, client: P115Client | None = None) -> dict:
    """Poll the read-only 115 life feed and incrementally scan one watched subtree."""
    global _last_signature
    settings = get_settings()
    if not settings.p115_strm_life_monitor_enabled:
        return {"triggered": False, "reason": "disabled"}
    watched = settings.p115_strm_life_monitor_path.strip()
    output = settings.strm_output_root.strip()
    if not watched or not output or not settings.p115_strm_enabled:
        return {"triggered": False, "reason": "incomplete"}
    if not _lock.acquire(blocking=False):
        return {"triggered": False, "reason": "busy"}
    try:
        payload = (client or P115Client()).recent_life_operations(limit=20)
        signature = sha256(json.dumps(payload.get("data", payload), ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()
        if not _last_signature:
            _last_signature = signature
            return {"triggered": False, "reason": "baseline"}
        if signature == _last_signature:
            return {"triggered": False, "reason": "unchanged"}
        _last_signature = signature
        job_id = create_strm_job(provider="p115", mode="incremental", root_path=watched, output_root=output, playback_base_url=settings.strm_playback_base_url or None)
        run_strm_job(job_id, provider="p115", mode="incremental", root_path=watched, output_root=output, playback_base_url=settings.strm_playback_base_url or None)
        add_notification(f"p115-life:{signature}", "info", "115 变化已同步", f"监控目录 {watched} 已触发 STRM 增量更新。", "strm")
        return {"triggered": True, "job_id": job_id, "path": watched}
    except P115Error as exc:
        add_notification("p115-life:error", "error", "115 生活事件监控失败", str(exc), "strm", deliver=False)
        return {"triggered": False, "reason": "error", "message": str(exc)}
    finally:
        _lock.release()


def reset_life_monitor_state() -> None:
    global _last_signature
    _last_signature = ""
