from __future__ import annotations

import secrets

from fastapi import APIRouter, Header, HTTPException, Query, Request, status

from app.core.config import get_settings
from app.services.scheduler import schedule_webhook_incremental_sync


router = APIRouter(tags=["strm-incremental-webhook"])


@router.api_route("/api/webhooks/mdc-ng", methods=["GET", "POST"], status_code=status.HTTP_202_ACCEPTED, include_in_schema=False)
@router.api_route("/api/webhooks/strm-incremental", methods=["GET", "POST"], status_code=status.HTTP_202_ACCEPTED)
async def receive_strm_incremental_webhook(
    request: Request,
    token: str = Query(default="", max_length=512),
    x_mediaindex_webhook: str = Header(default=""),
):
    settings = get_settings()
    if not bool(getattr(settings, "mdc_webhook_enabled", False)):
        raise HTTPException(status_code=409, detail="增量同步 Webhook 未启用；请先在 MediaIndex 开启并保存设置")
    expected = str(getattr(settings, "mdc_webhook_token", "") or "").strip()
    supplied = x_mediaindex_webhook.strip() or token.strip()
    if not expected or not secrets.compare_digest(expected, supplied):
        raise HTTPException(status_code=401, detail="Invalid webhook credential")

    if request.method == "POST":
        body = await request.body()
        if len(body) > 256 * 1024:
            raise HTTPException(status_code=413, detail="Webhook 请求过大")
    provider = str(getattr(settings, "mdc_webhook_provider", "p115") or "p115").strip().lower()
    provider = provider if provider in {"p115", "quark"} else "p115"
    if request.headers.get("x-mediaindex-settings-test", "").strip() == "1":
        return {
            "ok": True,
            "state": "validated",
            "message": "Webhook 凭据和已保存的网盘配置验证通过；测试未生成 STRM",
        }
    root_path = settings.provider_strm_source_root(provider)
    try:
        result = schedule_webhook_incremental_sync(
            provider,
            root_path,
            int(getattr(settings, "mdc_webhook_debounce_seconds", 30) or 30),
        )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "ok": True,
        "state": "coalesced" if result["coalesced"] else "scheduled",
        "job_id": result["job_id"],
        "message": "已合并到等待中的 STRM 增量生成" if result["coalesced"] else "已安排 STRM 增量生成",
    }
