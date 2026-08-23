from __future__ import annotations

import re
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from typing import Any

from app.clients.http import open_url
from app.db.database import db
from app.services.channel_monitor import process_channel_post, update_channel_sync_status


_LAST_SYNC_AT = 0.0
_SEARCH_DEDUPE_SECONDS = 30
_SYNC_LOCK = threading.Lock()


def sync_public_channels(channel_id: str = "", *, force: bool = False) -> list[dict[str, Any]]:
    """Pull public channel pages on demand, with a short search-burst dedupe window."""
    global _LAST_SYNC_AT
    if not _SYNC_LOCK.acquire(blocking=force):
        return []
    try:
        now = time.monotonic()
        if not force and not channel_id and now - _LAST_SYNC_AT < _SEARCH_DEDUPE_SECONDS:
            return []
        with db() as conn:
            if channel_id:
                rows = conn.execute(
                    "SELECT channel_id,display_name FROM channel_subscriptions WHERE enabled=1 AND channel_id=?",
                    (channel_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT channel_id,display_name FROM channel_subscriptions WHERE enabled=1 AND channel_id LIKE '@%'"
                ).fetchall()
        sources = [(str(row["channel_id"]), str(row["display_name"] or "")) for row in rows]
        if not sources:
            results: list[dict[str, Any]] = []
        else:
            with ThreadPoolExecutor(max_workers=min(8, len(sources)), thread_name_prefix="tg-source") as executor:
                results = list(executor.map(lambda item: pull_public_channel(*item), sources))
        if not channel_id:
            _LAST_SYNC_AT = now
        return results
    finally:
        _SYNC_LOCK.release()


def pull_public_channel(channel_id: str, display_name: str = "") -> dict[str, Any]:
    username = channel_id.lstrip("@")
    if not re.fullmatch(r"[A-Za-z0-9_]{5,32}", username):
        return {"channel_id": channel_id, "ok": False, "message": "该来源不是公开频道名", "posts": 0, "resources": 0}
    try:
        request = urllib.request.Request(
            f"https://t.me/s/{username}",
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 MediaIndex/0.6",
                "Accept": "text/html,application/xhtml+xml",
            },
            method="GET",
        )
        with open_url(request, timeout=10) as response:
            status = int(getattr(response, "status", 200))
            if status >= 400:
                raise RuntimeError(f"Telegram HTTP {status}")
            html = response.read(2_000_000).decode("utf-8", errors="replace")
        parser = _TelegramPublicPageParser(username)
        parser.feed(html)
        resource_count = 0
        processed = 0
        for post in sorted(parser.posts, key=lambda item: int(item["message_id"])):
            result = process_channel_post(post)
            if result:
                processed += 1
                resource_count += int(result.get("indexed_resource_count") or 0)
        update_channel_sync_status(channel_id, resource_found=resource_count > 0)
        label = display_name or channel_id
        return {
            "channel_id": channel_id,
            "ok": True,
            "message": f"{label} 已拉取 {processed} 条近期消息，索引 {resource_count} 个候选链接",
            "posts": processed,
            "resources": resource_count,
        }
    except Exception as exc:
        safe_error = _safe_error(exc)
        update_channel_sync_status(channel_id, error=safe_error)
        return {"channel_id": channel_id, "ok": False, "message": safe_error, "posts": 0, "resources": 0}


class _TelegramPublicPageParser(HTMLParser):
    def __init__(self, username: str):
        super().__init__(convert_charrefs=True)
        self.username = username
        self.username_casefold = username.casefold()
        self.posts: list[dict[str, Any]] = []
        self._div_depth = 0
        self._capture_depth = 0
        self._current: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if tag == "div":
            self._div_depth += 1
            classes = set(values.get("class", "").split())
            data_post = values.get("data-post", "")
            if self._current is None and "tgme_widget_message" in classes and data_post:
                match = re.fullmatch(r"([^/]+)/([0-9]+)", data_post)
                if match and match.group(1).casefold() == self.username_casefold:
                    self._capture_depth = self._div_depth
                    self._current = {"message_id": int(match.group(2)), "parts": [], "links": [], "date": ""}
        if self._current is None:
            return
        if tag == "a" and values.get("href"):
            self._current["links"].append(values["href"])
        elif tag == "time" and values.get("datetime"):
            self._current["date"] = values["datetime"]

    def handle_endtag(self, tag: str) -> None:
        if tag != "div":
            return
        if self._current is not None and self._div_depth == self._capture_depth:
            parts = [str(value).strip() for value in self._current["parts"] if str(value).strip()]
            links = [str(value).strip() for value in self._current["links"] if str(value).strip()]
            text = "\n".join(dict.fromkeys([*parts, *links]))
            message_url = next((url for url in links if re.fullmatch(r"https://t\.me/[^/]+/[0-9]+", url)), "")
            self.posts.append(
                {
                    "message_id": self._current["message_id"],
                    "chat": {"id": f"@{self.username}"},
                    "text": text,
                    "date": self._current["date"],
                    "message_url": message_url,
                }
            )
            self._current = None
            self._capture_depth = 0
        self._div_depth = max(0, self._div_depth - 1)

    def handle_data(self, data: str) -> None:
        if self._current is not None and data.strip():
            self._current["parts"].append(data)


def _safe_error(exc: Exception) -> str:
    value = re.sub(r"https?://\S+", "Telegram", str(exc or "频道拉取失败"))
    return f"公开频道拉取失败：{value[:300]}"
