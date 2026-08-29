from __future__ import annotations

import time
import urllib.parse

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from fastapi.responses import FileResponse

from app.core.config import get_settings
from app.db.database import db
from app.services.wecom_callback import (
    decrypt_message,
    extract_encrypted_xml,
    handle_command,
    parse_inbound_xml,
    verify_signature,
)
from app.services.poster_cache import find_cached_poster, poster_media_type

router = APIRouter(tags=["wecom-callback"])

_CALLBACK_MAX_CLOCK_SKEW_SECONDS = 300


@router.get("/api/notifications/wecom/callback")
def verify_wecom_callback(
    msg_signature: str = Query(default=""),
    timestamp: str = Query(default=""),
    nonce: str = Query(default=""),
    echostr: str = Query(default=""),
):
    settings = get_settings()
    _require_callback_config()
    _require_fresh_timestamp(timestamp)
    if not verify_signature(msg_signature, timestamp, nonce, echostr, settings.wecom_callback_token):
        raise HTTPException(status_code=403, detail="企业微信回调签名校验失败")
    try:
        content = decrypt_message(echostr, settings.wecom_callback_aes_key, settings.wecom_corp_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PlainTextResponse(content)


@router.post("/api/notifications/wecom/callback")
async def receive_wecom_callback(
    request: Request,
    background_tasks: BackgroundTasks,
    msg_signature: str = Query(default=""),
    timestamp: str = Query(default=""),
    nonce: str = Query(default=""),
):
    settings = get_settings()
    _require_callback_config()
    _require_fresh_timestamp(timestamp)
    try:
        encrypted = extract_encrypted_xml(await request.body())
    except Exception as exc:
        raise HTTPException(status_code=400, detail="企业微信回调正文无效") from exc
    if not verify_signature(msg_signature, timestamp, nonce, encrypted, settings.wecom_callback_token):
        raise HTTPException(status_code=403, detail="企业微信回调签名校验失败")
    try:
        inbound = parse_inbound_xml(
            decrypt_message(encrypted, settings.wecom_callback_aes_key, settings.wecom_corp_id)
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail="企业微信回调消息解密失败") from exc
    if inbound and _claim_message(inbound.message_id):
        background_tasks.add_task(
            handle_command,
            inbound.command,
            inbound.from_user,
            _public_base_url(request),
        )
    return PlainTextResponse("success")


@router.get("/api/notifications/wecom/posters/{key}")
def get_wecom_poster(key: str):
    path = find_cached_poster(key)
    if not path:
        raise HTTPException(status_code=404, detail="海报缓存不存在")
    return FileResponse(
        path,
        media_type=poster_media_type(path),
        headers={"Cache-Control": "public, max-age=2592000, immutable"},
    )


def _require_callback_config() -> None:
    settings = get_settings()
    if not settings.wecom_callback_enabled:
        raise HTTPException(status_code=404, detail="企业微信交互回调未启用")
    if not settings.wecom_callback_token or not settings.wecom_callback_aes_key:
        raise HTTPException(status_code=503, detail="企业微信交互回调配置不完整")


def _public_base_url(request: Request) -> str:
    configured_callback_url = get_settings().wecom_callback_url.strip()
    if configured_callback_url:
        parsed = urllib.parse.urlparse(configured_callback_url)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    forwarded_host = request.headers.get("x-forwarded-host", "").split(",", 1)[0].strip()
    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip().lower()
    candidate = (
        f"{forwarded_proto}://{forwarded_host}"
        if forwarded_host and forwarded_proto in {"http", "https"}
        else str(request.base_url).rstrip("/")
    )
    parsed = urllib.parse.urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def _claim_message(message_id: str) -> bool:
    safe_id = str(message_id or "").strip()[:256]
    if not safe_id:
        return False
    with db() as conn:
        conn.execute("DELETE FROM wecom_callback_receipts WHERE received_at < datetime('now','-1 day')")
        cursor = conn.execute(
            "INSERT OR IGNORE INTO wecom_callback_receipts(message_id) VALUES(?)",
            (safe_id,),
        )
        return cursor.rowcount == 1


def _require_fresh_timestamp(timestamp: str) -> None:
    try:
        supplied = int(str(timestamp or "").strip())
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="企业微信回调时间戳无效") from exc
    if abs(int(time.time()) - supplied) > _CALLBACK_MAX_CLOCK_SKEW_SECONDS:
        raise HTTPException(status_code=403, detail="企业微信回调已过期")
