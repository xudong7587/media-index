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
COVER_RESOLUTIONS = {"1080p", "720p", "480p"}
COVER_SOURCE_SORTS = {"Random", "DateCreated", "PremiereDate"}
COVER_IMAGE_SOURCES = {"Primary", "Backdrop"}
COVER_BG_MODES = {"auto", "custom"}
DEFAULT_COVER_OPTIONS: dict[str, Any] = {
    "resolution": "1080p",
    "source_sort": "Random",
    "image_source": "Primary",
    "zh_title": "",
    "en_title": "",
    "zh_font_size": 170,
    "en_font_size": 75,
    "title_scale": 1.0,
    "zh_font_offset": 0,
    "title_spacing": 40,
    "en_line_spacing": 40,
    "blur_size": 50,
    "showcase_blur": True,
    "color_ratio": 0.8,
    "bg_color_mode": "auto",
    "custom_bg_color": "#2f6f57",
}
_FONT_CANDIDATES = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/msyh.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)


def normalise_cover_options(options: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = options if isinstance(options, dict) else {}
    result = dict(DEFAULT_COVER_OPTIONS)
    result.update({key: value for key, value in raw.items() if key in result})
    result["resolution"] = result["resolution"] if result["resolution"] in COVER_RESOLUTIONS else "1080p"
    result["source_sort"] = result["source_sort"] if result["source_sort"] in COVER_SOURCE_SORTS else "Random"
    result["image_source"] = result["image_source"] if result["image_source"] in COVER_IMAGE_SOURCES else "Primary"
    result["bg_color_mode"] = result["bg_color_mode"] if result["bg_color_mode"] in COVER_BG_MODES else "auto"
    result["zh_title"] = str(result["zh_title"] or "").strip()[:28]
    result["en_title"] = str(result["en_title"] or "").strip()[:48]
    result["zh_font_size"] = _bounded_int(result["zh_font_size"], 48, 320, 170)
    result["en_font_size"] = _bounded_int(result["en_font_size"], 24, 180, 75)
    try:
        result["title_scale"] = max(0.5, min(float(result["title_scale"]), 2.0))
    except (TypeError, ValueError):
        result["title_scale"] = 1.0
    result["zh_font_offset"] = _bounded_int(result["zh_font_offset"], -300, 300, 0)
    result["title_spacing"] = _bounded_int(result["title_spacing"], -100, 300, 40)
    result["en_line_spacing"] = _bounded_int(result["en_line_spacing"], -100, 300, 40)
    result["blur_size"] = _bounded_int(result["blur_size"], 0, 150, 50)
    result["showcase_blur"] = bool(result["showcase_blur"])
    try:
        result["color_ratio"] = max(0.0, min(float(result["color_ratio"]), 1.0))
    except (TypeError, ValueError):
        result["color_ratio"] = 0.8
    custom_color = str(result["custom_bg_color"] or "").strip()
    result["custom_bg_color"] = custom_color if re.fullmatch(r"#[0-9A-Fa-f]{6}", custom_color) else "#2f6f57"
    return result


def cover_options_from_settings() -> dict[str, Any]:
    raw = str(getattr(get_settings(), "emby_cover_options_json", "") or "").strip()
    try:
        value = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        value = {}
    return normalise_cover_options(value if isinstance(value, dict) else {})


def normalise_cover_library_options(value: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for library_id, options in list(value.items())[:100]:
        safe_id = str(library_id or "").strip()
        if _EMBY_ITEM_ID.fullmatch(safe_id) and isinstance(options, dict):
            result[safe_id] = normalise_cover_options(options)
    return result


def cover_library_options_from_settings() -> dict[str, dict[str, Any]]:
    raw = str(getattr(get_settings(), "emby_cover_library_options_json", "") or "").strip()
    try:
        value = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        value = {}
    return normalise_cover_library_options(value if isinstance(value, dict) else {})


def cover_library_ids_from_settings() -> list[str]:
    raw = str(getattr(get_settings(), "emby_cover_library_ids_json", "") or "").strip()
    try:
        value = json.loads(raw) if raw else []
    except json.JSONDecodeError:
        value = []
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(
        safe_id for item in value[:100]
        if (safe_id := str(item or "").strip()) and _EMBY_ITEM_ID.fullmatch(safe_id)
    ))


def library_cover_bytes(library_id: str, *, title: str, style: str, options: dict[str, Any] | None = None) -> bytes:
    """Build one static cover at the selected resolution from Emby artwork.

    The source images are read only for the rendering request.  They are held
    in a temporary directory for the upstream renderer and are removed before
    this function returns.
    """
    safe_id = safe_emby_id(library_id)
    safe_style = style if style in COVER_STYLES else "collage"
    selected_options = normalise_cover_options(options)
    images = _library_images(
        safe_id,
        limit=9 if safe_style == "showcase" else 1,
        source_sort=selected_options["source_sort"],
        image_source=selected_options["image_source"],
    )
    if not images:
        raise ValueError("媒体库没有可用于生成封面的海报")
    return _render_static_cover(images, title=title, style=safe_style, options=selected_options)


def _render_static_cover(images: list[Image.Image], *, title: str, style: str, options: dict[str, Any]) -> bytes:
    title_pair = (options["zh_title"] or str(title or "媒体库").strip()[:28] or "媒体库", options["en_title"])
    font_paths = _font_paths()
    resolution = ResolutionConfig(options["resolution"])
    render_options = {
        "font_size": (
            options["zh_font_size"] * options["title_scale"],
            options["en_font_size"] * options["title_scale"],
        ),
        "font_offset": (options["zh_font_offset"], options["title_spacing"], options["en_line_spacing"]),
        "blur_size": options["blur_size"],
        "color_ratio": options["color_ratio"],
        "resolution_config": resolution,
        "bg_color_config": {
            "mode": options["bg_color_mode"],
            "custom_color": options["custom_bg_color"],
            "config_color": None,
        },
    }
    with tempfile.TemporaryDirectory(prefix="mediaindex-cover-") as raw_directory:
        directory = Path(raw_directory)
        for number in range(1, 10):
            image = images[(number - 1) % len(images)]
            image.convert("RGB").save(directory / f"{number}.jpg", format="JPEG", quality=92)

        source = directory / "1.jpg"
        renderer: Callable[..., str | bool]
        if style == "collage":
            renderer = create_style_static_1
            rendered = renderer(str(source), title_pair, font_paths, **render_options)
        elif style == "showcase":
            renderer = create_style_static_3
            rendered = renderer(str(directory), title_pair, font_paths, is_blur=options["showcase_blur"], **render_options)
        elif style == "mosaic":
            renderer = create_style_static_2
            rendered = renderer(str(source), title_pair, font_paths, **render_options)
        else:
            renderer = create_style_static_4
            rendered = renderer(str(source), title_pair, font_paths, **render_options)
    return _normalise_rendered_cover(rendered, expected_size=resolution.size)


def _normalise_rendered_cover(rendered: str | bool, *, expected_size: tuple[int, int]) -> bytes:
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
    if canvas.size != expected_size:
        canvas = canvas.resize(expected_size, Image.Resampling.LANCZOS)
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


def _library_images(library_id: str, *, limit: int, source_sort: str, image_source: str) -> list[Image.Image]:
    sort_by = source_sort if source_sort in COVER_SOURCE_SORTS else "Random"
    payload = _read_json(
        "/Items",
        query={
            "ParentId": library_id,
            "Recursive": "true",
            "IncludeItemTypes": "Movie,Series",
            **({"HasPrimaryImage": "true"} if image_source == "Primary" else {}),
            "SortBy": sort_by,
            "SortOrder": "Descending",
            "Limit": max(12, limit) if image_source == "Backdrop" else max(1, limit),
            "Fields": "ImageTags",
        },
    )
    items = payload.get("Items", []) if isinstance(payload, dict) else []
    item_ids = [str(item["Id"]) for item in items if isinstance(item, dict) and item.get("Id")] if isinstance(items, list) else []
    if image_source == "Primary":
        item_ids = item_ids[:limit]
    if not item_ids:
        return []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(item_ids))) as executor:
        images = [image for image in executor.map(lambda item_id: _read_item_image(item_id, image_source), item_ids) if image is not None]
    return images[:limit]


def _read_item_image(item_id: str, image_source: str = "Primary") -> Image.Image | None:
    try:
        base_url, api_key = _credentials()
        request = urllib.request.Request(
            f"{base_url}/Items/{safe_emby_id(item_id)}/Images/{'Backdrop/0' if image_source == 'Backdrop' else 'Primary'}?maxWidth=960&quality=88",
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


def apply_library_cover(library_id: str, *, title: str, style: str, options: dict[str, Any] | None = None) -> None:
    body = library_cover_bytes(library_id, title=title, style=style, options=options)
    base_url, api_key = _credentials()
    # Emby's item-image endpoint accepts a base64 image body. Sending the raw
    # JPEG can still return a successful HTTP response on some versions while
    # leaving the library image unchanged.
    encoded = base64.b64encode(body)
    request = urllib.request.Request(
        f"{base_url}/Items/{safe_emby_id(library_id)}/Images/Primary",
        data=encoded,
        headers={"X-Emby-Token": api_key, "Content-Type": "image/jpeg"},
        method="POST",
    )
    with open_url(request, timeout=20) as response:
        response.read(1024)


def refresh_all_library_covers(
    style: str | None = None,
    options: dict[str, Any] | None = None,
    *,
    library_options: dict[str, Any] | None = None,
    library_ids: list[str] | None = None,
) -> dict[str, Any]:
    selected_style = style or get_settings().emby_cover_style
    selected_options = normalise_cover_options(options) if options is not None else cover_options_from_settings()
    selected_library_options = (
        normalise_cover_library_options(library_options)
        if library_options is not None
        else cover_library_options_from_settings()
    )
    selected_library_ids = (
        [safe_emby_id(item) for item in dict.fromkeys(library_ids)]
        if library_ids is not None
        else cover_library_ids_from_settings()
    )
    included = set(selected_library_ids)
    folders = _read_json("/Library/VirtualFolders")
    results: list[dict[str, str]] = []
    for folder in folders if isinstance(folders, list) else []:
        if not isinstance(folder, dict):
            continue
        library_id = str(folder.get("ItemId") or "")
        title = str(folder.get("Name") or "媒体库")
        if not library_id:
            continue
        if included and library_id not in included:
            continue
        try:
            apply_library_cover(
                library_id,
                title=title,
                style=selected_style,
                options=selected_library_options.get(library_id, selected_options),
            )
            results.append({"library_id": library_id, "title": title, "status": "updated"})
        except Exception as exc:
            results.append({"library_id": library_id, "title": title, "status": "failed", "error": type(exc).__name__})
    updated = sum(item["status"] == "updated" for item in results)
    return {"updated": updated, "failed": len(results) - updated, "results": results, "style": selected_style}


def _bounded_int(value: Any, minimum: int, maximum: int, fallback: int) -> int:
    try:
        return max(minimum, min(int(value), maximum))
    except (TypeError, ValueError):
        return fallback


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
