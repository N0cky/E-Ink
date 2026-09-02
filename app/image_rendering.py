"""
Bild-Kompositions-Helpers: Skalierung, Overlays, Gradienten, Fortschrittsbalken.
"""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFilter



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

COVER_MAX_FRACTION      = 0.78  # Anteil des Covers an der Rendergröße
COVER_VERTICAL_OFFSET   = -30   # px vertikaler Versatz des zentrierten Covers
LIGHT_BG_COLOR              = (250, 248, 244)
LIGHT_COVER_VERTICAL_OFFSET = -185  # Cover im Light-Theme stark nach oben, damit unten Platz für Text ist


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
# Light-Theme Canvas
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
