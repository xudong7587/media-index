# SPDX-License-Identifier: GPL-3.0-only
# Derived from wio-ki/MoviePilot-Plugins, static MediaCoverGenerator style.
# Modified for MediaIndex on 2026-08-24; static-only integration.
import base64
import random
import colorsys
from io import BytesIO

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, ImageEnhance

from .._log import logger
from ..utils.image_manager import ResolutionConfig, managed_image
from ..utils.performance_helper import (
    OptimizedImageProcessor, memory_efficient_operation
)
from ..utils.color_helper import ColorHelper


# ========== 配置 ==========
# canvas_size = (1920, 1080)  # 移除固定尺寸，改为动态配置

def rgb_to_hsv(color):
    """将 RGB 颜色转换为 HSV 颜色。"""
    r, g, b = [x / 255.0 for x in color]
    return colorsys.rgb_to_hsv(r, g, b)

def hsv_to_rgb(h, s, v):
    """将 HSV 颜色转换为 RGB 颜色。"""
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return (int(r * 255), int(g * 255), int(b * 255))

def color_distance(color1, color2):
    """计算两个颜色在HSV空间中的距离"""
    h1, s1, v1 = rgb_to_hsv(color1)
    h2, s2, v2 = rgb_to_hsv(color2)

    # 色调在环形空间中，需要特殊处理
    h_dist = min(abs(h1 - h2), 1 - abs(h1 - h2))

    # 综合距离，给予色调更高的权重
    return h_dist * 5 + abs(s1 - s2) + abs(v1 - v2)

def darken_color(color, factor=0.7):
    """
    将颜色加深。
    """
    r, g, b = color
    return (int(r * factor), int(g * factor), int(b * factor))

def add_film_grain(image, intensity=0.05):
    """添加胶片颗粒效果"""
    img_array = np.asarray(image, dtype=np.float32)

    # 创建随机噪点
    noise = np.random.default_rng().standard_normal(img_array.shape, dtype=np.float32)
    noise *= float(intensity) * 255

    # 应用噪点
    img_array += noise
    np.clip(img_array, 0, 255, out=img_array)

    return Image.fromarray(img_array.astype(np.uint8))

def _premium_finish(image, accent_color=None, vignette_strength=0.28, glow_strength=0.20):
    """为背景增加柔和高光、暗角和纸感层次。"""
    base = image.convert("RGBA")
    width, height = base.size
    if accent_color is None:
        accent_color = (220, 170, 112)
    accent = tuple(int(max(0, min(255, c))) for c in accent_color[:3])

    x = np.linspace(-1, 1, width, dtype=np.float32)
    y = np.linspace(-1, 1, height, dtype=np.float32)
    X, Y = np.meshgrid(x, y)

    glow_a = np.exp(-(((X + 0.58) ** 2) / 0.42 + ((Y + 0.52) ** 2) / 0.25))
    glow_b = np.exp(-(((X - 0.42) ** 2) / 0.32 + ((Y - 0.36) ** 2) / 0.34))
    vignette = np.clip((np.sqrt((X * 0.86) ** 2 + (Y * 1.05) ** 2) - 0.18) / 0.95, 0, 1)

    overlay = np.zeros((height, width, 4), dtype=np.uint8)
    overlay[..., 0] = np.clip(255 * glow_a + accent[0] * glow_b, 0, 255)
    overlay[..., 1] = np.clip(238 * glow_a + accent[1] * glow_b, 0, 255)
    overlay[..., 2] = np.clip(205 * glow_a + accent[2] * glow_b, 0, 255)
    overlay[..., 3] = np.clip((glow_a * 54 + glow_b * 42) * glow_strength, 0, 58).astype(np.uint8)
    base = Image.alpha_composite(base, Image.fromarray(overlay, "RGBA"))

    shade = np.zeros((height, width, 4), dtype=np.uint8)
    shade[..., 3] = np.clip(vignette * 255 * vignette_strength, 0, 120).astype(np.uint8)
    base = Image.alpha_composite(base, Image.fromarray(shade, "RGBA"))
    return base.convert("RGB")


def _polish_card(image):
    """轻微增强卡片质感，避免过锐或发灰。"""
    polished = ImageEnhance.Color(image.convert("RGB")).enhance(1.06)
    polished = ImageEnhance.Contrast(polished).enhance(1.04)
    polished = ImageEnhance.Sharpness(polished).enhance(1.08)
    return polished


def _adaptive_background_tone(image, bg_color, color_ratio):
    """根据海报明暗自动调和背景混色比例与背景色。"""
    try:
        lum = float(np.array(image.convert("L").resize((64, 64), Image.LANCZOS)).mean())
    except Exception:
        lum = 128.0
    ratio = float(color_ratio)
    r, g, b = bg_color[:3]
    if lum > 180:
        ratio = min(0.94, ratio + 0.10)
        bg_color = darken_color((r, g, b), 0.70)
    elif lum < 55:
        ratio = max(0.58, ratio - 0.12)
        bg_color = tuple(min(255, int(c * 1.18 + 10)) for c in (r, g, b))
    return bg_color, ratio


def crop_to_square(img):
    """将图片裁剪为正方形"""
    width, height = img.size
    size = min(width, height)

    left = (width - size) // 2
    top = (height - size) // 2
    right = left + size
    bottom = top + size

    return img.crop((left, top, right, bottom))

def add_rounded_corners(img, radius=30):
    """
    给图片添加圆角，通过超采样技术消除锯齿

    Args:
        img: PIL.Image对象
        radius: 圆角半径

    Returns:
        带圆角的图片(RGBA模式)
    """
    # 超采样倍数
    factor = 2

    # 获取原始尺寸
    width, height = img.size

    # 创建更大尺寸的空白图像（用于超采样）
    enlarged_img = img.resize((width * factor, height * factor), Image.Resampling.LANCZOS)
    enlarged_img = enlarged_img.convert("RGBA")

    # 创建透明蒙版，尺寸为放大后的尺寸
    mask = Image.new('L', (width * factor, height * factor), 0)
    draw = ImageDraw.Draw(mask)

    draw.rounded_rectangle([(0, 0), (width * factor, height * factor)],
                            radius=radius * factor, fill=255)

    # 创建超采样尺寸的透明背景
    background = Image.new("RGBA", (width * factor, height * factor), (255, 255, 255, 0))

    # 使用蒙版合成图像（在高分辨率下）
    high_res_result = Image.composite(enlarged_img, background, mask)

    # 将结果缩小回原来的尺寸，应用抗锯齿
    result = high_res_result.resize((width, height), Image.Resampling.LANCZOS)

    return result



def add_shadow_and_rotate(canvas, img, angle, offset=(10, 10), radius=10, opacity=0.5, center_pos=None):
    """添加多层弥散阴影并旋转图像，营造悬浮卡片层次。"""
    width, height = img.size
    if center_pos is None:
        center_pos = (canvas.width // 2, canvas.height // 2)

    if img.mode == "RGBA":
        shadow_mask = img.split()[3]
    else:
        shadow_mask = Image.new("L", (width, height), 255)

    shadow_layers = [
        (max(1, radius // 3), (max(1, offset[0] // 3), max(1, offset[1] // 3)), min(0.22, opacity * 0.55)),
        (radius, offset, opacity * 0.55),
        (int(radius * 2.4), (int(offset[0] * 1.55), int(offset[1] * 1.70)), opacity * 0.22),
    ]

    for blur_radius, layer_offset, layer_opacity in shadow_layers:
        padding = max(abs(layer_offset[0]), abs(layer_offset[1])) + blur_radius * 3
        shadow = Image.new("RGBA", (width + padding * 2, height + padding * 2), (0, 0, 0, 0))
        shadow.paste(
            (0, 0, 0, int(255 * layer_opacity)),
            (padding, padding, padding + width, padding + height),
            shadow_mask,
        )
        shadow = shadow.filter(ImageFilter.GaussianBlur(blur_radius))
        rotated_shadow = rotate_image(shadow, angle)
        shadow_x = center_pos[0] - rotated_shadow.width // 2 + layer_offset[0]
        shadow_y = center_pos[1] - rotated_shadow.height // 2 + layer_offset[1]
        canvas.paste(rotated_shadow, (shadow_x, shadow_y), rotated_shadow)

    rotated_img = rotate_image(img, angle)
    img_x = center_pos[0] - rotated_img.width // 2
    img_y = center_pos[1] - rotated_img.height // 2
    canvas.paste(rotated_img, (img_x, img_y), rotated_img)
    return canvas

def rotate_image(img, angle, bg_color=(0, 0, 0, 0)):
    """旋转图片并确保不会截断图片内容"""
    # expand=True 确保旋转后的图片不会被截断
    return img.rotate(angle, Image.BICUBIC, expand=True, fillcolor=bg_color)


@memory_efficient_operation
def create_style_static_1(image_path, title, font_path, font_size=(170,75), font_offset=(0,40,40), blur_size=50, color_ratio=0.8, resolution_config=None, bg_color_config=None, title_x_offset=0):
    try:
        logger.info("开始创建单图封面...")

        # 初始化分辨率配置
        if resolution_config is None:
            resolution_config = ResolutionConfig("1080p")

        canvas_size = resolution_config.size
        logger.info(f"图像生成使用的画布尺寸: {canvas_size} (分辨率配置: {resolution_config})")

        zh_font_path, en_font_path = font_path
        title_zh, title_en = title
        zh_font_size = float(font_size[0])
        en_font_size = float(font_size[1])
        zh_font_offset, title_spacing, en_line_spacing = font_offset

        if int(blur_size) < 0:
            blur_size = 50

        if float(color_ratio) < 0 or float(color_ratio) > 1:
            color_ratio = 0.8

        if not float(zh_font_size) > 0:
            zh_font_size = resolution_config.get_font_size(170)
        if not float(en_font_size) > 0:
            en_font_size = resolution_config.get_font_size(75)


        num_colors = 6

        # 使用资源管理器加载原始图片
        with managed_image(image_path, "RGB") as original_img:

            # 获取背景颜色
            if bg_color_config:
                bg_color = ColorHelper.get_background_color(
                    original_img,
                    color_mode=bg_color_config.get('mode', 'auto'),
                    custom_color=bg_color_config.get('custom_color'),
                    config_color=bg_color_config.get('config_color')
                )
                logger.info(f"使用背景颜色: {bg_color} (模式: {bg_color_config.get('mode', 'auto')})")
            else:
                # 从图片提取马卡龙风格的颜色（使用优化的颜色分析）
                candidate_colors = OptimizedImageProcessor.optimized_color_analysis(original_img, num_colors)
                random.shuffle(candidate_colors)
                extracted_colors = candidate_colors[:num_colors]

                # 柔和的马卡龙备选颜色
                soft_macaron_colors = [
                    (237, 159, 77),    # 杏色
                    (186, 225, 255),   # 淡蓝色
                    (255, 223, 186),   # 浅橘色
                    (202, 231, 200),   # 淡绿色
                ]

                # 确保有足够的颜色
                while len(extracted_colors) < num_colors:
                    # 从备选颜色中选择一个与已有颜色差异最大的
                    if not extracted_colors:
                        extracted_colors.append(random.choice(soft_macaron_colors))
                    else:
                        max_diff = 0
                        best_color = None
                        for color in soft_macaron_colors:
                            min_dist = min(color_distance(color, existing) for existing in extracted_colors)
                            if min_dist > max_diff:
                                max_diff = min_dist
                                best_color = color
                        extracted_colors.append(best_color or random.choice(soft_macaron_colors))

                # 处理颜色
                bg_color = darken_color(extracted_colors[0], 0.85)  # 背景色

            bg_color, color_ratio = _adaptive_background_tone(original_img, bg_color, color_ratio)

            # 获取卡片颜色（始终从图片提取）
            card_colors_extracted = ColorHelper.extract_dominant_colors(original_img, num_colors=3, style="macaron")
            card_colors = [card_colors_extracted[1] if len(card_colors_extracted) > 1 else (186, 225, 255),
                          card_colors_extracted[2] if len(card_colors_extracted) > 2 else (255, 223, 186)]

            # 2. 背景处理
            bg_img = original_img.copy()
            bg_img = ImageOps.fit(bg_img, canvas_size, method=Image.LANCZOS)
            # 使用优化的高斯模糊
            bg_img = OptimizedImageProcessor.optimized_gaussian_blur(bg_img, int(blur_size))

            # 将背景图片与背景色混合
            bg_img_array = np.array(bg_img, dtype=np.float32)
            bg_color_array = np.array([[bg_color]], dtype=np.float32)

            # 混合背景图和颜色 (15% 背景图 + 85% 颜色)
            bg_img_array *= 1 - float(color_ratio)
            bg_img_array += bg_color_array * float(color_ratio)
            np.clip(bg_img_array, 0, 255, out=bg_img_array)
            blended_bg = bg_img_array.astype(np.uint8)
            blended_bg_img = Image.fromarray(blended_bg)

            # 添加柔和高光、暗角与细颗粒，提升背景层次
            blended_bg_img = _premium_finish(blended_bg_img, bg_color, vignette_strength=0.26, glow_strength=0.80)
            blended_bg_img = add_film_grain(blended_bg_img, intensity=0.018)

            # 创建最终画布
            canvas = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
            canvas.paste(blended_bg_img)

            # 3. 处理卡片效果
            # 裁剪为正方形
            square_img = crop_to_square(original_img)

            # 计算卡片尺寸 (画布高度的70%)
            card_size = int(canvas_size[1] * 0.7)
            square_img = square_img.resize((card_size, card_size), Image.LANCZOS)
            square_img = _polish_card(square_img)

            # 准备三张卡片图像
            cards = []

            # 主卡片 - 原始图
            main_card = add_rounded_corners(square_img, radius=card_size//8)
            main_card = main_card.convert("RGBA")

            # 辅助卡片1 (中间层) - 与第二种颜色混合，加深颜色
            aux_card1 = square_img.copy().filter(ImageFilter.GaussianBlur(radius=8))
            aux_card1_array = np.array(aux_card1, dtype=np.float32)
            card_color1_array = np.array([[card_colors[0]]], dtype=np.float32)
            # 降低原图比例，增加颜色混合比例
            aux_card1_array *= 0.5
            aux_card1_array += card_color1_array * 0.5
            np.clip(aux_card1_array, 0, 255, out=aux_card1_array)
            blended_card1 = aux_card1_array.astype(np.uint8)
            aux_card1 = Image.fromarray(blended_card1)
            aux_card1 = add_rounded_corners(aux_card1, radius=card_size//8)
            aux_card1 = aux_card1.convert("RGBA")

            # 辅助卡片2 (底层) - 与第三种颜色混合，加深颜色
            aux_card2 = square_img.copy().filter(ImageFilter.GaussianBlur(radius=16))
            aux_card2_array = np.array(aux_card2, dtype=np.float32)
            card_color2_array = np.array([[card_colors[1]]], dtype=np.float32)
            # 降低原图比例，增加颜色混合比例
            aux_card2_array *= 0.4
            aux_card2_array += card_color2_array * 0.6
            np.clip(aux_card2_array, 0, 255, out=aux_card2_array)
            blended_card2 = aux_card2_array.astype(np.uint8)
            aux_card2 = Image.fromarray(blended_card2)
            aux_card2 = add_rounded_corners(aux_card2, radius=card_size//8)
            aux_card2 = aux_card2.convert("RGBA")

            # 4. 分别添加阴影和旋转
            # 计算卡片放置中心位置 (画布右侧)
            center_x = int(canvas_size[0] - canvas_size[1] * 0.5)  # 稍微左移，给旋转后的卡片留出空间
            center_y = int(canvas_size[1] * 0.5)
            center_pos = (center_x, center_y)

            # 按照需求指定旋转角度
            rotation_angles = [36, 18, 0]  # 底层、中间层、顶层的旋转角度

            # 阴影配置
            shadow_configs = [
                {'offset': (12, 20), 'radius': 22, 'opacity': 0.30},  # 底层：更柔和的环境阴影
                {'offset': (16, 26), 'radius': 26, 'opacity': 0.38},  # 中间层：加大扩散半径
                {'offset': (20, 30), 'radius': 30, 'opacity': 0.48},  # 顶层：保留重点但不过脏
            ]

            # 创建一个临时画布，用于叠加卡片和阴影效果
            cards_canvas = Image.new("RGBA", canvas_size, (0, 0, 0, 0))

            # 从底层到顶层依次添加阴影和卡片
            cards = [aux_card2, aux_card1, main_card]

            for i, (card, angle, shadow_config) in enumerate(zip(cards, rotation_angles, shadow_configs)):
                # 使用优化后的函数添加阴影和旋转图片
                cards_canvas = add_shadow_and_rotate(
                    cards_canvas,
                    card,
                    angle,
                    offset=shadow_config['offset'],
                    radius=shadow_config['radius'],
                    opacity=shadow_config['opacity'],
                    center_pos=center_pos
                )

            # 将裁剪后的卡片画布与背景合并
            canvas = Image.alpha_composite(canvas.convert("RGBA"), cards_canvas)

            # 5. 文字处理
            text_layer = Image.new('RGBA', canvas_size, (255, 255, 255, 0))
            shadow_layer = Image.new("RGBA", canvas_size, (0, 0, 0, 0))

            shadow_draw = ImageDraw.Draw(shadow_layer)
            draw = ImageDraw.Draw(text_layer)

            # 计算左侧区域的中心 X 位置 (画布宽度的四分之一处)
            left_area_center_x = int(canvas_size[0] * 0.25 + float(title_x_offset))
            left_area_center_y = canvas_size[1] // 2

            # 使用动态字体大小
            zh_font = ImageFont.truetype(zh_font_path, int(zh_font_size))
            en_font = ImageFont.truetype(en_font_path, int(en_font_size))

            # 文字颜色和阴影颜色
            text_color = (255, 250, 238, 238)
            shadow_color = darken_color(bg_color, 0.58) + (96,)
            shadow_offset = 14
            shadow_alpha = 72

        # 计算中文标题的位置
        zh_bbox = draw.textbbox((0, 0), title_zh, font=zh_font)
        zh_text_w = zh_bbox[2] - zh_bbox[0]
        zh_text_h = zh_bbox[3] - zh_bbox[1]

        # 定义英文行间距
        en_line_spacing = int(float(en_line_spacing))

        # 处理英文标题（如果有）
        en_lines = []
        en_text_w = 0
        en_text_h = 0
        total_en_height = 0

        if title_en:
            # 检查英文标题是否需要分行
            en_bbox = draw.textbbox((0, 0), title_en, font=en_font)
            en_full_width = en_bbox[2] - en_bbox[0]

            # 如果英文标题比中文标题宽，且包含多个单词，则分行处理
            if en_full_width > zh_text_w and " " in title_en:
                words = title_en.split(" ")
                current_line = words[0]

                for word in words[1:]:
                    test_line = current_line + " " + word
                    test_bbox = draw.textbbox((0, 0), test_line, font=en_font)
                    test_width = test_bbox[2] - test_bbox[0]

                    # 如果添加新单词后超过中文宽度，则换行
                    if test_width > zh_text_w:
                        en_lines.append(current_line)
                        current_line = word
                    else:
                        current_line = test_line

                # 添加最后一行
                if current_line:
                    en_lines.append(current_line)

                # 计算所有英文行的最大宽度和总高度
                for line in en_lines:
                    line_bbox = draw.textbbox((0, 0), line, font=en_font)
                    line_width = line_bbox[2] - line_bbox[0]
                    line_height = line_bbox[3] - line_bbox[1]
                    en_text_w = max(en_text_w, line_width)
                    total_en_height += line_height + en_line_spacing

                # 减去最后一个多余的行间距
                if en_lines:
                    total_en_height -= en_line_spacing

                en_text_h = total_en_height
            else:
                # 英文标题不需要分行
                en_lines = [title_en]
                en_text_w = en_full_width
                en_text_h = en_bbox[3] - en_bbox[1]
                total_en_height = en_text_h

        # 定义中英文标题间距
        title_spacing = float(title_spacing) if title_en else 0

        # 计算整体文本高度：中文标题高度 + 英文标题高度（如果有）+ 间距（如果有英文标题）
        total_text_height = zh_text_h + total_en_height + title_spacing

        # 计算整体的垂直居中起始位置
        total_text_y = left_area_center_y - total_text_height // 2

        # 中文标题位置
        zh_x = left_area_center_x - zh_text_w // 2
        zh_y = total_text_y + float(zh_font_offset)

        # 中文标题阴影效果
        for offset in range(3, shadow_offset + 1, 2):
            current_shadow_color = shadow_color[:3] + (shadow_alpha,)
            shadow_draw.text((zh_x + offset, zh_y + offset), title_zh, font=zh_font, fill=current_shadow_color)

            # 中文标题
            draw.text((zh_x, zh_y), title_zh, font=zh_font, fill=text_color)

            if en_lines:
                # 英文标题起始位置
                en_y = zh_y + zh_text_h + title_spacing

                # 处理多行英文
                for i, line in enumerate(en_lines):
                    # 计算每行的水平居中位置
                    line_bbox = draw.textbbox((0, 0), line, font=en_font)
                    line_width = line_bbox[2] - line_bbox[0]
                    line_height = line_bbox[3] - line_bbox[1]

                    en_x = left_area_center_x - line_width // 2
                    current_y = en_y + i * (line_height + en_line_spacing)

                    # 英文标题阴影效果
                    for offset in range(2, shadow_offset // 2 + 1):
                        current_shadow_color = shadow_color[:3] + (shadow_alpha,)
                        shadow_draw.text((en_x + offset, current_y + offset), line, font=en_font, fill=current_shadow_color)

                    # 英文标题
                    draw.text((en_x, current_y), line, font=en_font, fill=text_color)

            blurred_shadow = shadow_layer.filter(ImageFilter.GaussianBlur(radius=shadow_offset))
            combined = Image.alpha_composite(canvas, blurred_shadow)
            # 合并所有图层
            combined = Image.alpha_composite(combined, text_layer)

            # 转为 RGB
            # rgb_image = combined.convert("RGB")

            def image_to_base64(image, format="auto", quality=85):
                buffer = BytesIO()
                if format.lower() == "auto":
                    if image.mode == "RGBA" or (image.info.get('transparency') is not None):
                        format = "PNG"
                    else:
                        try:
                            image.save(buffer, format="WEBP", quality=quality, optimize=True)
                            base64_str = base64.b64encode(buffer.getvalue()).decode('utf-8')
                            return base64_str
                        except Exception:
                            format = "JPEG" # Fallback to JPEG if WebP fails
                if format.lower() == "png":
                    image.save(buffer, format="PNG", optimize=True)
                    base64_str = base64.b64encode(buffer.getvalue()).decode('utf-8')
                    return base64_str
                elif format.lower() == "jpeg":
                    image = image.convert("RGB") # Ensure RGB for JPEG
                    image.save(buffer, format="JPEG", quality=quality, optimize=True, progressive=True)
                    base64_str = base64.b64encode(buffer.getvalue()).decode('utf-8')
                    return base64_str
                else:
                    raise ValueError(f"Unsupported format: {format}")

            return image_to_base64(combined)

    except Exception as e:
        logger.error(f"创建单图封面时出错: {e}")
        return False


def create_style_single_1(*args, **kwargs):
    """兼容旧命名"""
    return create_style_static_1(*args, **kwargs)
