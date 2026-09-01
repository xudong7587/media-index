from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.security import require_user
from app.db.database import db
from app.services import generic_webhooks


router = APIRouter(
    prefix="/api/webhooks/connections",
    tags=["generic-webhooks"],
    dependencies=[Depends(require_user)],
)
ingress_router = APIRouter(tags=["generic-webhooks"])


class ConnectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    direction: Literal["inbound", "outbound"]
    target_url: str = Field(default="", max_length=2048)
    event_types: list[str] = Field(default_factory=lambda: ["*"])


class ConnectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    enabled: bool | None = None
    target_url: str | None = Field(default=None, max_length=2048)
    event_types: list[str] | None = None


def _managed_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"


def _mdc_connection() -> dict:
    settings = get_settings()
    enabled = bool(getattr(settings, "mdc_webhook_enabled", False))
    has_secret = bool(str(getattr(settings, "mdc_webhook_token", "") or "").strip())
    with db() as conn:
        row = conn.execute(
            """SELECT created_at,status,stage FROM transfer_jobs
               WHERE request_source='mdc-ng' ORDER BY id DESC LIMIT 1"""
        ).fetchone()
    last_event_at = str(row["created_at"]) if row else None
    state = "verified" if enabled and has_secret and row else "configured" if enabled and has_secret else "disabled"
    return {
        "id": "mdc-ng",
        "kind": "built_in",
        "name": "MDC-NG 增量 STRM",
        "direction": "inbound",
        "enabled": enabled,
        "endpoint_key": "strm-incremental",
        "target_url": "",
        "event_types": ["mdc.download.finished"],
        "verification_state": state,
        "last_event_at": last_event_at,
        "last_success_at": last_event_at if row and str(row["status"]) != "failed" else None,
        "last_failure_at": last_event_at if row and str(row["status"]) == "failed" else None,
        "last_error": "",
        "has_signing_secret": has_secret,
        "managed_by": "mdc_settings",
    }


@router.get("")
def connections():
    return {
        "items": [_mdc_connection(), *generic_webhooks.list_connections()],
        "event_types": list(generic_webhooks.DEFAULT_EVENT_TYPES),
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def create_connection(payload: ConnectionCreate, response: Response):
    _no_store(response)
    try:
        return generic_webhooks.create_connection(
            payload.name,
            payload.direction,
            payload.target_url,
            payload.event_types,
        )
    except (ValueError, LookupError) as exc:
        raise _managed_error(exc) from exc


@router.patch("/{connection_id}")
def update_connection(connection_id: int, payload: ConnectionUpdate):
    try:
        result = generic_webhooks.update_connection(
            connection_id,
            name=payload.name,
            enabled=payload.enabled,
            target_url=payload.target_url,
            event_types=payload.event_types,
        )
    except (ValueError, LookupError) as exc:
        raise _managed_error(exc) from exc
    if not result:
        raise HTTPException(status_code=404, detail="Webhook 连接不存在")
    return result


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_connection(connection_id: int):
    if not generic_webhooks.delete_connection(connection_id):
        raise HTTPException(status_code=404, detail="Webhook 连接不存在")


@router.get("/{connection_id}/secret")
def reveal_secret(connection_id: int, response: Response):
    _no_store(response)
    secret = generic_webhooks.reveal_secret(connection_id)
    if secret is None:
        raise HTTPException(status_code=404, detail="Webhook 连接不存在")
    return {"signing_secret": secret}


@router.post("/{connection_id}/rotate-secret")
def rotate_secret(connection_id: int, response: Response):
    _no_store(response)
    result = generic_webhooks.rotate_secret(connection_id)
    if not result:
        raise HTTPException(status_code=404, detail="Webhook 连接不存在")
    return result


@router.post("/{connection_id}/test")
def test_connection(connection_id: int):
    try:
        delivery_id = generic_webhooks.enqueue_test_event(connection_id)
    except (ValueError, LookupError) as exc:
        raise _managed_error(exc) from exc
    item = next((item for item in generic_webhooks.list_deliveries(connection_id, 10) if int(item["id"]) == delivery_id), None)
    if not item:
        raise HTTPException(status_code=500, detail="测试投递记录创建失败")
    if item["status"] != "delivered":
        raise HTTPException(status_code=422, detail=item["error_safe"] or "目标端未确认测试事件")
    return {"ok": True, "delivery": item, "message": "目标端已返回 2xx，连接验证成功"}


@router.post("/deliveries/{delivery_id}/retry")
def retry_delivery(delivery_id: int):
    try:
        generic_webhooks.retry_delivery(delivery_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "message": "已加入重投队列"}


@router.get("/deliveries/recent")
def recent_deliveries(
    connection_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    return {"items": generic_webhooks.list_deliveries(connection_id, limit)}


@ingress_router.post("/api/webhooks/in/{endpoint_key}", status_code=status.HTTP_202_ACCEPTED)
async def receive_generic_webhook(endpoint_key: str, request: Request):
    body = await request.body()
    headers = {key.casefold(): value for key, value in request.headers.items()}
    try:
        result, _duplicate = generic_webhooks.accept_inbound(endpoint_key, body, headers)
        return result
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except ValueError as exc:
        code = 413 if "256 KB" in str(exc) else 422
        raise HTTPException(status_code=code, detail=str(exc)) from exc
