from __future__ import annotations

import base64
import hashlib
import hmac
import threading
import time
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterator

from app.clients.p115 import P115Client, P115Error
from app.clients.quark import QuarkClient, QuarkError
from app.core.config import get_settings
from app.core.security import load_or_create_auth_secret
from app.services.media_assets import get_asset


class PlaybackError(RuntimeError):
    pass


_CACHE_LOCK = threading.Lock()
_DIRECT_LINK_CACHE: dict[int, tuple[float, "PlaybackSource"]] = {}
_CACHE_SECONDS = 60


def issue_asset_token(asset: dict[str, Any]) -> str:
    asset_id = int(asset["id"])
    version = _asset_version(asset)
    payload = f"{asset_id}:{version}"
    signature = hmac.new(_token_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
    return _b64_encode(f"{payload}:{signature}")


def verify_asset_token(token: str) -> dict[str, Any]:
    try:
        payload = _b64_decode(token)
        asset_id_text, version, signature = payload.rsplit(":", 2)
        asset_id = int(asset_id_text)
    except Exception as exc:
        raise PlaybackError("播放令牌无效") from exc
    asset = get_asset(asset_id)
    if not asset or asset.get("status") != "ready":
        raise PlaybackError("播放资产不存在或不可用")
    expected_payload = f"{asset_id}:{_asset_version(asset)}"
    expected_signature = hmac.new(_token_secret(), expected_payload.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
    if payload != f"{expected_payload}:{expected_signature}" or not hmac.compare_digest(signature, expected_signature):
        raise PlaybackError("播放令牌已失效")
    return asset


def resolve_playback_redirect(token: str) -> str:
    source = _resolve_playback_source(token)
    if source.requires_headers:
        raise PlaybackError("115 直链要求附带请求头，不能安全地用 302 交付")
    return source.url


@dataclass(frozen=True)
class PlaybackSource:
    url: str
    request_headers: dict[str, str]
    requires_headers: bool = False


@dataclass
class PlaybackStream:
    status_code: int
    headers: dict[str, str]
    chunks: Iterator[bytes]


def open_playback_stream(token: str, range_header: str = "") -> PlaybackStream:
    normalized_range = range_header.strip()
    if normalized_range and not re.fullmatch(r"bytes=\d*-\d*", normalized_range):
        raise PlaybackError("播放范围请求无效")
    response = None
    for attempt in range(2):
        source = _resolve_playback_source(token, force_refresh=attempt > 0)
        headers = {"User-Agent": P115Client.PLAYBACK_USER_AGENT, **source.request_headers}
        if normalized_range:
            headers["Range"] = normalized_range
        request = urllib.request.Request(source.url, headers=headers, method="GET")
        try:
            response = urllib.request.urlopen(request, timeout=30)
            break
        except urllib.error.HTTPError as exc:
            exc.close()
            if exc.code in {401, 403} and attempt == 0:
                continue
            if exc.code == 416:
                raise PlaybackError("播放范围超出文件长度") from exc
            raise PlaybackError(f"播放上游返回 HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise PlaybackError("无法连接网盘播放地址") from exc
    if response is None:
        raise PlaybackError("无法连接网盘播放地址")
    status = int(getattr(response, "status", 200) or 200)
    if status not in {200, 206}:
        response.close()
        raise PlaybackError(f"播放上游返回 HTTP {status}")
    forwarded = {}
    for name in ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges", "Content-Disposition"):
        value = str(response.headers.get(name) or "").strip()
        if value and "\r" not in value and "\n" not in value:
            forwarded[name] = value
    return PlaybackStream(status, forwarded, _iter_upstream(response))


def _iter_upstream(response: Any) -> Iterator[bytes]:
    try:
        while chunk := response.read(1024 * 1024):
            yield chunk
    finally:
        response.close()


def _resolve_playback_source(token: str, *, force_refresh: bool = False) -> PlaybackSource:
    asset = verify_asset_token(token)
    asset_id = int(asset["id"])
    now = time.monotonic()
    with _CACHE_LOCK:
        if force_refresh:
            _DIRECT_LINK_CACHE.pop(asset_id, None)
        cached = _DIRECT_LINK_CACHE.get(asset_id)
        if cached and cached[0] > now:
            return cached[1]
    try:
        if asset["provider"] == "p115":
            link = P115Client().direct_download_link(str(asset["file_id"]))
            source = PlaybackSource(link.url, dict(link.request_headers), bool(link.required_headers))
        elif asset["provider"] == "quark":
            source = PlaybackSource(QuarkClient().download_link(str(asset["file_id"])).url, {})
        else:
            raise PlaybackError("该资产暂不支持 302 播放")
    except (P115Error, QuarkError) as exc:
        raise PlaybackError(str(exc)) from exc
    with _CACHE_LOCK:
        _DIRECT_LINK_CACHE[asset_id] = (now + _CACHE_SECONDS, source)
    return source


def invalidate_asset_cache(asset_id: int) -> None:
    with _CACHE_LOCK:
        _DIRECT_LINK_CACHE.pop(int(asset_id), None)


def _asset_version(asset: dict[str, Any]) -> str:
    raw = "|".join(
        str(asset.get(key) or "")
        for key in ("provider", "account_id", "file_id", "revision", "sha1", "size", "status")
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _token_secret() -> bytes:
    settings = get_settings()
    return (settings.auth_secret or load_or_create_auth_secret(settings.db_path)).encode("utf-8")


def _b64_encode(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def _b64_decode(value: str) -> str:
    raw = str(value or "")
    if not raw or len(raw) > 512 or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for char in raw):
        raise ValueError("bad token")
    return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8")
