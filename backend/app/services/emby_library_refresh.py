from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from app.clients.http import open_url
from app.core.config import get_settings


def _discover_single_library_id(base_url: str, api_key: str) -> tuple[str, int]:
    request = urllib.request.Request(
        f"{base_url}/Library/VirtualFolders",
        headers={"X-Emby-Token": api_key, "Accept": "application/json"},
        method="GET",
    )
    with open_url(request, timeout=20) as response:
        payload = json.loads(response.read(1024 * 1024).decode("utf-8"))
    libraries = [item for item in payload if isinstance(item, dict) and str(item.get("ItemId") or "").strip()] if isinstance(payload, list) else []
    if len(libraries) == 1:
        return str(libraries[0]["ItemId"]).strip(), 1
    return "", len(libraries)


def refresh_emby_library_after_strm() -> str:
    """Ask Emby to scan the configured STRM library after a successful job.

    This is intentionally opt-in. A single Emby library can be identified
    safely; installations with multiple libraries require an explicit choice.
    """
    settings = get_settings()
    if not settings.emby_library_refresh_enabled:
        return ""
    base_url = settings.emby_base_url.strip().rstrip("/")
    api_key = settings.emby_api_key.strip()
    library_id = settings.emby_library_id.strip()
    if not base_url or not api_key:
        return "；Emby 刷新待处理（请配置 Emby 地址和 API Key）"
    if not library_id:
        try:
            library_id, library_count = _discover_single_library_id(base_url, api_key)
        except urllib.error.HTTPError as exc:
            return f"；Emby 刷新待处理（读取媒体库失败：HTTP {exc.code}）"
        except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
            return "；Emby 刷新待处理（无法读取 Emby 媒体库）"
        if not library_id:
            if library_count > 1:
                return "；Emby 刷新待处理（检测到多个媒体库，请在 STRM 通用设置中选择）"
            return "；Emby 刷新待处理（Emby 中没有可用媒体库）"
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
