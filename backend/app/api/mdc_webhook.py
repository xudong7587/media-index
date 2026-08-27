from __future__ import annotations

import json
import secrets
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request, status

from app.core.config import get_settings
from app.services.scheduler import schedule_webhook_targeted_sync
from app.services.targeted_strm import TargetedStrmError, map_external_media_path


router = APIRouter(tags=["strm-incremental-webhook"])


@router.api_route("/api/webhooks/mdc-ng", methods=["GET", "POST"], status_code=status.HTTP_202_ACCEPTED, include_in_schema=False)
@router.api_route("/api/webhooks/strm-incremental", methods=["GET", "POST"], status_code=status.HTTP_202_ACCEPTED)
async def receive_strm_incremental_webhook(
    request: Request,
    token: str = Query(default="", max_length=512),
    path: str = Query(default="", max_length=4000),
    x_mediaindex_webhook: str = Header(default=""),
):
    settings = get_settings()
    if not bool(getattr(settings, "mdc_webhook_enabled", False)):
        raise HTTPException(status_code=409, detail="增量同步 Webhook 未启用；请先在 MediaIndex 开启并保存设置")
    expected = str(getattr(settings, "mdc_webhook_token", "") or "").strip()
    supplied = x_mediaindex_webhook.strip() or token.strip()
    if not expected or not secrets.compare_digest(expected, supplied):
        raise HTTPException(status_code=401, detail="Invalid webhook credential")

    payload: Any = {}
    if request.method == "POST":
        body = await request.body()
        if len(body) > 256 * 1024:
            raise HTTPException(status_code=413, detail="Webhook 请求过大")
        if body:
            try:
                payload = json.loads(body)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise HTTPException(status_code=422, detail="Webhook JSON 格式无效") from exc
    provider = str(getattr(settings, "mdc_webhook_provider", "p115") or "p115").strip().lower()
    provider = provider if provider in {"p115", "quark"} else "p115"
    supplied_path = path.strip() or _extract_media_path(payload)
    if not supplied_path and isinstance(payload, dict) and payload.get("source") == "mediaindex-settings-test":
        return {
            "ok": True,
            "state": "validated",
            "message": "Webhook 凭据和已保存的网盘配置验证通过；测试未生成 STRM",
        }
    if not supplied_path:
        raise HTTPException(status_code=422, detail="Webhook 必须提供本次刮削完成的精确文件路径")
    try:
        mapped_path = map_external_media_path(supplied_path, provider=provider, settings=settings)
    except (ValueError, TargetedStrmError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        result = schedule_webhook_targeted_sync(
            provider,
            mapped_path,
            int(getattr(settings, "mdc_webhook_debounce_seconds", 30) or 30),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "ok": True,
        "state": "coalesced" if result["coalesced"] else "scheduled",
        "job_id": result["job_id"],
        "message": "已合并同一文件的重复完成事件" if result["coalesced"] else "已安排该文件的定点 STRM 生成",
    }


_PATH_KEYS = {
    "path",
    "file_path",
    "filepath",
    "target_path",
    "output_path",
    "destination",
    "dest_path",
}


def _extract_media_path(value: Any, *, depth: int = 0) -> str:
    if depth > 4:
        return ""
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).strip().lower() in _PATH_KEYS and isinstance(item, str) and item.strip():
                return item.strip()
        for key in ("data", "result", "task", "event", "payload"):
            if key in value:
                found = _extract_media_path(value[key], depth=depth + 1)
                if found:
                    return found
    elif isinstance(value, list):
        for item in value[:20]:
            found = _extract_media_path(item, depth=depth + 1)
            if found:
                return found
    return ""
