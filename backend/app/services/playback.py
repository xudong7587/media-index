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
from app.clients.http import NoRedirectHandler
from app.clients.quark import QuarkClient, QuarkError
from app.core.config import get_settings
from app.core.security import load_or_create_auth_secret
from app.services.media_assets import get_asset
from app.services.diagnostics import record_diagnostic_event


class PlaybackError(RuntimeError):
    pass


class PlaybackHeadersRequired(PlaybackError):
    pass


_CACHE_LOCK = threading.Lock()
_DIRECT_LINK_CACHE: dict[tuple[int, str], tuple[float, "PlaybackSource"]] = {}
_CACHE_SECONDS = 60
_PLAYBACK_RANGE_BYTES = 8 * 1024 * 1024


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


def resolve_playback_redirect(token: str, user_agent: str = "") -> str:
    source = _resolve_playback_source(token, user_agent=user_agent)
    if source.requires_headers:
        raise PlaybackHeadersRequired("网盘直链要求附带请求头，不能安全地用 302 交付")
    return source.url


@dataclass(frozen=True)
class PlaybackSource:
    url: str
    request_headers: dict[str, str]
    requires_headers: bool = False
    forbid_redirects: bool = False
    bounded_ranges: bool = False


@dataclass
class PlaybackStream:
    status_code: int
    headers: dict[str, str]
    chunks: Iterator[bytes]


def open_playback_stream(token: str, range_header: str = "", user_agent: str = "", *, head_only: bool = False) -> PlaybackStream:
    normalized_range = range_header.strip()
    if normalized_range and not re.fullmatch(r"bytes=\d*-\d*", normalized_range):
        raise PlaybackError("播放范围请求无效")
    open_range = re.fullmatch(r"bytes=(\d+)-", normalized_range)
    if not head_only and (not normalized_range or open_range):
        source = _resolve_playback_source(token, user_agent=user_agent)
        if source.bounded_ranges:
            return _open_segmented_stream(token, int(open_range[1]) if open_range else 0, user_agent, bool(normalized_range))
    response = _open_upstream(token, normalized_range, user_agent, head_only=head_only)
    forwarded = _forwarded_headers(response)
    status = int(getattr(response, "status", 200) or 200)
    if head_only:
        response.close()
        return PlaybackStream(status, forwarded, iter(()))
    return PlaybackStream(status, forwarded, _iter_upstream(response))


def _open_upstream(token: str, normalized_range: str, user_agent: str, *, head_only: bool = False) -> Any:
    response = None
    for attempt in range(2):
        source = _resolve_playback_source(token, user_agent=user_agent, force_refresh=attempt > 0)
        headers = {"User-Agent": str(user_agent or "").strip() or P115Client.PLAYBACK_USER_AGENT, **source.request_headers}
        if normalized_range:
            headers["Range"] = normalized_range
        request = urllib.request.Request(source.url, headers=headers, method="HEAD" if head_only else "GET")
        try:
            if source.forbid_redirects:
                response = urllib.request.build_opener(NoRedirectHandler()).open(request, timeout=30)
            else:
                response = urllib.request.urlopen(request, timeout=30)
            break
        except urllib.error.HTTPError as exc:
            exc.close()
            if (exc.code in {401, 403} or (source.forbid_redirects and exc.code == 412)) and attempt == 0:
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
    return response


def _forwarded_headers(response: Any) -> dict[str, str]:
    forwarded = {}
    for name in ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges", "Content-Disposition"):
        value = str(response.headers.get(name) or "").strip()
        if value and "\r" not in value and "\n" not in value:
            forwarded[name] = value
    return forwarded


def _validate_segment(response: Any, start: int, requested_end: int, total: int | None = None) -> tuple[int, int]:
    match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", str(response.headers.get("Content-Range") or ""))
    if int(getattr(response, "status", 200) or 200) != 206 or not match:
        raise PlaybackError("播放上游未返回有效分段范围")
    actual_start, actual_end, actual_total = map(int, match.groups())
    if (actual_start != start or actual_total <= start or actual_end != min(requested_end, actual_total - 1)
            or (total is not None and actual_total != total)):
        raise PlaybackError("播放上游分段范围与请求不一致")
    length = str(response.headers.get("Content-Length") or "")
    if length and (not length.isdigit() or int(length) != actual_end - start + 1):
        raise PlaybackError("播放上游分段长度与范围不一致")
    return actual_end, actual_total


def _open_segmented_stream(token: str, start: int, user_agent: str, has_range: bool) -> PlaybackStream:
    # An open-ended Quark request can deliver too slowly for Emby's large MP4
    # metadata probe. Fetch finite ranges while retaining one continuous reply.
    end = start + _PLAYBACK_RANGE_BYTES - 1
    response = _open_upstream(token, f"bytes={start}-{end}", user_agent)
    try:
        segment_end, total = _validate_segment(response, start, end)
        headers = _forwarded_headers(response)
        headers["Content-Length"] = str(total - start)
        headers["Accept-Ranges"] = "bytes"
        if has_range:
            headers["Content-Range"] = f"bytes {start}-{total - 1}/{total}"
        else:
            headers.pop("Content-Range", None)
    except Exception:
        response.close()
        raise
    return PlaybackStream(206 if has_range else 200, headers, _iter_segments(token, user_agent, response, start, segment_end, total))


def _iter_segments(token: str, user_agent: str, response: Any, start: int, segment_end: int, total: int) -> Iterator[bytes]:
    try:
        while True:
            remaining = segment_end - start + 1
            read = getattr(response, "read1", None) or response.read
            while remaining:
                chunk = read(min(64 * 1024, remaining))
                if not chunk or len(chunk) > remaining:
                    raise PlaybackError("播放上游分段正文长度不一致")
                remaining -= len(chunk)
                yield chunk
            response.close()
            response = None
            start = segment_end + 1
            if start >= total:
                break
            end = min(start + _PLAYBACK_RANGE_BYTES - 1, total - 1)
            # Reuses token validation and the existing bounded refresh retry;
            # signed links and cookies are never copied into client headers.
            response = _open_upstream(token, f"bytes={start}-{end}", user_agent)
            segment_end, _ = _validate_segment(response, start, end, total)
    except Exception as exc:
        record_diagnostic_event("playback", "stream_failed", level="error", message="播放上游分段读取中断", context={"exception_type": type(exc).__name__})
        raise
    finally:
        if response is not None:
            response.close()


def _iter_upstream(response: Any) -> Iterator[bytes]:
    try:
        # HTTPResponse.read(n) waits for n bytes; read1 lets the player receive
        # buffered data immediately instead of waiting for a full MiB.
        read = getattr(response, "read1", None) or response.read
        while chunk := read(64 * 1024):
            yield chunk
    except Exception as exc:
        record_diagnostic_event("playback", "stream_failed", level="error", message="播放上游读取中断", context={"exception_type": type(exc).__name__})
        raise
    finally:
        response.close()


def _resolve_playback_source(token: str, *, user_agent: str = "", force_refresh: bool = False) -> PlaybackSource:
    asset = verify_asset_token(token)
    asset_id = int(asset["id"])
    normalized_user_agent = str(user_agent or "").strip() or P115Client.PLAYBACK_USER_AGENT
    cache_key = (asset_id, hashlib.sha256(normalized_user_agent.encode("utf-8")).hexdigest()[:16])
    now = time.monotonic()
    with _CACHE_LOCK:
        if force_refresh:
            _DIRECT_LINK_CACHE.pop(cache_key, None)
        cached = _DIRECT_LINK_CACHE.get(cache_key)
        if cached and cached[0] > now:
            return cached[1]
    try:
        if asset["provider"] == "p115":
            link = P115Client().direct_download_link(str(asset["file_id"]), user_agent=normalized_user_agent)
            unsupported_headers = {str(name).lower() for name in link.required_headers} - {"user-agent"}
            required_user_agent = next(
                (
                    str(value).strip()
                    for name, value in link.request_headers.items()
                    if str(name).strip().lower() == "user-agent"
                ),
                "",
            )
            user_agent_mismatch = bool(required_user_agent and required_user_agent != normalized_user_agent)
            source = PlaybackSource(link.url, dict(link.request_headers), bool(unsupported_headers or user_agent_mismatch))
        elif asset["provider"] == "quark":
            link = QuarkClient().download_link(str(asset["file_id"]))
            source = PlaybackSource(link.url, dict(link.request_headers), requires_headers=True, forbid_redirects=True, bounded_ranges=True)
        else:
            raise PlaybackError("该资产暂不支持 302 播放")
    except (P115Error, QuarkError) as exc:
        raise PlaybackError(str(exc)) from exc
    with _CACHE_LOCK:
        _DIRECT_LINK_CACHE[cache_key] = (now + _CACHE_SECONDS, source)
    return source


def invalidate_asset_cache(asset_id: int) -> None:
    with _CACHE_LOCK:
        target_id = int(asset_id)
        for key in [key for key in _DIRECT_LINK_CACHE if key[0] == target_id]:
            _DIRECT_LINK_CACHE.pop(key, None)


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
