"""
Tagesschau-Renderer: Hintergrund, Karten mit Thumbnail, Header.
Alle Tagesschau-spezifischen Zeichenfunktionen leben hier im Modul.
"""

from __future__ import annotations

from typing import Callable

from PIL import Image, ImageDraw, ImageFilter

from app.config import format_date_long
from app.image_rendering import create_rounded_thumbnail, fit_crop
from app.module_services import ModuleRenderServices
from app.text_rendering import draw_lines, fit_optional_text_block

Color3 = tuple[int, int, int]
Color4 = tuple[int, int, int, int]
FontLoader = Callable[[int, bool], object]
ImageFetcher = Callable[[str], Image.Image | None]
ThumbnailFactory = Callable[[Image.Image, int, int, int], Image.Image]


# ---------------------------------------------------------------------------
# Farbpaletten für Dark / Light Theme
# ---------------------------------------------------------------------------

_NEWS_DARK = {
    "idle_text":      (245, 245, 245, 235),
    "title_text":     (255, 255, 255, 255),
    "label_text":     (215, 215, 215, 240),
    "card_tint":      (18, 24, 34, 120),
    "card_outline":   (255, 255, 255, 52),
    "thumb_border":   (255, 255, 255, 60),
    "meta_color":     (230, 230, 230, 245),
    "news_title":     (255, 255, 255, 255),
    "news_summary":   (244, 244, 244, 248),
    "empty_title":    (255, 255, 255, 255),
    "empty_sub":      (235, 235, 235, 255),
}

_NEWS_LIGHT = {
    "idle_text":      (75, 62, 48, 235),
    "title_text":     (18, 12, 6, 255),
    "label_text":     (95, 80, 62, 240),
    "card_tint":      (252, 248, 242, 200),
    "card_outline":   (172, 155, 132, 80),
    "thumb_border":   (155, 140, 122, 80),
    "meta_color":     (105, 88, 70, 245),
    "news_title":     (18, 12, 6, 255),
    "news_summary":   (58, 46, 34, 248),
    "empty_title":    (22, 16, 8, 255),
    "empty_sub":      (80, 68, 52, 255),
}


def _spectra(name: str) -> Color4:
    from app.image_rendering import SPECTRA6_COLORS as _C
    return (*_C[name], 255)


# E-Ink: nur Spectra-Farben, alles deckend, keine Schatten/Blur (siehe "flat")
_NEWS_EINK = {
    "flat":           True,
    "idle_text":      _spectra("black"),
    "title_text":     _spectra("black"),
    "label_text":     _spectra("blue"),
    "card_tint":      _spectra("white"),
    "card_outline":   _spectra("black"),
    "thumb_border":   _spectra("black"),
    "meta_color":     _spectra("blue"),
    "news_title":     _spectra("black"),
    "news_summary":   _spectra("black"),
    "empty_title":    _spectra("black"),
    "empty_sub":      _spectra("black"),
}


def _news_pal(theme: str) -> dict:
    if theme == "eink":
        return _NEWS_EINK
    return _NEWS_LIGHT if theme == "light" else _NEWS_DARK


# ---------------------------------------------------------------------------
# Farbverlauf-Hilfsfunktionen
# ---------------------------------------------------------------------------

def interpolate_color(start_color: Color3, end_color: Color3, progress: float) -> Color3:
    clamped = min(max(progress, 0.0), 1.0)
    return tuple(int(start + ((end - start) * clamped)) for start, end in zip(start_color, end_color))


def fill_vertical_gradient(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    start_color: Color3,
    end_color: Color3,
):
    for y in range(height):
        progress = y / max(height - 1, 1)
        color = interpolate_color(start_color, end_color, progress)
        draw.rectangle([(0, y), (width, y + 1)], fill=(*color, 255))


def alpha_composite_blurred_shape(
    img: Image.Image,
    bounds: tuple[int, int, int, int],
    fill: Color4,
    blur_radius: int,
    shape: str = "rounded_rectangle",
    radius: int = 0,
):
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay, "RGBA")

    if shape == "ellipse":
        overlay_draw.ellipse(bounds, fill=fill)
    else:
        overlay_draw.rounded_rectangle(bounds, radius=radius, fill=fill)

    img.alpha_composite(overlay.filter(ImageFilter.GaussianBlur(radius=blur_radius)))


# ---------------------------------------------------------------------------
# Hintergründe
# ---------------------------------------------------------------------------

def create_tagesschau_idle_background(render_width: int, render_height: int) -> Image.Image:
    img = Image.new("RGB", (render_width, render_height), (10, 20, 34))
    draw = ImageDraw.Draw(img, "RGBA")

    fill_vertical_gradient(draw, render_width, render_height, (22, 48, 84), (12, 30, 58))

    draw.ellipse(
        [(-180, -140), (int(render_width * 0.58), int(render_height * 0.38))],
        fill=(70, 132, 210, 34),
    )
    draw.ellipse(
        [(int(render_width * 0.42), -120), (render_width + 160, int(render_height * 0.3))],
        fill=(28, 84, 160, 30),
    )
    draw.rounded_rectangle(
        [(-80, int(render_height * 0.62)), (render_width + 80, render_height + 120)],
        radius=120,
        fill=(6, 16, 30, 110),
    )
    draw.line(
        [(0, int(render_height * 0.16)), (render_width, int(render_height * 0.1))],
        fill=(120, 170, 225, 24),
        width=6,
    )
    return img



def create_tagesschau_idle_background_light(render_width: int, render_height: int) -> Image.Image:
    """Heller Hintergrund für das Tagesschau-Modul (Light-Theme)."""
    img = Image.new("RGB", (render_width, render_height), (246, 242, 236))
    draw = ImageDraw.Draw(img, "RGBA")

    fill_vertical_gradient(draw, render_width, render_height, (248, 244, 238), (236, 230, 220))

    draw.ellipse(
        [(-100, -80), (int(render_width * 0.46), int(render_height * 0.28))],
        fill=(215, 205, 190, 40),
    )
    draw.ellipse(
        [(int(render_width * 0.55), -60), (render_width + 80, int(render_height * 0.22))],
        fill=(208, 196, 178, 35),
    )
    draw.rounded_rectangle(
        [(-60, int(render_height * 0.68)), (render_width + 60, render_height + 80)],
        radius=100,
        fill=(225, 218, 208, 70),
    )
    return img



# ---------------------------------------------------------------------------
# Zeichenfunktionen
# ---------------------------------------------------------------------------

def draw_idle_empty_state(
    draw: ImageDraw.ImageDraw,
    render_height: int,
    font_idle,
    font_idle_sub,
    theme: str = "dark",
):
    pal = _news_pal(theme)
    draw.text(
        (80, render_height - 230),
        "Tagesschau",
        font=font_idle,
        fill=pal["empty_title"],
    )
    draw.text(
        (80, render_height - 140),
        "Gerade keine Nachrichten verfügbar.",
        font=font_idle_sub,
        fill=pal["empty_sub"],
    )


def draw_tagesschau_header(
    draw: ImageDraw.ImageDraw,
    font_idle,
    font_idle_sub,
    font_news_label,
    theme: str = "dark",
):
    pal = _news_pal(theme)
    draw.text((80, 72),  format_date_long(),      font=font_idle_sub,   fill=pal["idle_text"])
    draw.text((80, 126), "Tagesschau",            font=font_idle,        fill=pal["title_text"])
    draw.text((82, 228), "Aktuelle Schlagzeilen", font=font_news_label,  fill=pal["label_text"])


def draw_card_thumbnail(
    img: Image.Image,
    x: int,
    y: int,
    width: int,
    height: int,
    thumb: Image.Image,
    border_color: Color4 = (255, 255, 255, 60),
    flat: bool = False,
):
    if not flat:
        shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow, "RGBA")
        shadow_draw.rounded_rectangle(
            [(x + 6, y + 8), (x + width + 6, y + height + 8)],
            radius=20,
            fill=(0, 0, 0, 135),
        )
        img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(radius=10)))

    border = Image.new("RGBA", img.size, (0, 0, 0, 0))
    border_draw = ImageDraw.Draw(border, "RGBA")
    border_draw.rounded_rectangle(
        [(x - 2, y - 2), (x + width + 2, y + height + 2)],
        radius=0 if flat else 20,
        outline=border_color,
        width=4 if flat else 2,
    )
    img.alpha_composite(border)
    img.alpha_composite(thumb, (x, y))


def apply_frosted_panel(
    img: Image.Image,
    bounds: tuple[int, int, int, int],
    radius: int,
    blur_radius: int,
    tint: Color4,
    outline: Color4,
    outline_width: int = 2,
):
    left, top, right, bottom = bounds
    panel_w = max(1, right - left)
    panel_h = max(1, bottom - top)

    backdrop = img.crop((left, top, right, bottom)).convert("RGBA")
    if blur_radius > 0 and len(tint) > 3 and tint[3] < 255:
        # Nur blurren, wenn die Tönung durchscheinend ist – bei deckenden
        # E-Ink-Flächen wäre das verschwendete Arbeit
        backdrop = backdrop.filter(ImageFilter.GaussianBlur(radius=blur_radius))
    backdrop.alpha_composite(Image.new("RGBA", (panel_w, panel_h), tint))

    mask = Image.new("L", (panel_w, panel_h), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle([(0, 0), (panel_w - 1, panel_h - 1)], radius=radius, fill=255)
    backdrop.putalpha(mask)
    img.alpha_composite(backdrop, (left, top))

    border = Image.new("RGBA", img.size, (0, 0, 0, 0))
    border_draw = ImageDraw.Draw(border, "RGBA")
    border_draw.rounded_rectangle(bounds, radius=radius, outline=outline, width=outline_width)
    img.alpha_composite(border)


def draw_tagesschau_card(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    item: dict,
    top: int,
    bottom: int,
    render_width: int,
    font_news_label,
    font_news_title,
    font_news_summary,
    load_font: FontLoader,
    fetch_image: ImageFetcher,
    create_thumbnail: ThumbnailFactory,
    theme: str = "dark",
):
    pal = _news_pal(theme)
    flat = bool(pal.get("flat"))
    card_bounds = (60, top, render_width - 60, bottom)
    apply_frosted_panel(
        img,
        card_bounds,
        radius=0 if flat else 24,
        blur_radius=20,
        tint=pal["card_tint"],
        outline=pal["card_outline"],
        outline_width=3 if flat else 2,
    )

    inner_x = 88
    inner_y = top + 20
    inner_width = render_width - 176
    inner_height = bottom - top - 40
    image = fetch_image(item.get("image_url", ""))
    image_box_w = 0

    if image is not None:
        image_box_h = min(max(118, inner_height - 4), inner_height)
        image_box_w = min(236, max(192, int(inner_width * 0.3)))
        if flat:
            # E-Ink: Foto unverändert (kein Entsättigen/Abdunkeln), eckig – das Dithering
            # macht aus einem satten Foto ein lesbares Bild, aus einem grauen nur Matsch
            thumb = fit_crop(image, image_box_w, image_box_h).convert("RGBA")
        else:
            thumb = create_thumbnail(image, image_box_w, image_box_h, 18)
        draw_card_thumbnail(img, inner_x, inner_y, image_box_w, image_box_h, thumb,
                            border_color=pal["thumb_border"], flat=flat)

    text_x = inner_x + image_box_w + 24 if image_box_w else inner_x
    text_width = inner_width - image_box_w - 24 if image_box_w else inner_width
    meta_label = (item.get("meta") or "").strip()

    meta_font, meta_lines, meta_line_h, meta_spacing, meta_total_h = fit_optional_text_block(
        draw, meta_label, text_width, int(inner_height * 0.11),
        22, 18, font_news_label, load_font, is_bold=True, max_lines=1, line_spacing=0.08,
    )
    title_font, title_lines, title_line_h, title_spacing, title_total_h = fit_optional_text_block(
        draw, item["title"], text_width,
        int(inner_height * (0.24 if meta_lines else 0.28)),
        29, 22, font_news_title, load_font, is_bold=True, max_lines=2, line_spacing=0.08,
    )

    summary_start_y = inner_y
    if meta_lines:
        summary_start_y += meta_total_h + 6
    if title_lines:
        summary_start_y += title_total_h + 6

    text_bottom_limit = inner_y + inner_height - 16
    summary_max_height = max(0, text_bottom_limit - summary_start_y)

    summary_font, summary_lines, summary_line_h, summary_spacing, summary_total_h = fit_optional_text_block(
        draw, item["summary"], text_width, summary_max_height,
        24, 22, font_news_summary, load_font, is_bold=False, max_lines=14, line_spacing=0.1,
    )

    # Wenn der Summary-Block sehr knapp auf Kante sitzt, etwas früher kürzen,
    # statt die letzte Zeile optisch in den unteren Rand laufen zu lassen.
    if summary_lines and summary_total_h >= max(0, summary_max_height - 2):
        summary_font, summary_lines, summary_line_h, summary_spacing, _ = fit_optional_text_block(
            draw, item["summary"], text_width, max(0, summary_max_height - 8),
            24, 22, font_news_summary, load_font, is_bold=False, max_lines=13, line_spacing=0.1,
        )

    current_y = inner_y
    if meta_lines:
        current_y = draw_lines(draw, text_x, current_y, meta_lines, meta_font,
                               pal["meta_color"], meta_line_h, meta_spacing)
        current_y += 6

    current_y = draw_lines(draw, text_x, current_y, title_lines,
                           title_font or font_news_title, pal["news_title"],
                           title_line_h, title_spacing)

    if summary_lines:
        current_y += 6
        draw_lines(draw, text_x, current_y, summary_lines, summary_font,
                   pal["news_summary"], summary_line_h, summary_spacing)


def draw_idle_overlay(
    base: Image.Image,
    news_items: list[dict] | None,
    render_width: int,
    render_height: int,
    load_font: FontLoader,
    fetch_image: ImageFetcher,
    create_thumbnail: ThumbnailFactory,
    display_theme: str = "dark",
) -> Image.Image:
    img = base.copy().convert("RGBA")
    draw = ImageDraw.Draw(img, "RGBA")

    news_items = news_items or []
    font_idle = load_font(84, True)
    font_idle_sub = load_font(40, False)
    font_news_label = load_font(28, True)
    font_news_title = load_font(34, True)
    font_news_summary = load_font(24, False)

    if not news_items:
        draw_idle_empty_state(draw, render_height, font_idle, font_idle_sub, theme=display_theme)
        return img.convert("RGB")

    draw_tagesschau_header(draw, font_idle, font_idle_sub, font_news_label, theme=display_theme)

    card_top = 290
    card_height = int((render_height - card_top - 70) / max(len(news_items), 1))
    card_gap = 14

    for idx, item in enumerate(news_items):
        top = card_top + idx * card_height
        bottom = min(render_height - 40, top + card_height - card_gap)
        draw_tagesschau_card(
            img, draw, item, top, bottom, render_width,
            font_news_label, font_news_title, font_news_summary,
            load_font, fetch_image, create_thumbnail,
            theme=display_theme,
        )

    return img.convert("RGB")


# ---------------------------------------------------------------------------
# Modul-Einstieg
# ---------------------------------------------------------------------------

def render_tagesschau_module(services: ModuleRenderServices, content: object) -> Image.Image:
    from .data_source import fetch_tagesschau_image

    news_items = content if isinstance(content, list) else []
    theme = services.display_theme
    if theme == "eink":
        from app.image_rendering import SPECTRA6_COLORS
        base = Image.new("RGB", (services.render_width, services.render_height), SPECTRA6_COLORS["white"])
    elif theme == "light":
        base = create_tagesschau_idle_background_light(services.render_width, services.render_height)
    else:
        base = create_tagesschau_idle_background(services.render_width, services.render_height)
    return draw_idle_overlay(
        base,
        news_items,
        services.render_width,
        services.render_height,
        services.load_font,
        fetch_tagesschau_image,
        create_rounded_thumbnail,
        display_theme=theme,
    )
