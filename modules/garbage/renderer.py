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


def _group_events(events: list[dict]) -> list[dict]:
    """Gleiche Tonne an mehreren Adressen → eine Zeile mit allen Adressen."""
    groups: list[dict] = []
    for ev in events:
        for g in groups:
            if g["summary"] == ev.get("summary") and g["color"] == ev.get("color"):
                if ev.get("label") and ev["label"] not in g["labels"]:
                    g["labels"].append(ev["label"])
                break
        else:
            groups.append({"summary": ev.get("summary", ""), "color": ev.get("color", "grey"),
                           "labels": [ev["label"]] if ev.get("label") else []})
    return groups


def _ellipsize(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> str:
    if draw.textlength(text, font=font) <= max_w:
        return text
    while text and draw.textlength(text + "…", font=font) > max_w:
        text = text[:-1]
    return text.rstrip() + "…"


def render_garbage_module(services: ModuleRenderServices, content: object, compact: bool = False) -> Image.Image:
    """compact=True: Dashboard-Kachel – kleine Titelzeile, kleinerer Hero."""
    data = content if isinstance(content, dict) else {}
    rw, rh = services.render_width, services.render_height
    pal = get_palette(services.display_theme)
    flat = pal["flat"]
    load_font = services.load_font

    img = Image.new("RGBA", (rw, rh), pal["bg"])
    draw = ImageDraw.Draw(img, "RGBA")

    margin = max(40, rw // 20) if not compact else max(24, rw // 30)
    scale = max(0.5, min(rw / 1200.0, 1.4)) if compact else min(rw / 1200.0, rh / 1600.0)

    def px(v: float) -> int:
        return max(1, int(v * scale))

    # ── Kopfzeile ────────────────────────────────────────────────────────────
    if compact:
        draw.text((margin, px(14)), "Müllabfuhr", font=load_font(px(26), True), fill=pal["title"])
        y = px(56)
    else:
        font_date  = load_font(px(32), False)
        font_title = load_font(px(60), True)
        draw.text((margin, px(46)), format_date_long(), font=font_date, fill=pal["header"])
        draw.text((margin, px(86)), "Müllabfuhr", font=font_title, fill=pal["title"])
        y = px(180)

    next_day = data.get("next")
    days = data.get("days") or []
    groups = _group_events(next_day["events"])[:4] if next_day else []

    # ── Hero: nächster Abfuhrtag ─────────────────────────────────────────────
    # Die Höhe folgt dem Inhalt (Datum + eine Zeile pro Tonne), damit nichts
    # aus dem Rahmen läuft; in der Kachel wird alles etwas kleiner gesetzt.
    small = compact
    avail = rh - y - margin
    hs = 1.0  # Verdichtung, falls die Kachel zu niedrig für den vollen Satz ist

    def _measure(hs: float):
        f = {
            "rel":   load_font(max(18, int(px(54 if small else 78) * hs)), True),
            "when":  load_font(max(14, int(px(26 if small else 32) * hs)), False),
            "label": load_font(max(12, int(px(22 if small else 26) * hs)), False),
        }
        type_max = max(16, int(px(40 if small else 60) * hs))
        type_min = max(14, int(px(24 if small else 28) * hs))
        h = {
            "pad_top": int(px(22 if small else 48) * hs),
            "rel":     int(px(60 if small else 96) * hs),
            "when":    int(px(38 if small else 56) * hs),
            "pad_bot": int(px(18 if small else 40) * hs),
            "line":    int(px(50 if small else 66) * hs),
            "wrap":    int(px(28 if small else 34) * hs),
        }
        probe_font = load_font(type_max, True)
        line_heights: list[int] = []
        for g in groups:
            label = ", ".join(g["labels"])
            inline = not label or (draw.textlength(g["summary"], font=probe_font) + px(16)
                                   + draw.textlength(label, font=f["label"]) <= text_w)
            line_heights.append(h["line"] + (0 if inline else h["wrap"]))
        needed = h["pad_top"] + h["rel"] + h["when"] + sum(line_heights) + h["pad_bot"]
        if next_day and data.get("next_outside_window"):
            needed += int(px(34) * hs)
        return f, type_max, type_min, h, line_heights, needed

    bin_max = px(200 if small else 280)
    bin_w_max = int(bin_max * 0.75)
    extra_n = max(0, len(groups) - 1)
    text_x = margin + px(48) + bin_w_max + (extra_n * (px(70) + px(12)) + px(6) if extra_n else 0) + px(40)
    text_w = rw - margin - text_x - px(32)

    fonts, type_max, type_min, hh, line_heights, needed = _measure(1.0)
    if needed > avail > 0:
        hs = max(0.55, avail / needed)
        fonts, type_max, type_min, hh, line_heights, needed = _measure(hs)
    font_rel, font_when, font_label = fonts["rel"], fonts["when"], fonts["label"]
    pad_top, rel_h, when_h = hh["pad_top"], hh["rel"], hh["when"]
    hero_h = max(px(200) if small else px(420), needed)
    # Passt darunter keine Terminzeile mehr, bekommt der Hero den Platz (die Tonnen wachsen mit)
    rows_need = px(28 if small else 40) + int(px(48 * (0.78 if compact else 1.0))) + int(px(84 * (0.78 if compact else 1.0)))
    if compact and hero_h + rows_need > avail:
        oneliner = px(28) + px(34 * 0.78) + px(6) if days and len(days) > 1 else 0
        hero_h = max(hero_h, avail - oneliner)
    hero_h = min(hero_h, avail)
    hero = (margin, y, rw - margin, y + hero_h)
    draw.rounded_rectangle(hero, radius=0 if flat else px(28), fill=pal["card_fill"],
                           outline=pal["card_outline"], width=4 if flat else 2)

    if next_day:
        bin_h = max(px(80), min(bin_max, hero_h - px(50 if small else 60)))
        bin_w = int(bin_h * 0.75)
        bin_x = hero[0] + px(48)
        bin_y = y + (hero_h - bin_h) // 2 + px(6)
        draw_bin(draw, bin_x, bin_y, bin_w, bin_h, pal["bins"][groups[0]["color"]], pal)
        # Weitere Tonnenarten am selben Tag klein daneben
        ex = bin_x + bin_w + px(18)
        for g in groups[1:]:
            small_w = px(70)
            small_h = min(px(96), bin_h - px(10))
            draw_bin(draw, ex, bin_y + bin_h - small_h, small_w, small_h, pal["bins"][g["color"]], pal)
            ex += small_w + px(12)

        ty = y + pad_top + max(0, (hero_h - needed) // 2)  # senkrecht mittig, wenn Luft ist
        draw.text((text_x, ty), next_day["relative"], font=font_rel, fill=pal["accent"] if flat else pal["title"])
        ty += rel_h
        draw.text((text_x, ty), format_date_long(next_day["date"]), font=font_when, fill=pal["muted"])
        ty += when_h
        for g, lh_total in zip(groups, line_heights):
            type_font, lines, lh, sp, th = fit_wrapped_text(
                draw, g["summary"], text_w, px(60), type_max, type_min, load_font, is_bold=True, max_lines=1)
            draw_lines(draw, text_x, ty, lines, type_font, pal["text"], lh, sp)
            label = ", ".join(g["labels"])
            if label:
                summary_w = draw.textlength(lines[0], font=type_font) if lines else 0
                if summary_w + px(16) + draw.textlength(label, font=font_label) <= text_w:
                    draw.text((text_x + summary_w + px(16), ty + max(0, th - int(px(30 if small else 34) * hs))),
                              label, font=font_label, fill=pal["muted"])
                else:
                    draw.text((text_x, ty + th + px(2)), _ellipsize(draw, label, font_label, text_w),
                              font=font_label, fill=pal["muted"])
            ty += lh_total
        if data.get("next_outside_window"):
            draw.text((text_x, ty),
                      f"Keine Abfuhr in den nächsten {data.get('days_ahead', 14)} Tagen",
                      font=font_label, fill=pal["muted"])
    else:
        font_empty = load_font(px(40), True)
        draw.text((hero[0] + px(48), y + px(60)), "Keine Abfuhrtermine gefunden", font=font_empty, fill=pal["text"])

    y = hero[3] + px(28 if small else 40)

    # ── Liste: weitere Termine ───────────────────────────────────────────────
    rs = 0.78 if compact else 1.0

    def lp(v: float) -> int:
        return px(v * rs)

    font_section  = load_font(lp(28), True)
    font_row_date = load_font(lp(30), True)
    font_row_rel  = load_font(lp(22), False)
    font_row_type = load_font(lp(28), False)
    row_h = lp(84)
    upcoming = [d for d in days if not next_day or d["date"] != next_day["date"]]
    remaining = rh - margin - y

    if upcoming and remaining < lp(48) + row_h:
        # Zu wenig Platz für Zeilen: die nächsten Tage als eine Textzeile
        if remaining >= lp(34):
            parts = [f"{_short_date(d['date'])} {' + '.join(g['summary'] for g in _group_events(d['events']))}"
                     for d in upcoming[:4]]
            draw.text((margin, y), _ellipsize(draw, "Danach: " + "  ·  ".join(parts), font_row_rel, rw - 2 * margin),
                      font=font_row_rel, fill=pal["muted"])
        return img.convert("RGB")
    if remaining < lp(48) + row_h:
        return img.convert("RGB")

    draw.text((margin, y), f"Nächste {data.get('days_ahead', 14)} Tage", font=font_section, fill=pal["muted"])
    y += lp(48)

    if not upcoming and next_day and not data.get("next_outside_window"):
        draw.text((margin, y), "Danach keine weiteren Termine im Zeitraum.", font=font_row_type, fill=pal["muted"])
    for day in upcoming:
        if y + row_h > rh - margin:
            break
        draw.line([(margin, y), (rw - margin, y)], fill=pal["row_line"], width=2 if flat else 1)
        draw.text((margin, y + lp(14)), _short_date(day["date"]), font=font_row_date, fill=pal["text"])
        draw.text((margin, y + lp(50)), day["relative"], font=font_row_rel, fill=pal["muted"])
        cx = margin + lp(230)
        for g in _group_events(day["events"])[:4]:
            chip_w, chip_h = lp(30), lp(40)
            draw_bin(draw, cx, y + lp(20), chip_w, chip_h, pal["bins"][g["color"]], pal)
            cx += chip_w + lp(14)
            label = g["summary"] + (f"  · {', '.join(g['labels'])}" if g["labels"] else "")
            draw.text((cx, y + lp(22)), label, font=font_row_type, fill=pal["text"])
            cx += int(draw.textlength(label, font=font_row_type)) + lp(34)
            if cx > rw - margin - lp(200):
                break
        y += row_h

    return img.convert("RGB")
