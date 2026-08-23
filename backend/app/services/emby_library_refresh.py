from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from app.clients.http import open_url
from app.core.config import get_settings


def refresh_emby_library_after_strm() -> str:
    """Ask Emby to scan the configured STRM library after a successful job.

    This is intentionally opt-in: a completed cloud transfer must never cause
    an outbound Emby request until the user has selected its library.
    """
    settings = get_settings()
    if not settings.emby_library_refresh_enabled:
        return ""
    base_url = settings.emby_base_url.strip().rstrip("/")
    api_key = settings.emby_api_key.strip()
    library_id = settings.emby_library_id.strip()
    if not base_url or not api_key or not library_id:
        return "；Emby 刷新待处理（请配置 Emby 地址、API Key 和媒体库 ID）"
    query = urllib.parse.urlencode({"LibraryId": library_id})
    request = urllib.request.Request(
        f"{base_url}/Library/Refresh?{query}",
        headers={"X-Emby-Token": api_key, "Accept": "application/json"},
        method="POST",
    )
    try:
        with open_url(request, timeout=20) as response:
            response.read(64 * 1024)
    except urllib.error.HTTPError as exc:
        return f"；Emby 刷新待处理（HTTP {exc.code}）"
    except (urllib.error.URLError, TimeoutError, ValueError):
        return "；Emby 刷新待处理（无法连接 Emby）"
    return "；已通知 Emby 刷新媒体库，Emby 将按自身刮削设置识别和刮削 STRM"
