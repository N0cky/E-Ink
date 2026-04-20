"""
Bild-Kompositions-Helpers: Skalierung, Overlays, Gradienten, Fortschrittsbalken.
"""

from __future__ import annotations

from datetime import datetime

from PIL import Image, ImageDraw, ImageFilter

from app.config import get_bool_setting, get_cfg, load_font
from app.idle_news_rendering import draw_lines, fit_wrapped_text


# ---------------------------------------------------------------------------
# Spectra 6 – Farbkonvertierung für Waveshare E-Ink-Farbdisplay
# ---------------------------------------------------------------------------

# Reale Farben wie sie auf dem Display erscheinen (für Quantisierung/Dithering)
_SPECTRA6_REAL_WORLD_RGB: list[tuple[int, int, int]] = [
    (25, 30, 33),    # Schwarz
    (232, 232, 232), # Weiß
    (239, 222, 68),  # Gelb
    (178, 19, 24),   # Rot
    (33, 87, 186),   # Blau
    (18, 95, 32),    # Grün
]

# Geräte-RGB-Werte, die das Display-Protokoll erwartet
_SPECTRA6_DEVICE_RGB: list[tuple[int, int, int]] = [
    (0, 0, 0),       # Schwarz
    (255, 255, 255),  # Weiß
    (255, 255, 0),    # Gelb
    (255, 0, 0),      # Rot
    (0, 0, 255),      # Blau
    (0, 255, 0),      # Grün
]


def convert_to_spectra6(img: Image.Image) -> tuple[Image.Image, Image.Image]:
    """Konvertiert ein RGB-Bild für das Waveshare Spectra 6 E-Ink-Display.

    Nutzt Floyd-Steinberg-Dithering und die realen Display-Farbwerte
    (portiert aus dem Waveshare-Konvertierungsskript).

    Rückgabe:
        device_img  – BMP-fertiges Bild mit Geräte-RGB (sieht am PC falsch aus,
                      wird vom E-Ink-Display korrekt interpretiert)
        preview_img – Vorschau mit realen Farben (korrekte Darstellung am PC /
                      in der Settings-Seite)
    """
    # Paletten-Bild mit realen Farbwerten aufbauen (6 Farben + 250× Schwarz-Auffüllung)
    pal_image = Image.new("P", (1, 1))
    pal_flat  = tuple(v for rgb in _SPECTRA6_REAL_WORLD_RGB for v in rgb)
    pal_flat += _SPECTRA6_REAL_WORLD_RGB[0] * 250  # restliche 250 Paletteneinträge mit Schwarz
    pal_image.putpalette(pal_flat)

    # Quantisierung mit Floyd-Steinberg-Dithering → Palette-Modus P
    quantized_p = img.convert("RGB").quantize(
        dither=Image.Dither.FLOYDSTEINBERG,
        palette=pal_image,
    )

    # Vorschau-Bild: Palettenindizes → reale Farben
    preview_img = quantized_p.convert("RGB")

    # Device-Bild: Palette durch Gerätefarben ersetzen (gleiche Indexreihenfolge)
    dev_pal  = tuple(v for rgb in _SPECTRA6_DEVICE_RGB for v in rgb)
    dev_pal += _SPECTRA6_DEVICE_RGB[0] * 250
    device_p = quantized_p.copy()
    device_p.putpalette(dev_pal)
    device_img = device_p.convert("RGB")

    return device_img, preview_img


# ---------------------------------------------------------------------------
# Layout-Konstanten (benannte Konstanten statt magischer Zahlen)
# ---------------------------------------------------------------------------

OVERLAY_X_MARGIN      = 80    # px linker/rechter Rand für Text im Overlay
PROGRESS_BAR_Y_OFFSET = 55    # px Abstand Progress-Bar vom unteren Bildrand
PROGRESS_BAR_HEIGHT   = 18    # px Höhe des Fortschrittsbalkens
TIMESTAMP_X_OFFSET    = 420   # px Abstand Timestamp vom rechten Rand
TIMESTAMP_Y           = 40    # px Abstand Timestamp vom oberen Rand
PROGRESS_BOTTOM_RESERVE = 60  # px Puffer für Progress-Bar-Block
STATUS_BOTTOM_RESERVE   = 45  # px Puffer für Status-Label-Block
OVERLAY_TEXT_TOP_OFFSET = 35  # px Abstand Text-Anfang von Overlay-Oberkante
MIN_VIDEO_TEXT_HEIGHT   = 120 # px Mindesthöhe Textbereich Video
MIN_MUSIC_TEXT_HEIGHT   = 160 # px Mindesthöhe Textbereich Musik
COVER_MAX_FRACTION      = 0.78  # Anteil des Covers an der Rendergröße
COVER_VERTICAL_OFFSET   = -30   # px vertikaler Versatz des zentrierten Covers

# Light-Theme-Konstanten
LIGHT_BG_COLOR              = (250, 248, 244)
LIGHT_TEXT_PRIMARY          = (25, 20, 15, 255)
LIGHT_TEXT_SECONDARY        = (90, 85, 78, 255)
LIGHT_TEXT_META             = (140, 133, 124, 255)
LIGHT_PROGRESS_TRACK        = (205, 200, 192, 255)
LIGHT_PROGRESS_FILL         = (30, 25, 20, 255)
LIGHT_COVER_VERTICAL_OFFSET = -185  # Cover im Light-Theme stark nach oben, damit unten Platz für Text ist
LIGHT_PANEL_PADDING         = 80    # px seitlicher Textabstand im Light-Panel


# ---------------------------------------------------------------------------
# Bild-Skalierung und -Beschnitt
# ---------------------------------------------------------------------------

def resize_to_fit(img: Image.Image, max_width: int, max_height: int) -> Image.Image:
    src_w, src_h = img.size
    scale = min(max_width / src_w, max_height / src_h)
    return img.resize((max(1, int(src_w * scale)), max(1, int(src_h * scale))), Image.LANCZOS)


def fit_crop(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    src_w, src_h = img.size
    src_ratio    = src_w / src_h
    target_ratio = target_w / target_h
    if src_ratio > target_ratio:
        new_h, new_w = target_h, int(target_h * src_ratio)
    else:
        new_w, new_h = target_w, int(target_w / src_ratio)
    img  = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    top  = (new_h - target_h) // 2
    return img.crop((left, top, left + target_w, top + target_h))


def create_blurred_cover_background(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    bg = fit_crop(img, target_w, target_h).filter(ImageFilter.GaussianBlur(radius=28))
    bg = bg.convert("RGBA")
    bg.alpha_composite(Image.new("RGBA", (target_w, target_h), (0, 0, 0, 85)))
    return bg.convert("RGB")


def create_centered_cover_canvas(
    img: Image.Image,
    target_w: int,
    target_h: int,
    vertical_offset: int = COVER_VERTICAL_OFFSET,
) -> Image.Image:
    background = create_blurred_cover_background(img, target_w, target_h)
    bg = background.copy()

    max_cover_w = int(target_w * COVER_MAX_FRACTION)
    max_cover_h = int(target_h * COVER_MAX_FRACTION)
    cover       = resize_to_fit(img, max_cover_w, max_cover_h)
    cover_w, cover_h = cover.size

    cover_x = (target_w - cover_w) // 2
    cover_y = (target_h - cover_h) // 2 + vertical_offset

    shadow = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    ImageDraw.Draw(shadow, "RGBA").rounded_rectangle(
        [(cover_x + 10, cover_y + 14), (cover_x + cover_w + 10, cover_y + cover_h + 14)],
        radius=24, fill=(0, 0, 0, 120),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=16))

    bg_rgba = bg.convert("RGBA")
    bg_rgba.alpha_composite(shadow)

    border_layer = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    ImageDraw.Draw(border_layer, "RGBA").rounded_rectangle(
        [(cover_x - 4, cover_y - 4), (cover_x + cover_w + 4, cover_y + cover_h + 4)],
        radius=26, fill=(255, 255, 255, 25),
    )
    bg_rgba.alpha_composite(border_layer)
    bg_rgba.paste(cover, (cover_x, cover_y))
    return bg_rgba.convert("RGB")


def create_rounded_thumbnail(img: Image.Image, target_w: int, target_h: int, radius: int = 18) -> Image.Image:
    thumb = fit_crop(img, target_w, target_h).convert("RGBA")
    thumb = Image.blend(thumb, thumb.convert("L").convert("RGBA"), alpha=0.45)
    thumb.alpha_composite(Image.new("RGBA", (target_w, target_h), (0, 0, 0, 60)))
    mask = Image.new("L", (target_w, target_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([(0, 0), (target_w, target_h)], radius=radius, fill=255)
    thumb.putalpha(mask)
    return thumb


# ---------------------------------------------------------------------------
# Fortschritt und Zeitstempel
# ---------------------------------------------------------------------------

def calc_progress(session: dict | None) -> float:
    if not session:
        return 0.0
    try:
        duration_i = max(int(session.get("duration") or 0), 1)
        offset_i   = max(int(session.get("viewOffset") or 0), 0)
        return min(offset_i / duration_i, 1.0)
    except Exception:
        return 0.0


def draw_progress_bar(
    img: Image.Image,
    progress: float,
    x: int, y: int, width: int, height: int,
    show: bool,
) -> None:
    """Zeichnet den Fortschrittsbalken korrekt via RGBA-Overlay-Kompositing."""
    if not show:
        return
    # Separate RGBA-Schicht, damit alpha korrekt auf dem RGB-Bild landet.
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    d.rounded_rectangle([(x, y), (x + width, y + height)], radius=8, fill=(255, 255, 255, 70))
    d.rounded_rectangle([(x, y), (x + int(width * progress), y + height)], radius=8, fill=(255, 255, 255, 210))
    img.paste(Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB"))


def draw_updated_timestamp(
    draw: ImageDraw.ImageDraw, font, text_x: int, text_y: int, show: bool
) -> None:
    if not show:
        return
    stamp = datetime.now().strftime("Aktualisiert: %d.%m.%Y %H:%M")
    draw.text((text_x, text_y), stamp, font=font, fill=(255, 255, 255, 230))


def get_bottom_reserved_space(show_progress_bar: bool) -> int:
    return (PROGRESS_BOTTOM_RESERVE if show_progress_bar else 0) + STATUS_BOTTOM_RESERVE


# ---------------------------------------------------------------------------
# Gradient
# ---------------------------------------------------------------------------

def draw_bottom_gradient(
    img: Image.Image,
    overlay_height: int,
    alpha_max: int,
    render_width: int,
    render_height: int,
) -> None:
    """Schwarzer Transparenz-Verlauf am unteren Bildrand via PIL-Byte-Buffer."""
    alphas   = [int(alpha_max * i / overlay_height) for i in range(overlay_height)]
    row_bytes = [bytes([0, 0, 0, a]) * render_width for a in alphas]
    gradient  = Image.frombytes("RGBA", (render_width, overlay_height), b"".join(row_bytes))
    black     = Image.new("RGB", (render_width, overlay_height), (0, 0, 0))
    img.paste(black, (0, render_height - overlay_height), gradient.getchannel("A"))


# ---------------------------------------------------------------------------
# Gemeinsame Overlay-Basis
# ---------------------------------------------------------------------------

def _setup_overlay_base(cfg, base: Image.Image, overlay_h_fraction: float, alpha_max: int):
    """Bereitet die gemeinsame Grundstruktur beider Overlays vor."""
    img  = base.copy()
    draw = ImageDraw.Draw(img, "RGBA")
    font_small  = load_font(28, is_bold=False)
    overlay_h   = int(cfg.render_height * overlay_h_fraction)
    draw_bottom_gradient(img, overlay_h, alpha_max, cfg.render_width, cfg.render_height)

    x           = OVERLAY_X_MARGIN
    text_width  = cfg.render_width - 2 * x
    progress_y  = cfg.render_height - PROGRESS_BAR_Y_OFFSET
    reserved_bottom = get_bottom_reserved_space(get_bool_setting("SHOW_PROGRESS_BAR", True))
    text_top    = cfg.render_height - overlay_h + OVERLAY_TEXT_TOP_OFFSET
    text_bottom_limit = progress_y - reserved_bottom

    layout = {
        "x": x,
        "text_width": text_width,
        "progress_y": progress_y,
        "text_top": text_top,
        "text_bottom_limit": text_bottom_limit,
    }
    return img, draw, font_small, layout


# ---------------------------------------------------------------------------
# Overlay-Rendering
# ---------------------------------------------------------------------------

def draw_video_overlay(base: Image.Image, session: dict) -> Image.Image:
    from app.plex import get_playback_label
    cfg = get_cfg()
    img, draw, font_small, layout = _setup_overlay_base(cfg, base, 0.42, 240)

    title       = session.get("title", "Unbekannt")
    grandparent = session.get("grandparentTitle", "")
    media_type  = session.get("type", "video")
    year        = session.get("year", "")
    parent_index = session.get("parentIndex", "")
    index       = session.get("index", "")
    player_state = session.get("playerState", "unknown")

    if media_type == "episode" and grandparent:
        subtitle  = grandparent
        meta_line = (f"Staffel {parent_index} · Folge {index}"
                     if parent_index and index else get_playback_label(player_state))
    else:
        subtitle  = year if year else ""
        meta_line = get_playback_label(player_state)

    x   = layout["x"]
    tw  = layout["text_width"]
    py  = layout["progress_y"]
    ttop = layout["text_top"]
    tbl  = layout["text_bottom_limit"]
    text_max_h = max(MIN_VIDEO_TEXT_HEIGHT, tbl - ttop)

    title_font, title_lines, title_lh, title_sp, title_th = fit_wrapped_text(
        draw, title, tw, int(text_max_h * 0.52), 72, 34, load_font, is_bold=True, max_lines=3, line_spacing=0.15)
    sub_font, sub_lines, sub_lh, sub_sp, sub_th = (
        fit_wrapped_text(draw, subtitle, tw, int(text_max_h * 0.22), 42, 24, load_font,
                         is_bold=False, max_lines=2, line_spacing=0.15)
        if subtitle else (None, [], 0, 0, 0)
    )
    meta_font, meta_lines, meta_lh, meta_sp, meta_th = fit_wrapped_text(
        draw, meta_line, tw, int(text_max_h * 0.20), 42, 24, load_font, is_bold=False, max_lines=2, line_spacing=0.15)

    block_h = title_th + (20 if sub_lines else 0) + sub_th + 18 + meta_th
    cur_y = max(ttop, tbl - block_h)
    cur_y = draw_lines(draw, x, cur_y, title_lines, title_font, (255, 255, 255, 255), title_lh, title_sp)
    if sub_lines:
        cur_y += 20
        cur_y = draw_lines(draw, x, cur_y, sub_lines, sub_font, (235, 235, 235, 255), sub_lh, sub_sp)
    cur_y += 18
    draw_lines(draw, x, cur_y, meta_lines, meta_font, (235, 235, 235, 255), meta_lh, meta_sp)

    show_progress = get_bool_setting("SHOW_PROGRESS_BAR", True)
    show_updated = get_bool_setting("SHOW_UPDATED_TIMESTAMP", True)
    draw_progress_bar(img, calc_progress(session), x, py, cfg.render_width - 2 * x, PROGRESS_BAR_HEIGHT, show_progress)
    draw_updated_timestamp(draw, font_small, cfg.render_width - TIMESTAMP_X_OFFSET, TIMESTAMP_Y, show_updated)
    return img


def draw_music_overlay(base: Image.Image, session: dict) -> Image.Image:
    from app.plex import get_playback_label
    cfg = get_cfg()
    img, draw, font_small, layout = _setup_overlay_base(cfg, base, 0.46, 245)

    title        = session.get("title", "Unbekannt")
    artist       = session.get("grandparentTitle", "")
    album        = session.get("parentTitle", "")
    track_no     = session.get("index", "")
    player_state = session.get("playerState", "unknown")

    album_line = (f"{album} · Track {track_no}" if album else f"Track {track_no}") if track_no else album
    info_line  = get_playback_label(player_state, "Musik")

    x    = layout["x"]
    tw   = layout["text_width"]
    py   = layout["progress_y"]
    ttop = layout["text_top"]
    tbl  = layout["text_bottom_limit"]
    text_max_h = max(MIN_MUSIC_TEXT_HEIGHT, tbl - ttop)

    title_font,  title_lines,  title_lh,  title_sp,  title_th  = fit_wrapped_text(
        draw, title, tw, int(text_max_h * 0.38), 78, 34, load_font, is_bold=True, max_lines=3, line_spacing=0.15)
    artist_font, artist_lines, artist_lh, artist_sp, artist_th = (
        fit_wrapped_text(draw, artist, tw, int(text_max_h * 0.22), 48, 24, load_font,
                         is_bold=False, max_lines=2, line_spacing=0.15)
        if artist else (None, [], 0, 0, 0)
    )
    album_font,  album_lines,  album_lh,  album_sp,  album_th  = (
        fit_wrapped_text(draw, album_line, tw, int(text_max_h * 0.18), 38, 22, load_font,
                         is_bold=False, max_lines=2, line_spacing=0.15)
        if album_line else (None, [], 0, 0, 0)
    )
    info_font,   info_lines,   info_lh,   info_sp,   info_th   = fit_wrapped_text(
        draw, info_line, tw, int(text_max_h * 0.14), 38, 22, load_font, is_bold=False, max_lines=1, line_spacing=0.15)

    block_h = (title_th + (18 if artist_lines else 0) + artist_th
               + (16 if album_lines else 0) + album_th + 16 + info_th)
    cur_y = max(ttop, tbl - block_h)
    cur_y = draw_lines(draw, x, cur_y, title_lines, title_font, (255, 255, 255, 255), title_lh, title_sp)
    if artist_lines:
        cur_y += 18
        cur_y = draw_lines(draw, x, cur_y, artist_lines, artist_font, (235, 235, 235, 255), artist_lh, artist_sp)
    if album_lines:
        cur_y += 16
        cur_y = draw_lines(draw, x, cur_y, album_lines, album_font, (220, 220, 220, 255), album_lh, album_sp)
    cur_y += 16
    draw_lines(draw, x, cur_y, info_lines, info_font, (220, 220, 220, 255), info_lh, info_sp)

    show_progress = get_bool_setting("SHOW_PROGRESS_BAR", True)
    show_updated = get_bool_setting("SHOW_UPDATED_TIMESTAMP", True)
    draw_progress_bar(img, calc_progress(session), x, py, cfg.render_width - 2 * x, PROGRESS_BAR_HEIGHT, show_progress)
    draw_updated_timestamp(draw, font_small, cfg.render_width - TIMESTAMP_X_OFFSET, TIMESTAMP_Y, show_updated)
    return img


# ---------------------------------------------------------------------------
# Light-Theme Canvas und Overlays
# ---------------------------------------------------------------------------

def create_light_cover_canvas(
    img: Image.Image,
    target_w: int,
    target_h: int,
) -> tuple[Image.Image, int]:
    """Light-Theme: Cover exakt gleich groß wie Dark-Theme, heller Cover-Blur als Hintergrund.

    Gibt (canvas, cover_bottom_y) zurück, damit Overlay-Funktionen den Textbereich
    dynamisch unterhalb des Covers positionieren können.
    """
    # ── 1. Hintergrund: Cover unscharf + heller Schleier ─────────────────────
    blurred_bg = fit_crop(img, target_w, target_h)
    blurred_bg = blurred_bg.filter(ImageFilter.GaussianBlur(radius=48))
    blurred_bg = blurred_bg.convert("RGBA")
    veil = Image.new("RGBA", (target_w, target_h), (250, 248, 244, 175))
    blurred_bg.alpha_composite(veil)
    bg_rgba = blurred_bg

    # ── 2. Cover – identische Größe wie Dark-Theme, aber stärker nach oben ──
    max_cover_w = int(target_w * COVER_MAX_FRACTION)
    max_cover_h = int(target_h * COVER_MAX_FRACTION)
    cover       = resize_to_fit(img, max_cover_w, max_cover_h)
    cw, ch      = cover.size

    # Stärkerer Versatz nach oben, damit unten Platz für Text entsteht
    cx = (target_w - cw) // 2
    cy = (target_h - ch) // 2 + LIGHT_COVER_VERTICAL_OFFSET
    cy = max(16, cy)  # nie über den oberen Bildrand
    cover_bottom = cy + ch  # tatsächliche Unterkante des Covers

    # ── 3. Schatten ──────────────────────────────────────────────────────────
    shadow = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    ImageDraw.Draw(shadow, "RGBA").rounded_rectangle(
        [(cx + 8, cy + 12), (cx + cw + 8, cy + ch + 12)],
        radius=24, fill=(0, 0, 0, 80),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=18))
    bg_rgba.alpha_composite(shadow)

    # ── 4. Feiner Rahmen ─────────────────────────────────────────────────────
    border_layer = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    ImageDraw.Draw(border_layer, "RGBA").rounded_rectangle(
        [(cx - 4, cy - 4), (cx + cw + 4, cy + ch + 4)],
        radius=26, fill=(160, 155, 148, 55),
    )
    bg_rgba.alpha_composite(border_layer)

    # ── 5. Cover einfügen ────────────────────────────────────────────────────
    bg_rgba.paste(cover, (cx, cy))
    return bg_rgba.convert("RGB"), cover_bottom


def _draw_light_progress_bar(
    draw: ImageDraw.ImageDraw,
    progress: float,
    x: int, y: int, width: int, height: int,
    show: bool,
) -> None:
    if not show:
        return
    draw.rounded_rectangle([(x, y), (x + width, y + height)], radius=8, fill=LIGHT_PROGRESS_TRACK)
    fill_w = max(height, int(width * progress))  # min width = height (fully round)
    draw.rounded_rectangle([(x, y), (x + fill_w, y + height)], radius=8, fill=LIGHT_PROGRESS_FILL)


def draw_video_overlay_light(base: Image.Image, session: dict, cover_bottom: int) -> Image.Image:
    from app.plex import get_playback_label
    cfg = get_cfg()
    img  = base.copy()
    draw = ImageDraw.Draw(img)

    title        = session.get("title", "Unbekannt")
    grandparent  = session.get("grandparentTitle", "")
    media_type   = session.get("type", "video")
    year         = session.get("year", "")
    parent_index = session.get("parentIndex", "")
    index        = session.get("index", "")
    player_state = session.get("playerState", "unknown")

    if media_type == "episode" and grandparent:
        subtitle  = grandparent
        meta_line = (f"Staffel {parent_index} · Folge {index}"
                     if parent_index and index else get_playback_label(player_state))
    else:
        subtitle  = year if year else ""
        meta_line = get_playback_label(player_state)

    # Text-Panel beginnt direkt unterhalb des Covers (dynamisch, kein fester Bruchteil).
    panel_top = cover_bottom + 24

    x  = LIGHT_PANEL_PADDING
    tw = cfg.render_width - 2 * x
    py = cfg.render_height - PROGRESS_BAR_Y_OFFSET

    show_progress = get_bool_setting("SHOW_PROGRESS_BAR", True)
    show_updated = get_bool_setting("SHOW_UPDATED_TIMESTAMP", True)
    reserved    = get_bottom_reserved_space(show_progress)
    text_top    = panel_top + 22
    text_bottom = py - reserved
    text_max_h  = max(MIN_VIDEO_TEXT_HEIGHT, text_bottom - text_top)

    font_small = load_font(26, is_bold=False)

    title_font, title_lines, title_lh, title_sp, title_th = fit_wrapped_text(
        draw, title, tw, int(text_max_h * 0.52), 68, 28, load_font, is_bold=True, max_lines=3, line_spacing=0.14)
    sub_font, sub_lines, sub_lh, sub_sp, sub_th = (
        fit_wrapped_text(draw, subtitle, tw, int(text_max_h * 0.24), 40, 22, load_font,
                         is_bold=False, max_lines=2, line_spacing=0.14)
        if subtitle else (None, [], 0, 0, 0)
    )
    meta_font, meta_lines, meta_lh, meta_sp, meta_th = fit_wrapped_text(
        draw, meta_line, tw, int(text_max_h * 0.20), 36, 20, load_font,
        is_bold=False, max_lines=2, line_spacing=0.14)

    block_h = title_th + (16 if sub_lines else 0) + sub_th + 14 + meta_th
    cur_y   = max(text_top, text_bottom - block_h)
    cur_y   = draw_lines(draw, x, cur_y, title_lines, title_font, LIGHT_TEXT_PRIMARY,   title_lh, title_sp)
    if sub_lines:
        cur_y += 16
        cur_y = draw_lines(draw, x, cur_y, sub_lines,   sub_font,   LIGHT_TEXT_SECONDARY, sub_lh,   sub_sp)
    cur_y += 14
    draw_lines(draw, x, cur_y, meta_lines, meta_font, LIGHT_TEXT_META, meta_lh, meta_sp)

    _draw_light_progress_bar(draw, calc_progress(session), x, py,
                             cfg.render_width - 2 * x, PROGRESS_BAR_HEIGHT, show_progress)
    if show_updated:
        stamp = datetime.now().strftime("Aktualisiert: %d.%m.%Y %H:%M")
        draw.text((cfg.render_width - TIMESTAMP_X_OFFSET, TIMESTAMP_Y), stamp,
                  font=font_small, fill=LIGHT_TEXT_META)
    return img


def draw_music_overlay_light(base: Image.Image, session: dict, cover_bottom: int) -> Image.Image:
    from app.plex import get_playback_label
    cfg = get_cfg()
    img  = base.copy()
    draw = ImageDraw.Draw(img)

    title        = session.get("title", "Unbekannt")
    artist       = session.get("grandparentTitle", "")
    album        = session.get("parentTitle", "")
    track_no     = session.get("index", "")
    player_state = session.get("playerState", "unknown")

    album_line = (f"{album} · Track {track_no}" if album else f"Track {track_no}") if track_no else album
    info_line  = get_playback_label(player_state, "Musik")

    # Text-Panel beginnt direkt unterhalb des Covers (dynamisch, kein fester Bruchteil).
    panel_top = cover_bottom + 24

    x  = LIGHT_PANEL_PADDING
    tw = cfg.render_width - 2 * x
    py = cfg.render_height - PROGRESS_BAR_Y_OFFSET

    show_progress = get_bool_setting("SHOW_PROGRESS_BAR", True)
    show_updated = get_bool_setting("SHOW_UPDATED_TIMESTAMP", True)
    reserved    = get_bottom_reserved_space(show_progress)
    text_top    = panel_top + 22
    text_bottom = py - reserved
    text_max_h  = max(MIN_MUSIC_TEXT_HEIGHT, text_bottom - text_top)

    font_small = load_font(26, is_bold=False)

    title_font,  title_lines,  title_lh,  title_sp,  title_th  = fit_wrapped_text(
        draw, title, tw, int(text_max_h * 0.38), 68, 28, load_font, is_bold=True, max_lines=3, line_spacing=0.14)
    artist_font, artist_lines, artist_lh, artist_sp, artist_th = (
        fit_wrapped_text(draw, artist, tw, int(text_max_h * 0.24), 44, 20, load_font,
                         is_bold=False, max_lines=2, line_spacing=0.14)
        if artist else (None, [], 0, 0, 0)
    )
    album_font,  album_lines,  album_lh,  album_sp,  album_th  = (
        fit_wrapped_text(draw, album_line, tw, int(text_max_h * 0.20), 34, 18, load_font,
                         is_bold=False, max_lines=2, line_spacing=0.14)
        if album_line else (None, [], 0, 0, 0)
    )
    info_font,   info_lines,   info_lh,   info_sp,   info_th   = fit_wrapped_text(
        draw, info_line, tw, int(text_max_h * 0.14), 34, 18, load_font,
        is_bold=False, max_lines=1, line_spacing=0.14)

    block_h = (title_th + (14 if artist_lines else 0) + artist_th
               + (12 if album_lines else 0) + album_th + 12 + info_th)
    cur_y   = max(text_top, text_bottom - block_h)
    cur_y   = draw_lines(draw, x, cur_y, title_lines,  title_font,  LIGHT_TEXT_PRIMARY,   title_lh,  title_sp)
    if artist_lines:
        cur_y += 14
        cur_y = draw_lines(draw, x, cur_y, artist_lines, artist_font, LIGHT_TEXT_SECONDARY, artist_lh, artist_sp)
    if album_lines:
        cur_y += 12
        cur_y = draw_lines(draw, x, cur_y, album_lines,  album_font,  LIGHT_TEXT_META,      album_lh,  album_sp)
    cur_y += 12
    draw_lines(draw, x, cur_y, info_lines, info_font, LIGHT_TEXT_META, info_lh, info_sp)

    _draw_light_progress_bar(draw, calc_progress(session), x, py,
                             cfg.render_width - 2 * x, PROGRESS_BAR_HEIGHT, show_progress)
    if show_updated:
        stamp = datetime.now().strftime("Aktualisiert: %d.%m.%Y %H:%M")
        draw.text((cfg.render_width - TIMESTAMP_X_OFFSET, TIMESTAMP_Y), stamp,
                  font=font_small, fill=LIGHT_TEXT_META)
    return img
