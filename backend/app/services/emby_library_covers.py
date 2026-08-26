"""Emby cover service using the GPL static MediaCoverGenerator renderer.

The actual renderers live in ``app.third_party.mediacovergenerator``.  They
are a retained, static-only adaptation of wio-ki/MoviePilot-Plugins and are
covered by GPL-3.0-only; see ``THIRD_PARTY_NOTICES.md``.
"""

from __future__ import annotations

import base64
import concurrent.futures
import hashlib
import io
import json
import logging
import os
import re
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageFont

from app.clients.http import open_url
from app.core.config import get_settings
from app.db.database import db
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
_FONT_ID = re.compile(r"^(?:default|builtin:[0-9a-f]{12}|uploaded:[0-9a-f]{32})$")
_FONT_EXTENSIONS = {".ttf", ".otf", ".ttc"}
_MAX_FONT_BYTES = 12 * 1024 * 1024
_PREVIEW_SOURCE_TTL_SECONDS = 120
_POSTER_CACHE_TTL_SECONDS = 300
_POSTER_CACHE_LIMIT = 96
_cache_lock = threading.RLock()
_preview_source_cache: dict[tuple[str, int, str, str, str], tuple[float, tuple[str, ...]]] = {}
_poster_cache: OrderedDict[tuple[str, str], tuple[float, bytes]] = OrderedDict()
logger = logging.getLogger(__name__)
DEFAULT_COVER_OPTIONS: dict[str, Any] = {
    "resolution": "1080p",
    "source_sort": "Random",
    "image_source": "Primary",
    "zh_title": "",
    "en_title": "",
    "zh_font_id": "default",
    "en_font_id": "default",
    "zh_font_size": 170,
    "en_font_size": 75,
    "title_scale": 1.0,
    "title_x_offset": 0,
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


def run_cover_activity(display_title: str, operation: Callable[[], Any]) -> Any:
    """Run a user-triggered cover write and mirror its state to Activity.

    The activity row is deliberately best-effort: a logging failure must not
    turn an otherwise valid Emby cover update into a failed write.
    """
    title = re.sub(r"[\x00-\x1f\x7f]", "", str(display_title or "")).strip()[:120] or "Emby 媒体库封面"
    job_id = _start_cover_activity(title)
    try:
        result = operation()
    except Exception as exc:
        _finish_cover_activity(
            job_id,
            status="failed",
            stage="cover_failed",
            message=f"封面生成或写入失败（{type(exc).__name__}）",
        )
        raise
    status, stage, message = _cover_activity_outcome(result)
    _finish_cover_activity(job_id, status=status, stage=stage, message=message)
    return result


def _start_cover_activity(display_title: str) -> int | None:
    try:
        with db() as conn:
            cursor = conn.execute(
                """INSERT INTO transfer_jobs(media_type,display_title,target,provider,status,stage,message,request_source)
                   VALUES('emby_cover',?,'local','emby','running','cover_rendering','正在生成并写入 Emby','web')""",
                (display_title,),
            )
            return int(cursor.lastrowid)
    except Exception as exc:
        logger.warning("Unable to create Emby cover activity row: %s", type(exc).__name__)
        return None


def _finish_cover_activity(job_id: int | None, *, status: str, stage: str, message: str) -> None:
    if job_id is None:
        return
    try:
        with db() as conn:
            conn.execute(
                "UPDATE transfer_jobs SET status=?,stage=?,message=?,finished_at=CURRENT_TIMESTAMP WHERE id=?",
                (status, stage, message, job_id),
            )
    except Exception as exc:
        logger.warning("Unable to finish Emby cover activity row: %s", type(exc).__name__)


def _cover_activity_outcome(result: Any) -> tuple[str, str, str]:
    if isinstance(result, dict) and "updated" in result and "failed" in result:
        try:
            updated = max(0, int(result.get("updated") or 0))
            failed = max(0, int(result.get("failed") or 0))
        except (TypeError, ValueError):
            updated, failed = 0, 1
        message = f"封面生成完成：已更新 {updated} 个媒体库，失败 {failed} 个"
        return ("failed", "cover_failed", message) if failed else ("done", "cover_completed", message)
    return "done", "cover_completed", "媒体库封面已生成并写入 Emby"


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
    for key in ("zh_font_id", "en_font_id"):
        font_id = str(result[key] or "default").strip()
        result[key] = font_id if _FONT_ID.fullmatch(font_id) else "default"
    result["zh_font_size"] = _bounded_int(result["zh_font_size"], 48, 320, 170)
    result["en_font_size"] = _bounded_int(result["en_font_size"], 24, 180, 75)
    try:
        result["title_scale"] = max(0.5, min(float(result["title_scale"]), 2.0))
    except (TypeError, ValueError):
        result["title_scale"] = 1.0
    result["title_x_offset"] = _bounded_int(result["title_x_offset"], -500, 500, 0)
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


def library_cover_bytes(
    library_id: str,
    *,
    title: str,
    style: str,
    options: dict[str, Any] | None = None,
    sample_key: str = "",
) -> bytes:
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
        sample_key=sample_key,
    )
    if not images:
        raise ValueError("媒体库没有可用于生成封面的海报")
    return _render_static_cover(images, title=title, style=safe_style, options=selected_options)


def _render_static_cover(images: list[Image.Image], *, title: str, style: str, options: dict[str, Any]) -> bytes:
    title_pair = (options["zh_title"] or str(title or "媒体库").strip()[:28] or "媒体库", options["en_title"])
    font_paths = _font_paths(options)
    resolution = ResolutionConfig(options["resolution"])
    render_options = {
        "font_size": (
            options["zh_font_size"] * options["title_scale"],
            options["en_font_size"] * options["title_scale"],
        ),
        "font_offset": (options["zh_font_offset"], options["title_spacing"], options["en_line_spacing"]),
        "title_x_offset": options["title_x_offset"],
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
        source_count = 9 if style == "showcase" else 1

        def save_source(number: int) -> None:
            image = images[(number - 1) % len(images)]
            image.convert("RGB").save(directory / f"{number}.jpg", format="JPEG", quality=92)

        if source_count == 1:
            save_source(1)
        else:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=min(max(2, os.cpu_count() or 2), 8, source_count)
            ) as executor:
                list(executor.map(save_source, range(1, source_count + 1)))

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


def list_cover_fonts() -> list[dict[str, str]]:
    fonts: list[dict[str, str]] = [{"id": "default", "label": "MediaIndex 默认", "source": "system"}]
    seen: set[str] = set()
    for path in _available_system_fonts():
        resolved = str(Path(path).resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        fonts.append({
            "id": _builtin_font_id(path),
            "label": _font_label(path),
            "source": "system",
        })
    root = _font_root()
    if root.is_dir():
        for path in sorted(root.iterdir(), key=lambda item: item.name.casefold()):
            if path.is_file() and path.suffix.casefold() in _FONT_EXTENSIONS and re.fullmatch(r"[0-9a-f]{32}", path.stem):
                fonts.append({
                    "id": f"uploaded:{path.stem}",
                    "label": _font_label(path),
                    "source": "uploaded",
                })
    return fonts


def save_cover_font(filename: str, body: bytes) -> dict[str, str]:
    supplied_suffix = Path(str(filename or "").strip()).suffix.casefold()
    if supplied_suffix not in _FONT_EXTENSIONS:
        raise ValueError("仅支持 TTF、OTF 或 TTC 字体文件")
    if not body or len(body) > _MAX_FONT_BYTES:
        raise ValueError("字体文件为空或超过 12MB")
    if not body.startswith((b"\x00\x01\x00\x00", b"OTTO", b"ttcf", b"true")):
        raise ValueError("字体文件格式无效")
    try:
        font = ImageFont.truetype(io.BytesIO(body), 28)
        family, style = font.getname()
    except (OSError, ValueError) as exc:
        raise ValueError("字体文件无法读取") from exc
    digest = hashlib.sha256(body).hexdigest()[:32]
    suffix = ".ttc" if body.startswith(b"ttcf") else ".otf" if body.startswith(b"OTTO") else ".ttf"
    root = _font_root()
    root.mkdir(parents=True, exist_ok=True)
    destination = root / f"{digest}{suffix}"
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=root, prefix=f".{digest}.{os.getpid()}.", suffix=".tmp", delete=False) as handle:
            handle.write(body)
            temporary = Path(handle.name)
        temporary.replace(destination)
    except OSError as exc:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise RuntimeError("字体文件保存失败") from exc
    return {
        "id": f"uploaded:{digest}",
        "label": _safe_font_label(family, style, fallback=Path(filename).stem),
        "source": "uploaded",
    }


def _font_paths(options: dict[str, Any] | None = None) -> tuple[str, str]:
    available = [path for path in _FONT_CANDIDATES if os.path.exists(path)]
    if not available:
        raise RuntimeError("容器中未找到可用于静态封面的中文字体")
    bold = next((path for path in available if "Bold" in path or "bd" in path.lower()), available[0])
    regular = next((path for path in available if path != bold), bold)
    selected = normalise_cover_options(options)
    return (
        _font_path_from_id(selected["zh_font_id"]) or bold,
        _font_path_from_id(selected["en_font_id"]) or regular,
    )


def _font_path_from_id(font_id: str) -> str:
    if font_id == "default":
        return ""
    if font_id.startswith("builtin:"):
        return next((path for path in _available_system_fonts() if _builtin_font_id(path) == font_id), "")
    if font_id.startswith("uploaded:"):
        digest = font_id.removeprefix("uploaded:")
        if re.fullmatch(r"[0-9a-f]{32}", digest):
            root = _font_root().resolve()
            for suffix in _FONT_EXTENSIONS:
                candidate = (root / f"{digest}{suffix}").resolve()
                if candidate.parent == root and candidate.is_file():
                    return str(candidate)
    return ""


def _available_system_fonts() -> list[str]:
    return [path for path in _FONT_CANDIDATES if os.path.isfile(path)]


def _builtin_font_id(path: str) -> str:
    return f"builtin:{hashlib.sha256(str(Path(path).resolve()).encode('utf-8')).hexdigest()[:12]}"


def _font_label(path: str | Path) -> str:
    try:
        family, style = ImageFont.truetype(str(path), 24).getname()
        return _safe_font_label(family, style, fallback=Path(path).stem)
    except (OSError, ValueError):
        return Path(path).stem


def _safe_font_label(family: Any, style: Any, *, fallback: str) -> str:
    label = " ".join(part for part in (str(family or "").strip(), str(style or "").strip()) if part).strip()
    label = re.sub(r"[\x00-\x1f\x7f]", "", label).strip()
    fallback_label = re.sub(r"[\x00-\x1f\x7f]", "", str(fallback or "字体")).strip()
    return (label or fallback_label or "字体")[:80]


def _font_root() -> Path:
    return Path(get_settings().cache_dir).parent / "cover-fonts"


def _library_images(
    library_id: str,
    *,
    limit: int,
    source_sort: str,
    image_source: str,
    sample_key: str = "",
) -> list[Image.Image]:
    sort_by = source_sort if source_sort in COVER_SOURCE_SORTS else "Random"
    cache_key = (library_id, limit, sort_by, image_source, str(sample_key or ""))
    now = time.monotonic()
    with _cache_lock:
        cached = _preview_source_cache.get(cache_key)
        item_ids = list(cached[1]) if cached and cached[0] > now else []
    if not item_ids:
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
        if sample_key:
            with _cache_lock:
                _preview_source_cache[cache_key] = (now + _PREVIEW_SOURCE_TTL_SECONDS, tuple(item_ids))
                expired = [key for key, value in _preview_source_cache.items() if value[0] <= now]
                for key in expired:
                    _preview_source_cache.pop(key, None)
    if image_source == "Primary":
        item_ids = item_ids[:limit]
    if not item_ids:
        return []
    worker_count = min(max(2, os.cpu_count() or 2), 8, len(item_ids))
    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
        images = [image for image in executor.map(lambda item_id: _read_item_image(item_id, image_source), item_ids) if image is not None]
    return images[:limit]


def _read_item_image(item_id: str, image_source: str = "Primary") -> Image.Image | None:
    try:
        cache_key = (safe_emby_id(item_id), image_source)
        now = time.monotonic()
        with _cache_lock:
            cached = _poster_cache.get(cache_key)
            if cached and cached[0] > now:
                _poster_cache.move_to_end(cache_key)
                raw = cached[1]
            else:
                _poster_cache.pop(cache_key, None)
                raw = b""
        base_url, api_key = _credentials()
        if not raw:
            request = urllib.request.Request(
                f"{base_url}/Items/{safe_emby_id(item_id)}/Images/{'Backdrop/0' if image_source == 'Backdrop' else 'Primary'}?maxWidth=960&quality=88",
                headers={"X-Emby-Token": api_key, "Accept": "image/*"},
                method="GET",
            )
            with open_url(request, timeout=15) as response:
                raw = response.read(10 * 1024 * 1024 + 1)
            if len(raw) > 10 * 1024 * 1024:
                return None
            with _cache_lock:
                _poster_cache[cache_key] = (now + _POSTER_CACHE_TTL_SECONDS, raw)
                _poster_cache.move_to_end(cache_key)
                while len(_poster_cache) > _POSTER_CACHE_LIMIT:
                    _poster_cache.popitem(last=False)
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
            library_options_for_item = dict(selected_options)
            title_options = selected_library_options.get(library_id, {})
            # Typography, style and output properties are shared.  Only the
            # two title strings remain library-specific.
            library_options_for_item["zh_title"] = str(title_options.get("zh_title") or "")
            library_options_for_item["en_title"] = str(title_options.get("en_title") or "")
            apply_library_cover(
                library_id,
                title=title,
                style=selected_style,
                options=library_options_for_item,
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
