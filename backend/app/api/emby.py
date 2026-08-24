from __future__ import annotations

import secrets
import hashlib
import base64
import concurrent.futures
from email import policy
from email.parser import BytesParser
import io
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.security import require_user
from app.clients.http import open_url
from app.services.deletion_workflow import DeletionWorkflowError, confirm_deletion, request_deletion_for_strm
from app.services.emby_library_covers import refresh_all_library_covers
from app.services.notification_channels import send_configured_channels
from app.services.notifications import add_notification


router = APIRouter(prefix="/api/integrations/emby", tags=["emby-integration"])
_EMBY_ITEM_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class EmbyStrmDeletedEvent(BaseModel):
    relative_path: str = Field(min_length=6, max_length=500)
    event_id: str = Field(default="", max_length=256)


class EmbyLibraryCoverRequest(BaseModel):
    title: str = Field(default="", max_length=80)
    style: str = Field(default="collage", pattern="^(collage|showcase|mosaic|minimal)$")


def _emby_credentials() -> tuple[str, str]:
    settings = get_settings()
    base_url = settings.emby_base_url.strip().rstrip("/")
    api_key = settings.emby_api_key.strip()
    if not base_url or not api_key:
        raise HTTPException(status_code=422, detail="请先保存 Emby 地址和 API Key")
    return base_url, api_key


def _read_emby_json(path: str, *, query: dict[str, str | int] | None = None) -> object:
    base_url, api_key = _emby_credentials()
    suffix = f"?{urllib.parse.urlencode(query)}" if query else ""
    request = urllib.request.Request(
        f"{base_url}{path}{suffix}",
        headers={"X-Emby-Token": api_key, "Accept": "application/json"},
        method="GET",
    )
    with open_url(request, timeout=10) as response:
        return json.loads(response.read(4 * 1024 * 1024).decode("utf-8"))


def _safe_emby_json(path: str, *, query: dict[str, str | int] | None = None, fallback: object) -> object:
    try:
        return _read_emby_json(path, query=query)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return fallback


def _read_emby_bytes(path: str, *, query: dict[str, str | int] | None = None, limit: int = 10 * 1024 * 1024) -> bytes:
    base_url, api_key = _emby_credentials()
    suffix = f"?{urllib.parse.urlencode(query)}" if query else ""
    request = urllib.request.Request(
        f"{base_url}{path}{suffix}",
        headers={"X-Emby-Token": api_key, "Accept": "image/*"},
        method="GET",
    )
    with open_url(request, timeout=15) as response:
        body = response.read(limit + 1)
    if len(body) > limit:
        raise ValueError("Emby 图片过大")
    return body


@router.post("/test", dependencies=[Depends(require_user)])
def test_emby_connection():
    try:
        payload = _read_emby_json("/System/Info")
    except urllib.error.HTTPError as exc:
        return {"ok": False, "message": f"Emby 返回 HTTP {exc.code}，请检查地址和 API Key"}
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return {"ok": False, "message": "无法读取 Emby 系统信息，请检查地址和网络"}
    if not isinstance(payload, dict):
        return {"ok": False, "message": "Emby 系统信息格式不兼容"}
    name = str(payload.get("ServerName") or payload.get("OperatingSystemDisplayName") or "Emby")
    version = str(payload.get("Version") or "未知版本")
    return {"ok": True, "message": f"已连接 {name}（{version}）", "server_name": name, "version": version}


@router.get("/libraries", dependencies=[Depends(require_user)])
def emby_libraries():
    """Return selectable libraries without loading dashboard items or artwork."""
    try:
        payload = _read_emby_json("/Library/VirtualFolders")
    except urllib.error.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Emby 返回 HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail="无法读取 Emby 媒体库") from exc
    libraries = []
    for folder in payload if isinstance(payload, list) else []:
        if not isinstance(folder, dict):
            continue
        library_id = str(folder.get("ItemId") or "").strip()
        if library_id:
            libraries.append({
                "id": library_id,
                "name": str(folder.get("Name") or "媒体库"),
                "collection_type": str(folder.get("CollectionType") or "mixed"),
            })
    return {"libraries": libraries}


@router.get("/dashboard", dependencies=[Depends(require_user)])
def emby_dashboard():
    """Return a read-only dashboard view without exposing the Emby API key."""
    try:
        system = _read_emby_json("/System/Info")
    except urllib.error.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Emby 返回 HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail="无法读取 Emby 服务器状态") from exc
    if not isinstance(system, dict):
        raise HTTPException(status_code=502, detail="Emby 服务器状态格式不兼容")

    counts = _safe_emby_json("/Items/Counts", fallback={})
    sessions = _safe_emby_json("/Sessions", fallback=[])
    virtual_folders = _safe_emby_json("/Library/VirtualFolders", fallback=[])
    latest_payload = _safe_emby_json(
        "/Items",
        query={
            "Recursive": "true",
            "IncludeItemTypes": "Movie,Series",
            "SortBy": "DateCreated",
            "SortOrder": "Descending",
            "Limit": 18,
            "Fields": "PrimaryImageAspectRatio,ProductionYear,CommunityRating,ImageTags",
        },
        fallback={"Items": []},
    )
    latest_items = latest_payload.get("Items", []) if isinstance(latest_payload, dict) else []
    libraries: list[dict[str, object]] = []
    for folder in virtual_folders if isinstance(virtual_folders, list) else []:
        if not isinstance(folder, dict):
            continue
        folder_id = str(folder.get("ItemId") or "")
        cover_id = ""
        if folder_id:
            sample = _safe_emby_json(
                "/Items",
                query={
                    "ParentId": folder_id,
                    "Recursive": "true",
                    "IncludeItemTypes": "Movie,Series,Season,BoxSet",
                    "HasPrimaryImage": "true",
                    "Fields": "ImageTags",
                    "Limit": 1,
                    "SortBy": "DateCreated",
                    "SortOrder": "Descending",
                },
                fallback={"Items": []},
            )
            sample_items = sample.get("Items", []) if isinstance(sample, dict) else []
            if sample_items and isinstance(sample_items[0], dict) and _has_primary_image(sample_items[0]):
                cover_id = str(sample_items[0].get("Id") or "")
        libraries.append({
            "id": folder_id,
            "name": str(folder.get("Name") or "媒体库"),
            "collection_type": str(folder.get("CollectionType") or "mixed"),
            "cover_item_id": cover_id,
        })

    active_sessions: list[dict[str, object]] = []
    for session in sessions if isinstance(sessions, list) else []:
        if not isinstance(session, dict):
            continue
        now_playing = session.get("NowPlayingItem") if isinstance(session.get("NowPlayingItem"), dict) else None
        user_name = str(session.get("UserName") or "访客")
        if now_playing or session.get("UserId"):
            active_sessions.append({
                "id": str(session.get("Id") or ""),
                "user_name": user_name,
                "device_name": str(session.get("DeviceName") or session.get("Client") or "未知设备"),
                "item_name": str(now_playing.get("Name") or "") if now_playing else "",
                "item_id": str(now_playing.get("Id") or "") if now_playing else "",
                "is_playing": bool(now_playing),
            })

    items = []
    for item in latest_items if isinstance(latest_items, list) else []:
        if not isinstance(item, dict):
            continue
        items.append({
            "id": str(item.get("Id") or ""),
            "name": str(item.get("Name") or "未命名媒体"),
            "type": str(item.get("Type") or "Unknown"),
            "year": item.get("ProductionYear"),
            "rating": item.get("CommunityRating"),
            "has_image": _has_primary_image(item),
        })

    return {
        "server": {
            "name": str(system.get("ServerName") or system.get("OperatingSystemDisplayName") or "Emby"),
            "version": str(system.get("Version") or "未知版本"),
            "operating_system": str(system.get("OperatingSystemDisplayName") or system.get("OperatingSystem") or ""),
        },
        "counts": counts if isinstance(counts, dict) else {},
        "libraries": libraries,
        "sessions": active_sessions,
        "latest_items": items,
    }


def _has_primary_image(item: dict[str, object]) -> bool:
    tags = item.get("ImageTags")
    return bool(item.get("PrimaryImageTag") or (isinstance(tags, dict) and tags.get("Primary")))


@router.get("/libraries/{library_id}/cover-preview", dependencies=[Depends(require_user)])
def preview_emby_library_cover(
    library_id: str,
    title: str = Query(default="", max_length=80),
    style: str = Query(default="collage", pattern="^(collage|showcase|mosaic|minimal)$"),
):
    try:
        body = _library_cover_bytes(library_id, title=title, style=style)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        raise HTTPException(status_code=502, detail=f"媒体库封面预览生成失败（{type(exc).__name__}）") from exc
    return Response(content=body, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.post("/libraries/{library_id}/cover", dependencies=[Depends(require_user)])
def apply_emby_library_cover(library_id: str, payload: EmbyLibraryCoverRequest):
    try:
        body = _library_cover_bytes(library_id, title=payload.title, style=payload.style)
        base_url, api_key = _emby_credentials()
        request = urllib.request.Request(
            f"{base_url}/Items/{_safe_emby_id(library_id)}/Images/Primary",
            data=base64.b64encode(body),
            headers={"X-Emby-Token": api_key, "Content-Type": "application/octet-stream"},
            method="POST",
        )
        with open_url(request, timeout=20) as response:
            response.read(1024)
    except urllib.error.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Emby 封面写入失败（HTTP {exc.code}）") from exc
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        raise HTTPException(status_code=502, detail=f"Emby 封面写入失败（{type(exc).__name__}）") from exc
    return {"ok": True, "message": "媒体库封面已生成并写入 Emby"}


@router.post("/libraries/covers/refresh", dependencies=[Depends(require_user)])
def refresh_emby_library_covers(payload: EmbyLibraryCoverRequest):
    try:
        result = refresh_all_library_covers(payload.style)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        raise HTTPException(status_code=502, detail=f"媒体库封面批量生成失败（{type(exc).__name__}）") from exc
    return {"ok": result["failed"] == 0, "message": f"已更新 {result['updated']} 个媒体库，失败 {result['failed']} 个", **result}


def _library_cover_bytes(library_id: str, *, title: str, style: str) -> bytes:
    safe_id = _safe_emby_id(library_id)
    payload = _read_emby_json(
        "/Items",
        query={
            "ParentId": safe_id,
            "Recursive": "true",
            "IncludeItemTypes": "Movie,Series",
            "HasPrimaryImage": "true",
            "SortBy": "DateCreated",
            "SortOrder": "Descending",
            "Limit": 8,
            "Fields": "ImageTags",
        },
    )
    items = payload.get("Items", []) if isinstance(payload, dict) else []
    item_ids = [
        str(item["Id"])
        for item in items[:6] if isinstance(items, list) and isinstance(item, dict) and item.get("Id")
    ] if isinstance(items, list) else []
    images: list[Image.Image] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(item_ids) or 1)) as executor:
        for image in executor.map(_read_library_item_image, item_ids):
            if image is not None:
                images.append(image)
    if not images:
        raise ValueError("媒体库没有可用于合成的海报")
    builders = {
        "collage": _collage_library_cover,
        "showcase": _showcase_library_cover,
        "mosaic": _mosaic_library_cover,
        "minimal": _minimal_library_cover,
    }
    canvas = builders.get(style, _collage_library_cover)(images)
    _draw_library_cover_label(canvas, title)
    output = io.BytesIO()
    canvas.save(output, format="JPEG", quality=91, optimize=True)
    return output.getvalue()


def _read_library_item_image(item_id: str) -> Image.Image | None:
    try:
        raw = _read_emby_bytes(
            f"/Items/{_safe_emby_id(item_id)}/Images/Primary",
            query={"maxWidth": 720, "quality": 88},
        )
        with Image.open(io.BytesIO(raw)) as opened:
            return opened.convert("RGB").copy()
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None


def _collage_library_cover(images: list[Image.Image]) -> Image.Image:
    canvas = Image.new("RGB", (960, 540), "#111a22")
    cell_width, cell_height = 320, 270
    for index in range(6):
        source = images[index % len(images)]
        tile = ImageOps.fit(source, (cell_width, cell_height), method=Image.Resampling.LANCZOS, centering=(0.5, 0.35))
        tile = ImageEnhance.Color(tile).enhance(0.82)
        canvas.paste(tile, ((index % 3) * cell_width, (index // 3) * cell_height))
    overlay = Image.new("RGBA", canvas.size, (8, 16, 24, 72))
    overlay.paste((4, 12, 20, 190), (0, 330, 960, 540))
    return Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")


def _minimal_library_cover(images: list[Image.Image]) -> Image.Image:
    background = ImageOps.fit(images[0], (960, 540), method=Image.Resampling.LANCZOS).filter(ImageFilter.GaussianBlur(18))
    background = ImageEnhance.Brightness(background).enhance(0.42)
    poster = ImageOps.fit(images[min(1, len(images) - 1)], (260, 390), method=Image.Resampling.LANCZOS)
    canvas = background.convert("RGBA")
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((74, 70, 350, 476), radius=20, fill=(0, 0, 0, 135))
    canvas = Image.alpha_composite(canvas, shadow)
    canvas.paste(poster, (82, 76))
    return canvas.convert("RGB")


def _showcase_library_cover(images: list[Image.Image]) -> Image.Image:
    background = ImageOps.fit(images[0], (960, 540), method=Image.Resampling.LANCZOS).filter(ImageFilter.GaussianBlur(22))
    canvas = ImageEnhance.Brightness(background).enhance(0.48).convert("RGBA")
    for index, angle in enumerate((-8, 0, 8)):
        poster = ImageOps.fit(images[index % len(images)], (220, 330), method=Image.Resampling.LANCZOS).rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)
        canvas.alpha_composite(poster.convert("RGBA"), (355 + index * 145, 52 + abs(angle) * 2))
    return canvas.convert("RGB")


def _mosaic_library_cover(images: list[Image.Image]) -> Image.Image:
    canvas = Image.new("RGB", (960, 540), "#102a30")
    canvas.paste(ImageOps.fit(images[0], (480, 540), method=Image.Resampling.LANCZOS), (0, 0))
    for index in range(4):
        tile = ImageOps.fit(images[(index + 1) % len(images)], (240, 270), method=Image.Resampling.LANCZOS)
        canvas.paste(tile, (480 + (index % 2) * 240, (index // 2) * 270))
    return ImageEnhance.Color(canvas).enhance(0.88)


def _draw_library_cover_label(canvas: Image.Image, title: str) -> None:
    draw = ImageDraw.Draw(canvas)
    ascii_title = "".join(char for char in str(title or "") if char.isascii() and (char.isalnum() or char in " -_"))
    label = ascii_title.strip().upper()[:28] or "MEDIA LIBRARY"
    font = ImageFont.load_default(size=38)
    draw.rounded_rectangle((386, 372, 910, 476), radius=18, fill=(4, 12, 20, 178), outline=(255, 255, 255, 46), width=1)
    draw.text((420, 402), label, fill=(247, 250, 252), font=font)


def _safe_emby_id(value: str) -> str:
    safe_id = str(value or "").strip()
    if not _EMBY_ITEM_ID.fullmatch(safe_id):
        raise ValueError("Emby 媒体库标识无效")
    return safe_id


@router.get("/images/{item_id}", dependencies=[Depends(require_user)])
def emby_item_image(item_id: str):
    if not _EMBY_ITEM_ID.fullmatch(item_id):
        raise HTTPException(status_code=422, detail="Emby 媒体标识无效")
    base_url, api_key = _emby_credentials()
    request = urllib.request.Request(
        f"{base_url}/Items/{item_id}/Images/Primary?maxWidth=640&quality=88",
        headers={"X-Emby-Token": api_key, "Accept": "image/*"},
        method="GET",
    )
    try:
        with open_url(request, timeout=10) as upstream:
            content_type = str(upstream.headers.get("Content-Type") or "image/jpeg").split(";", 1)[0].lower()
            if content_type not in {"image/jpeg", "image/png", "image/webp"}:
                raise HTTPException(status_code=502, detail="Emby 返回了不受支持的图片格式")
            body = upstream.read(8 * 1024 * 1024 + 1)
            if len(body) > 8 * 1024 * 1024:
                raise HTTPException(status_code=502, detail="Emby 图片过大")
    except urllib.error.HTTPError as exc:
        raise HTTPException(status_code=exc.code if exc.code in {404, 410} else 502, detail="Emby 图片读取失败") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise HTTPException(status_code=502, detail="Emby 图片读取失败") from exc
    return Response(content=body, media_type=content_type, headers={"Cache-Control": "private, max-age=300"})


@router.post("/strm-deleted")
async def emby_strm_deleted(
    request: Request,
    x_mediaindex_webhook: str = Header(default=""),
    token: str = Query(default="", max_length=512),
):
    payload = await _read_emby_webhook_payload(request)
    return _process_emby_webhook(payload, x_mediaindex_webhook, token)


def _process_emby_webhook(payload: dict[str, Any], x_mediaindex_webhook: str, token: str):
    expected = get_settings().emby_deletion_webhook_token.strip()
    supplied = x_mediaindex_webhook.strip() or token.strip()
    if not expected or not secrets.compare_digest(expected, supplied):
        raise HTTPException(status_code=401, detail="Invalid webhook credential")
    if _is_emby_webhook_test(payload):
        results = send_configured_channels(
            "Emby 通知测试",
            "已收到来自 Emby 的测试 Webhook，MediaIndex 通知中继正常。",
            "settings-notifications",
            force=True,
        )
        return {"ok": True, "test": True, "state": "notified", "channels": _channel_summary(results)}
    is_delete = _is_emby_delete_event(payload)
    if not is_delete:
        if _is_emby_library_event(payload):
            inserted = _queue_emby_library_notification(payload, "入库")
            return {"ok": True, "state": "queued" if inserted else "aggregated", "channels": []}
        notification_results = send_configured_channels(
            _emby_notification_title(payload),
            _emby_notification_message(payload),
            "media-server",
        )
        return {"ok": True, "state": "notified", "channels": _channel_summary(notification_results)}
    try:
        strm_name = _emby_deleted_strm_name(payload)
    except DeletionWorkflowError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    try:
        intent = request_deletion_for_strm(
            strm_name,
            trigger_source="emby_webhook",
            trigger_ref=_emby_event_id(payload),
        )
        if get_settings().emby_deletion_auto_confirm:
            intent = confirm_deletion(int(intent["id"]))
    except DeletionWorkflowError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _queue_emby_library_notification(payload, "删除")
    return {"ok": True, "intent_id": intent["id"], "state": intent["state"], "channels": []}


def _is_emby_library_event(payload: dict[str, Any]) -> bool:
    event = str(_find_payload_value(payload, {"Event", "event", "NotificationType", "notification_type"}) or "").casefold()
    return "new" in event or "add" in event or "library" in event


def _queue_emby_library_notification(payload: dict[str, Any], action: str) -> bool:
    identity = str(_find_payload_value(payload, {"SeriesId", "series_id", "SeriesName", "series_name", "ParentId", "parent_id", "ParentName", "parent_name"}) or "").strip()
    if not identity:
        raw_path = str(_find_payload_value(payload, {"Path", "path", "ItemPath", "item_path"}) or "").replace("\\", "/").rstrip("/")
        identity = raw_path.rsplit("/", 2)[0] if "/" in raw_path else raw_path
    if not identity:
        identity = str(_find_payload_value(payload, {"ItemName", "item_name", "Name", "name"}) or "媒体")
    group = hashlib.sha256(identity.casefold().encode("utf-8")).hexdigest()[:24]
    return add_notification(
        f"library-ready:emby:{action}:{group}:{date.today().isoformat()}",
        "success" if action == "入库" else "info",
        f"{identity[:120]} 已{action}",
        _emby_notification_message(payload),
        action_page="media-server",
        deliver=False,
    )


async def _read_emby_webhook_payload(request: Request) -> dict[str, Any]:
    content_type = str(request.headers.get("content-type") or "").strip()
    try:
        content_length = int(request.headers.get("content-length") or "0")
    except ValueError:
        content_length = 0
    if content_length > 4 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Emby Webhook 请求过大")
    body = await request.body()
    if len(body) > 4 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Emby Webhook 请求过大")
    if content_type.casefold().startswith("application/json"):
        return _json_payload(body)
    if content_type.casefold().startswith("multipart/form-data"):
        return _multipart_payload(content_type, body)
    if content_type.casefold().startswith("application/x-www-form-urlencoded"):
        fields = {key: values[-1] for key, values in urllib.parse.parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True).items() if values}
        return _payload_from_form_fields(fields)
    raise HTTPException(status_code=415, detail="Emby Webhook 仅支持 multipart/form-data 或 application/json")


def _json_payload(body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Emby Webhook JSON 无效") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Emby Webhook 必须是 JSON 对象")
    return payload


def _multipart_payload(content_type: str, body: bytes) -> dict[str, Any]:
    message = BytesParser(policy=policy.default).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8") + body
    )
    if not message.is_multipart():
        raise HTTPException(status_code=400, detail="Emby Webhook multipart 格式无效")
    fields: dict[str, str] = {}
    for part in message.iter_parts():
        name = str(part.get_param("name", header="content-disposition") or "").strip()
        if not name or part.get_filename():
            continue
        value = part.get_content()
        fields[name] = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
    return _payload_from_form_fields(fields)


def _payload_from_form_fields(fields: dict[str, str]) -> dict[str, Any]:
    for key in ("data", "payload", "json", "event"):
        raw = str(fields.get(key) or "").strip()
        if raw.startswith("{"):
            return _json_payload(raw.encode("utf-8"))
    for raw in fields.values():
        candidate = str(raw or "").strip()
        if candidate.startswith("{"):
            return _json_payload(candidate.encode("utf-8"))
    if fields:
        return dict(fields)
    raise HTTPException(status_code=400, detail="Emby Webhook multipart 中没有事件数据")


def _is_emby_webhook_test(payload: dict[str, Any]) -> bool:
    event = str(_find_payload_value(payload, {"Event", "event", "NotificationType", "notification_type"}) or "").strip().casefold()
    return event == "test" or "webhooktest" in event or "notificationtest" in event or ("test" in event and ("webhook" in event or "notification" in event))


def _is_emby_delete_event(payload: dict[str, Any]) -> bool:
    event = str(_find_payload_value(payload, {"Event", "event", "NotificationType", "notification_type"}) or "").strip().casefold()
    if "delete" in event or "remove" in event:
        return True
    path = str(_find_payload_value(payload, {"relative_path", "Path", "path"}) or "").strip().casefold()
    return not event and path.endswith(".strm")


def _emby_notification_title(payload: dict[str, Any]) -> str:
    event = str(_find_payload_value(payload, {"Event", "event", "NotificationType", "notification_type"}) or "").casefold()
    if "playback" in event and ("start" in event or "begin" in event):
        return "Emby 开始播放"
    if "playback" in event and ("stop" in event or "end" in event):
        return "Emby 停止播放"
    if "delete" in event or "remove" in event:
        return "Emby 媒体删除"
    if "new" in event or "add" in event:
        return "Emby 媒体入库"
    if "auth" in event or "login" in event:
        return "Emby 用户登录"
    return "Emby 事件通知"


def _emby_notification_message(payload: dict[str, Any]) -> str:
    event = str(_find_payload_value(payload, {"Event", "event", "NotificationType", "notification_type"}) or "未知事件").strip()
    item = str(_find_payload_value(payload, {"ItemName", "item_name", "Name", "name"}) or "").strip()
    user = str(_find_payload_value(payload, {"UserName", "user_name"}) or "").strip()
    parts = [f"事件：{event}"]
    if item:
        parts.append(f"媒体：{item[:200]}")
    if user:
        parts.append(f"用户：{user[:100]}")
    return "\n".join(parts)


def _channel_summary(results) -> list[dict[str, Any]]:
    return [{"provider": result.provider, "ok": result.ok, "message": result.message} for result in results]


def _emby_deleted_strm_name(payload: dict[str, Any]) -> str:
    path = _find_payload_value(payload, {"relative_path", "Path", "path", "ItemPath", "item_path", "FilePath", "file_path", "FullPath", "full_path"})
    normalized = str(path or "").strip().replace("\\", "/").rstrip("/")
    if not normalized.casefold().endswith(".strm"):
        raise DeletionWorkflowError("Webhook 中没有可识别的 STRM 文件路径")
    settings = get_settings()
    library_root = str(settings.emby_strm_library_root or settings.strm_output_root or "").strip().replace("\\", "/").rstrip("/")
    is_absolute = normalized.startswith("/") or bool(re.match(r"^[A-Za-z]:/", normalized))
    if is_absolute:
        if not library_root or normalized.casefold() == library_root.casefold() or not normalized.casefold().startswith(f"{library_root.casefold()}/"):
            raise DeletionWorkflowError("Webhook STRM 路径不在已配置的 Emby 媒体库根目录中")
        normalized = normalized[len(library_root) + 1 :]
    return normalized


def _emby_event_id(payload: dict[str, Any]) -> str:
    return str(_find_payload_value(payload, {"event_id", "EventId", "NotificationId"}) or "")[:256]


def _find_payload_value(value: Any, keys: set[str]) -> Any:
    if isinstance(value, dict):
        for key in keys:
            candidate = value.get(key)
            if isinstance(candidate, (str, int)) and str(candidate).strip():
                return candidate
        for child in value.values():
            candidate = _find_payload_value(child, keys)
            if candidate is not None:
                return candidate
    elif isinstance(value, list):
        for child in value[:50]:
            candidate = _find_payload_value(child, keys)
            if candidate is not None:
                return candidate
    return None
