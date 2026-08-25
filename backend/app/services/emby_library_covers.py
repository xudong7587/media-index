"""Emby cover service using the GPL static MediaCoverGenerator renderer.

The actual renderers live in ``app.third_party.mediacovergenerator``.  They
are a retained, static-only adaptation of wio-ki/MoviePilot-Plugins and are
covered by GPL-3.0-only; see ``THIRD_PARTY_NOTICES.md``.
"""

from __future__ import annotations

import base64
import concurrent.futures
import io
import json
import os
import re
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

from PIL import Image

from app.clients.http import open_url
from app.core.config import get_settings
from app.third_party.mediacovergenerator.style.style_static_1 import create_style_static_1
from app.third_party.mediacovergenerator.style.style_static_2 import create_style_static_2
from app.third_party.mediacovergenerator.style.style_static_3 import create_style_static_3
from app.third_party.mediacovergenerator.style.style_static_4 import create_style_static_4
from app.third_party.mediacovergenerator.utils.image_manager import ResolutionConfig


_EMBY_ITEM_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
COVER_STYLES = {"collage", "showcase", "mosaic", "minimal"}
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
    """Build one 1920×1080 static cover from Emby's existing poster artwork.

    The source images are read only for the rendering request.  They are held
    in a temporary directory for the upstream renderer and are removed before
    this function returns.
    """
    safe_id = safe_emby_id(library_id)
    safe_style = style if style in COVER_STYLES else "collage"
    images = _library_images(safe_id, limit=9 if safe_style == "showcase" else 1)
    if not images:
        raise ValueError("媒体库没有可用于生成封面的海报")
    return _render_static_cover(images, title=title, style=safe_style)


def _render_static_cover(images: list[Image.Image], *, title: str, style: str) -> bytes:
    title_pair = (str(title or "媒体库").strip()[:28] or "媒体库", "")
    font_paths = _font_paths()
    with tempfile.TemporaryDirectory(prefix="mediaindex-cover-") as raw_directory:
        directory = Path(raw_directory)
        for number in range(1, 10):
            image = images[(number - 1) % len(images)]
            image.convert("RGB").save(directory / f"{number}.jpg", format="JPEG", quality=92)

        source = directory / "1.jpg"
        renderer: Callable[..., str | bool]
        if style == "collage":
            renderer = create_style_static_1
            rendered = renderer(str(source), title_pair, font_paths, resolution_config=ResolutionConfig("1080p"))
        elif style == "showcase":
            renderer = create_style_static_3
            rendered = renderer(str(directory), title_pair, font_paths, resolution_config=ResolutionConfig("1080p"))
        elif style == "mosaic":
            renderer = create_style_static_2
            rendered = renderer(str(source), title_pair, font_paths, resolution_config=ResolutionConfig("1080p"))
        else:
            renderer = create_style_static_4
            rendered = renderer(str(source), title_pair, font_paths, resolution_config=ResolutionConfig("1080p"))
    return _normalise_rendered_cover(rendered)


def _normalise_rendered_cover(rendered: str | bool) -> bytes:
    if not isinstance(rendered, str) or not rendered:
        raise RuntimeError("静态封面渲染器没有返回图像")
    try:
        raw = base64.b64decode(rendered, validate=True)
    except ValueError as exc:
        raise RuntimeError("静态封面渲染器返回了无效图像") from exc
    if not raw or len(raw) > 20 * 1024 * 1024:
        raise RuntimeError("静态封面渲染器返回的图像大小异常")
    with Image.open(io.BytesIO(raw)) as generated:
        canvas = generated.convert("RGB").copy()
    if canvas.size != (1920, 1080):
        canvas = canvas.resize((1920, 1080), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    canvas.save(output, format="JPEG", quality=92, optimize=True)
    return output.getvalue()


def _font_paths() -> tuple[str, str]:
    available = [path for path in _FONT_CANDIDATES if os.path.exists(path)]
    if not available:
        raise RuntimeError("容器中未找到可用于静态封面的中文字体")
    bold = next((path for path in available if "Bold" in path or "bd" in path.lower()), available[0])
    regular = next((path for path in available if path != bold), bold)
    return bold, regular


def _library_images(library_id: str, *, limit: int) -> list[Image.Image]:
    payload = _read_json(
        "/Items",
        query={
            "ParentId": library_id,
            "Recursive": "true",
            "IncludeItemTypes": "Movie,Series",
            "HasPrimaryImage": "true",
            "SortBy": "DateCreated",
            "SortOrder": "Descending",
            "Limit": max(1, limit),
            "Fields": "ImageTags",
        },
    )
    items = payload.get("Items", []) if isinstance(payload, dict) else []
    item_ids = [str(item["Id"]) for item in items if isinstance(item, dict) and item.get("Id")][:limit] if isinstance(items, list) else []
    if not item_ids:
        return []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(item_ids))) as executor:
        return [image for image in executor.map(_read_item_image, item_ids) if image is not None]


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


def apply_library_cover(library_id: str, *, title: str, style: str) -> None:
    body = library_cover_bytes(library_id, title=title, style=style)
    base_url, api_key = _credentials()
    request = urllib.request.Request(
        f"{base_url}/Items/{safe_emby_id(library_id)}/Images/Primary",
        data=body,
        headers={"X-Emby-Token": api_key, "Content-Type": "image/jpeg"},
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
