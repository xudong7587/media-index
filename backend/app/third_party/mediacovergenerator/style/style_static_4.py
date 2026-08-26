# SPDX-License-Identifier: GPL-3.0-only
# Derived from wio-ki/MoviePilot-Plugins, static MediaCoverGenerator style.
# Modified for MediaIndex on 2026-08-24; static-only integration.
import base64
from io import BytesIO

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from .._log import logger
from .style_static_2 import (
    darken_color,
    find_dominant_vibrant_colors,
)
from ..utils.color_helper import ColorHelper


def _wrap_english(draw, text, font, max_width):
    if not text:
        return []
    bbox = draw.textbbox((0, 0), text, font=font)
    if (bbox[2] - bbox[0]) <= max_width or " " not in text:
        return [text]
    words = text.split(" ")
    lines = []
    line = words[0]
    for word in words[1:]:
        test = f"{line} {word}"
        tb = draw.textbbox((0, 0), test, font=font)
        if (tb[2] - tb[0]) > max_width:
            lines.append(line)
            line = word
        else:
            line = test
    if line:
        lines.append(line)
    return lines


def create_style_static_4(
    image_path,
    title,
    font_path,
    font_size=(170, 75),
    font_offset=(0, 40, 40),
    blur_size=50,
    color_ratio=0.8,
    resolution_config=None,
    bg_color_config=None,
    title_x_offset=0,
):
    try:
        zh_font_path, en_font_path = font_path
        title_zh, title_en = title
        zh_font_size, en_font_size = font_size
        zh_font_offset, title_spacing, en_line_spacing = font_offset

        width = 1920
        height = 1080
        if resolution_config:
            width = int(getattr(resolution_config, "width", width))
            height = int(getattr(resolution_config, "height", height))
        canvas_size = (max(1, width), max(1, height))

        src = Image.open(image_path).convert("RGB")
        bg = ImageOps.fit(src, canvas_size, method=Image.LANCZOS)

        scaled_blur = int(max(8, float(blur_size) * (canvas_size[1] / 1080.0)))
        bg = bg.filter(ImageFilter.GaussianBlur(radius=scaled_blur))

        if bg_color_config:
            tint = ColorHelper.get_background_color(
                src,
                color_mode=bg_color_config.get('mode', 'auto'),
                custom_color=bg_color_config.get('custom_color'),
                config_color=bg_color_config.get('config_color')
            )
        else:
            dominant = find_dominant_vibrant_colors(src, num_colors=5)
            tint = dominant[0] if dominant else (120, 120, 120)
        tint = darken_color(tint, 0.82)

        ratio = float(color_ratio)
        if ratio < 0 or ratio > 1:
            ratio = 0.8

        bg_np = np.array(bg, dtype=np.float32)
        tint_np = np.array([[tint]], dtype=np.float32)
        bg_np *= 1.0 - ratio
        bg_np += tint_np * ratio
        np.clip(bg_np, 0, 255, out=bg_np)
        mixed = bg_np.astype(np.uint8)
        canvas = Image.fromarray(mixed).convert("RGBA")

        text_layer = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
        shadow_layer = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(text_layer)
        sdraw = ImageDraw.Draw(shadow_layer)

        zh_font = ImageFont.truetype(zh_font_path, int(max(1, float(zh_font_size))))
        en_font = ImageFont.truetype(en_font_path, int(max(1, float(en_font_size))))

        cx = canvas_size[0] // 2 + int(float(title_x_offset))
        cy = canvas_size[1] // 2

        text_color = (255, 255, 255, 230)
        shadow_color = darken_color(tint, 0.65) + (92,)

        zh_bbox = draw.textbbox((0, 0), title_zh, font=zh_font)
        zh_w = zh_bbox[2] - zh_bbox[0]
        zh_h = zh_bbox[3] - zh_bbox[1]

        lines = _wrap_english(draw, title_en, en_font, zh_w)
        line_gap = int(max(1, float(en_line_spacing)))
        en_h = 0
        line_sizes = []
        for i, line in enumerate(lines):
            lb = draw.textbbox((0, 0), line, font=en_font)
            lw = lb[2] - lb[0]
            lh = lb[3] - lb[1]
            line_sizes.append((line, lw, lh))
            en_h += lh + (line_gap if i < len(lines) - 1 else 0)

        spacing = int(float(title_spacing)) if lines else 0
        total_h = zh_h + spacing + en_h
        y0 = cy - total_h // 2 + int(float(zh_font_offset))

        zh_x = cx - zh_w // 2
        zh_y = y0

        for off in range(3, 11, 2):
            sdraw.text((zh_x + off, zh_y + off), title_zh, font=zh_font, fill=shadow_color)
        draw.text((zh_x, zh_y), title_zh, font=zh_font, fill=text_color)

        ey = zh_y + zh_h + spacing
        for line, lw, lh in line_sizes:
            ex = cx - lw // 2
            for off in range(2, 8, 2):
                sdraw.text((ex + off, ey + off), line, font=en_font, fill=shadow_color)
            draw.text((ex, ey), line, font=en_font, fill=text_color)
            ey += lh + line_gap

        merged = Image.alpha_composite(canvas, shadow_layer.filter(ImageFilter.GaussianBlur(radius=8)))
        merged = Image.alpha_composite(merged, text_layer)

        buf = BytesIO()
        merged.save(buf, format="PNG", optimize=True)
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception as e:
        logger.error(f"创建静态4封面时出错: {e}")
        return False
