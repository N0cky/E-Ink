"""
Generische Text-Utilities für alle Renderer: Zeilenumbruch, Einpassen in
eine Box mit fallender Schriftgröße, mehrzeiliges Zeichnen.
"""

from __future__ import annotations

from typing import Callable

from PIL import ImageDraw

FontLoader = Callable[[int, bool], object]


def get_text_size(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int, max_lines: int | None = None) -> list[str]:
    if not text:
        return []

    lines = []
    truncated = False
    paragraphs = text.splitlines() or [text]

    for paragraph in paragraphs:
        words = paragraph.split()
        if not words:
            if lines and lines[-1] != "":
                lines.append("")
                if max_lines and len(lines) >= max_lines:
                    truncated = True
                    break
            continue

        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            width, _ = get_text_size(draw, candidate, font)

            if width <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = word

                if max_lines and len(lines) >= max_lines:
                    truncated = True
                    break

        if truncated:
            break

        if not max_lines or len(lines) < max_lines:
            lines.append(current)
        else:
            truncated = True
            break

    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
        truncated = True

    if truncated and lines:
        last = lines[-1]
        while True:
            width, _ = get_text_size(draw, last + "…", font)
            if width <= max_width:
                lines[-1] = last + "…"
                break
            if len(last) <= 1:
                lines[-1] = "…"
                break
            last = last[:-1].rstrip()

    return lines


def fit_wrapped_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    max_height: int,
    start_size: int,
    min_size: int,
    load_font: FontLoader,
    is_bold: bool = False,
    max_lines: int | None = None,
    line_spacing: float = 0.2,
):
    if max_width <= 0 or max_height <= 0:
        font = load_font(min_size, is_bold)
        return font, [], 0, 0, 0

    for size in range(start_size, min_size - 1, -2):
        font = load_font(size, is_bold)
        lines = wrap_text(draw, text, font, max_width, max_lines=max_lines)

        if not lines:
            return font, [], 0, 0, 0

        _, line_h = get_text_size(draw, "Ag", font)
        spacing_px = int(line_h * line_spacing)
        total_h = len(lines) * line_h + max(0, len(lines) - 1) * spacing_px
        max_line_w = max(get_text_size(draw, line, font)[0] for line in lines)

        if max_line_w <= max_width and total_h <= max_height:
            return font, lines, line_h, spacing_px, total_h

    font = load_font(min_size, is_bold)
    lines = wrap_text(draw, text, font, max_width, max_lines=max_lines)
    _, line_h = get_text_size(draw, "Ag", font)
    spacing_px = int(line_h * line_spacing)
    total_h = len(lines) * line_h + max(0, len(lines) - 1) * spacing_px
    return font, lines, line_h, spacing_px, total_h


def fit_optional_text_block(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    max_height: int,
    start_size: int,
    min_size: int,
    fallback_font,
    load_font: FontLoader,
    is_bold: bool = False,
    max_lines: int | None = None,
    line_spacing: float = 0.2,
):
    if not text:
        return fallback_font, [], 0, 0, 0

    return fit_wrapped_text(
        draw,
        text,
        max_width,
        max_height,
        start_size,
        min_size,
        load_font,
        is_bold=is_bold,
        max_lines=max_lines,
        line_spacing=line_spacing,
    )


def draw_lines(draw: ImageDraw.ImageDraw, x: int, y: int, lines: list[str], font, fill, line_h: int, spacing_px: int):
    current_y = y
    for line in lines:
        if line:
            draw.text((x, current_y), line, font=font, fill=fill)
        current_y += line_h + spacing_px
    return current_y
