from __future__ import annotations

import secrets
import base64
import concurrent.futures
import io
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.security import require_user
from app.clients.http import open_url
from app.services.deletion_workflow import DeletionWorkflowError, confirm_deletion, request_deletion_for_strm


router = APIRouter(prefix="/api/integrations/emby", tags=["emby-integration"])
_EMBY_ITEM_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class EmbyStrmDeletedEvent(BaseModel):
    relative_path: str = Field(min_length=6, max_length=500)
    event_id: str = Field(default="", max_length=256)


class EmbyLibraryCoverRequest(BaseModel):
    title: str = Field(default="", max_length=80)
    style: str = Field(default="collage", pattern="^(collage|minimal)$")


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
    style: str = Query(default="collage", pattern="^(collage|minimal)$"),
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
    canvas = _minimal_library_cover(images) if style == "minimal" else _collage_library_cover(images)
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
def emby_strm_deleted(payload: EmbyStrmDeletedEvent, x_mediaindex_webhook: str = Header(default="")):
    expected = get_settings().emby_deletion_webhook_token.strip()
    if not expected or not secrets.compare_digest(expected, x_mediaindex_webhook.strip()):
        raise HTTPException(status_code=401, detail="Invalid webhook credential")
    try:
        intent = request_deletion_for_strm(
            payload.relative_path,
            trigger_source="emby_webhook",
            trigger_ref=payload.event_id,
        )
        if get_settings().emby_deletion_auto_confirm:
            intent = confirm_deletion(int(intent["id"]))
    except DeletionWorkflowError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True, "intent_id": intent["id"], "state": intent["state"]}
