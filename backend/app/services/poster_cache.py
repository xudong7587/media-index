from __future__ import annotations

import hashlib
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

from app.clients.http import open_url
from app.core.config import get_settings

_MAX_POSTER_BYTES = 8 * 1024 * 1024
_POSTER_MAX_AGE_SECONDS = 90 * 24 * 60 * 60
_CONTENT_TYPES = {
    "image/jpeg": (".jpg", b"\xff\xd8\xff"),
    "image/png": (".png", b"\x89PNG\r\n\x1a\n"),
}


def cache_tmdb_poster(source_url: str) -> str:
    parsed = urllib.parse.urlparse(source_url.strip())
    if parsed.scheme != "https" or parsed.hostname != "image.tmdb.org":
        return ""
    key = hashlib.sha256(source_url.encode("utf-8")).hexdigest()[:40]
    cached = find_cached_poster(key)
    if cached:
        os.utime(cached, None)
        return key

    request = urllib.request.Request(
        source_url,
        headers={"User-Agent": "MediaIndex/1.0"},
        method="GET",
    )
    try:
        response = open_url(request, timeout=20)
        with response:
            content_type = str(response.headers.get_content_type() or "").lower()
            body = response.read(_MAX_POSTER_BYTES + 1)
    except Exception:
        return ""
    expected = _CONTENT_TYPES.get(content_type)
    if not expected or len(body) > _MAX_POSTER_BYTES or not body.startswith(expected[1]):
        return ""

    root = _poster_root()
    root.mkdir(parents=True, exist_ok=True)
    destination = root / f"{key}{expected[0]}"
    temporary = root / f".{key}.{os.getpid()}.tmp"
    try:
        temporary.write_bytes(body)
        temporary.replace(destination)
        _cleanup_old_posters(root)
        return key
    except OSError:
        temporary.unlink(missing_ok=True)
        return ""


def find_cached_poster(key: str) -> Path | None:
    if len(key) != 40 or any(char not in "0123456789abcdef" for char in key):
        return None
    root = _poster_root()
    for extension in (".jpg", ".png"):
        candidate = root / f"{key}{extension}"
        if candidate.is_file():
            return candidate
    return None


def poster_media_type(path: Path) -> str:
    return "image/png" if path.suffix.lower() == ".png" else "image/jpeg"


def _poster_root() -> Path:
    return Path(get_settings().cache_dir) / "wecom-posters"


def _cleanup_old_posters(root: Path) -> None:
    cutoff = time.time() - _POSTER_MAX_AGE_SECONDS
    try:
        for path in root.iterdir():
            if path.is_file() and not path.name.startswith(".") and path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
    except OSError:
        return
