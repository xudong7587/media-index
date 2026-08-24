from __future__ import annotations

import base64
import concurrent.futures
import io
import json
import os
import re
import urllib.parse
import urllib.request
from typing import Any

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from app.clients.http import open_url
from app.core.config import get_settings


_EMBY_ITEM_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
# These identifiers are persisted in the user's configuration, so keep them
# stable while the rendered layout behind each one follows the four static
# MediaCoverGenerator-style templates.
COVER_STYLES = {"collage", "showcase", "mosaic", "minimal"}
_CANVAS_SIZE = (1920, 1080)
_FONT_CANDIDATES = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/msyh.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)


def library_cover_bytes(library_id: str, *, title: str, style: str) -> bytes:
    safe_id = safe_emby_id(library_id)
    safe_style = style if style in COVER_STYLES else "collage"
    builders = {
        "collage": _collage_cover,
        "showcase": _showcase_cover,
        "mosaic": _mosaic_cover,
        "minimal": _minimal_cover,
    }

    # The typography-only template does not need Emby item artwork.  Keeping it
    # independent makes it usable for an empty library too, and avoids an
    # otherwise unnecessary image read during preview or scheduled refreshes.
    if safe_style == "minimal":
        canvas = builders[safe_style]([], title)
        return _encode_cover(canvas)

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
    canvas = builders[safe_style](images, title)
    return _encode_cover(canvas)


def _encode_cover(canvas: Image.Image) -> bytes:
    output = io.BytesIO()
    canvas.save(output, format="JPEG", quality=92, optimize=True)
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


def _font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    preferred = _FONT_CANDIDATES[:1] if bold else _FONT_CANDIDATES[1:]
    for path in (*preferred, *_FONT_CANDIDATES):
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size=size, index=0)
            except OSError:
                continue
    return ImageFont.load_default(size=size)


def _cover_background(images: list[Image.Image], *, color: tuple[int, int, int], darkness: float = 0.48) -> Image.Image:
    background = _poster(images[0], _CANVAS_SIZE).filter(ImageFilter.GaussianBlur(24))
    background = ImageEnhance.Color(background).enhance(0.58)
    background = ImageEnhance.Brightness(background).enhance(darkness).convert("RGBA")
    tint = Image.new("RGBA", _CANVAS_SIZE, (*color, 184))
    return Image.alpha_composite(background, tint)


def _rounded_card(image: Image.Image, size: tuple[int, int], *, radius: int = 34, angle: float = 0) -> Image.Image:
    card = _poster(image, size).convert("RGBA")
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    card.putalpha(mask)
    if angle:
        card = card.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
    return card


def _place_card(canvas: Image.Image, image: Image.Image, position: tuple[int, int], size: tuple[int, int], *, angle: float = 0, radius: int = 34, shadow: int = 22) -> None:
    card = _rounded_card(image, size, radius=radius, angle=angle)
    x, y = position
    shadow_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shadow_mask = card.getchannel("A").filter(ImageFilter.GaussianBlur(shadow))
    shadow_layer.paste((2, 8, 22, 112), (x + 14, y + 18), shadow_mask)
    canvas.alpha_composite(shadow_layer)
    canvas.alpha_composite(card, (x, y))


def _draw_title(canvas: Image.Image, title: str, *, color: tuple[int, int, int] = (255, 255, 255), x: int = 150, y: int = 400, centered: bool = False) -> None:
    draw = ImageDraw.Draw(canvas)
    safe_title = str(title or "").strip()[:28] or "媒体库"
    title_font = _font(112, bold=True)
    subtitle_font = _font(30)
    if centered:
        box = draw.textbbox((0, 0), safe_title, font=title_font)
        x = max(80, (_CANVAS_SIZE[0] - (box[2] - box[0])) // 2)
    draw.text((x, y), safe_title, fill=color, font=title_font, stroke_width=1, stroke_fill=(0, 0, 0, 45))
    subtitle = "MEDIA LIBRARY"
    if centered:
        box = draw.textbbox((0, 0), subtitle, font=subtitle_font)
        x = max(80, (_CANVAS_SIZE[0] - (box[2] - box[0])) // 2)
    draw.text((x + 4, y + 140), subtitle, fill=(*color, 205), font=subtitle_font)


def _collage_cover(images: list[Image.Image], title: str) -> Image.Image:
    """Style 1: rounded-rectangle posters layered like the MP static cover."""
    canvas = _cover_background(images, color=(80, 24, 100), darkness=0.42)
    overlay = Image.new("RGBA", _CANVAS_SIZE, (49, 19, 72, 120))
    canvas = Image.alpha_composite(canvas, overlay)
    _draw_title(canvas, title, x=148, y=404)
    for index, (x, y, angle) in enumerate(((1222, 173, -18), (1370, 122, -8), (1514, 205, 9))):
        _place_card(canvas, images[(index + 1) % len(images)], (x, y), (250, 368), angle=angle, radius=30, shadow=18)
    _place_card(canvas, images[0], (1274, 204), (390, 574), angle=6, radius=40, shadow=25)
    return canvas.convert("RGB")


def _showcase_cover(images: list[Image.Image], title: str) -> Image.Image:
    """Style 2: a directional, tilted multi-poster composition."""
    canvas = _cover_background(images, color=(50, 27, 91), darkness=0.46)
    for index, (x, y, angle) in enumerate(((1015, 150, -20), (1160, 110, -11), (1326, 158, -2), (1480, 112, 8), (1624, 184, 17))):
        _place_card(canvas, images[index % len(images)], (x, y), (248, 366), angle=angle, radius=28, shadow=20)
    _draw_title(canvas, title, x=142, y=412)
    return canvas.convert("RGB")


def _mosaic_cover(images: list[Image.Image], title: str) -> Image.Image:
    """Style 3: one large poster diagonally placed on a cool blue background."""
    canvas = _cover_background(images, color=(13, 105, 136), darkness=0.50)
    glow = Image.new("RGBA", _CANVAS_SIZE, (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((1130, -130, 2210, 1070), fill=(48, 211, 232, 54))
    canvas = Image.alpha_composite(canvas, glow)
    _place_card(canvas, images[0], (1270, 94), (426, 628), angle=17, radius=42, shadow=26)
    _draw_title(canvas, title, x=142, y=396)
    return canvas.convert("RGB")


def _minimal_cover(images: list[Image.Image], title: str) -> Image.Image:
    """Style 4: typography-only library cover, intentionally no poster artwork."""
    canvas = Image.new("RGBA", _CANVAS_SIZE, (9, 103, 111, 255))
    color_layer = Image.new("RGBA", _CANVAS_SIZE, (0, 0, 0, 0))
    draw = ImageDraw.Draw(color_layer)
    draw.ellipse((-430, -500, 1160, 1150), fill=(44, 176, 177, 155))
    draw.ellipse((950, 220, 2500, 1420), fill=(2, 54, 73, 154))
    canvas = Image.alpha_composite(canvas, color_layer.filter(ImageFilter.GaussianBlur(58)))
    _draw_title(canvas, title, y=400, centered=True)
    return canvas.convert("RGB")
