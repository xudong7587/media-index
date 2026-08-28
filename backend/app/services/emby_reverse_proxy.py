from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode, urlparse, urlunparse

import httpx
from fastapi import HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import RedirectResponse, Response, StreamingResponse
from websockets.asyncio.client import connect as websocket_connect
from websockets.exceptions import ConnectionClosed, WebSocketException

from app.core.config import get_settings
from app.services.playback import PlaybackError, PlaybackHeadersRequired, resolve_playback_redirect


HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
WEBSOCKET_HANDSHAKE_HEADERS = HOP_BY_HOP_HEADERS | {
    "host",
    "sec-websocket-accept",
    "sec-websocket-extensions",
    "sec-websocket-key",
    "sec-websocket-protocol",
    "sec-websocket-version",
}
_PLAYBACK_INFO_LIMIT = 16 * 1024 * 1024
_MEDIA_SOURCE_TTL_SECONDS = 6 * 60 * 60
_MEDIA_SOURCE_LOCK = threading.Lock()


@dataclass(frozen=True)
class _CachedMediaSource:
    token: str
    expires_at: float


_MEDIA_SOURCE_BY_ID: dict[str, _CachedMediaSource] = {}
_MEDIA_SOURCE_BY_ITEM: dict[str, _CachedMediaSource] = {}


def emby_upstream_url(path: str, query: str = "", *, websocket: bool = False) -> str:
    raw = str(get_settings().emby_base_url or "").strip().rstrip("/")
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.path not in {"", "/"}:
        raise HTTPException(status_code=503, detail="请先在 STRM 与 302 设置中填写 Emby 内网地址")
    scheme = "wss" if websocket and parsed.scheme == "https" else "ws" if websocket else parsed.scheme
    normalized_path = "/" + str(path or "").lstrip("/")
    return urlunparse((scheme, parsed.netloc, normalized_path, "", query, ""))


async def proxy_emby_http(request: Request, path: str) -> Response:
    redirected = _redirect_emby_stream(request, path)
    if redirected is not None:
        return redirected
    target = emby_upstream_url(path, request.url.query)
    headers = _request_headers(request)
    playback_info = _is_playback_info_path(path)
    if playback_info:
        headers["accept-encoding"] = "identity"
    body = await request.body()
    client = httpx.AsyncClient(
        follow_redirects=False,
        timeout=httpx.Timeout(connect=10, read=None, write=60, pool=10),
        trust_env=False,
    )
    try:
        upstream = await client.send(
            client.build_request(request.method, target, headers=headers, content=body),
            stream=True,
        )
    except httpx.RequestError as exc:
        await client.aclose()
        raise HTTPException(status_code=502, detail="Emby 内网服务不可达") from exc

    if playback_info and upstream.status_code == 200:
        payload = await upstream.aread()
        response_headers = _response_headers(upstream, exclude={"content-length", "content-encoding"})
        await upstream.aclose()
        await client.aclose()
        if len(payload) <= _PLAYBACK_INFO_LIMIT:
            payload, modified = _rewrite_playback_info(payload, request, path)
            if modified:
                response_headers["Content-Type"] = "application/json; charset=utf-8"
                response_headers["X-MediaIndex-Playback-Mode"] = "playback-info-rewritten"
        return Response(payload, status_code=upstream.status_code, headers=response_headers)

    async def chunks() -> AsyncIterator[bytes]:
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    response = StreamingResponse(chunks(), status_code=upstream.status_code)
    response.raw_headers = [
        (key.encode("latin-1"), value.encode("latin-1"))
        for key, value in upstream.headers.multi_items()
        if key.casefold() not in HOP_BY_HOP_HEADERS
    ]
    return response


def _redirect_emby_stream(request: Request, path: str) -> RedirectResponse | None:
    if not _is_emby_stream_path(path):
        return None
    source_id = str(request.query_params.get("MediaSourceId") or request.query_params.get("mediaSourceId") or "").strip()
    item_id = _extract_emby_item_id(path)
    cached = _cached_media_source(source_id, item_id)
    if not cached:
        return None
    user_agent = request.headers.get("user-agent", "")
    try:
        target = resolve_playback_redirect(cached.token, user_agent)
        return RedirectResponse(
            target,
            status_code=302,
            headers={"Cache-Control": "no-store", "X-MediaIndex-Playback-Mode": "emby-redirect"},
        )
    except PlaybackHeadersRequired:
        return RedirectResponse(
            f"/api/play/{cached.token}",
            status_code=302,
            headers={
                "Cache-Control": "no-store",
                "X-MediaIndex-Playback-Mode": "emby-proxy-fallback",
                "X-MediaIndex-Playback-Reason": "provider-headers-required",
            },
        )
    except PlaybackError:
        return None


def _rewrite_playback_info(payload: bytes, request: Request, path: str) -> tuple[bytes, bool]:
    try:
        document = json.loads(payload)
    except (TypeError, ValueError):
        return payload, False
    if not isinstance(document, dict) or not isinstance(document.get("MediaSources"), list):
        return payload, False
    item_id = str(document.get("ItemId") or _extract_emby_item_id(path) or "").strip()
    api_key = _emby_api_key(request)
    prefix = "/emby" if str(path).lower().lstrip("/").startswith("emby/") else ""
    modified = False
    for source in document["MediaSources"]:
        if not isinstance(source, dict):
            continue
        source_id = str(source.get("Id") or "").strip()
        source_item_id = str(source.get("ItemId") or item_id or "").strip()
        token = _playback_token_from_media_source_path(str(source.get("Path") or ""))
        if not source_id or not token:
            continue
        _cache_media_source(source_id, source_item_id, token)
        if source_item_id:
            query = {"MediaSourceId": source_id, "Static": "true"}
            if api_key:
                query["api_key"] = api_key
            source["DirectStreamUrl"] = f"{prefix}/Videos/{source_item_id}/stream?{urlencode(query)}"
            source["AddApiKeyToDirectStreamUrl"] = False
        source["SupportsDirectPlay"] = True
        source["SupportsDirectStream"] = True
        source["SupportsTranscoding"] = False
        for key in ("TranscodingUrl", "TranscodingSubProtocol", "TranscodingContainer"):
            source.pop(key, None)
        modified = True
    if not modified:
        return payload, False
    return json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), True


def _playback_token_from_media_source_path(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.lower().endswith(".strm") and not raw.lower().startswith(("http://", "https://")):
        try:
            configured_root = str(get_settings().strm_output_root or "").strip()
            if not configured_root:
                return ""
            root = Path(configured_root).resolve(strict=False)
            target = _resolve_strm_file(raw, root)
            if target is None:
                return ""
            if not target.is_file() or target.stat().st_size > 4096:
                return ""
            raw = target.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError, ValueError):
            return ""
    parsed = urlparse(raw)
    match = re.fullmatch(r"/api/play/([A-Za-z0-9_-]{1,512})", parsed.path)
    return match.group(1) if parsed.scheme in {"http", "https"} and parsed.netloc and match else ""


def _resolve_strm_file(raw_path: str, root: Path) -> Path | None:
    try:
        direct = Path(raw_path).resolve(strict=True)
        direct.relative_to(root)
        return direct
    except (OSError, ValueError):
        pass
    # Emby and MediaIndex containers may mount the same host STRM directory at
    # different roots. Match the longest relative tail, never an arbitrary
    # basename, so duplicate movie names cannot cross libraries.
    parts = [part for part in str(raw_path).replace("\\", "/").split("/") if part and not part.endswith(":")]
    for start in range(1, max(1, len(parts) - 1)):
        tail = parts[start:]
        if len(tail) < 2:
            break
        try:
            candidate = root.joinpath(*tail).resolve(strict=True)
            candidate.relative_to(root)
        except (OSError, ValueError):
            continue
        if candidate.is_file():
            return candidate
    return None


def _cache_media_source(source_id: str, item_id: str, token: str) -> None:
    entry = _CachedMediaSource(token, time.monotonic() + _MEDIA_SOURCE_TTL_SECONDS)
    with _MEDIA_SOURCE_LOCK:
        _MEDIA_SOURCE_BY_ID[source_id] = entry
        if item_id:
            _MEDIA_SOURCE_BY_ITEM[item_id] = entry


def _cached_media_source(source_id: str, item_id: str) -> _CachedMediaSource | None:
    now = time.monotonic()
    with _MEDIA_SOURCE_LOCK:
        entry = _MEDIA_SOURCE_BY_ID.get(source_id) if source_id else None
        if entry is None and item_id:
            entry = _MEDIA_SOURCE_BY_ITEM.get(item_id)
        if entry and entry.expires_at > now:
            return entry
        if source_id:
            _MEDIA_SOURCE_BY_ID.pop(source_id, None)
        if item_id:
            _MEDIA_SOURCE_BY_ITEM.pop(item_id, None)
    return None


def _clear_emby_playback_cache() -> None:
    with _MEDIA_SOURCE_LOCK:
        _MEDIA_SOURCE_BY_ID.clear()
        _MEDIA_SOURCE_BY_ITEM.clear()


def _is_playback_info_path(path: str) -> bool:
    normalized = "/" + str(path or "").strip("/").lower()
    return "/items/" in normalized and normalized.endswith("/playbackinfo")


def _is_emby_stream_path(path: str) -> bool:
    normalized = "/" + str(path or "").strip("/").lower()
    if "/subtitles" in normalized:
        return False
    return any(marker in normalized for marker in ("/stream", "/universal", "/original")) and any(
        marker in normalized for marker in ("/videos/", "/audio/")
    )


def _extract_emby_item_id(path: str) -> str:
    parts = [part for part in str(path or "").strip("/").split("/") if part]
    for index, part in enumerate(parts[:-1]):
        if part.lower() in {"videos", "audio", "items"}:
            candidate = parts[index + 1]
            if candidate and candidate.lower() not in {"stream", "universal", "original", "playbackinfo"}:
                return candidate
    return ""


def _emby_api_key(request: Request) -> str:
    return str(
        request.query_params.get("api_key")
        or request.query_params.get("X-Emby-Token")
        or request.headers.get("x-emby-token")
        or request.headers.get("x-mediabrowser-token")
        or ""
    ).strip()


def _response_headers(upstream: httpx.Response, *, exclude: set[str] | None = None) -> dict[str, str]:
    blocked = HOP_BY_HOP_HEADERS | {str(value).lower() for value in (exclude or set())}
    return {
        key: value
        for key, value in upstream.headers.items()
        if key.casefold() not in blocked
    }


async def proxy_emby_websocket(websocket: WebSocket, path: str) -> None:
    try:
        target = emby_upstream_url(path, websocket.url.query, websocket=True)
    except HTTPException:
        await websocket.close(code=1011, reason="请先配置 Emby 内网地址")
        return
    requested_protocols = [
        value.strip()
        for value in websocket.headers.get("sec-websocket-protocol", "").split(",")
        if value.strip()
    ]
    headers = {
        key: value
        for key, value in websocket.headers.items()
        if key.casefold() not in WEBSOCKET_HANDSHAKE_HEADERS
    }
    try:
        async with websocket_connect(
            target,
            additional_headers=headers,
            subprotocols=requested_protocols or None,
            max_size=None,
        ) as upstream:
            await websocket.accept(subprotocol=upstream.subprotocol)
            downstream = asyncio.create_task(_client_to_emby(websocket, upstream))
            upstream_task = asyncio.create_task(_emby_to_client(websocket, upstream))
            done, pending = await asyncio.wait({downstream, upstream_task}, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*done, *pending, return_exceptions=True)
    except (OSError, ConnectionClosed, WebSocketException):
        try:
            await websocket.close(code=1011, reason="Emby 内网服务不可达")
        except RuntimeError:
            pass


async def _client_to_emby(websocket: WebSocket, upstream) -> None:
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                await upstream.close(code=int(message.get("code") or 1000))
                return
            if message.get("text") is not None:
                await upstream.send(message["text"])
            elif message.get("bytes") is not None:
                await upstream.send(message["bytes"])
    except WebSocketDisconnect:
        await upstream.close()


async def _emby_to_client(websocket: WebSocket, upstream) -> None:
    async for message in upstream:
        if isinstance(message, str):
            await websocket.send_text(message)
        else:
            await websocket.send_bytes(message)


def _request_headers(request: Request) -> dict[str, str]:
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.casefold() not in HOP_BY_HOP_HEADERS | {"host", "content-length"}
    }
    forwarded_for = request.headers.get("x-forwarded-for", "").strip()
    client_host = request.client.host if request.client else ""
    if client_host:
        headers["x-forwarded-for"] = f"{forwarded_for}, {client_host}".strip(", ")
    headers["x-forwarded-proto"] = request.headers.get("x-forwarded-proto", request.url.scheme)
    headers["x-forwarded-host"] = request.headers.get("x-forwarded-host", request.headers.get("host", ""))
    return headers
