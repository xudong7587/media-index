"""Short-lived static cover renderer.

This module is intentionally executed in a child process so NumPy and the
vendored renderers are released as soon as one cover has been generated.
"""

from __future__ import annotations

import base64
import io
import json
import sys
from pathlib import Path
from typing import Any, Callable

from PIL import Image

from app.third_party.mediacovergenerator.style.style_static_1 import create_style_static_1
from app.third_party.mediacovergenerator.style.style_static_2 import create_style_static_2
from app.third_party.mediacovergenerator.style.style_static_3 import create_style_static_3
from app.third_party.mediacovergenerator.style.style_static_4 import create_style_static_4
from app.third_party.mediacovergenerator.utils.image_manager import ResolutionConfig


_MAX_OUTPUT_BYTES = 20 * 1024 * 1024
_RENDERERS: dict[str, Callable[..., str | bool]] = {
    "collage": create_style_static_1,
    "showcase": create_style_static_3,
    "mosaic": create_style_static_2,
    "minimal": create_style_static_4,
}


def render_cover(payload: dict[str, Any]) -> bytes:
    style = str(payload["style"])
    renderer = _RENDERERS.get(style)
    if renderer is None:
        raise ValueError("unsupported cover style")
    options = payload["options"]
    if not isinstance(options, dict):
        raise ValueError("invalid cover options")
    raw_title = payload.get("title")
    raw_font_paths = payload.get("font_paths")
    if not isinstance(raw_title, list) or len(raw_title) != 2:
        raise ValueError("invalid cover title")
    if not isinstance(raw_font_paths, list) or len(raw_font_paths) != 2:
        raise ValueError("invalid cover fonts")
    source_directory = Path(str(payload["source_directory"])).resolve()
    source = source_directory / "1.jpg"
    title = tuple(str(item) for item in raw_title)
    font_paths = tuple(str(item) for item in raw_font_paths)
    if not source.is_file():
        raise ValueError("invalid cover input")
    resolution = ResolutionConfig(str(options["resolution"]))
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
    if style == "showcase":
        rendered = renderer(
            str(source_directory),
            title,
            font_paths,
            is_blur=options["showcase_blur"],
            **render_options,
        )
    else:
        rendered = renderer(str(source), title, font_paths, **render_options)
    return _normalise_rendered_cover(rendered, expected_size=resolution.size)


def _normalise_rendered_cover(rendered: str | bool, *, expected_size: tuple[int, int]) -> bytes:
    if not isinstance(rendered, str) or not rendered:
        raise RuntimeError("renderer returned no image")
    try:
        raw = base64.b64decode(rendered, validate=True)
    except ValueError as exc:
        raise RuntimeError("renderer returned invalid image data") from exc
    if not raw or len(raw) > _MAX_OUTPUT_BYTES:
        raise RuntimeError("renderer output size is invalid")
    with Image.open(io.BytesIO(raw)) as generated:
        canvas = generated.convert("RGB").copy()
    if canvas.size != expected_size:
        canvas = canvas.resize(expected_size, Image.Resampling.LANCZOS)
    output = io.BytesIO()
    canvas.save(output, format="JPEG", quality=92, optimize=True)
    return output.getvalue()


def main(arguments: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if arguments is None else arguments)
    if len(args) != 2:
        return 64
    request_path = Path(args[0])
    output_path = Path(args[1])
    try:
        payload = json.loads(request_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("invalid request")
        body = render_cover(payload)
        output_path.write_bytes(body)
    except Exception as exc:
        print(f"cover worker failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
