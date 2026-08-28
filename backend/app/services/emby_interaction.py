from __future__ import annotations

import json
import urllib.error
import urllib.request

from app.clients.http import open_url
from app.core.config import get_settings


def emby_status_reply() -> str:
    settings = get_settings()
    base_url = settings.emby_base_url.strip().rstrip("/")
    api_key = settings.emby_api_key.strip()
    if not base_url or not api_key:
        return "MediaIndex Emby\n\n尚未配置 Emby 地址或 API Key。"
    try:
        counts = _read_emby_json(base_url, api_key, "/Items/Counts")
        sessions = _read_emby_json(base_url, api_key, "/Sessions")
    except urllib.error.HTTPError as exc:
        return f"MediaIndex Emby\n\n读取失败：Emby 返回 HTTP {exc.code}。"
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return "MediaIndex Emby\n\n无法连接 Emby，请检查地址、API Key 和网络。"

    count_values = counts if isinstance(counts, dict) else {}
    movies = _positive_count(count_values.get("MovieCount"))
    series = _positive_count(count_values.get("SeriesCount"))
    episodes = _positive_count(count_values.get("EpisodeCount"))
    media_total = movies + series + episodes

    users: dict[str, str] = {}
    playing_users: set[str] = set()
    for raw in sessions if isinstance(sessions, list) else []:
        if not isinstance(raw, dict):
            continue
        user_id = str(raw.get("UserId") or "").strip()
        user_name = str(raw.get("UserName") or "").strip()
        if not user_id and not user_name:
            continue
        user_name = user_name or "未命名用户"
        identity = user_id or user_name.casefold()
        users.setdefault(identity, user_name)
        if isinstance(raw.get("NowPlayingItem"), dict):
            playing_users.add(identity)

    user_names = "、".join(list(users.values())[:5])
    user_suffix = f"（{user_names}{'…' if len(users) > 5 else ''}）" if user_names else ""
    return (
        "MediaIndex Emby\n\n"
        f"媒体条目：{media_total}\n"
        f"电影：{movies} · 剧集：{series} · 单集：{episodes}\n"
        f"活跃用户：{len(users)}{user_suffix}\n"
        f"正在播放：{len(playing_users)}"
    )


def _read_emby_json(base_url: str, api_key: str, path: str) -> object:
    request = urllib.request.Request(
        f"{base_url}{path}",
        headers={"X-Emby-Token": api_key, "Accept": "application/json"},
        method="GET",
    )
    with open_url(request, timeout=10) as response:
        return json.loads(response.read(4 * 1024 * 1024).decode("utf-8"))


def _positive_count(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0
