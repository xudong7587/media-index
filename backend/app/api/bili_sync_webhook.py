"""A separate, server-scoped completion signal for bili-sync downloads."""

from __future__ import annotations

import json
import secrets

from fastapi import APIRouter, Header, HTTPException, Request, status

from app.core.config import get_settings
from app.services.scheduler import schedule_webhook_incremental_sync


router = APIRouter(tags=["bili-sync-webhook"])


@router.post("/api/webhooks/bili-sync", status_code=status.HTTP_202_ACCEPTED)
async def receive_bili_sync_webhook(
    request: Request,
    x_mediaindex_webhook: str = Header(default=""),
):
    settings = get_settings()
    if not settings.bili_sync_webhook_enabled:
        raise HTTPException(status_code=409, detail="bili-sync Webhook 未启用")
    expected = settings.bili_sync_webhook_token.strip()
    if not expected or not secrets.compare_digest(expected, x_mediaindex_webhook.strip()):
        raise HTTPException(status_code=401, detail="Invalid webhook credential")

    body = await request.body()
    if len(body) > 4096:
        raise HTTPException(status_code=413, detail="Webhook 请求过大")
    try:
        payload = json.loads(body)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="Webhook JSON 格式无效") from exc
    if not isinstance(payload, dict) or payload.get("event") != "finished":
        raise HTTPException(status_code=422, detail="只接受 finished 完成事件")

    provider = settings.bili_sync_webhook_provider.strip().lower()
    if provider not in {"p115", "quark"}:
        raise HTTPException(status_code=409, detail="bili-sync Webhook 网盘类型无效")
    scan_path = settings.bili_sync_webhook_scan_path.strip()
    if not scan_path:
        raise HTTPException(status_code=409, detail="请先配置 bili-sync 专用扫描目录")
    root = settings.provider_strm_source_root(provider)
    debounce = max(5, min(settings.bili_sync_webhook_debounce_seconds, 600))
    try:
        result = schedule_webhook_incremental_sync(
            provider, root, debounce, scan_path=scan_path, request_source="bili-sync"
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "ok": True,
        "state": "coalesced" if result["coalesced"] else "scheduled",
        "scope": "configured_incremental",
        "job_id": result["job_id"],
        "scan_path": scan_path,
    }
