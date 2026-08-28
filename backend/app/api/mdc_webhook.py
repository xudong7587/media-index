from __future__ import annotations

import json
import secrets
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request, status

from app.core.config import get_settings
from app.services.scheduler import schedule_webhook_incremental_sync, schedule_webhook_targeted_sync
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
    if request.headers.get("x-mediaindex-settings-test", "").strip() == "1":
        return {
            "ok": True,
            "state": "validated",
            "message": "Webhook 凭据和已保存的网盘配置验证通过；测试未生成 STRM",
        }

    # Preferred contract: the external service is only a completion signal.
    # The scan scope is selected and authorized in MediaIndex, so MDC-NG does
    # not need to know or send either container's media path.
    configured_scan_path = str(getattr(settings, "mdc_webhook_scan_path", "") or "").strip()
    debounce_seconds = int(getattr(settings, "mdc_webhook_debounce_seconds", 30) or 30)
    if configured_scan_path:
        root_path = settings.provider_strm_source_root(provider)
        try:
            result = schedule_webhook_incremental_sync(
                provider,
                root_path,
                debounce_seconds,
                scan_path=configured_scan_path,
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
            "scan_path": configured_scan_path,
            "message": "已合并到所选目录的增量扫描" if result["coalesced"] else "已按所选目录安排增量 STRM 扫描",
        }

    supplied_path = _extract_media_path(dict(request.query_params)) or path.strip() or _extract_media_path(payload)
    mapped_path = ""
    fallback_reason = ""
    if supplied_path:
        if len(supplied_path) > 4000 or any(char in supplied_path for char in "\x00\r\n"):
            fallback_reason = "请求路径格式无效"
        else:
            try:
                mapped_path = map_external_media_path(supplied_path, provider=provider, settings=settings)
            except (ValueError, TargetedStrmError) as exc:
                fallback_reason = str(exc)

    if mapped_path:
        try:
            result = schedule_webhook_targeted_sync(provider, mapped_path, debounce_seconds)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {
            "ok": True,
            "state": "coalesced" if result["coalesced"] else "scheduled",
            "scope": "targeted",
            "job_id": result["job_id"],
            "target_path": mapped_path,
            "message": "已合并同一路径的重复完成事件" if result["coalesced"] else "已安排指定文件或目录的定点 STRM 生成",
        }

    root_path = settings.provider_strm_source_root(provider)
    try:
        result = schedule_webhook_incremental_sync(
            provider,
            root_path,
            debounce_seconds,
        )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "ok": True,
        "state": "coalesced" if result["coalesced"] else "scheduled",
        "scope": "saved_incremental",
        "job_id": result["job_id"],
        "message": (
            "未收到可用目标路径，已合并到已保存范围的增量生成"
            if result["coalesced"]
            else "未收到可用目标路径，已按已保存范围安排增量生成"
        ) + (f"（{fallback_reason}）" if fallback_reason else ""),
    }


_PATH_KEY_PRIORITY = (
    "targetfilepath",
    "targetpath",
    "targetfile",
    "outputfilepath",
    "outputpath",
    "outputfile",
    "destinationfilepath",
    "destinationpath",
    "destinationfile",
    "destpath",
    "destination",
    "filepath",
    "path",
)


def _extract_media_path(value: Any, *, depth: int = 0) -> str:
    if depth > 4:
        return ""
    if isinstance(value, dict):
        normalized = {
            _normalize_path_key(key): item
            for key, item in value.items()
            if isinstance(item, str) and item.strip()
        }
        for key in _PATH_KEY_PRIORITY:
            item = normalized.get(key)
            if isinstance(item, str) and item.strip():
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


def _normalize_path_key(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "").replace("_", "")
