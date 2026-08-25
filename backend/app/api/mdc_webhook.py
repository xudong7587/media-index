from __future__ import annotations

import secrets

from fastapi import APIRouter, Header, HTTPException, Query, Request, status

from app.core.config import get_settings
from app.services.scheduler import schedule_mdc_incremental_sync


router = APIRouter(tags=["mdc-ng-webhook"])


@router.api_route("/api/webhooks/mdc-ng", methods=["GET", "POST"], status_code=status.HTTP_202_ACCEPTED)
async def receive_mdc_webhook(
    request: Request,
    token: str = Query(default="", max_length=512),
    x_mediaindex_webhook: str = Header(default=""),
):
    settings = get_settings()
    if not bool(getattr(settings, "mdc_webhook_enabled", False)):
        raise HTTPException(status_code=404, detail="MDC-NG Webhook 未启用")
    expected = str(getattr(settings, "mdc_webhook_token", "") or "").strip()
    supplied = x_mediaindex_webhook.strip() or token.strip()
    if not expected or not secrets.compare_digest(expected, supplied):
        raise HTTPException(status_code=401, detail="Invalid webhook credential")

    # MDC-NG may send a templated JSON body, but MediaIndex deliberately does
    # not trust paths or provider choices supplied by an external request.
    # The saved settings are the sole authority for scan scope.
    if request.method == "POST":
        body = await request.body()
        if len(body) > 256 * 1024:
            raise HTTPException(status_code=413, detail="MDC-NG Webhook 请求过大")
    provider = str(getattr(settings, "mdc_webhook_provider", "p115") or "p115").strip().lower()
    provider = provider if provider in {"p115", "quark"} else "p115"
    root_path = str(getattr(settings, "mdc_webhook_root_path", "") or "").strip() or settings.provider_strm_source_root(provider)
    try:
        result = schedule_mdc_incremental_sync(
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
        "message": "已合并到等待中的 MDC-NG 增量同步" if result["coalesced"] else "已安排 MDC-NG 增量同步",
    }
