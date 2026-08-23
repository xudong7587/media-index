from __future__ import annotations

import base64
import concurrent.futures
import io
import json
import re
import urllib.parse
import urllib.request
from typing import Any

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from app.clients.http import open_url
from app.core.config import get_settings


_EMBY_ITEM_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
COVER_STYLES = {"collage", "showcase", "mosaic", "minimal"}


def library_cover_bytes(library_id: str, *, title: str, style: str) -> bytes:
    safe_id = safe_emby_id(library_id)
    safe_style = style if style in COVER_STYLES else "collage"
    payload = _read_json(
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
    item_ids = [str(item["Id"]) for item in items[:6] if isinstance(item, dict) and item.get("Id")] if isinstance(items, list) else []
    images: list[Image.Image] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(item_ids) or 1)) as executor:
        for image in executor.map(_read_item_image, item_ids):
            if image is not None:
                images.append(image)
    if not images:
        raise ValueError("媒体库没有可用于合成的海报")
    builders = {
        "collage": _collage_cover,
        "showcase": _showcase_cover,
        "mosaic": _mosaic_cover,
        "minimal": _minimal_cover,
    }
    canvas = builders[safe_style](images)
    _draw_label(canvas, title)
    output = io.BytesIO()
    canvas.save(output, format="JPEG", quality=91, optimize=True)
    return output.getvalue()


def apply_library_cover(library_id: str, *, title: str, style: str) -> None:
    body = library_cover_bytes(library_id, title=title, style=style)
    base_url, api_key = _credentials()
    request = urllib.request.Request(
        f"{base_url}/Items/{safe_emby_id(library_id)}/Images/Primary",
        data=base64.b64encode(body),
        headers={"X-Emby-Token": api_key, "Content-Type": "application/octet-stream"},
        method="POST",
    )
    with open_url(request, timeout=20) as response:
        response.read(1024)


def refresh_all_library_covers(style: str | None = None) -> dict[str, Any]:
    selected_style = style or get_settings().emby_cover_style
    folders = _read_json("/Library/VirtualFolders")
    results: list[dict[str, str]] = []
    for folder in folders if isinstance(folders, list) else []:
        if not isinstance(folder, dict):
            continue
        library_id = str(folder.get("ItemId") or "")
        title = str(folder.get("Name") or "媒体库")
        if not library_id:
            continue
        try:
            apply_library_cover(library_id, title=title, style=selected_style)
            results.append({"library_id": library_id, "title": title, "status": "updated"})
        except Exception as exc:
            results.append({"library_id": library_id, "title": title, "status": "failed", "error": type(exc).__name__})
    updated = sum(item["status"] == "updated" for item in results)
    return {"updated": updated, "failed": len(results) - updated, "results": results, "style": selected_style}


def safe_emby_id(value: str) -> str:
    safe_id = str(value or "").strip()
    if not _EMBY_ITEM_ID.fullmatch(safe_id):
        raise ValueError("Emby 媒体库标识无效")
    return safe_id


def _credentials() -> tuple[str, str]:
    settings = get_settings()
    base_url = settings.emby_base_url.strip().rstrip("/")
    api_key = settings.emby_api_key.strip()
    if not base_url or not api_key:
        raise ValueError("请先保存 Emby 地址和 API Key")
    return base_url, api_key


def _read_json(path: str, *, query: dict[str, str | int] | None = None) -> object:
    base_url, api_key = _credentials()
    suffix = f"?{urllib.parse.urlencode(query)}" if query else ""
    request = urllib.request.Request(f"{base_url}{path}{suffix}", headers={"X-Emby-Token": api_key, "Accept": "application/json"}, method="GET")
    with open_url(request, timeout=15) as response:
        return json.loads(response.read(4 * 1024 * 1024).decode("utf-8"))


def _read_item_image(item_id: str) -> Image.Image | None:
    try:
        base_url, api_key = _credentials()
        request = urllib.request.Request(
            f"{base_url}/Items/{safe_emby_id(item_id)}/Images/Primary?maxWidth=720&quality=88",
            headers={"X-Emby-Token": api_key, "Accept": "image/*"},
            method="GET",
        )
        with open_url(request, timeout=15) as response:
            raw = response.read(10 * 1024 * 1024 + 1)
        if len(raw) > 10 * 1024 * 1024:
            return None
        with Image.open(io.BytesIO(raw)) as opened:
            return opened.convert("RGB").copy()
    except Exception:
        return None


def _poster(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    return ImageOps.fit(image, size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.35))


def _collage_cover(images: list[Image.Image]) -> Image.Image:
    canvas = Image.new("RGB", (960, 540), "#111a22")
    for index in range(6):
        tile = ImageEnhance.Color(_poster(images[index % len(images)], (320, 270))).enhance(0.82)
        canvas.paste(tile, ((index % 3) * 320, (index // 3) * 270))
    overlay = Image.new("RGBA", canvas.size, (8, 16, 24, 72))
    overlay.paste((4, 12, 20, 190), (0, 330, 960, 540))
    return Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")


def _showcase_cover(images: list[Image.Image]) -> Image.Image:
    background = _poster(images[0], (960, 540)).filter(ImageFilter.GaussianBlur(22))
    background = ImageEnhance.Brightness(background).enhance(0.48).convert("RGBA")
    for index, angle in enumerate((-8, 0, 8)):
        poster = _poster(images[index % len(images)], (220, 330)).rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)
        x = 355 + index * 145
        background.alpha_composite(poster.convert("RGBA"), (x, 52 + abs(angle) * 2))
    return background.convert("RGB")


def _mosaic_cover(images: list[Image.Image]) -> Image.Image:
    canvas = Image.new("RGB", (960, 540), "#102a30")
    canvas.paste(_poster(images[0], (480, 540)), (0, 0))
    for index in range(4):
        canvas.paste(_poster(images[(index + 1) % len(images)], (240, 270)), (480 + (index % 2) * 240, (index // 2) * 270))
    canvas = ImageEnhance.Color(canvas).enhance(0.88)
    shade = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(shade).rectangle((0, 340, 960, 540), fill=(3, 18, 22, 150))
    return Image.alpha_composite(canvas.convert("RGBA"), shade).convert("RGB")


def _minimal_cover(images: list[Image.Image]) -> Image.Image:
    background = _poster(images[0], (960, 540)).filter(ImageFilter.GaussianBlur(18))
    background = ImageEnhance.Brightness(background).enhance(0.42)
    poster = _poster(images[min(1, len(images) - 1)], (260, 390))
    canvas = background.convert("RGBA")
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((74, 70, 350, 476), radius=20, fill=(0, 0, 0, 135))
    canvas = Image.alpha_composite(canvas, shadow)
    canvas.paste(poster, (82, 76))
    return canvas.convert("RGB")


def _draw_label(canvas: Image.Image, title: str) -> None:
    draw = ImageDraw.Draw(canvas)
    ascii_title = "".join(char for char in str(title or "") if char.isascii() and (char.isalnum() or char in " -_"))
    label = ascii_title.strip().upper()[:28] or "MEDIA LIBRARY"
    font = ImageFont.load_default(size=38)
    draw.rounded_rectangle((386, 372, 910, 476), radius=18, fill=(4, 12, 20, 178), outline=(255, 255, 255, 46), width=1)
    draw.text((420, 402), label, fill=(247, 250, 252), font=font)
