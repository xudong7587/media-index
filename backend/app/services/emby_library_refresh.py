from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from app.clients.http import open_url
from app.core.config import get_settings


def _discover_library_id(base_url: str, api_key: str, output_root: str = "") -> tuple[str, int, bool]:
    request = urllib.request.Request(
        f"{base_url}/Library/VirtualFolders",
        headers={"X-Emby-Token": api_key, "Accept": "application/json"},
        method="GET",
    )
    with open_url(request, timeout=20) as response:
        payload = json.loads(response.read(1024 * 1024).decode("utf-8"))
    libraries = [item for item in payload if isinstance(item, dict) and str(item.get("ItemId") or "").strip()] if isinstance(payload, list) else []
    normalized_output = str(output_root or "").strip().replace("\\", "/").rstrip("/").casefold()
    matches: list[tuple[int, str]] = []
    if normalized_output:
        for library in libraries:
            locations = library.get("Locations") if isinstance(library.get("Locations"), list) else []
            for value in locations:
                location = str(value or "").strip().replace("\\", "/").rstrip("/")
                if location and (normalized_output == location.casefold() or normalized_output.startswith(f"{location.casefold()}/")):
                    matches.append((len(location), str(library["ItemId"]).strip()))
    if matches:
        longest = max(score for score, _library_id in matches)
        matched_ids = {library_id for score, library_id in matches if score == longest}
        if len(matched_ids) == 1:
            return matched_ids.pop(), len(libraries), True
    if len(libraries) == 1:
        return str(libraries[0]["ItemId"]).strip(), 1, False
    return "", len(libraries), False


def refresh_emby_library_after_strm(output_root: str = "") -> str:
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
    # An explicit library selection is authoritative and avoids a full
    # VirtualFolders round-trip before every STRM-triggered refresh.
    if not library_id:
        try:
            discovered_id, library_count, matched_path = _discover_library_id(base_url, api_key, output_root)
        except urllib.error.HTTPError as exc:
            return f"；Emby 刷新待处理（读取媒体库失败：HTTP {exc.code}）"
        except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
            return "；Emby 刷新待处理（无法读取 Emby 媒体库）"
        if matched_path or not library_id:
            library_id = discovered_id
        if not library_id:
            if library_count > 1:
                return "；Emby 刷新待处理（STRM 输出路径未匹配到 Emby 媒体库 Locations）"
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
    return "；已按 STRM 输出路径通知对应 Emby 媒体库刷新，Emby 将按自身刮削设置识别和刮削 STRM"
