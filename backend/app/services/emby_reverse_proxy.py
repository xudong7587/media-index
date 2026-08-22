from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from urllib.parse import urlparse, urlunparse

import httpx
from fastapi import HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from websockets.asyncio.client import connect as websocket_connect
from websockets.exceptions import ConnectionClosed, WebSocketException

from app.core.config import get_settings


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


def emby_upstream_url(path: str, query: str = "", *, websocket: bool = False) -> str:
    raw = str(get_settings().emby_base_url or "").strip().rstrip("/")
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.path not in {"", "/"}:
        raise HTTPException(status_code=503, detail="请先在 STRM 与 302 设置中填写 Emby 内网地址")
    scheme = "wss" if websocket and parsed.scheme == "https" else "ws" if websocket else parsed.scheme
    normalized_path = "/" + str(path or "").lstrip("/")
    return urlunparse((scheme, parsed.netloc, normalized_path, "", query, ""))


async def proxy_emby_http(request: Request, path: str) -> StreamingResponse:
    target = emby_upstream_url(path, request.url.query)
    headers = _request_headers(request)
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
