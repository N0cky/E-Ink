"""
Kalender-Renderer: Heute groß, dann die nächsten Tage mit Terminen.
Jede Quelle hat eine Farbe (Balken links am Termin). Drei Themes.
"""

from __future__ import annotations

from datetime import date, datetime

from PIL import Image, ImageDraw

from app.config import WEEKDAYS_DE_LONG, format_date_long, format_weekday_short
from app.image_rendering import SPECTRA6_COLORS
from app.module_services import ModuleRenderServices
from app.text_rendering import draw_lines, fit_wrapped_text

Color = tuple[int, int, int, int]


def _c(name: str) -> Color:
    return (*SPECTRA6_COLORS[name], 255)


_PALETTES: dict[str, dict] = {
    "dark": {
        "flat": False,
        "bg":           (26, 28, 34, 255),
        "header":       (225, 228, 235, 255),
        "title":        (255, 255, 255, 255),
        "muted":        (160, 166, 178, 255),
        "text":         (240, 242, 246, 255),
        "time":         (200, 210, 225, 255),
        "card_fill":    (40, 44, 54, 255),
        "card_outline": (255, 255, 255, 40),
        "row_line":     (255, 255, 255, 26),
        "chip_text":    (20, 22, 28, 255),
        "sources": {"blue": (110, 170, 255), "green": (90, 200, 130), "red": (240, 110, 100), "yellow": (240, 200, 70)},
    },
    "light": {
        "flat": False,
        "bg":           (244, 241, 236, 255),
        "header":       (60, 54, 46, 255),
        "title":        (24, 20, 16, 255),
        "muted":        (120, 112, 102, 255),
        "text":         (30, 26, 22, 255),
        "time":         (70, 62, 54, 255),
        "card_fill":    (255, 254, 251, 255),
        "card_outline": (150, 142, 130, 90),
        "row_line":     (0, 0, 0, 24),
        "chip_text":    (255, 255, 255, 255),
        "sources": {"blue": (40, 105, 200), "green": (48, 140, 76), "red": (198, 50, 46), "yellow": (214, 160, 20)},
    },
    "eink": {
        "flat": True,
        "bg":           _c("white"),
        "header":       _c("black"),
        "title":        _c("black"),
        "muted":        _c("blue"),
        "text":         _c("black"),
        "time":         _c("black"),
        "card_fill":    _c("white"),
        "card_outline": _c("black"),
        "row_line":     _c("black"),
        "chip_text":    _c("white"),
        "sources": {"blue": SPECTRA6_COLORS["blue"], "green": SPECTRA6_COLORS["green"],
                    "red": SPECTRA6_COLORS["red"], "yellow": SPECTRA6_COLORS["yellow"]},
    },
}


def get_palette(theme: str) -> dict:
    return _PALETTES.get(theme, _PALETTES["dark"])


def _time_label(ev: dict) -> str:
    if ev.get("all_day"):
        return "Ganztägig"
    s, e = ev.get("start"), ev.get("end")
    if not isinstance(s, datetime):
        return ""
    if ev.get("continues"):
        return f"bis {e.strftime('%H:%M')}" if isinstance(e, datetime) else "weiter"
    if isinstance(e, datetime) and e > s and e.date() == s.date():
        return f"{s.strftime('%H:%M')} – {e.strftime('%H:%M')}"
    return s.strftime("%H:%M")


def _day_heading(day: dict) -> str:
    d: date = day["date"]
    rel = day["relative"]
    if day["in_days"] <= 2:
        return f"{rel}  ·  {WEEKDAYS_DE_LONG[d.weekday()]}, {d.day}.{d.month}."
    return f"{WEEKDAYS_DE_LONG[d.weekday()]}, {d.day}.{d.month}.  ·  {rel}"


def render_calendar_module(services: ModuleRenderServices, content: object) -> Image.Image:
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
    draw.text((margin, px(86)), "Kalender", font=font_title, fill=pal["title"])

    # Legende der Quellen rechts oben
    sources = data.get("sources") or []
    font_legend = load_font(px(22), False)
    lx = rw - margin
    for src in reversed(sources[:4]):
        label = src.get("label", "")
        tw = int(draw.textlength(label, font=font_legend))
        lx -= tw
        draw.text((lx, px(104)), label, font=font_legend, fill=pal["muted"])
        lx -= px(16)
        col = pal["sources"].get(src.get("color", "blue"), pal["sources"]["blue"])
        draw.rectangle([(lx - px(14), px(108)), (lx, px(122))], fill=(*col, 255))
        lx -= px(34)

    days = data.get("days") or []
    y = px(180)
    font_heading  = load_font(px(30), True)
    font_time     = load_font(px(26), True)
    font_event    = load_font(px(32), False)
    font_location = load_font(px(22), False)
    font_more     = load_font(px(22), False)
    time_col_w    = px(190)
    bar_w         = px(10)

    for day_index, day in enumerate(days):
        is_today = day["in_days"] <= 0
        if y > rh - margin - px(80):
            break

        # Tagesüberschrift
        heading = _day_heading(day)
        draw.text((margin, y), heading, font=font_heading, fill=pal["title"] if is_today else pal["muted"])
        y += px(44)
        draw.line([(margin, y), (rw - margin, y)], fill=pal["row_line"], width=3 if (flat and is_today) else (2 if flat else 1))
        y += px(12)

        events = day.get("events") or []
        if not events:
            draw.text((margin + time_col_w, y + px(6)), "Keine Termine", font=font_event, fill=pal["muted"])
            y += px(64)
        for ev in events:
            if y > rh - margin - px(60):
                break
            col = pal["sources"].get(ev.get("color", "blue"), pal["sources"]["blue"])
            # Farbbalken der Quelle
            draw.rectangle([(margin, y + px(6)), (margin + bar_w, y + px(50))], fill=(*col, 255))
            # Zeit
            draw.text((margin + bar_w + px(16), y + px(10)), _time_label(ev), font=font_time, fill=pal["time"])
            # Titel (eine Zeile, ggf. gekürzt) + Ort
            text_x = margin + time_col_w
            text_w = rw - margin - text_x
            title_font, lines, lh, sp, th = fit_wrapped_text(
                draw, ev.get("summary", ""), text_w, px(44), px(32), px(24), load_font, is_bold=is_today, max_lines=1)
            draw_lines(draw, text_x, y + px(6), lines, title_font, pal["text"], lh, sp)
            row_h = px(58)
            location = (ev.get("location") or "").strip()
            if location:
                loc_font, loc_lines, llh, lsp, lth = fit_wrapped_text(
                    draw, location, text_w, px(28), px(22), px(18), load_font, is_bold=False, max_lines=1)
                draw_lines(draw, text_x, y + px(6) + th + px(4), loc_lines, loc_font, pal["muted"], llh, lsp)
                row_h += lth + px(4)
            y += row_h
        if day.get("hidden"):
            draw.text((margin + time_col_w, y), f"+ {day['hidden']} weitere", font=font_more, fill=pal["muted"])
            y += px(36)
        y += px(26)

    if not days:
        draw.text((margin, y), "Keine Kalenderdaten", font=font_event, fill=pal["muted"])

    return img.convert("RGB")
