"""
Müllabfuhr-Renderer: nächster Abfuhrtag groß mit Tonne, darunter die
Termine der nächsten Tage. Drei Themes; E-Ink flach in Spectra-Farben.
"""

from __future__ import annotations

from datetime import date

from PIL import Image, ImageDraw

from app.config import format_date_long, format_weekday_short
from app.image_rendering import SPECTRA6_COLORS
from app.module_services import ModuleRenderServices
from app.text_rendering import draw_lines, fit_wrapped_text

Color = tuple[int, int, int, int]


def _c(name: str) -> Color:
    return (*SPECTRA6_COLORS[name], 255)


_PALETTES: dict[str, dict] = {
    "dark": {
        "flat": False,
        "bg":            (26, 28, 34, 255),
        "header":        (225, 228, 235, 255),
        "title":         (255, 255, 255, 255),
        "muted":         (160, 166, 178, 255),
        "text":          (240, 242, 246, 255),
        "accent":        (120, 180, 255, 255),
        "card_fill":     (40, 44, 54, 255),
        "card_outline":  (255, 255, 255, 40),
        "row_line":      (255, 255, 255, 28),
        "bin_outline":   (255, 255, 255, 90),
        "bins": {
            "black":  (78, 80, 88),
            "green":  (58, 150, 84),
            "yellow": (232, 196, 48),
            "blue":   (70, 130, 220),
            "red":    (208, 62, 58),
        },
    },
    "light": {
        "flat": False,
        "bg":            (244, 241, 236, 255),
        "header":        (60, 54, 46, 255),
        "title":         (24, 20, 16, 255),
        "muted":         (120, 112, 102, 255),
        "text":          (30, 26, 22, 255),
        "accent":        (30, 100, 170, 255),
        "card_fill":     (255, 254, 251, 255),
        "card_outline":  (150, 142, 130, 90),
        "row_line":      (0, 0, 0, 24),
        "bin_outline":   (0, 0, 0, 70),
        "bins": {
            "black":  (55, 55, 60),
            "green":  (48, 140, 76),
            "yellow": (236, 190, 30),
            "blue":   (40, 105, 200),
            "red":    (198, 50, 46),
        },
    },
    "eink": {
        "flat": True,
        "bg":            _c("white"),
        "header":        _c("black"),
        "title":         _c("black"),
        "muted":         _c("blue"),
        "text":          _c("black"),
        "accent":        _c("blue"),
        "card_fill":     _c("white"),
        "card_outline":  _c("black"),
        "row_line":      _c("black"),
        "bin_outline":   _c("black"),
        "bins": {
            "black":  SPECTRA6_COLORS["black"],
            "green":  SPECTRA6_COLORS["green"],
            "yellow": SPECTRA6_COLORS["yellow"],
            "blue":   SPECTRA6_COLORS["blue"],
            "red":    SPECTRA6_COLORS["red"],
        },
    },
}


def get_palette(theme: str) -> dict:
    return _PALETTES.get(theme, _PALETTES["dark"])


# ---------------------------------------------------------------------------
# Tonnen-Icon
# ---------------------------------------------------------------------------

def draw_bin(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int, color: tuple, pal: dict) -> None:
    """Mülltonne: Deckel, Korpus mit Griffleiste, zwei Räder. Größe frei skalierbar."""
    flat = pal["flat"]
    outline = pal["bin_outline"]
    ow = max(2, w // 22) if flat else max(1, w // 40)
    fill = (*color, 255)

    lid_h = max(4, int(h * 0.11))
    body_top = y + lid_h
    body_left = x + int(w * 0.08)
    body_right = x + w - int(w * 0.08)
    wheel_r = max(3, int(w * 0.09))
    body_bottom = y + h - wheel_r

    # Deckel (etwas breiter als der Korpus)
    draw.rounded_rectangle([(x, y), (x + w, y + lid_h)], radius=0 if flat else lid_h // 2,
                           fill=fill, outline=outline, width=ow)
    # Griff auf dem Deckel
    handle_w = int(w * 0.28)
    draw.rectangle([(x + (w - handle_w) // 2, y - max(2, lid_h // 3)), (x + (w + handle_w) // 2, y)],
                   fill=fill, outline=outline, width=ow)
    # Korpus
    draw.rounded_rectangle([(body_left, body_top), (body_right, body_bottom)],
                           radius=0 if flat else max(4, w // 12), fill=fill, outline=outline, width=ow)
    # Rillen (Kontrast auf Weiß/Schwarz-Tonnen)
    groove = pal["card_fill"] if flat else (*pal["bg"][:3], 110)
    for i in (1, 2):
        gx = body_left + int((body_right - body_left) * i / 3)
        draw.line([(gx, body_top + int(h * 0.12)), (gx, body_bottom - int(h * 0.08))], fill=groove, width=max(2, ow))
    # Räder
    for wx in (body_left + wheel_r + ow, body_right - wheel_r - ow):
        draw.ellipse([(wx - wheel_r, body_bottom - wheel_r // 2), (wx + wheel_r, body_bottom + wheel_r + wheel_r // 2)],
                     fill=pal["text"] if flat else (*color, 255), outline=outline, width=ow)


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

def _short_date(d: date) -> str:
    return f"{format_weekday_short(d)} {d.day:02d}.{d.month:02d}."


def render_garbage_module(services: ModuleRenderServices, content: object) -> Image.Image:
    data = content if isinstance(content, dict) else {}
    rw, rh = services.render_width, services.render_height
    pal = get_palette(services.display_theme)
    flat = pal["flat"]
    load_font = services.load_font

    img = Image.new("RGBA", (rw, rh), pal["bg"])
    draw = ImageDraw.Draw(img, "RGBA")

    margin = max(40, rw // 20)
    scale = min(rw / 1200.0, rh / 1600.0)

    def px(v: float) -> int:
        return max(1, int(v * scale))

    # ── Kopfzeile ────────────────────────────────────────────────────────────
    font_date  = load_font(px(32), False)
    font_title = load_font(px(60), True)
    draw.text((margin, px(46)), format_date_long(), font=font_date, fill=pal["header"])
    draw.text((margin, px(86)), "Müllabfuhr", font=font_title, fill=pal["title"])

    next_day = data.get("next")
    days = data.get("days") or []
    y = px(180)

    # ── Hero: nächster Abfuhrtag ─────────────────────────────────────────────
    hero_h = px(420)
    hero = (margin, y, rw - margin, y + hero_h)
    draw.rounded_rectangle(hero, radius=0 if flat else px(28), fill=pal["card_fill"],
                           outline=pal["card_outline"], width=4 if flat else 2)

    if next_day:
        bin_w, bin_h = px(210), px(280)
        bin_x = hero[0] + px(48)
        bin_y = y + (hero_h - bin_h) // 2 + px(10)
        first_color = pal["bins"][next_day["events"][0]["color"]]
        draw_bin(draw, bin_x, bin_y, bin_w, bin_h, first_color, pal)
        # Weitere Tonnen am selben Tag klein daneben
        extra = next_day["events"][1:4]
        ex = bin_x + bin_w + px(18)
        for ev in extra:
            small_w, small_h = px(70), px(96)
            draw_bin(draw, ex, bin_y + bin_h - small_h, small_w, small_h, pal["bins"][ev["color"]], pal)
            ex += small_w + px(12)

        text_x = max(ex, bin_x + bin_w) + px(40)
        text_w = hero[2] - text_x - px(40)
        font_rel   = load_font(px(78), True)
        font_when  = load_font(px(32), False)
        font_type  = load_font(px(44), True)
        font_label = load_font(px(26), False)

        ty = y + px(48)
        draw.text((text_x, ty), next_day["relative"], font=font_rel, fill=pal["accent"] if flat else pal["title"])
        ty += px(96)
        draw.text((text_x, ty), format_date_long(next_day["date"]), font=font_when, fill=pal["muted"])
        ty += px(56)
        for ev in next_day["events"][:4]:
            type_font, lines, lh, sp, th = fit_wrapped_text(
                draw, ev["summary"], text_w, px(60), px(44), px(28), load_font, is_bold=True, max_lines=1)
            draw_lines(draw, text_x, ty, lines, type_font, pal["text"], lh, sp)
            if ev.get("label"):
                lbl_w = draw.textlength(lines[0] if lines else "", font=type_font) if lines else 0
                draw.text((text_x + lbl_w + px(16), ty + px(14)), ev["label"], font=font_label, fill=pal["muted"])
            ty += th + px(12)
        if data.get("next_outside_window"):
            draw.text((text_x, hero[3] - px(56)),
                      f"Keine Abfuhr in den nächsten {data.get('days_ahead', 14)} Tagen",
                      font=font_label, fill=pal["muted"])
    else:
        font_empty = load_font(px(40), True)
        draw.text((hero[0] + px(48), y + px(60)), "Keine Abfuhrtermine gefunden", font=font_empty, fill=pal["text"])

    y = hero[3] + px(40)

    # ── Liste: weitere Termine ───────────────────────────────────────────────
    font_section = load_font(px(28), True)
    font_row_date = load_font(px(30), True)
    font_row_rel  = load_font(px(22), False)
    font_row_type = load_font(px(28), False)
    draw.text((margin, y), f"Nächste {data.get('days_ahead', 14)} Tage", font=font_section, fill=pal["muted"])
    y += px(48)

    row_h = px(84)
    upcoming = [d for d in days if not next_day or d["date"] != next_day["date"]]
    if not upcoming and next_day and not data.get("next_outside_window"):
        draw.text((margin, y), "Danach keine weiteren Termine im Zeitraum.", font=font_row_type, fill=pal["muted"])
    for day in upcoming:
        if y + row_h > rh - margin:
            break
        draw.line([(margin, y), (rw - margin, y)], fill=pal["row_line"], width=2 if flat else 1)
        draw.text((margin, y + px(14)), _short_date(day["date"]), font=font_row_date, fill=pal["text"])
        draw.text((margin, y + px(50)), day["relative"], font=font_row_rel, fill=pal["muted"])
        cx = margin + px(230)
        for ev in day["events"][:4]:
            chip_w, chip_h = px(30), px(40)
            draw_bin(draw, cx, y + px(20), chip_w, chip_h, pal["bins"][ev["color"]], pal)
            cx += chip_w + px(14)
            label = ev["summary"] + (f"  · {ev['label']}" if ev.get("label") else "")
            draw.text((cx, y + px(22)), label, font=font_row_type, fill=pal["text"])
            cx += int(draw.textlength(label, font=font_row_type)) + px(34)
            if cx > rw - margin - px(200):
                break
        y += row_h

    return img.convert("RGB")
