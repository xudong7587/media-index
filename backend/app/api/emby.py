from __future__ import annotations

import secrets
import hashlib
from email import policy
from email.parser import BytesParser
import json
from pathlib import Path, PurePosixPath
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.security import require_user
from app.clients.http import open_url
from app.db.database import db
from app.services.deletion_workflow import DeletionWorkflowError, confirm_deletion, deletion_intent_deletes_directory, deletion_webhook_event_handled, log_deletion_webhook_failure, request_deletions_for_strm_path
from app.services.emby_library_covers import apply_library_cover, library_cover_bytes as _library_cover_bytes, list_cover_fonts, normalise_cover_options, refresh_all_library_covers, run_cover_activity, save_cover_font
from app.services.notification_channels import send_configured_channels
from app.services.notifications import add_notification
from app.services.poster_cache import cache_poster_bytes, find_cached_poster


router = APIRouter(prefix="/api/integrations/emby", tags=["emby-integration"])
_EMBY_ITEM_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class EmbyStrmDeletedEvent(BaseModel):
    relative_path: str = Field(min_length=6, max_length=500)
    event_id: str = Field(default="", max_length=256)


class EmbyLibraryCoverRequest(BaseModel):
    title: str = Field(default="", max_length=80)
    style: str = Field(default="collage", pattern="^(collage|showcase|mosaic|minimal)$")
    options: dict[str, Any] = Field(default_factory=dict)
    library_ids: list[str] = Field(default_factory=list, max_length=100)
    library_options: dict[str, dict[str, Any]] = Field(default_factory=dict)


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
                "locations": [str(value) for value in folder.get("Locations", []) if str(value).strip()] if isinstance(folder.get("Locations"), list) else [],
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
        libraries.append({
            "id": folder_id,
            "name": str(folder.get("Name") or "媒体库"),
            "collection_type": str(folder.get("CollectionType") or "mixed"),
            # The library item owns the generated cover. A sample child item
            # would keep showing a movie poster after a successful upload and
            # make the replacement appear to have failed.
            "cover_item_id": folder_id,
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


@router.get("/libraries/covers/fonts", dependencies=[Depends(require_user)])
def emby_cover_fonts():
    return {"fonts": list_cover_fonts()}


@router.post("/libraries/covers/fonts", dependencies=[Depends(require_user)])
async def upload_emby_cover_font(request: Request, filename: str = Query(min_length=1, max_length=180)):
    try:
        content_length = int(request.headers.get("content-length") or "0")
    except ValueError:
        content_length = 0
    if content_length > 12 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="字体文件超过 12MB")
    chunks = bytearray()
    async for chunk in request.stream():
        chunks.extend(chunk)
        if len(chunks) > 12 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="字体文件超过 12MB")
    try:
        font = save_cover_font(filename, bytes(chunks))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "font": font, "message": f"字体 {font['label']} 已上传"}


@router.get("/libraries/{library_id}/cover-preview", dependencies=[Depends(require_user)])
def preview_emby_library_cover(
    library_id: str,
    title: str = Query(default="", max_length=80),
    style: str = Query(default="collage", pattern="^(collage|showcase|mosaic|minimal)$"),
    options: str = Query(default="", max_length=4096),
    sample: str = Query(default="0", max_length=32),
):
    try:
        parsed_options = json.loads(options) if options else {}
        if not isinstance(parsed_options, dict):
            raise ValueError("封面参数格式无效")
        body = _library_cover_bytes(
            library_id,
            title=title,
            style=style,
            options=normalise_cover_options(parsed_options),
            sample_key=sample,
        )
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError, RuntimeError, OSError) as exc:
        raise HTTPException(status_code=502, detail=f"媒体库封面预览生成失败（{type(exc).__name__}）") from exc
    return Response(content=body, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.post("/libraries/{library_id}/cover", dependencies=[Depends(require_user)])
def apply_emby_library_cover(library_id: str, payload: EmbyLibraryCoverRequest):
    try:
        safe_id = _safe_emby_id(library_id)
        run_cover_activity(
            f"{payload.title.strip() or '媒体库'} · 封面生成",
            lambda: apply_library_cover(
                safe_id,
                title=payload.title,
                style=payload.style,
                options=payload.options,
            ),
        )
    except urllib.error.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Emby 封面写入失败（HTTP {exc.code}）") from exc
    except (urllib.error.URLError, TimeoutError, ValueError, RuntimeError, OSError) as exc:
        raise HTTPException(status_code=502, detail=f"Emby 封面写入失败（{type(exc).__name__}）") from exc
    return {"ok": True, "message": "媒体库封面已生成并写入 Emby"}


@router.post("/libraries/covers/refresh", dependencies=[Depends(require_user)])
def refresh_emby_library_covers(payload: EmbyLibraryCoverRequest):
    try:
        result = run_cover_activity(
            "批量生成媒体库封面",
            lambda: refresh_all_library_covers(
                payload.style,
                payload.options,
                library_options=payload.library_options,
                library_ids=payload.library_ids,
            ),
        )
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError, RuntimeError, OSError) as exc:
        raise HTTPException(status_code=502, detail=f"媒体库封面批量生成失败（{type(exc).__name__}）") from exc
    return {"ok": result["failed"] == 0, "message": f"已更新 {result['updated']} 个媒体库，失败 {result['failed']} 个", **result}


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
    # The cover workshop can replace this image in-place. Revalidation avoids
    # serving an old library cover after a successful upload.
    return Response(content=body, media_type=content_type, headers={"Cache-Control": "private, no-cache, must-revalidate"})


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
        if _is_emby_playback_event(payload):
            event_id = _emby_event_id(payload) or hashlib.sha256(
                json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()[:32]
            add_notification(
                f"emby-playback:{event_id}",
                "info",
                _emby_notification_title(payload),
                _emby_notification_message(payload),
                "media-server",
                poster_key=_cache_emby_notification_poster(payload),
            )
            return {"ok": True, "state": "notified", "channels": []}
        notification_results = send_configured_channels(
            _emby_notification_title(payload),
            _emby_notification_message(payload),
            "media-server",
        )
        return {"ok": True, "state": "notified", "channels": _channel_summary(notification_results)}
    event_ref = _emby_event_ref(payload)
    if deletion_webhook_event_handled(event_ref):
        return {
            "ok": True,
            "state": "duplicate",
            "message": "重复的 Emby 删除事件已忽略，不会再次尝试网盘删除",
            "channels": [],
        }
    try:
        strm_path = _emby_deleted_strm_name(payload)
    except DeletionWorkflowError as exc:
        log_deletion_webhook_failure(str(exc), trigger_ref=event_ref)
        return {"ok": False, "state": "rejected", "message": str(exc), "channels": []}
    try:
        display_identity, deletion_group = _emby_library_group(payload)
        intents = request_deletions_for_strm_path(
            strm_path,
            trigger_source="emby_webhook",
            trigger_ref=event_ref,
            log_group=deletion_group,
            log_label=display_identity,
            delete_directory=_emby_deletes_directory(payload, strm_path),
        )
        if get_settings().emby_deletion_auto_confirm:
            intents = [confirm_deletion(int(intent["id"])) for intent in intents]
    except DeletionWorkflowError as exc:
        message = f"{exc}；Webhook 路径：{strm_path}"
        log_deletion_webhook_failure(message, trigger_ref=event_ref)
        return {"ok": False, "state": "rejected", "message": message, "channels": []}
    if intents and all(intent["state"] == "completed" for intent in intents):
        _queue_emby_library_notification(
            payload,
            "删除",
            relative_strm_path=strm_path,
            deleted_directory=any(deletion_intent_deletes_directory(intent) for intent in intents),
        )
    return {
        "ok": True,
        "intent_id": intents[0]["id"] if len(intents) == 1 else None,
        "intent_ids": [intent["id"] for intent in intents],
        "count": len(intents),
        "state": intents[0]["state"] if len({intent["state"] for intent in intents}) == 1 else "partial",
        "channels": [],
    }


def _is_emby_library_event(payload: dict[str, Any]) -> bool:
    event = str(_find_payload_value(payload, {"Event", "event", "NotificationType", "notification_type"}) or "").casefold()
    return "new" in event or "add" in event or "library" in event


def _queue_emby_library_notification(
    payload: dict[str, Any],
    action: str,
    *,
    relative_strm_path: str = "",
    deleted_directory: bool = False,
) -> bool:
    display_identity, group = _emby_library_group(payload)
    item_id = _emby_notification_item_id(payload)
    poster_key = (
        _cache_emby_notification_poster(payload)
        or _cached_emby_group_poster(group)
        or _cache_strm_sidecar_poster(relative_strm_path)
    )
    action_suffix = "删除同步完成" if action == "删除" else f"已{action}"
    title = f"{display_identity[:120]} {action_suffix}"
    message = (
        (
            "该媒体对应的 115 媒体目录已按 Emby 删除范围移入回收站，目录内附属文件和 STRM 映射已同步移除。"
            if deleted_directory
            else "该媒体目录的源文件已按精确 ID 移入 115 回收站，STRM 映射已标记移除。"
        )
        if action == "删除"
        else _emby_notification_message(payload)
    )
    return add_notification(
        f"library-ready:emby:{action}:{group}:{date.today().isoformat()}",
        "success" if action == "入库" else "info",
        title,
        message,
        action_page="media-server",
        poster_url=f"emby-item:{item_id}" if item_id and not poster_key else "",
        poster_key=poster_key,
        deliver=action == "入库" and not _should_defer_emby_library_notification(display_identity),
    )


def _should_defer_emby_library_notification(display_identity: str) -> bool:
    """Keep aggregation only for a recent, known contiguous multi-episode batch."""
    identity = _media_identity_key(display_identity)
    if not identity:
        return False
    with db() as conn:
        rows = conn.execute(
            """
            SELECT j.display_title,j.rename_pairs_json FROM transfer_jobs j
            JOIN transfer_batch_jobs bj ON bj.job_id=j.id
            WHERE j.media_type='tv' AND COALESCE(j.share_url,'')<>''
              AND j.status IN ('running','done','triggered')
              AND datetime(COALESCE(j.finished_at,j.created_at)) >= datetime('now','-15 minutes')
            ORDER BY j.id DESC LIMIT 20
            """
        ).fetchall()
    for row in rows:
        job_identity = _media_identity_key(str(row["display_title"] or ""))
        if not job_identity or (identity not in job_identity and job_identity not in identity):
            continue
        try:
            pairs = json.loads(str(row["rename_pairs_json"] or "[]"))
        except json.JSONDecodeError:
            continue
        episodes: set[int] = set()
        for pair in pairs if isinstance(pairs, list) else ():
            if not isinstance(pair, dict):
                continue
            values = pair.get("episode_numbers") or ()
            if pair.get("episode_number") is not None:
                values = (*values, pair.get("episode_number"))
            cycle = pair.get("_tracking_cycle") if isinstance(pair.get("_tracking_cycle"), dict) else {}
            values = (*values, *(cycle.get("requested") or ()))
            for value in values:
                try:
                    number = int(value)
                except (TypeError, ValueError):
                    continue
                if number > 0:
                    episodes.add(number)
        ordered = sorted(episodes)
        if len(ordered) >= 2 and all(current == previous + 1 for previous, current in zip(ordered, ordered[1:])):
            return True
    return False


def _media_identity_key(value: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").casefold())


def _emby_library_group(payload: dict[str, Any]) -> tuple[str, str]:
    display_identity = str(
        _find_payload_value(payload, {"SeriesName", "series_name"})
        or _find_payload_value(payload, {"ParentName", "parent_name"})
        or _find_payload_value(payload, {"ItemName", "item_name", "Name", "name"})
        or "媒体"
    ).strip()
    group_identity = str(
        _find_payload_value(payload, {"SeriesId", "series_id"})
        or _find_payload_value(payload, {"ParentId", "parent_id"})
        or ""
    ).strip()
    if not group_identity:
        raw_path = str(_find_payload_value(payload, {"Path", "path", "ItemPath", "item_path"}) or "").replace("\\", "/").rstrip("/")
        group_identity = raw_path.rsplit("/", 2)[0] if "/" in raw_path else raw_path
    group_identity = group_identity or display_identity
    group = hashlib.sha256(group_identity.casefold().encode("utf-8")).hexdigest()[:24]
    return display_identity, group


def _cached_emby_group_poster(group: str) -> str:
    with db() as conn:
        row = conn.execute(
            """SELECT poster_key FROM notifications
               WHERE source_key LIKE ? AND poster_key<>''
               ORDER BY id DESC LIMIT 1""",
            (f"library-ready:emby:%:{group}:%",),
        ).fetchone()
    key = str(row["poster_key"] or "") if row else ""
    return key if key and find_cached_poster(key) else ""


def _cache_strm_sidecar_poster(relative_path: str) -> str:
    """Use a local STRM sidecar only when Emby can no longer serve a deleted item."""
    raw = str(relative_path or "").strip().replace("\\", "/").strip("/")
    root_value = get_settings().strm_output_root.strip()
    if not raw or not root_value:
        return ""
    relative = PurePosixPath(raw)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        return ""
    root = Path(root_value).resolve()
    target = root.joinpath(*relative.parts).resolve()
    directory = target.parent if target.suffix.casefold() == ".strm" else target
    try:
        directory.relative_to(root)
    except ValueError:
        return ""
    if not directory.is_dir():
        return ""
    preferred = ("backdrop.jpg", "fanart.jpg", "folder.jpg", "poster.jpg", "backdrop.png", "poster.png")
    candidates = [directory / name for name in preferred]
    try:
        candidates.extend(
            path for path in sorted(directory.iterdir(), key=lambda item: item.name.casefold())
            if path.suffix.casefold() in {".jpg", ".jpeg", ".png"} and path not in candidates
        )
    except OSError:
        return ""
    for candidate in candidates:
        try:
            if not candidate.is_file() or candidate.stat().st_size > 8 * 1024 * 1024:
                continue
            key = cache_poster_bytes(f"strm-sidecar:{relative}:{candidate.name}", candidate.read_bytes())
            if key:
                return key
        except OSError:
            continue
    return ""


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


def _is_emby_playback_event(payload: dict[str, Any]) -> bool:
    event = str(_find_payload_value(payload, {"Event", "event", "NotificationType", "notification_type"}) or "").strip().casefold()
    return "playback" in event or "playbackstart" in event or "playbackstop" in event


def _emby_notification_title(payload: dict[str, Any]) -> str:
    event = str(_find_payload_value(payload, {"Event", "event", "NotificationType", "notification_type"}) or "").casefold()
    if "playback" in event and ("start" in event or "begin" in event):
        return f"开始播放 · {_emby_media_label(payload)}"
    if "playback" in event and ("stop" in event or "end" in event):
        return f"停止播放 · {_emby_media_label(payload)}"
    if "delete" in event or "remove" in event:
        return "Emby 媒体删除"
    if "new" in event or "add" in event:
        return "Emby 媒体入库"
    if "auth" in event or "login" in event:
        return "Emby 用户登录"
    return "Emby 事件通知"


def _emby_notification_message(payload: dict[str, Any]) -> str:
    item = _emby_media_label(payload)
    user = str(_find_payload_value(payload, {"UserName", "user_name"}) or "").strip()
    device = str(_find_payload_value(payload, {"DeviceName", "device_name", "Client", "client"}) or "").strip()
    address = str(_find_payload_value(payload, {"RemoteEndPoint", "remote_endpoint", "IpAddress", "ip_address"}) or "").strip()
    overview = str(_find_payload_value(payload, {"Overview", "overview", "Description", "description"}) or "").strip()
    position = _find_payload_value(payload, {"PlaybackPositionTicks", "PositionTicks", "position_ticks"})
    runtime = _find_payload_value(payload, {"RunTimeTicks", "RuntimeTicks", "runtime_ticks"})
    parts: list[str] = []
    if item:
        parts.append(f"媒体：{item[:200]}")
    if user:
        parts.append(f"用户：{user[:100]}")
    if device:
        parts.append(f"设备：{device[:160]}")
    if address:
        parts.append(f"地址：{address[:160]}")
    progress = _playback_progress(position, runtime)
    if progress:
        parts.append(f"进度：{progress}")
    if overview:
        parts.append(f"简介：{overview[:260]}{'…' if len(overview) > 260 else ''}")
    return "\n".join(parts)


def _emby_media_label(payload: dict[str, Any]) -> str:
    series = str(_find_payload_value(payload, {"SeriesName", "series_name"}) or "").strip()
    name = str(_find_payload_value(payload, {"ItemName", "item_name", "Name", "name"}) or "媒体").strip()
    season = _find_payload_value(payload, {"ParentIndexNumber", "SeasonNumber", "season_number"})
    episode = _find_payload_value(payload, {"IndexNumber", "EpisodeNumber", "episode_number"})
    marker = ""
    try:
        if season is not None and episode is not None:
            marker = f" S{int(season)}E{int(episode)}"
    except (TypeError, ValueError):
        marker = ""
    if series:
        return f"{series}{marker} {name}".strip()
    return name or "媒体"


def _playback_progress(position: Any, runtime: Any) -> str:
    try:
        total = int(runtime or 0)
        current = max(0, int(position or 0))
    except (TypeError, ValueError):
        return ""
    if total <= 0:
        return ""
    return f"{min(100, current * 100 / total):.1f}%"


def _cache_emby_notification_poster(payload: dict[str, Any]) -> str:
    item_id = _emby_notification_item_id(payload)
    if not _EMBY_ITEM_ID.fullmatch(item_id):
        return ""
    for image_path, image_kind in (
        (f"/Items/{item_id}/Images/Backdrop/0", "backdrop"),
        (f"/Items/{item_id}/Images/Primary", "primary"),
    ):
        try:
            body = _read_emby_bytes(image_path, query={"maxWidth": 1200, "quality": 88}, limit=8 * 1024 * 1024)
        except (HTTPException, urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError, OSError):
            continue
        key = cache_poster_bytes(f"emby:{item_id}:{image_kind}", body)
        if key:
            return key
    return ""


def _emby_notification_item_id(payload: dict[str, Any]) -> str:
    item = payload.get("Item") if isinstance(payload.get("Item"), dict) else payload.get("item")
    item_id = str(item.get("Id") or item.get("id") or "").strip() if isinstance(item, dict) else ""
    return item_id or str(_find_payload_value(payload, {"ItemId", "item_id"}) or "").strip()


def _channel_summary(results) -> list[dict[str, Any]]:
    return [{"provider": result.provider, "ok": result.ok, "message": result.message} for result in results]


def _emby_deleted_strm_name(payload: dict[str, Any]) -> str:
    path = _find_payload_value(payload, {"relative_path", "Path", "path", "ItemPath", "item_path", "FilePath", "file_path", "FullPath", "full_path"})
    normalized = urllib.parse.unquote(str(path or "").strip()).replace("\\", "/").rstrip("/")
    if not normalized:
        raise DeletionWorkflowError("Webhook 中没有可识别的 STRM 文件或目录路径")
    settings = get_settings()
    # Prefer the explicitly configured common STRM root.  Emby virtual-folder
    # locations usually point one level deeper (for example
    # /strm/02系列电影).  Stripping that longer location would lose the
    # leading directory stored in strm_entries and break an otherwise exact
    # mapping.
    configured_roots = [settings.emby_strm_library_root, settings.strm_output_root]
    explicit_roots = sorted(
        {str(root or "").strip().replace("\\", "/").rstrip("/") for root in configured_roots if str(root or "").strip()},
        key=len,
        reverse=True,
    )
    discovered_roots: list[str] = []
    try:
        folders = _read_emby_json("/Library/VirtualFolders")
        if isinstance(folders, list):
            discovered_roots.extend(
                location
                for folder in folders if isinstance(folder, dict) and isinstance(folder.get("Locations"), list)
                for location in folder["Locations"]
            )
    except (HTTPException, urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
        pass
    discovered_roots = sorted(
        {str(root or "").strip().replace("\\", "/").rstrip("/") for root in discovered_roots if str(root or "").strip()},
        key=len,
        reverse=True,
    )
    is_absolute = normalized.startswith("/") or bool(re.match(r"^[A-Za-z]:/", normalized))
    if is_absolute:
        library_root = next((root for root in explicit_roots if normalized.casefold().startswith(f"{root.casefold()}/")), "")
        if not library_root:
            library_root = next((root for root in discovered_roots if normalized.casefold().startswith(f"{root.casefold()}/")), "")
        if not library_root:
            raise DeletionWorkflowError("Webhook STRM 路径不在已配置的 Emby 媒体库根目录中")
        normalized = normalized[len(library_root) + 1 :]
    elif not normalized.casefold().endswith(".strm"):
        raise DeletionWorkflowError("目录删除必须包含 Emby 媒体库中的绝对路径")
    return normalized


def _emby_deletes_directory(payload: dict[str, Any], relative_strm_path: str) -> bool:
    """Mirror Emby's deletion unit without inferring from 115 folder contents."""
    if not str(relative_strm_path or "").casefold().endswith(".strm"):
        return True
    item = payload.get("Item") if isinstance(payload.get("Item"), dict) else payload.get("item")
    item = item if isinstance(item, dict) else {}
    if item.get("IsFolder") is True or item.get("is_folder") is True:
        return True
    item_type = str(
        item.get("Type")
        or item.get("type")
        or payload.get("ItemType")
        or payload.get("item_type")
        or ""
    ).strip().casefold()
    # A Movie item represents the movie's media directory in Emby. Episodes
    # and unknown item types remain file-scoped so a single bad episode can be
    # removed without affecting its season or series directory.
    return item_type in {"movie", "series", "season", "boxset", "collectionfolder", "folder"}


def _emby_event_id(payload: dict[str, Any]) -> str:
    return str(_find_payload_value(payload, {"event_id", "EventId", "NotificationId"}) or "")[:256]


def _emby_event_ref(payload: dict[str, Any]) -> str:
    event_id = _emby_event_id(payload)
    if event_id:
        return event_id
    if _is_emby_delete_event(payload):
        # Exclude delivery timestamps so repeated copies of the same Emby
        # deletion remain idempotent even when no NotificationId is supplied.
        event = str(_find_payload_value(payload, {"Event", "event", "NotificationType", "notification_type"}) or "").casefold()
        item_id = _emby_notification_item_id(payload)
        path = str(_find_payload_value(payload, {"relative_path", "Path", "path", "ItemPath", "item_path", "FilePath", "file_path", "FullPath", "full_path"}) or "").strip().replace("\\", "/")
        identity = json.dumps([event, item_id, path], ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:32]


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
