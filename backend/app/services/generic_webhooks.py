from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import logging
import queue
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.clients.http import open_url
from app.db.database import db


LOGGER = logging.getLogger(__name__)
MAX_WEBHOOK_BODY = 256 * 1024
MAX_STORED_PAYLOAD = 64 * 1024
SIGNATURE_TOLERANCE_SECONDS = 5 * 60
RETRY_DELAYS_SECONDS = (5, 5 * 60, 30 * 60, 2 * 60 * 60, 5 * 60 * 60, 10 * 60 * 60, 14 * 60 * 60, 20 * 60 * 60, 24 * 60 * 60)
DEFAULT_EVENT_TYPES = ("transfer_success", "failure", "review", "library", "no_resource", "playback")

_delivery_queue: queue.Queue[int] = queue.Queue()
_worker_stop = threading.Event()
_worker_wake = threading.Event()
_worker: threading.Thread | None = None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat(timespec="seconds")


def generate_signing_secret() -> str:
    return "whsec_" + base64.b64encode(secrets.token_bytes(32)).decode("ascii")


def generate_endpoint_key() -> str:
    return "whin_" + secrets.token_urlsafe(18)


def serialize_connection(row: dict[str, Any], *, include_secret: bool = False) -> dict[str, Any]:
    result = {
        "id": int(row["id"]),
        "kind": "generic",
        "name": str(row.get("name") or ""),
        "direction": str(row.get("direction") or ""),
        "enabled": bool(row.get("enabled")),
        "endpoint_key": str(row.get("endpoint_key") or ""),
        "target_url": str(row.get("target_url") or ""),
        "event_types": _load_event_types(row.get("event_types_json")),
        "verification_state": str(row.get("verification_state") or "unverified"),
        "last_event_at": row.get("last_event_at"),
        "last_success_at": row.get("last_success_at"),
        "last_failure_at": row.get("last_failure_at"),
        "last_error": str(row.get("last_error_safe") or ""),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "has_signing_secret": bool(row.get("signing_secret")),
    }
    if include_secret:
        result["signing_secret"] = str(row.get("signing_secret") or "")
    return result


def list_connections() -> list[dict[str, Any]]:
    with db() as conn:
        rows = conn.execute("SELECT * FROM webhook_connections ORDER BY updated_at DESC,id DESC").fetchall()
    return [serialize_connection(dict(row)) for row in rows]


def get_connection(connection_id: int) -> dict[str, Any] | None:
    with db() as conn:
        row = conn.execute("SELECT * FROM webhook_connections WHERE id=?", (connection_id,)).fetchone()
    return dict(row) if row else None


def create_connection(name: str, direction: str, target_url: str, event_types: list[str]) -> dict[str, Any]:
    clean_name = _validate_name(name)
    clean_direction = _validate_direction(direction)
    clean_target = validate_target_url(target_url) if clean_direction == "outbound" else ""
    clean_events = normalize_event_types(event_types)
    endpoint_key = generate_endpoint_key()
    secret = generate_signing_secret()
    with db() as conn:
        cursor = conn.execute(
            """INSERT INTO webhook_connections(
                   name,direction,endpoint_key,target_url,signing_secret,event_types_json
               ) VALUES(?,?,?,?,?,?)""",
            (clean_name, clean_direction, endpoint_key, clean_target, secret, json.dumps(clean_events)),
        )
        connection_id = int(cursor.lastrowid)
        row = conn.execute("SELECT * FROM webhook_connections WHERE id=?", (connection_id,)).fetchone()
    return serialize_connection(dict(row), include_secret=True)


def update_connection(
    connection_id: int,
    *,
    name: str | None = None,
    enabled: bool | None = None,
    target_url: str | None = None,
    event_types: list[str] | None = None,
) -> dict[str, Any] | None:
    current = get_connection(connection_id)
    if not current:
        return None
    values: list[Any] = []
    assignments: list[str] = []
    if name is not None:
        assignments.append("name=?")
        values.append(_validate_name(name))
    if enabled is not None:
        assignments.append("enabled=?")
        values.append(int(enabled))
    if target_url is not None:
        if current["direction"] != "outbound":
            raise ValueError("接收型 Webhook 没有目标 URL")
        assignments.append("target_url=?")
        values.append(validate_target_url(target_url))
        assignments.extend(["verification_state='unverified'", "last_error_safe=''"])
    if event_types is not None:
        assignments.append("event_types_json=?")
        values.append(json.dumps(normalize_event_types(event_types)))
    if assignments:
        values.append(connection_id)
        with db() as conn:
            conn.execute(
                f"UPDATE webhook_connections SET {','.join(assignments)},updated_at=CURRENT_TIMESTAMP WHERE id=?",
                tuple(values),
            )
    updated = get_connection(connection_id)
    return serialize_connection(updated) if updated else None


def delete_connection(connection_id: int) -> bool:
    with db() as conn:
        cursor = conn.execute("DELETE FROM webhook_connections WHERE id=?", (connection_id,))
    return cursor.rowcount > 0


def rotate_secret(connection_id: int) -> dict[str, Any] | None:
    secret = generate_signing_secret()
    with db() as conn:
        cursor = conn.execute(
            """UPDATE webhook_connections SET signing_secret=?,verification_state='unverified',
                   last_error_safe='',updated_at=CURRENT_TIMESTAMP WHERE id=?""",
            (secret, connection_id),
        )
        if cursor.rowcount <= 0:
            return None
        row = conn.execute("SELECT * FROM webhook_connections WHERE id=?", (connection_id,)).fetchone()
    return serialize_connection(dict(row), include_secret=True)


def reveal_secret(connection_id: int) -> str | None:
    row = get_connection(connection_id)
    return str(row["signing_secret"]) if row else None


def list_deliveries(connection_id: int | None = None, limit: int = 50) -> list[dict[str, Any]]:
    params: tuple[Any, ...]
    where = ""
    if connection_id is None:
        params = (limit,)
    else:
        where = "WHERE d.connection_id=?"
        params = (connection_id, limit)
    with db() as conn:
        rows = conn.execute(
            f"""SELECT d.id,d.connection_id,c.name,d.event_id,d.direction,d.event_type,d.status,
                       d.attempts,d.response_status,d.error_safe,d.next_attempt_at,d.created_at,d.updated_at
                FROM webhook_deliveries d JOIN webhook_connections c ON c.id=d.connection_id
                {where} ORDER BY d.created_at DESC,d.id DESC LIMIT ?""",
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def accept_inbound(
    endpoint_key: str,
    body: bytes,
    headers: dict[str, str],
) -> tuple[dict[str, Any], bool]:
    if len(body) > MAX_WEBHOOK_BODY:
        raise ValueError("Webhook 请求不能超过 256 KB")
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM webhook_connections WHERE endpoint_key=? AND direction='inbound'",
            (endpoint_key,),
        ).fetchone()
    if not row:
        raise LookupError("Webhook 接收端不存在")
    connection = dict(row)
    if not bool(connection["enabled"]):
        raise PermissionError("Webhook 接收端已停用")
    _verify_inbound_auth(str(connection["signing_secret"]), body, headers)
    try:
        payload = json.loads(body or b"{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Webhook JSON 格式无效") from exc
    if not isinstance(payload, dict):
        raise ValueError("Webhook 请求体必须是 JSON 对象")
    event_id = str(headers.get("webhook-id") or payload.get("id") or "").strip()
    event_type = str(payload.get("type") or headers.get("x-event-type") or "message.received").strip()
    if payload.get("specversion") and str(payload.get("specversion")) != "1.0":
        raise ValueError("当前仅支持 CloudEvents specversion 1.0")
    if not event_id:
        event_id = "evt_" + uuid.uuid4().hex
    if len(event_id) > 200 or len(event_type) > 200:
        raise ValueError("事件 ID 或事件类型过长")
    stored = _bounded_payload(payload)
    with db() as conn:
        cursor = conn.execute(
            """INSERT OR IGNORE INTO webhook_deliveries(
                   connection_id,event_id,direction,event_type,status,payload_json
               ) VALUES(?,?,'inbound',?,'received',?)""",
            (int(connection["id"]), event_id, event_type, stored),
        )
        duplicate = cursor.rowcount <= 0
        if not duplicate:
            conn.execute(
                """UPDATE webhook_connections SET verification_state='verified',last_event_at=CURRENT_TIMESTAMP,
                       last_success_at=CURRENT_TIMESTAMP,last_error_safe='',updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                (int(connection["id"]),),
            )
    return {"ok": True, "accepted": not duplicate, "duplicate": duplicate, "event_id": event_id}, duplicate


def enqueue_outbound_event(
    event_type: str,
    data: dict[str, Any],
    *,
    subject: str = "",
    event_id: str = "",
) -> int:
    normalized_type = str(event_type or "message").strip()[:200]
    stable_event_id = str(event_id or "").strip()[:200] or "evt_" + uuid.uuid4().hex
    payload = {
        "specversion": "1.0",
        "id": stable_event_id,
        "source": "/mediaindex/notifications",
        "type": f"io.mediaindex.{normalized_type}",
        "time": iso_now(),
        "datacontenttype": "application/json",
        "data": data,
    }
    if subject:
        payload["subject"] = str(subject)[:200]
    payload_json = _bounded_payload(payload)
    queued: list[int] = []
    with db() as conn:
        rows = conn.execute(
            "SELECT id,event_types_json FROM webhook_connections WHERE direction='outbound' AND enabled=1"
        ).fetchall()
        for row in rows:
            selected = _load_event_types(row["event_types_json"])
            if "*" not in selected and normalized_type not in selected:
                continue
            cursor = conn.execute(
                """INSERT OR IGNORE INTO webhook_deliveries(
                       connection_id,event_id,direction,event_type,status,payload_json,next_attempt_at
                   ) VALUES(?,?,'outbound',?,'queued',?,CURRENT_TIMESTAMP)""",
                (int(row["id"]), stable_event_id, normalized_type, payload_json),
            )
            if cursor.rowcount > 0:
                queued.append(int(cursor.lastrowid))
    for delivery_id in queued:
        _delivery_queue.put(delivery_id)
    if queued:
        _worker_wake.set()
    return len(queued)


def publish_notification(notification_id: int, event_type: str) -> int:
    """Expose the stable notification contract without coupling webhooks to channel delivery."""
    with db() as conn:
        row = conn.execute(
            """SELECT id,source_key,type,title,message,action_page,created_at
               FROM notifications WHERE id=?""",
            (notification_id,),
        ).fetchone()
    if not row:
        return 0
    item = dict(row)
    return enqueue_outbound_event(
        event_type,
        {
            "notification_id": int(item["id"]),
            "source_key": str(item["source_key"] or ""),
            "level": str(item["type"] or "info"),
            "title": str(item["title"] or ""),
            "message": str(item["message"] or ""),
            "action_page": str(item["action_page"] or ""),
            "created_at": item["created_at"],
        },
        subject=str(item["source_key"] or item["id"]),
        event_id=f"notification:{int(item['id'])}",
    )


def enqueue_test_event(connection_id: int) -> int:
    connection = get_connection(connection_id)
    if not connection:
        raise LookupError("Webhook 连接不存在")
    if connection["direction"] != "outbound":
        raise ValueError("接收型 Webhook 请从外部向接收 URL 发送测试事件")
    event_id = "test_" + uuid.uuid4().hex
    payload = {
        "specversion": "1.0",
        "id": event_id,
        "source": "/mediaindex/webhook-workspace",
        "type": "io.mediaindex.webhook.test",
        "time": iso_now(),
        "datacontenttype": "application/json",
        "data": {"message": "MediaIndex Webhook 连接测试", "connection": str(connection["name"])},
    }
    with db() as conn:
        cursor = conn.execute(
            """INSERT INTO webhook_deliveries(
                   connection_id,event_id,direction,event_type,status,payload_json,next_attempt_at
               ) VALUES(?,?,'outbound','test','queued',?,CURRENT_TIMESTAMP)""",
            (connection_id, event_id, _bounded_payload(payload)),
        )
        delivery_id = int(cursor.lastrowid)
    deliver_outbound(delivery_id, schedule_retry=False)
    return delivery_id


def retry_delivery(delivery_id: int) -> None:
    with db() as conn:
        cursor = conn.execute(
            """UPDATE webhook_deliveries SET status='queued',next_attempt_at=CURRENT_TIMESTAMP,
                   attempts=0,error_safe='',updated_at=CURRENT_TIMESTAMP
               WHERE id=? AND direction='outbound'""",
            (delivery_id,),
        )
    if cursor.rowcount <= 0:
        raise LookupError("Webhook 投递记录不存在")
    _delivery_queue.put(delivery_id)
    _worker_wake.set()


def deliver_outbound(delivery_id: int, *, schedule_retry: bool = True) -> bool:
    with db() as conn:
        row = conn.execute(
            """SELECT d.*,c.target_url,c.signing_secret,c.enabled
               FROM webhook_deliveries d JOIN webhook_connections c ON c.id=d.connection_id
               WHERE d.id=? AND d.direction='outbound'""",
            (delivery_id,),
        ).fetchone()
        if not row or not bool(row["enabled"]):
            return False
        attempt = int(row["attempts"] or 0) + 1
        conn.execute(
            "UPDATE webhook_deliveries SET status='delivering',attempts=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (attempt, delivery_id),
        )
    delivery = dict(row)
    payload_text = str(delivery["payload_json"] or "{}")
    payload_bytes = payload_text.encode("utf-8")
    timestamp = str(int(time.time()))
    event_id = str(delivery["event_id"])
    signature = sign_payload(str(delivery["signing_secret"]), event_id, timestamp, payload_bytes)
    request = urllib.request.Request(
        str(delivery["target_url"]),
        data=payload_bytes,
        method="POST",
        headers={
            "Content-Type": "application/cloudevents+json; charset=utf-8",
            "User-Agent": "MediaIndex-Webhook/1.0",
            "webhook-id": event_id,
            "webhook-timestamp": timestamp,
            "webhook-signature": signature,
        },
    )
    response_status: int | None = None
    error_safe = ""
    try:
        with open_url(request, timeout=20) as response:
            response_status = int(getattr(response, "status", response.getcode()))
        if 200 <= response_status < 300:
            _mark_delivered(delivery_id, int(delivery["connection_id"]), response_status)
            return True
        error_safe = f"目标端返回 HTTP {response_status}"
    except urllib.error.HTTPError as exc:
        response_status = int(exc.code)
        error_safe = f"目标端返回 HTTP {exc.code}"
    except Exception as exc:  # external transports vary; never persist credentials from exception URLs
        error_safe = f"请求失败（{type(exc).__name__}）"
        LOGGER.warning("Webhook delivery %s failed: %s", delivery_id, type(exc).__name__)
    _mark_failed(delivery_id, int(delivery["connection_id"]), attempt, response_status, error_safe, schedule_retry)
    return False


def sign_payload(secret: str, event_id: str, timestamp: str, payload: bytes) -> str:
    key = _decode_secret(secret)
    signed = event_id.encode("utf-8") + b"." + timestamp.encode("ascii") + b"." + payload
    digest = hmac.new(key, signed, hashlib.sha256).digest()
    return "v1," + base64.b64encode(digest).decode("ascii")


def verify_signature(secret: str, event_id: str, timestamp: str, payload: bytes, signature_header: str) -> bool:
    expected = sign_payload(secret, event_id, timestamp, payload)
    return any(hmac.compare_digest(expected, item) for item in signature_header.split())


def start_webhook_worker() -> None:
    global _worker
    if _worker and _worker.is_alive():
        return
    with db() as conn:
        conn.execute(
            """UPDATE webhook_deliveries SET status='retry_wait',next_attempt_at=CURRENT_TIMESTAMP,
                   error_safe='服务重启后恢复未完成投递',updated_at=CURRENT_TIMESTAMP
               WHERE direction='outbound' AND status='delivering'"""
        )
    _worker_stop.clear()
    _worker = threading.Thread(target=_worker_loop, name="media-index-webhook-delivery", daemon=True)
    _worker.start()


def stop_webhook_worker() -> None:
    _worker_stop.set()
    _worker_wake.set()


def _worker_loop() -> None:
    while not _worker_stop.is_set():
        try:
            delivery_id = _delivery_queue.get_nowait()
        except queue.Empty:
            due = _due_delivery_ids()
            if due:
                for delivery_id in due:
                    deliver_outbound(delivery_id)
                continue
            _worker_wake.wait(30)
            _worker_wake.clear()
            continue
        try:
            deliver_outbound(delivery_id)
        finally:
            _delivery_queue.task_done()


def _due_delivery_ids() -> list[int]:
    with db() as conn:
        rows = conn.execute(
            """SELECT id FROM webhook_deliveries
               WHERE direction='outbound' AND status IN ('queued','retry_wait')
                 AND COALESCE(next_attempt_at,CURRENT_TIMESTAMP)<=CURRENT_TIMESTAMP
               ORDER BY id LIMIT 25"""
        ).fetchall()
    return [int(row["id"]) for row in rows]


def _mark_delivered(delivery_id: int, connection_id: int, response_status: int) -> None:
    with db() as conn:
        conn.execute(
            """UPDATE webhook_deliveries SET status='delivered',response_status=?,error_safe='',
                   next_attempt_at=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
            (response_status, delivery_id),
        )
        conn.execute(
            """UPDATE webhook_connections SET verification_state='verified',last_event_at=CURRENT_TIMESTAMP,
                   last_success_at=CURRENT_TIMESTAMP,last_error_safe='',updated_at=CURRENT_TIMESTAMP WHERE id=?""",
            (connection_id,),
        )


def _mark_failed(
    delivery_id: int,
    connection_id: int,
    attempt: int,
    response_status: int | None,
    error_safe: str,
    schedule_retry: bool,
) -> None:
    retry = schedule_retry and attempt <= len(RETRY_DELAYS_SECONDS)
    next_attempt = (
        (utc_now() + timedelta(seconds=RETRY_DELAYS_SECONDS[attempt - 1])).isoformat(timespec="seconds")
        if retry else None
    )
    with db() as conn:
        conn.execute(
            """UPDATE webhook_deliveries SET status=?,response_status=?,error_safe=?,next_attempt_at=?,
                   updated_at=CURRENT_TIMESTAMP WHERE id=?""",
            ("retry_wait" if retry else "failed", response_status, error_safe[:500], next_attempt, delivery_id),
        )
        conn.execute(
            """UPDATE webhook_connections SET verification_state='failing',last_failure_at=CURRENT_TIMESTAMP,
                   last_error_safe=?,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
            (error_safe[:500], connection_id),
        )


def _verify_inbound_auth(secret: str, body: bytes, headers: dict[str, str]) -> None:
    authorization = str(headers.get("authorization") or "")
    if authorization.startswith("Bearer ") and hmac.compare_digest(authorization[7:].strip(), secret):
        return
    event_id = str(headers.get("webhook-id") or "").strip()
    timestamp = str(headers.get("webhook-timestamp") or "").strip()
    signature = str(headers.get("webhook-signature") or "").strip()
    if not event_id or not timestamp or not signature:
        raise PermissionError("缺少 Standard Webhooks 签名或 Bearer 凭据")
    try:
        if abs(int(time.time()) - int(timestamp)) > SIGNATURE_TOLERANCE_SECONDS:
            raise PermissionError("Webhook 时间戳已过期")
    except ValueError as exc:
        raise PermissionError("Webhook 时间戳无效") from exc
    if not verify_signature(secret, event_id, timestamp, body, signature):
        raise PermissionError("Webhook 签名无效")


def _decode_secret(secret: str) -> bytes:
    value = secret.removeprefix("whsec_")
    try:
        return base64.b64decode(value, validate=True)
    except ValueError as exc:
        raise ValueError("Webhook 签名密钥格式无效") from exc


def _validate_name(name: str) -> str:
    value = str(name or "").strip()
    if not value or len(value) > 80 or any(char in value for char in "\x00\r\n"):
        raise ValueError("连接名称需为 1–80 个字符")
    return value


def _validate_direction(direction: str) -> str:
    value = str(direction or "").strip().lower()
    if value not in {"inbound", "outbound"}:
        raise ValueError("Webhook 方向必须是 inbound 或 outbound")
    return value


def validate_target_url(url: str) -> str:
    value = str(url or "").strip()
    if len(value) > 2048 or any(char in value for char in "\x00\r\n"):
        raise ValueError("Webhook 目标 URL 无效")
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Webhook 目标必须是完整的 HTTP(S) URL，且不能在 URL 中携带凭据")
    hostname = parsed.hostname.casefold()
    local = hostname in {"localhost", "host.docker.internal"} or hostname.endswith(".local") or "." not in hostname
    try:
        address = ipaddress.ip_address(hostname)
        if address.is_link_local or address.is_multicast or address.is_unspecified or address.is_reserved:
            raise ValueError("Webhook 目标不能使用链路本地、组播、未指定或保留地址")
        local = local or address.is_private or address.is_loopback
    except ValueError as exc:
        if str(exc).startswith("Webhook"):
            raise
    if parsed.scheme == "http" and not local:
        raise ValueError("公网 Webhook 必须使用 HTTPS；HTTP 仅允许本机、局域网或 Docker 服务名")
    return value.rstrip("/")


def normalize_event_types(values: list[str]) -> list[str]:
    allowed = set(DEFAULT_EVENT_TYPES) | {"*"}
    result = list(dict.fromkeys(str(item).strip() for item in values if str(item).strip()))
    if not result:
        result = ["*"]
    invalid = [item for item in result if item not in allowed]
    if invalid:
        raise ValueError(f"不支持的事件类型：{', '.join(invalid)}")
    return result


def _load_event_types(value: Any) -> list[str]:
    try:
        parsed = json.loads(str(value or "[]"))
        return [str(item) for item in parsed] if isinstance(parsed, list) else ["*"]
    except json.JSONDecodeError:
        return ["*"]


def _bounded_payload(payload: dict[str, Any]) -> str:
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
    if len(text.encode("utf-8")) > MAX_STORED_PAYLOAD:
        raise ValueError("Webhook 事件持久化内容不能超过 64 KB")
    return text
