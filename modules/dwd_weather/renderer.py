from __future__ import annotations

import functools
import math
import time as _time
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.config import format_date_long, format_weekday_short
from app.image_rendering import SPECTRA6_COLORS
from app.module_services import ModuleRenderServices
from app.text_rendering import draw_lines, fit_wrapped_text


PROJECT_DIR = Path(__file__).resolve().parents[2]
FONT_AWESOME_SOLID = PROJECT_DIR / "font" / "Font Awesome 7 Free-Solid-900.otf"

FA_ICONS = {
    # UI-Icons (Stat-Panels, Legende)
    "droplet":            "\uf043",
    "umbrella":           "\uf0e9",
    "wind":               "\uf72e",
    "gauge":              "\uf625",
    "compass":            "\uf14e",
    "sunrise":            "\uf766",
    "sunset":             "\uf767",
    "moon":               "\uf186",   # Mondaufgang UND -untergang – Richtung per Pfeil
    "radiation":          "\uf7b9",
    "warning":            "\uf071",
    # Wetter-Icons
    "sun":                "\uf185",   # 1  Sonnig
    "cloud_sun":          "\uf6c4",   # 2  Leicht bewölkt / sonnig
    "cloud":              "\uf0c2",   # 3–4 Bewölkt / Bedeckt
    "smog":               "\uf75f",   # 5–6 Nebel
    "cloud_rain":         "\uf73d",   # 7–8 Regen
    "cloud_showers":      "\uf740",   # 9  Starker Regen
    "icicles":            "\uf7ad",   # Glätte / Hagel
    "snowflake":          "\uf2dc",   # 14–16 Schneefall
    "cloud_sun_rain":     "\uf743",   # 18–21 Sonnig mit Regen
    "bolt":               "\uf0e7",   # 26–30 Gewitter
}

# DWD-Wetter-Icon-Codes 1–31 → interner Icon-Name
WEATHER_ICON_MAP = {
    1:  "sun",            # Sonnig
    2:  "cloud_sun",      # Leicht bewölkt
    3:  "cloud",          # Bewölkt
    4:  "cloud",          # Bedeckt
    5:  "smog",           # Nebel
    6:  "smog",           # Nebel mit Glätte
    7:  "cloud_rain",     # Leichter Regen
    8:  "cloud_rain",     # Regen
    9:  "cloud_showers",  # Starker Regen
    10: "cloud_rain",     # Leichter Regen mit Glätte
    11: "cloud_showers",  # Starker Regen mit Glätte
    12: "cloud_rain",     # Regen und Schneeschauer
    13: "cloud_rain",     # Regen und Schneefall
    14: "snowflake",      # Leichter Schneefall
    15: "snowflake",      # Schneefall
    16: "snowflake",      # Starker Schneefall
    17: "icicles",        # Wolkig mit Hagel
    18: "cloud_sun_rain", # Sonnig mit leichtem Regen
    19: "cloud_sun_rain", # Sonnig mit starkem Regen
    20: "cloud_sun_rain", # Sonnig mit Regen und Schneeschauern
    21: "cloud_sun_rain", # Sonnig mit Regen und Schneefall
    22: "cloud_sun",      # Sonnig mit leichtem Schneefall
    23: "cloud_sun",      # Sonnig mit Schneefall
    24: "cloud_sun",      # Sonnig mit Hagel
    25: "cloud_sun",      # Sonnig mit starkem Hagel
    26: "bolt",           # Gewitter
    27: "bolt",           # Gewitter mit Regen
    28: "bolt",           # Starkes Gewitter
    29: "bolt",           # Gewitter mit Hagel
    30: "bolt",           # Starkes Gewitter mit Hagel
    31: "wind",           # Windig
}

SNOW_OVERRIDE_TEMP_C = 4.0


# ---------------------------------------------------------------------------
# Farbpaletten  (alle Einträge sind RGBA-4-Tupel oder RGB-3-Tupel)
# ---------------------------------------------------------------------------

_DWD_DARK: dict = {
    # Hintergrund
    "bg_top":              (84,  108, 142),
    "bg_bottom":           (66,  84,  114),
    # Haupt-Panel
    "panel_tint":          (12,  20,  34,  160),
    "panel_outline":       (255, 255, 255, 30),
    # Kopfzeile
    "header_idle":         (210, 224, 240, 220),
    "header_station":      (180, 208, 236, 235),
    # Aktuelle Temp / Zustand
    "temp_big":            (255, 255, 255, 255),
    "condition":           (230, 242, 255, 245),
    # Heute-Badge
    "badge_fill":          (52,  110, 190, 185),
    "badge_outline":       (180, 215, 255, 80),
    "badge_text":          (255, 255, 255, 248),
    # Großes Wetter-Icon
    "icon_main":           (243, 248, 255, 240),
    # Sonnen- und Mondauf-/-untergang
    "sun_icon":            (255, 210, 80,  240),
    "sun_arrow":           (132, 189, 255, 235),
    "sun_label":           (176, 202, 229, 232),
    "sun_value":           (250, 252, 255, 248),
    "moon_icon":           (200, 215, 255, 240),   # silbrig-blaues Mondlicht
    "moon_arrow":          (140, 168, 220, 225),
    "moon_label":          (170, 196, 228, 225),
    "moon_value":          (225, 235, 255, 248),
    # Mondphasen-Scheibe
    "moon_disc_lit":       (228, 236, 255, 245),   # beleuchtete Seite
    "moon_disc_dark":      (12,  22,  44,  220),   # Schattenseite
    "moon_disc_border":    (120, 155, 210, 160),   # Rand
    "moon_disc_label":     (190, 210, 240, 228),   # Beschriftung
    # Trennlinie
    "divider":             (180, 205, 232, 40),
    # Stat-Panels (Glas)
    "stat_glass_tint":     (14,  28,  48,  140),
    "stat_glass_outline":  (255, 255, 255, 40),
    "stat_icon":           (140, 196, 255, 235),
    "stat_label":          (188, 214, 239, 232),
    "stat_value":          (255, 255, 255, 248),
    # Stundenverlauf
    "chart_title":         (225, 235, 247, 240),
    "chart_nodata":        (180, 193, 207, 220),
    "grid":                (180, 205, 232, 36),
    "baseline":            (180, 205, 232, 80),
    "axis_label":          (180, 205, 232, 200),
    "curve_fill":          (110, 176, 244, 30),
    "curve_line":          (122, 194, 255, 240),
    "point_outer":         (255, 255, 255, 240),
    "point_inner":         (122, 194, 255, 255),
    "hourly_icon":         (210, 230, 255, 244),
    "hourly_temp":         (246, 249, 255, 240),
    "hourly_time":         (192, 207, 223, 228),
    # Prognose-Streifen
    "fc_glass_tint":       (14,  26,  44,  148),
    "fc_glass_outline":    (255, 255, 255, 36),
    "fc_icon":             (210, 230, 255, 240),
    "fc_day":              (220, 234, 248, 248),
    "fc_temp":             (255, 255, 255, 252),
    "fc_sun_text":         (200, 220, 244, 220),
    "fc_wind_text":        (180, 208, 235, 210),
    "fc_uv_text":          (180, 208, 235, 210),
    "fc_sun_icon":         (255, 210, 80,  220),
    "fc_wind_icon":        (160, 200, 240, 200),
    # Pollenleiste
    "pollen_glass_tint":   (16,  30,  52,  170),
    "pollen_glass_outline":(140, 185, 240, 55),
    "pollen_title":        (200, 225, 255, 245),
    "pollen_label":        (225, 240, 255, 235),
    # Warnungen
    "warning_glass_tint":  (42,  24,  18,  182),
    "warning_glass_outline": (255, 190, 120, 92),
    "warning_title":       (255, 225, 196, 245),
    "warning_text":        (255, 241, 228, 245),
    "warning_meta":        (255, 214, 182, 220),
}

_DWD_LIGHT: dict = {
    # Hintergrund
    "bg_top":              (196, 216, 238),
    "bg_bottom":           (172, 196, 222),
    # Haupt-Panel
    "panel_tint":          (255, 255, 255, 210),
    "panel_outline":       (130, 165, 200, 100),
    # Kopfzeile
    "header_idle":         (35,  65,  100, 240),
    "header_station":      (45,  80,  120, 240),
    # Aktuelle Temp / Zustand
    "temp_big":            (15,  35,  65,  255),
    "condition":           (40,  75,  110, 250),
    # Heute-Badge
    "badge_fill":          (58,  118, 185, 215),
    "badge_outline":       (80,  148, 210, 120),
    "badge_text":          (255, 255, 255, 255),
    # Großes Wetter-Icon
    "icon_main":           (25,  75,  145, 245),
    # Sonnen- und Mondauf-/-untergang
    "sun_icon":            (215, 150, 15,  245),
    "sun_arrow":           (35,  95,  165, 240),
    "sun_label":           (55,  95,  135, 240),
    "sun_value":           (15,  40,  70,  255),
    "moon_icon":           (55,  80,  175, 240),   # tiefes Nachtblau
    "moon_arrow":          (45,  90,  160, 225),
    "moon_label":          (55,  95,  145, 235),
    "moon_value":          (10,  35,  80,  255),
    # Mondphasen-Scheibe
    "moon_disc_lit":       (240, 244, 255, 250),   # beleuchtete Seite
    "moon_disc_dark":      (30,  50,  100, 200),   # Schattenseite
    "moon_disc_border":    (70,  105, 170, 180),   # Rand
    "moon_disc_label":     (30,  65,  120, 245),   # Beschriftung
    # Trennlinie
    "divider":             (110, 155, 195, 70),
    # Stat-Panels (Glas)
    "stat_glass_tint":     (240, 246, 255, 215),
    "stat_glass_outline":  (130, 165, 200, 100),
    "stat_icon":           (40,  95,  155, 245),
    "stat_label":          (55,  95,  135, 245),
    "stat_value":          (12,  35,  65,  255),
    # Stundenverlauf
    "chart_title":         (30,  65,  105, 245),
    "chart_nodata":        (70,  110, 150, 220),
    "grid":                (90,  135, 175, 55),
    "baseline":            (90,  135, 175, 110),
    "axis_label":          (55,  100, 140, 215),
    "curve_fill":          (55,  115, 195, 35),
    "curve_line":          (25,  80,  165, 220),
    "point_outer":         (25,  80,  165, 255),
    "point_inner":         (255, 255, 255, 255),
    "hourly_icon":         (35,  95,  160, 245),
    "hourly_temp":         (12,  40,  75,  248),
    "hourly_time":         (65,  108, 148, 232),
    # Prognose-Streifen
    "fc_glass_tint":       (238, 244, 254, 215),
    "fc_glass_outline":    (130, 165, 200, 100),
    "fc_icon":             (35,  95,  160, 240),
    "fc_day":              (25,  62,  105, 252),
    "fc_temp":             (8,   30,  60,  255),
    "fc_sun_text":         (55,  108, 162, 224),
    "fc_wind_text":        (65,  112, 158, 218),
    "fc_uv_text":          (65,  112, 158, 218),
    "fc_sun_icon":         (215, 150, 15,  230),
    "fc_wind_icon":        (45,  95,  148, 215),
    # Pollenleiste
    "pollen_glass_tint":   (230, 240, 255, 220),
    "pollen_glass_outline":(85,  130, 185, 120),
    "pollen_title":        (20,  55,  100, 255),
    "pollen_label":        (8,   30,  62,  255),
    # Warnungen
    "warning_glass_tint":  (255, 243, 232, 230),
    "warning_glass_outline": (214, 138, 68, 130),
    "warning_title":       (130, 60, 10, 255),
    "warning_text":        (92,  40,  8,  255),
    "warning_meta":        (120, 72,  32, 236),
}


def _spectra(name: str, alpha: int = 255) -> tuple[int, int, int, int]:
    from app.image_rendering import SPECTRA6_COLORS as _C
    return (*_C[name], alpha)


# E-Ink: ausschließlich die sechs Spectra-Farben, alles deckend. Was hier
# steht, wird auf dem Display ohne Dithering dargestellt. "flat" schaltet
# in den Zeichenfunktionen Transparenzen und Blur ab.
_DWD_EINK: dict = {
    "flat":                True,
    "bg_top":              _spectra("white")[:3],
    "bg_bottom":           _spectra("white")[:3],
    "panel_tint":          _spectra("white"),
    "panel_outline":       _spectra("black"),
    "header_idle":         _spectra("black"),
    "header_station":      _spectra("blue"),
    "temp_big":            _spectra("black"),
    "condition":           _spectra("black"),
    "badge_fill":          _spectra("blue"),
    "badge_outline":       _spectra("blue"),
    "badge_text":          _spectra("white"),
    "icon_main":           _spectra("blue"),
    "sun_icon":            _spectra("yellow"),
    "sun_arrow":           _spectra("black"),
    "sun_label":           _spectra("black"),
    "sun_value":           _spectra("black"),
    "moon_icon":           _spectra("blue"),
    "moon_arrow":          _spectra("black"),
    "moon_label":          _spectra("black"),
    "moon_value":          _spectra("black"),
    "moon_disc_lit":       _spectra("white"),
    "moon_disc_dark":      _spectra("black"),
    "moon_disc_border":    _spectra("black"),
    "moon_disc_label":     _spectra("black"),
    "divider":             _spectra("black"),
    "stat_glass_tint":     _spectra("white"),
    "stat_glass_outline":  _spectra("black"),
    "stat_icon":           _spectra("blue"),
    "stat_label":          _spectra("black"),
    "stat_value":          _spectra("black"),
    "chart_title":         _spectra("black"),
    "chart_nodata":        _spectra("black"),
    "grid":                _spectra("black"),
    "baseline":            _spectra("black"),
    "axis_label":          _spectra("black"),
    "curve_fill":          _spectra("blue"),
    "curve_line":          _spectra("black"),
    "point_outer":         _spectra("black"),
    "point_inner":         _spectra("white"),
    "hourly_icon":         _spectra("blue"),
    "hourly_temp":         _spectra("black"),
    "hourly_time":         _spectra("black"),
    "fc_glass_tint":       _spectra("white"),
    "fc_glass_outline":    _spectra("black"),
    "fc_icon":             _spectra("blue"),
    "fc_day":              _spectra("black"),
    "fc_temp":             _spectra("black"),
    "fc_sun_text":         _spectra("black"),
    "fc_wind_text":        _spectra("black"),
    "fc_uv_text":          _spectra("black"),
    "fc_sun_icon":         _spectra("yellow"),
    "fc_wind_icon":        _spectra("blue"),
    "pollen_glass_tint":   _spectra("white"),
    "pollen_glass_outline": _spectra("black"),
    "pollen_title":        _spectra("black"),
    "pollen_label":        _spectra("black"),
    "warning_glass_tint":  _spectra("yellow"),
    "warning_glass_outline": _spectra("black"),
    "warning_title":       _spectra("black"),
    "warning_text":        _spectra("black"),
    "warning_meta":        _spectra("black"),
}


def get_dwd_palette(theme: str) -> dict:
    if theme == "eink":
        return _DWD_EINK
    return _DWD_LIGHT if theme == "light" else _DWD_DARK


def warning_level_label(level: int | None) -> str:
    return {
        1: "Amtliche Warnung",
        2: "Markantes Wetter",
        3: "Unwetterwarnung",
        4: "Extremes Unwetter",
        5: "Extremes Unwetter",
    }.get(level, "Warnung")


def warning_level_color(level: int | None, flat: bool = False) -> tuple[int, int, int]:
    if flat:
        return SPECTRA6_COLORS["red"] if (level or 0) >= 3 else SPECTRA6_COLORS["yellow"]
    if level is None:
        return (222, 176, 36)
    if level >= 4:
        return (124, 18, 18)
    if level == 3:
        return (188, 38, 26)
    if level == 2:
        return (214, 132, 24)
    return (226, 186, 52)


# ---------------------------------------------------------------------------
# Wetter-Icon-Helpers
# ---------------------------------------------------------------------------

def get_weather_icon_name(icon_code: int | None, temp_hint_c: float | None = None) -> str:
    name = WEATHER_ICON_MAP.get(icon_code, "cloud")
    if temp_hint_c is not None and temp_hint_c > SNOW_OVERRIDE_TEMP_C:
        # Bei Temperaturen über 4 °C Schnee-Codes auf Regen umstellen
        if name == "snowflake":
            return "cloud_rain"
        # Regen+Schnee-Misch-Codes bei Wärme → reiner Regen
        if icon_code in {12, 13}:
            return "cloud_rain"
        # Sonnig+Schnee → sonnig mit Regen
        if icon_code in {20, 21}:
            return "cloud_sun_rain"
    return name


@functools.lru_cache(maxsize=32)
def load_fa_font(size: int):
    try:
        if FONT_AWESOME_SOLID.exists():
            return ImageFont.truetype(str(FONT_AWESOME_SOLID), size)
    except Exception:
        pass
    return None


def format_temp(temp_c: float | None) -> str:
    if temp_c is None:
        return "--"
    return f"{round(temp_c)}°"


def format_day_label(day_date: str) -> str:
    """'Mi 03.09.' – deutscher Wochentag unabhängig vom System-Locale."""
    try:
        parsed = datetime.strptime(day_date, "%Y-%m-%d")
        return f"{format_weekday_short(parsed)} {parsed.strftime('%d.%m.')}"
    except ValueError:
        return day_date


def fetch_dwd_weather_content() -> dict | None:
    from app.config import get_int_setting, get_setting
    from .dwd import fetch_dwd_weather, format_unix_ms_time
    from .dwd_pollen import fetch_dwd_pollen

    weather = fetch_dwd_weather(False)
    if weather is None:
        return None
    weather = dict(weather)

    # ── Sonnen-/Mondzeiten mit aktueller Zeitzone neu formatieren ────────────
    # Die formatierten Strings im Cache spiegeln die Zeitzone zum Zeitpunkt
    # des letzten API-Abrufs wider.  Durch Neuformatierung aus den gespeicherten
    # Roh-Timestamps greifen Timezone-Änderungen in den Settings sofort.
    today_raw = dict(weather.get("today") or {})
    for key in ("sunrise", "sunset", "moonrise", "moonset"):
        raw_ms = today_raw.get(f"_{key}_ms")
        if raw_ms is not None:
            today_raw[key] = format_unix_ms_time(raw_ms)
    weather["today"] = today_raw

    warning_items = []
    for warning in weather.get("warnings") or []:
        warning_copy = dict(warning)
        for key in ("start", "end"):
            raw_ms = warning_copy.get(f"_{key}_ms")
            if raw_ms is not None:
                warning_copy[key] = format_unix_ms_time(raw_ms)
        warning_items.append(warning_copy)
    weather["warnings"] = warning_items

    # ── Stündlichen Verlauf nach aktueller Einstellung filtern (ohne Neustart) ──
    hourly_all: list[dict] = weather.get("hourly_all") or []
    interval_hours = max(1, get_int_setting("DWD_HOURLY_INTERVAL_HOURS", 2, 1, 4))
    target_visible_points = 14
    raw_window_size = target_visible_points * interval_hours

    # day_start startet am Tagesbeginn und hält genau das Rohfenster vor,
    # das für 14 sichtbare Punkte im gewählten Intervall nötig ist.
    day_start_hourly = hourly_all[:raw_window_size] if raw_window_size > 0 else hourly_all

    if get_setting("DWD_HOURLY_START", "day_start") == "current_hour" and hourly_all:
        # Ab der aktuellen vollen Stunde starten, damit z. B. 19:30 mit 19:00
        # beginnt und nicht fälschlich schon bei 20:00.
        now_ms = int(_time.time() * 1000)
        current_hour_start_ms = now_ms - (now_ms % 3_600_000)
        filtered = [p for p in hourly_all if p.get("point_ts", 0) >= current_hour_start_ms]
        hourly   = filtered if filtered else hourly_all
        hourly = hourly[:raw_window_size] if raw_window_size > 0 else hourly
    else:
        hourly = day_start_hourly

    # Intervall bestimmt den Abstand, nicht die Anzahl: immer bis zu 14 Werte.
    weather["hourly_forecast"] = hourly[::interval_hours][:target_visible_points]

    # ── UV-Index ──────────────────────────────────────────────────────────────
    from .dwd_uv import fetch_dwd_uv
    uv_data = fetch_dwd_uv(False)
    if uv_data is not None:
        uvi_list: list = uv_data.get("uvi_by_index") or []
        # UV-Wert per Tagesindex in weather["days"] einbetten
        days = weather.get("days") or []
        new_days = []
        for i, day in enumerate(days):
            d = dict(day)
            d["uvi_max"] = uvi_list[i] if i < len(uvi_list) else None
            new_days.append(d)
        weather["days"] = new_days

    # ── Pollen ────────────────────────────────────────────────────────────────
    pollen = fetch_dwd_pollen(False)
    if pollen is not None:
        weather["pollen"] = pollen

    return weather


def has_dwd_weather_content(content: object) -> bool:
    return isinstance(content, dict) and bool(content)


# ---------------------------------------------------------------------------
# Hintergrund
# ---------------------------------------------------------------------------

def _create_gradient_background(render_width: int, render_height: int,
                                top_color: tuple, bot_color: tuple) -> Image.Image:
    rows = []
    for y in range(render_height):
        progress = y / max(render_height - 1, 1)
        r = int(top_color[0] + (bot_color[0] - top_color[0]) * progress)
        g = int(top_color[1] + (bot_color[1] - top_color[1]) * progress)
        b = int(top_color[2] + (bot_color[2] - top_color[2]) * progress)
        rows.append(bytes([r, g, b]) * render_width)
    return Image.frombytes("RGB", (render_width, render_height), b"".join(rows))


def create_weather_background(render_width: int, render_height: int) -> Image.Image:
    return _create_gradient_background(render_width, render_height, (84, 108, 142), (66, 84, 114))


def create_weather_background_light(render_width: int, render_height: int) -> Image.Image:
    return _create_gradient_background(render_width, render_height, (196, 216, 238), (172, 196, 222))


# ---------------------------------------------------------------------------
# Glas-Panel
# ---------------------------------------------------------------------------

def draw_fa_icon(draw, x, y, icon_name, size, fill):
    font = load_fa_font(size)
    glyph = FA_ICONS.get(icon_name)
    if not font or not glyph:
        return
    draw.text((x, y), glyph, font=font, fill=fill)


def draw_humidity_icon(draw, x, y, color, label_font=None):
    fa = load_fa_font(20)
    if fa:
        draw.text((x, y - 1), FA_ICONS["droplet"], font=fa, fill=color)


def draw_weather_icon(draw, x, y, icon_code, size,
                      fill=(235, 244, 255, 248), temp_hint_c=None):
    draw_fa_icon(draw, x, y, get_weather_icon_name(icon_code, temp_hint_c), size, fill)


def apply_glass_panel(
    img: Image.Image,
    bounds: tuple[int, int, int, int],
    radius: int,
    tint: tuple,
    outline: tuple,
    blur_radius: int = 18,
):
    crop = img.crop(bounds).convert("RGBA")
    if blur_radius > 0:
        crop = crop.filter(ImageFilter.GaussianBlur(radius=blur_radius))
    crop.alpha_composite(Image.new("RGBA", crop.size, tint))

    mask = Image.new("L", crop.size, 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle((0, 0, crop.size[0], crop.size[1]), radius=radius, fill=255)
    crop.putalpha(mask)
    img.alpha_composite(crop, dest=(bounds[0], bounds[1]))

    draw = ImageDraw.Draw(img, "RGBA")
    draw.rounded_rectangle(bounds, radius=radius, outline=outline, width=2)


# ---------------------------------------------------------------------------
# Astronomische Ereignisse (Sonnen- / Mondauf- und -untergang)
# ---------------------------------------------------------------------------

def _draw_astro_arrow(draw, cx, cy, is_rise: bool, color):
    """Kleiner Pfeil ↑ (Aufgang) oder ↓ (Untergang) neben dem Himmels-Icon."""
    if is_rise:
        draw.line((cx, cy + 6, cx, cy - 4), fill=color, width=2)
        draw.line((cx - 4, cy, cx, cy - 4), fill=color, width=2)
        draw.line((cx + 4, cy, cx, cy - 4), fill=color, width=2)
    else:
        draw.line((cx, cy - 4, cx, cy + 6), fill=color, width=2)
        draw.line((cx - 4, cy + 2, cx, cy + 6), fill=color, width=2)
        draw.line((cx + 4, cy + 2, cx, cy + 6), fill=color, width=2)


def draw_astro_event(draw, x: int, y: int,
                     title: str, value: str,
                     is_rise: bool, is_moon: bool,
                     label_font, value_font, pal: dict):
    """
    Zeichnet ein Sonnen- oder Mond-Ereignis.

    • Sonne: gelbes ☀-Icon (f185) + Richtungspfeil
    • Mond:  silbernes ☾-Icon (f186) + Richtungspfeil
    Der Pfeil ↑/↓ zeigt ob es Auf- oder Untergang ist –
    dadurch brauchen Mondauf- und -untergang kein eigenes Glyph.
    """
    if is_moon:
        glyph      = FA_ICONS.get("moon", "\uf186")
        icon_color = pal.get("moon_icon",  pal["sun_icon"])
        arr_color  = pal.get("moon_arrow", pal["sun_arrow"])
        lbl_color  = pal.get("moon_label", pal["sun_label"])
        val_color  = pal.get("moon_value", pal["sun_value"])
    else:
        glyph      = FA_ICONS.get("sun", "\uf185")
        icon_color = pal["sun_icon"]
        arr_color  = pal["sun_arrow"]
        lbl_color  = pal["sun_label"]
        val_color  = pal["sun_value"]

    fa = load_fa_font(22)
    if fa and glyph:
        draw.text((x, y + 2), glyph, font=fa, fill=icon_color)
        _draw_astro_arrow(draw, x + 26, y + 13, is_rise, arr_color)
        text_x = x + 40
    else:
        text_x = x
    draw.text((text_x, y),      title, font=label_font, fill=lbl_color)
    draw.text((text_x, y + 22), value, font=value_font,  fill=val_color)


def draw_sun_event(draw, x, y, title, value, icon_name, label_font, value_font, pal: dict):
    """Rückwärtskompatible Alias für draw_astro_event (Sonne)."""
    draw_astro_event(draw, x, y, title, value,
                     is_rise=(icon_name == "sunrise"), is_moon=False,
                     label_font=label_font, value_font=value_font, pal=pal)


# ---------------------------------------------------------------------------
# Mondphase
# ---------------------------------------------------------------------------

def moon_phase_label(phase: float | None) -> str:
    """
    Gibt den deutschen Phasennamen für einen normalisierten Mondphasen-Wert 0–1 zurück.

    DWD liefert Integer 0–7, normalisiert auf exakte Werte:
      0 → 0.000 Neumond
      1 → 0.125 Zunehmende Sichel
      2 → 0.250 Erstes Viertel
      3 → 0.375 Zunehmender Mond
      4 → 0.500 Vollmond
      5 → 0.625 Abnehmender Mond
      6 → 0.750 Letztes Viertel
      7 → 0.875 Abnehmende Sichel
    Schwellwerte bei den Mittelpunkten zwischen je zwei Phasen.
    """
    if phase is None:
        return ""
    p = phase % 1.0
    if p < 0.0625:  return "Neumond"
    if p < 0.1875:  return "Zunehmende Sichel"
    if p < 0.3125:  return "Erstes Viertel"
    if p < 0.4375:  return "Zunehmender Mond"
    if p < 0.5625:  return "Vollmond"
    if p < 0.6875:  return "Abnehmender Mond"
    if p < 0.8125:  return "Letztes Viertel"
    return "Abnehmende Sichel"


def draw_moon_disc(img: Image.Image, cx: int, cy: int, r: int,
                   phase: float, pal: dict) -> None:
    """
    Zeichnet eine geometrisch korrekte Mondphasen-Scheibe.

    phase: 0.0 = Neumond · 0.25 = Erstes Viertel · 0.5 = Vollmond · 0.75 = Letztes Viertel

    Algorithmus:
      1. Dunkle Grundscheibe
      2. Beleuchteten Halbkreis überlagern (rechts bei zunehmend, links bei abnehmend)
      3. Terminator-Ellipse: a = r · cos(phase · 2π)
         a > 0 → dunkle Ellipse verkleinert die lit-Seite   (Sichel → Viertel)
         a < 0 → helle Ellipse erweitert auf die dark-Seite  (Viertel → Gibbous → Vollmond)
    """
    import math as _math

    LIT    = pal.get("moon_disc_lit",    (228, 236, 255, 245))
    DARK   = pal.get("moon_disc_dark",   (12,  22,  44,  220))
    BORDER = pal.get("moon_disc_border", (120, 155, 210, 160))

    pad  = 2
    size = (r + pad) * 2
    moon = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    md   = ImageDraw.Draw(moon, "RGBA")
    ox   = r + pad                                  # Mittelpunkt im moon-Image
    box  = [pad, pad, size - pad - 1, size - pad - 1]

    # 1. Dunkle Grundscheibe
    md.ellipse(box, fill=DARK)

    # 2. Beleuchteter Halbkreis
    if phase <= 0.5:
        md.pieslice(box, -90, 90,  fill=LIT)        # rechts = zunehmend
    else:
        md.pieslice(box, 90,  270, fill=LIT)        # links  = abnehmend

    # 3. Terminator-Ellipse
    a = r * _math.cos(phase * 2 * _math.pi)
    if abs(a) > 0.5:
        ea       = abs(int(round(a)))
        term_box = [ox - ea, pad, ox + ea, size - pad - 1]
        md.ellipse(term_box, fill=DARK if a > 0 else LIT)

    # 4. Rand
    md.ellipse(box, outline=BORDER, width=1)

    # 5. Auf Hauptbild compositen
    img.alpha_composite(moon, dest=(cx - ox, cy - ox))


# ---------------------------------------------------------------------------
# Stat-Panels
# ---------------------------------------------------------------------------

def draw_stat_panel(img, bounds, title, value, icon_name, label_font, value_font, pal: dict,
                    load_font=None):
    apply_glass_panel(img, bounds, radius=26,
                      tint=pal["stat_glass_tint"],
                      outline=pal["stat_glass_outline"],
                      blur_radius=14)
    draw = ImageDraw.Draw(img, "RGBA")
    left, top, _, _ = bounds

    if icon_name == "humidity":
        draw_humidity_icon(draw, left + 18, top + 16, pal["stat_icon"], label_font)
    else:
        draw_fa_icon(draw, left + 18, top + 18, icon_name, 18, pal["stat_icon"])
    draw.text((left + 54, top + 16), title, font=label_font, fill=pal["stat_label"])

    value_left = left + 22
    value_top  = top + 54
    max_value_width = bounds[2] - value_left - 18

    lines = value.split("\n")
    if len(lines) > 1:
        # Zweizeiliger Wert (z. B. Wind + Böen): beide Zeilen mit fester Schriftgröße
        line_font = load_font(20, True) if load_font else value_font
        for i, line in enumerate(lines):
            draw.text((value_left, value_top + i * 26), line,
                      font=line_font, fill=pal["stat_value"])
    else:
        chosen_font = value_font
        if load_font:
            # Schriftgröße schrittweise verkleinern bis der Text passt
            start_size = getattr(value_font, "size", 28)
            for size in range(start_size, 19, -2):
                candidate = load_font(size, True)
                text_bbox = draw.textbbox((0, 0), value, font=candidate)
                if (text_bbox[2] - text_bbox[0]) <= max_value_width:
                    chosen_font = candidate
                    break
        draw.text((value_left, value_top), value, font=chosen_font, fill=pal["stat_value"])


# ---------------------------------------------------------------------------
# Warnungen
# ---------------------------------------------------------------------------

_WARNING_CARD_GAP = 10
_WARNING_TITLE_H = 30
_WARNING_TITLE_PAD_TOP = 12
_WARNING_TITLE_PAD_BOTTOM = 10
_WARNING_CARD_LIMIT = 2


def _layout_warning_cards(warnings: list[dict], card_width: int, load_font) -> list[dict]:
    measure_img = Image.new("RGBA", (max(1, card_width), 220), (0, 0, 0, 0))
    measure_draw = ImageDraw.Draw(measure_img, "RGBA")
    layouts: list[dict] = []

    for warning in warnings[:_WARNING_CARD_LIMIT]:
        sev_label = warning_level_label(warning.get("level"))
        pill_font = load_font(14, True)
        pill_bb = measure_draw.textbbox((0, 0), sev_label, font=pill_font)
        pill_tw = pill_bb[2] - pill_bb[0]
        pill_w = max(98, pill_tw + 22)
        pill_h = 24

        inner_left = 12
        inner_right = 12
        headline_x = inner_left + pill_w + 10
        headline_width = max(80, card_width - headline_x - inner_right)
        headline = warning.get("headline") or warning.get("event") or "Amtliche Wetterwarnung"
        headline_font, headline_lines, headline_line_h, headline_spacing, headline_total_h = fit_wrapped_text(
            measure_draw,
            headline,
            max_width=headline_width,
            max_height=30,
            start_size=18,
            min_size=15,
            load_font=load_font,
            is_bold=True,
            max_lines=1,
            line_spacing=0.1,
        )

        detail_text = warning.get("description") or warning.get("event") or "Wetterwarnung"
        meta_text = f"{_warning_time_label(warning)} · {detail_text}"
        meta_font, meta_lines, meta_line_h, meta_spacing, meta_total_h = fit_wrapped_text(
            measure_draw,
            meta_text,
            max_width=max(80, card_width - inner_left - inner_right),
            max_height=54,
            start_size=17,
            min_size=13,
            load_font=load_font,
            max_lines=3,
            line_spacing=0.1,
        )

        header_h = max(pill_h, headline_total_h or headline_line_h)
        card_h = 12 + header_h + 8 + meta_total_h + 12
        layouts.append({
            "warning": warning,
            "pill_text": sev_label,
            "pill_font": pill_font,
            "pill_w": pill_w,
            "pill_h": pill_h,
            "headline_font": headline_font,
            "headline_lines": headline_lines[:1],
            "headline_line_h": headline_line_h,
            "headline_spacing": headline_spacing,
            "meta_font": meta_font,
            "meta_lines": meta_lines[:3],
            "meta_line_h": meta_line_h,
            "meta_spacing": meta_spacing,
            "header_h": header_h,
            "card_h": card_h,
        })

    return layouts


def warning_strip_height(warnings: list[dict], card_width: int, load_font) -> int:
    if not warnings:
        return 0
    layouts = _layout_warning_cards(warnings, card_width, load_font)
    return (
        _WARNING_TITLE_PAD_TOP
        + _WARNING_TITLE_H
        + _WARNING_TITLE_PAD_BOTTOM
        + sum(layout["card_h"] for layout in layouts)
        + (max(0, len(layouts) - 1) * _WARNING_CARD_GAP)
        + 14
    )


def _warning_time_label(warning: dict) -> str:
    start = warning.get("start") or "--:--"
    end = warning.get("end") or "--:--"
    if start == "--:--" and end == "--:--":
        return "Zeit unbekannt"
    return f"{start} - {end}"


def draw_warning_strip(
    img: Image.Image,
    bounds: tuple[int, int, int, int],
    warnings: list[dict],
    title_font,
    small_font,
    pal: dict,
    load_font,
) -> None:
    if not warnings:
        return

    left, top, right, bottom = bounds
    apply_glass_panel(
        img,
        bounds,
        radius=22,
        tint=pal["warning_glass_tint"],
        outline=pal["warning_glass_outline"],
        blur_radius=10,
    )
    draw = ImageDraw.Draw(img, "RGBA")

    title_y = top + _WARNING_TITLE_PAD_TOP
    draw_fa_icon(draw, left + 18, title_y + 1, "warning", 18, pal["warning_title"])
    count = len(warnings)
    title = "Amtliche Warnungen"
    if count == 1:
        title += " · 1 Warnung"
    else:
        title += f" · {count} Warnungen"
    draw.text((left + 44, title_y), title, font=title_font, fill=pal["warning_title"])

    card_left = left + 14
    card_right = right - 14
    card_top = top + _WARNING_TITLE_PAD_TOP + _WARNING_TITLE_H + _WARNING_TITLE_PAD_BOTTOM
    layouts = _layout_warning_cards(warnings, card_right - card_left, load_font)

    current_top = card_top
    for layout in layouts:
        warning = layout["warning"]
        card_bounds = (card_left, current_top, card_right, current_top + layout["card_h"])
        sev_rgb = warning_level_color(warning.get("level"))
        apply_glass_panel(
            img,
            card_bounds,
            radius=18,
            tint=(*sev_rgb, 34),
            outline=(*sev_rgb, 120),
            blur_radius=8,
        )
        draw = ImageDraw.Draw(img, "RGBA")

        pill_left = card_left + 12
        pill_top = current_top + 12
        pill_h = layout["pill_h"]
        pill_text = layout["pill_text"]
        pill_font = layout["pill_font"]
        pill_bb = draw.textbbox((0, 0), pill_text, font=pill_font)
        pill_tw = pill_bb[2] - pill_bb[0]
        pill_w = layout["pill_w"]
        draw.rounded_rectangle(
            (pill_left, pill_top, pill_left + pill_w, pill_top + pill_h),
            radius=12,
            fill=(*sev_rgb, 220),
        )
        draw.text(
            (pill_left + (pill_w - pill_tw) / 2, pill_top + 4),
            pill_text,
            font=pill_font,
            fill=(255, 255, 255, 255),
        )

        draw_lines(
            draw,
            pill_left + pill_w + 10,
            current_top + 13,
            layout["headline_lines"],
            layout["headline_font"],
            pal["warning_text"],
            layout["headline_line_h"],
            layout["headline_spacing"],
        )

        meta_y = current_top + 12 + layout["header_h"] + 8
        draw_lines(
            draw,
            pill_left,
            meta_y,
            layout["meta_lines"],
            layout["meta_font"],
            pal["warning_meta"],
            layout["meta_line_h"],
            layout["meta_spacing"],
        )
        current_top += layout["card_h"] + _WARNING_CARD_GAP

    remaining = len(warnings) - len(layouts)
    if remaining > 0:
        hint = f"+{remaining} weitere Warnung" if remaining == 1 else f"+{remaining} weitere Warnungen"
        draw.text((card_left + 2, bottom - 22), hint, font=small_font, fill=pal["warning_meta"])


# ---------------------------------------------------------------------------
# Stundenverlauf
# ---------------------------------------------------------------------------

def interpolate_curve(points, segments=14):
    if len(points) <= 2:
        return points
    smoothed = []
    for index in range(len(points) - 1):
        p0 = points[index - 1] if index > 0 else points[index]
        p1 = points[index]
        p2 = points[index + 1]
        p3 = points[index + 2] if index + 2 < len(points) else points[index + 1]
        for step in range(segments):
            t = step / segments
            t2, t3 = t * t, t * t * t
            x = 0.5 * ((2 * p1[0]) + (-p0[0] + p2[0]) * t
                        + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2
                        + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3)
            y = 0.5 * ((2 * p1[1]) + (-p0[1] + p2[1]) * t
                        + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2
                        + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3)
            smoothed.append((x, y))
    smoothed.append(points[-1])
    return smoothed


def draw_hourly_strip(draw, bounds, hourly_points, title_font, time_font, temp_font, pal: dict):
    """Tagesverlauf-Graph mit dynamischer 5°-Temperaturachse links."""
    left, top, right, bottom = bounds

    max_day_offset = max((int(p.get("day_offset", 1 if p.get("is_next_day") else 0)) for p in (hourly_points or [])), default=0)
    has_next_day = max_day_offset >= 1
    has_second_next_day = max_day_offset >= 2
    if has_second_next_day:
        title_text = "Verlauf heute, morgen & übermorgen früh"
    elif has_next_day:
        title_text = "Verlauf heute & morgen früh"
    else:
        title_text = "Heute im Verlauf"
    draw.text((left, top), title_text, font=title_font, fill=pal["chart_title"])

    if not hourly_points:
        draw.text((left, top + 36), "Keine Stundenwerte verfügbar",
                  font=time_font, fill=pal["chart_nodata"])
        return

    AXIS_W = 38          # Breite für Temperaturskala links

    icon_row_y     = top + 38
    temp_row_y     = top + 76
    chart_y_top    = temp_row_y + 30
    chart_y_bottom = bottom - 30
    time_row_y     = bottom - 24
    chart_left     = left + AXIS_W    # Datenfläche beginnt rechts der Skala

    chart_height = chart_y_bottom - chart_y_top
    if chart_height < 30:
        return

    temps = [p.get("temp_c") for p in hourly_points if p.get("temp_c") is not None]
    if not temps:
        temps = [0.0]
    min_temp = min(temps)
    max_temp = max(temps)

    # Achse auf 5°-Schritte runden
    axis_min = math.floor(min_temp / 5) * 5
    axis_max = math.ceil(max_temp / 5) * 5
    if axis_max == axis_min:
        axis_max = axis_min + 5
    spread = float(axis_max - axis_min)

    step_x = (right - chart_left) / max(len(hourly_points) - 1, 1)

    # Datenpunkt-Koordinaten relativ zur gerundeten Achse
    points = []
    for i, point in enumerate(hourly_points):
        px   = chart_left + i * step_x
        temp = point.get("temp_c") if point.get("temp_c") is not None else float(axis_min)
        norm = (temp - axis_min) / spread
        py   = chart_y_bottom - norm * chart_height
        points.append((px, py))

    # Gitternetz-Linien und Temperaturachse in 5°-Schritten
    ticks = list(range(axis_min, axis_max + 1, 5))
    for tick in ticks:
        norm = (tick - axis_min) / spread
        gy   = int(chart_y_bottom - norm * chart_height)
        if not (chart_y_top - 2 <= gy <= chart_y_bottom + 2):
            continue
        line_col = pal["baseline"] if tick == axis_min else pal["grid"]
        draw.line((chart_left, gy, right - 4, gy), fill=line_col, width=1)
        lbl    = f"{tick}°"
        bb     = draw.textbbox((0, 0), lbl, font=time_font)
        lbl_h  = bb[3] - bb[1]
        lbl_w  = bb[2] - bb[0]
        draw.text((left + AXIS_W - lbl_w - 4, gy - lbl_h // 2),
                  lbl, font=time_font, fill=pal["axis_label"])

    # Trennlinien bei Tageswechseln (gestrichelt)
    transition_labels = {
        1: "morgen",
        2: "übermorgen",
    }
    grid_color = pal["grid"]
    sep_color = (*grid_color[:3], min(255, (grid_color[3] if len(grid_color) > 3 else 200) + 80))
    for day_boundary in range(1, max_day_offset + 1):
        boundary_idx = next(
            (
                i for i, p in enumerate(hourly_points)
                if int(p.get("day_offset", 1 if p.get("is_next_day") else 0)) >= day_boundary
            ),
            None,
        )
        if boundary_idx is None or boundary_idx <= 0:
            continue
        sep_x = int(chart_left + (boundary_idx - 0.5) * step_x)
        dash_y = icon_row_y
        while dash_y < time_row_y + 8:
            draw.line((sep_x, dash_y, sep_x, min(dash_y + 7, time_row_y + 8)),
                      fill=sep_color, width=1)
            dash_y += 12
        lbl = transition_labels.get(day_boundary, f"+{day_boundary}d")
        lbl_bb = draw.textbbox((0, 0), lbl, font=time_font)
        lbl_w = lbl_bb[2] - lbl_bb[0]
        draw.text((sep_x - lbl_w // 2, icon_row_y - 16),
                  lbl, font=time_font, fill=pal["axis_label"])

    # Kurve
    curve_points = interpolate_curve(points)
    if len(curve_points) > 1:
        fill_pts = [(curve_points[0][0], chart_y_bottom)] + curve_points + [(curve_points[-1][0], chart_y_bottom)]
        draw.polygon(fill_pts, fill=pal["curve_fill"])
        draw.line(curve_points, fill=pal["curve_line"], width=4)

    # Datenpunkte und Beschriftung
    for i, point in enumerate(hourly_points):
        px, py = points[i]
        day_offset = int(point.get("day_offset", 1 if point.get("is_next_day") else 0))
        # Flat-Themes (E-Ink): keine Transparenz, sonst dithert es
        if pal.get("flat"):
            alpha = None
        else:
            alpha = 160 if day_offset == 1 else 110 if day_offset >= 2 else None
        outer_fill = (*pal["point_outer"][:3], alpha) if alpha is not None else pal["point_outer"]
        inner_fill = (*pal["point_inner"][:3], alpha) if alpha is not None else pal["point_inner"]
        icon_fill  = (*pal["hourly_icon"][:3], alpha) if alpha is not None else pal["hourly_icon"]
        temp_fill  = (*pal["hourly_temp"][:3], alpha) if alpha is not None else pal["hourly_temp"]
        time_fill  = (*pal["hourly_time"][:3], alpha) if alpha is not None else pal["hourly_time"]

        draw.ellipse((px - 5, py - 5, px + 5, py + 5), fill=outer_fill)
        draw.ellipse((px - 3, py - 3, px + 3, py + 3), fill=inner_fill)

        draw_weather_icon(draw, int(px - 10), int(icon_row_y), point.get("icon_code"),
                          18, icon_fill, temp_hint_c=point.get("temp_c"))

        temp_text = format_temp(point.get("temp_c"))
        t_bbox = draw.textbbox((0, 0), temp_text, font=temp_font)
        t_w    = t_bbox[2] - t_bbox[0]
        draw.text((px - t_w / 2, temp_row_y), temp_text, font=temp_font, fill=temp_fill)

        time_text = point.get("time", "--:--")
        ti_bbox = draw.textbbox((0, 0), time_text, font=time_font)
        ti_w    = ti_bbox[2] - ti_bbox[0]
        draw.text((px - ti_w / 2, time_row_y), time_text, font=time_font, fill=time_fill)


# ---------------------------------------------------------------------------
# Kompakter Prognose-Streifen
# ---------------------------------------------------------------------------

def draw_compact_forecast_strip(img, bounds, forecast_days, day_font, temp_font, meta_font, pal: dict):
    """Mehrtages-Vorschau-Streifen mit Palette. Zeigt UV-Index wenn vorhanden."""
    from .dwd_uv import uv_level_color, uv_level_label

    if not forecast_days:
        return

    left, top, right, bottom = bounds
    h = bottom - top
    count = len(forecast_days)
    gap = 10
    card_w = int((right - left - gap * (count - 1)) / count)

    # Prüfen ob UV-Daten vorhanden sind (mind. ein Tag mit Wert)
    has_uv = any(day.get("uvi_max") is not None for day in forecast_days)
    show_uv = has_uv and h >= 106

    # ── Zeilenpositionen von unten aufbauen ───────────────────────────────────
    ROW_H      = 22   # Zeilenhöhe (Icon 16 px + 6 px Luft)
    BOTTOM_PAD = 10   # Abstand Unterkante Karte

    if show_uv:
        uv_y   = bottom - BOTTOM_PAD - ROW_H
        wind_y = uv_y   - ROW_H
        sun_y  = wind_y - ROW_H
    else:
        uv_y   = None
        wind_y = bottom - BOTTOM_PAD - ROW_H
        sun_y  = wind_y - ROW_H

    meta_top = sun_y   # Oberkante des Meta-Bereichs

    # Temperatur vertikal zwischen Tag-Label-Bereich und Meta-Bereich zentrieren
    DAY_LABEL_BOTTOM = top + 32   # ca. Label (19 px) + 10 px oben + Luft
    avail_for_temp   = meta_top - DAY_LABEL_BOTTOM - 4
    temp_y = DAY_LABEL_BOTTOM + max(0, (avail_for_temp - 24) // 2)

    for idx, day in enumerate(forecast_days):
        card_left  = left + idx * (card_w + gap)
        card_right = card_left + card_w
        apply_glass_panel(
            img,
            (card_left, top, card_right, bottom),
            radius=18,
            tint=pal["fc_glass_tint"],
            outline=pal["fc_glass_outline"],
            blur_radius=10,
        )
        draw = ImageDraw.Draw(img, "RGBA")
        pad = 12

        draw_weather_icon(draw, card_right - 38, top + 8, day.get("icon_code"),
                          24, pal["fc_icon"], temp_hint_c=day.get("max_temp_c"))

        draw.text((card_left + pad, top + 10), format_day_label(day.get("day_date", "")),
                  font=day_font, fill=pal["fc_day"])

        temp_text = f"{format_temp(day.get('max_temp_c'))} / {format_temp(day.get('min_temp_c'))}"
        draw.text((card_left + pad, temp_y), temp_text,
                  font=temp_font, fill=pal["fc_temp"])

        if h >= 90:
            sun_text  = day.get("sunshine_text") or "--"
            wind_kmh  = day.get("wind_kmh")
            wind_dir  = day.get("wind_dir_label") or ""
            wind_text = f"{wind_kmh} km/h {wind_dir}" if wind_kmh is not None else "--"
            uvi       = day.get("uvi_max")

            fa     = load_fa_font(16)   # Icons etwas größer als bisher (13 → 16)
            ICON_W = 20                 # Platz den das Icon horizontal belegt

            # Sonne (Scheindauer)
            if fa:
                draw.text((card_left + pad,          sun_y),
                          FA_ICONS["sun"], font=fa, fill=pal["fc_sun_icon"])
                draw.text((card_left + pad + ICON_W, sun_y + 1),
                          sun_text, font=meta_font, fill=pal["fc_sun_text"])
            else:
                draw.text((card_left + pad, sun_y + 1), sun_text,
                          font=meta_font, fill=pal["fc_sun_text"])

            # Wind
            if fa:
                draw.text((card_left + pad,          wind_y),
                          FA_ICONS["wind"], font=fa, fill=pal["fc_wind_icon"])
                draw.text((card_left + pad + ICON_W, wind_y + 1),
                          wind_text, font=meta_font, fill=pal["fc_wind_text"])
            else:
                draw.text((card_left + pad, wind_y + 1), wind_text,
                          font=meta_font, fill=pal["fc_wind_text"])

            # UV-Index
            if show_uv and uv_y is not None:
                uv_rgb  = uv_level_color(uvi)
                uv_rgba = (*uv_rgb, 230)
                uv_lbl  = uv_level_label(uvi)
                uv_val  = f"{uvi:.0f}" if uvi is not None else "--"
                uv_str  = f"{uv_val}  {uv_lbl}"

                if fa:
                    draw.text((card_left + pad,          uv_y),
                              FA_ICONS.get("radiation") or FA_ICONS["sun"], font=fa, fill=uv_rgba)
                    draw.text((card_left + pad + ICON_W, uv_y + 1),
                              uv_str, font=meta_font, fill=pal["fc_uv_text"])
                else:
                    draw.text((card_left + pad, uv_y + 1), uv_str,
                              font=meta_font, fill=uv_rgba)


# ---------------------------------------------------------------------------
# Pollen-Strip
# ---------------------------------------------------------------------------

_POLLEN_DAY_KEYS   = ("today",  "tomorrow", "dayafter_to")
_POLLEN_DAY_LABELS = ("Heute",  "Morgen",   "Überm.")


def _pollen_load_color(value: float | None, flat: bool = False) -> tuple[int, int, int]:
    """Belastungswert 0..3 → RGB. flat=True nutzt nur Spectra-6-Farben (E-Ink)."""
    if flat:
        if value is None or value == 0.0:
            return SPECTRA6_COLORS["white"]
        if value <= 1.0:
            return SPECTRA6_COLORS["green"]
        if value <= 2.0:
            return SPECTRA6_COLORS["yellow"]
        return SPECTRA6_COLORS["red"]
    if value is None or value == 0.0:
        return (148, 155, 165)   # Grau  – keine Belastung
    if value <= 1.0:
        return (38,  165, 70)    # Grün  – gering
    if value <= 2.0:
        return (215, 145, 10)    # Amber – mittel
    return (205, 38,  38)        # Rot   – hoch


def _pollen_load_label(value: float | None) -> str:
    if value is None:  return "–"
    if value == 0.0:   return "0"
    if value <= 0.5:   return "0–1"
    if value <= 1.0:   return "1"
    if value <= 1.5:   return "1–2"
    if value <= 2.0:   return "2"
    if value <= 2.5:   return "2–3"
    return "3"


_POLLEN_ROW_H   = 54   # Höhe einer Allergen-Zeile
_POLLEN_ROW_GAP = 10   # Abstand zwischen Zeilen
_POLLEN_PAD_H   = 20   # horizontaler Innenabstand
_POLLEN_PAD_TOP = 14   # Abstand oben
_POLLEN_PAD_BOT = 16   # Abstand unten
_POLLEN_TITLE_H = 34   # Höhe der Titelzeile
_POLLEN_GAP_T   = 10   # Abstand Titel → Daten
_POLLEN_BIG_R   = 11   # Radius des Haupt-Farbpunktes
_POLLEN_SMALL_R = 8    # Radius der Tages-Farbpunkte
_POLLEN_NAME_W  = 120  # Reservierter Platz für Allergen-Namen (px)
_POLLEN_DAY_W   = 80   # Reservierter Platz pro Tag-Spalte (px)


def _allergen_has_load(days: dict) -> bool:
    """True wenn mindestens einer der drei Tage eine Belastung > 0 hat."""
    return any(
        v is not None and v > 0
        for v in (days.get(k) for k in _POLLEN_DAY_KEYS)
    )


def pollen_strip_height(allergens: dict) -> int:
    """Berechnet die benötigte Höhe des Pollen-Strips dynamisch."""
    if not allergens:
        return _POLLEN_PAD_TOP + _POLLEN_TITLE_H + _POLLEN_GAP_T + 36 + _POLLEN_PAD_BOT

    active = [d for d in allergens.values() if _allergen_has_load(d)]
    n_active   = len(active)
    n_inactive = len(allergens) - n_active

    if n_active == 0:
        # Nur Kein-Pollenflug-Text, keine Datengitter
        return _POLLEN_PAD_TOP + _POLLEN_TITLE_H + _POLLEN_GAP_T + 36 + _POLLEN_PAD_BOT

    cols = 2 if n_active > 1 else 1
    rows = (n_active + cols - 1) // cols
    grid_h = rows * _POLLEN_ROW_H + max(0, rows - 1) * _POLLEN_ROW_GAP
    # Wenn Pollen ohne Flug vorhanden: eine Extra-Zeile für den Hinweis-Text
    extra = (_POLLEN_ROW_GAP + 30) if n_inactive else 0
    return _POLLEN_PAD_TOP + _POLLEN_TITLE_H + _POLLEN_GAP_T + grid_h + extra + _POLLEN_PAD_BOT


def draw_pollen_strip(img: Image.Image, bounds: tuple,
                      pollen_data: dict,
                      title_font, label_font, small_font,
                      pal: dict) -> None:
    """
    Pollenleiste mit Rasterdarstellung (max. 2 Spalten).

    Allergene ohne jeglichen Pollenflug (alle 3 Tage = 0) werden nicht im
    Raster gezeigt, sondern kompakt als Textzeile aufgelistet.
    Haben ALLE Allergene keinen Pollenflug, entfällt das Raster ganz.
    """
    from .dwd_pollen import ALLERGEN_LABELS

    left, top, right, bottom = bounds
    w = right - left

    apply_glass_panel(img, bounds, radius=22,
                      tint=pal["pollen_glass_tint"],
                      outline=pal["pollen_glass_outline"],
                      blur_radius=8)
    draw = ImageDraw.Draw(img, "RGBA")

    allergens: dict = pollen_data.get("allergens", {})

    # Aufteilen in aktive (mind. 1 Tag > 0) und inaktive Allergene
    active   = {a: d for a, d in allergens.items() if _allergen_has_load(d)}
    inactive = [ALLERGEN_LABELS.get(a, a) for a in allergens if a not in active]

    # ── Titelzeile ────────────────────────────────────────────────────────
    title_y   = top + _POLLEN_PAD_TOP
    title_mid = title_y + _POLLEN_TITLE_H // 2

    draw.text((left + _POLLEN_PAD_H, title_y + 4),
              "Pollenflug", font=title_font, fill=pal["pollen_title"])

    if not allergens:
        draw.text((left + _POLLEN_PAD_H + 160, title_y + 4),
                  "keine Daten", font=label_font, fill=pal["pollen_label"])
        return

    # Legende (nur anzeigen wenn Raster vorhanden)
    if active:
        LEG_DOT_D = 12
        LEG_GAP   = 18
        lx = right - _POLLEN_PAD_H
        for lbl in reversed(_POLLEN_DAY_LABELS):
            bb = draw.textbbox((0, 0), lbl, font=small_font)
            tw = max(bb[2] - bb[0], 1)
            lx -= tw
            draw.text((lx, title_mid - (bb[3] - bb[1]) // 2),
                      lbl, font=small_font, fill=pal["pollen_title"])
            lx -= LEG_DOT_D + 5
            draw.ellipse([(lx, title_mid - LEG_DOT_D // 2),
                          (lx + LEG_DOT_D, title_mid + LEG_DOT_D // 2)],
                         fill=(*pal["pollen_title"][:3], 170))
            lx -= LEG_GAP

    # ── Kein-Pollenflug-Modus: nur Textzeile ─────────────────────────────
    if not active:
        names_str = ", ".join(inactive)
        msg = f"Kein Pollenflug: {names_str}"
        text_y = title_y + _POLLEN_TITLE_H + _POLLEN_GAP_T
        draw.text((left + _POLLEN_PAD_H, text_y), msg,
                  font=label_font, fill=pal["pollen_label"])
        return

    # ── Datenraster für aktive Allergene ─────────────────────────────────
    n       = len(active)
    cols    = 2 if n > 1 else 1
    col_gap = 18
    col_w   = (w - 2 * _POLLEN_PAD_H - (cols - 1) * col_gap) // cols

    data_top = top + _POLLEN_PAD_TOP + _POLLEN_TITLE_H + _POLLEN_GAP_T

    for idx, (allergen, days) in enumerate(active.items()):
        col_idx  = idx % cols
        row_idx  = idx // cols

        col_left = left + _POLLEN_PAD_H + col_idx * (col_w + col_gap)
        row_top  = data_top + row_idx * (_POLLEN_ROW_H + _POLLEN_ROW_GAP)
        mid_y    = row_top + _POLLEN_ROW_H // 2

        if mid_y + _POLLEN_BIG_R > bottom:
            continue

        label_txt  = ALLERGEN_LABELS.get(allergen, allergen)
        day_values = [days.get(k) for k in _POLLEN_DAY_KEYS]
        valid_vals = [v for v in day_values if v is not None]
        max_val    = max(valid_vals) if valid_vals else None
        main_color = _pollen_load_color(max_val, flat=pal.get("flat", False))

        # Haupt-Farbpunkt (Peak der 3 Tage)
        dot_cx = col_left + _POLLEN_BIG_R
        dot_cy = mid_y
        draw.ellipse(
            [(dot_cx - _POLLEN_BIG_R, dot_cy - _POLLEN_BIG_R),
             (dot_cx + _POLLEN_BIG_R, dot_cy + _POLLEN_BIG_R)],
            fill=(*main_color, 225),
        )

        # Allergen-Name
        name_x = col_left + _POLLEN_BIG_R * 2 + 7
        name_y = row_top + (_POLLEN_ROW_H - 18) // 2
        draw.text((name_x, name_y), label_txt, font=label_font, fill=pal["pollen_label"])

        # Drei Tageswerte
        day_x = name_x + _POLLEN_NAME_W
        for day_val in day_values:
            color    = _pollen_load_color(day_val, flat=pal.get("flat", False))
            val_text = _pollen_load_label(day_val)

            draw.ellipse(
                [(day_x, mid_y - _POLLEN_SMALL_R),
                 (day_x + _POLLEN_SMALL_R * 2, mid_y + _POLLEN_SMALL_R)],
                fill=(*color, 218),
            )

            val_y = row_top + (_POLLEN_ROW_H - 20) // 2
            val_color = pal["pollen_label"] if color == (148, 155, 165) else (*color, 235)
            draw.text((day_x + _POLLEN_SMALL_R * 2 + 5, val_y),
                      val_text, font=small_font, fill=val_color)

            day_x += _POLLEN_DAY_W

    # ── Kompakter Hinweis für inaktive Allergene ──────────────────────────
    if inactive:
        rows_used = (n + cols - 1) // cols
        hint_y = (data_top
                  + rows_used * _POLLEN_ROW_H
                  + max(0, rows_used - 1) * _POLLEN_ROW_GAP
                  + _POLLEN_ROW_GAP)
        names_str = ", ".join(inactive)
        hint_text = f"Kein Pollenflug: {names_str}"
        label_color = (*pal["pollen_label"][:3], 160)
        draw.text((left + _POLLEN_PAD_H, hint_y),
                  hint_text, font=small_font, fill=label_color)


# ---------------------------------------------------------------------------
# Haupt-Render-Funktion
# ---------------------------------------------------------------------------

def render_dwd_weather_module(context: ModuleRenderServices, content: object) -> Image.Image:
    data = content if isinstance(content, dict) else {}
    rw, rh = context.render_width, context.render_height
    theme = getattr(context, "display_theme", "dark")
    pal = get_dwd_palette(theme)

    # Hintergrund
    if pal.get("flat"):
        img = Image.new("RGBA", (rw, rh), (*pal["bg_top"], 255))   # E-Ink: flach, kein Verlauf
    elif theme == "light":
        img = create_weather_background_light(rw, rh).convert("RGBA")
    else:
        img = create_weather_background(rw, rh).convert("RGBA")
    draw = ImageDraw.Draw(img, "RGBA")

    # Schriften
    font_idle          = context.load_font(32, False)
    font_eyebrow       = context.load_font(28, True)
    font_big           = context.load_font(88, True)
    font_condition     = context.load_font(34, True)
    font_value         = context.load_font(28, True)
    font_label         = context.load_font(21, True)
    flat               = bool(pal.get("flat"))
    font_micro         = context.load_font(18 if flat else 16, False)
    font_warning_title = context.load_font(22, True)
    font_chart_title   = context.load_font(22, True)
    font_chart_time    = context.load_font(16 if flat else 13, False)
    font_chart_temp    = context.load_font(18 if flat else 16, True)
    font_forecast_day  = context.load_font(20, True)
    font_forecast_temp = context.load_font(22, True)
    font_forecast_meta = context.load_font(19, False)

    # Kopfzeile
    draw.text((70, 52), format_date_long(),
              font=font_idle, fill=pal["header_idle"])
    station_label = data.get("station_name") or f"DWD-Station {data.get('station_id', '--')}"
    draw.text((70, 92), f"DWD Wetter  ·  {station_label}",
              font=font_eyebrow, fill=pal["header_station"])

    # Haupt-Panel
    panel_left   = 50
    panel_right  = rw - 50
    panel_top    = 134
    panel_bottom = rh - 18
    panel_w      = panel_right - panel_left

    apply_glass_panel(img, (panel_left, panel_top, panel_right, panel_bottom),
                      radius=34, tint=pal["panel_tint"], outline=pal["panel_outline"],
                      blur_radius=0)
    draw = ImageDraw.Draw(img, "RGBA")

    # Zone 1: Aktuelles Wetter
    cur_top   = panel_top + 20
    cur_left  = panel_left + 42
    cur_right = panel_right - 42

    icon_size = 130
    icon_x = cur_right - icon_size - 10
    draw_weather_icon(draw, icon_x, cur_top + 8, data.get("current_icon_code"),
                      icon_size, pal["icon_main"],
                      temp_hint_c=data.get("current_temp_c"))

    current_temp  = format_temp(data.get("current_temp_c"))
    current_label = data.get("current_label") or "Keine aktuellen Daten"
    today         = data.get("today", {})
    today_min     = format_temp(today.get("min_temp_c"))
    today_max     = format_temp(today.get("max_temp_c"))

    draw.text((cur_left, cur_top + 10),  current_temp,  font=font_big,       fill=pal["temp_big"])
    draw.text((cur_left, cur_top + 116), current_label, font=font_condition,  fill=pal["condition"])

    # Heute-Badge (Min/Max)
    badge_top    = cur_top + 162
    badge_bottom = badge_top + 42
    draw.rounded_rectangle(
        (cur_left, badge_top, cur_left + 290, badge_bottom),
        radius=20, fill=pal["badge_fill"], outline=pal["badge_outline"], width=1,
    )
    draw.text((cur_left + 18, badge_top + 10),
              f"Heute  {today_min} – {today_max}", font=font_value, fill=pal["badge_text"])

    # Mondphase: Scheibe + Label rechts neben dem Badge
    moon_phase = today.get("moonPhase")
    if moon_phase is not None:
        disc_r  = 14
        disc_cx = cur_left + 308          # 18 px Abstand nach Badge-Rechtsrand (290)
        disc_cy = badge_top + 21          # vertikal mittig im Badge
        draw_moon_disc(img, disc_cx, disc_cy, disc_r, moon_phase, pal)
        phase_lbl = moon_phase_label(moon_phase)
        draw.text((disc_cx + disc_r + 7, badge_top + 11),
                  phase_lbl, font=font_micro, fill=pal["moon_disc_label"])

    # Sonne + Mond: 4 Ereignisse gleichmäßig über die verfügbare Breite verteilen
    astro_y  = cur_top + 214
    ev_step  = (cur_right - cur_left) // 4   # je ~104 px bei 600 px Breite
    astro_events = [
        ("Aufgang",   today.get("sunrise",  "--:--"), True,  False),
        ("Untergang", today.get("sunset",   "--:--"), False, False),
        ("Aufgang",   today.get("moonrise", "--:--"), True,  True),
        ("Untergang", today.get("moonset",  "--:--"), False, True),
    ]
    for i, (lbl, val, is_rise, is_moon) in enumerate(astro_events):
        draw_astro_event(draw, cur_left + i * ev_step, astro_y,
                         lbl, val, is_rise, is_moon,
                         font_micro, font_label, pal)

    cur_bottom = cur_top + 268
    draw.line((panel_left + 42, cur_bottom + 6, panel_right - 42, cur_bottom + 6),
              fill=pal["divider"], width=1)

    # Zone 2: Amtliche Warnungen (optional)
    warning_items = data.get("warnings") or []
    warning_gap = 10
    warning_h = warning_strip_height(warning_items, panel_right - panel_left - 112, context.load_font)
    stat_top = cur_bottom + 20
    if warning_h > 0:
        warning_top = stat_top
        draw_warning_strip(
            img,
            (panel_left + 42, warning_top, panel_right - 42, warning_top + warning_h),
            warning_items,
            font_warning_title,
            font_micro,
            pal,
            context.load_font,
        )
        stat_top = warning_top + warning_h + warning_gap

    # Zone 3: Stat-Panels
    stat_h   = 110
    stat_gap = 14
    stat_w   = int((panel_w - 84 - stat_gap * 3) / 4)

    wind_text = data.get("current_wind_text", "--")
    wind_dir  = data.get("current_wind_dir_label", "")
    if wind_dir and wind_dir != "--":
        if "\n" in wind_text:
            # Zweizeilig: Richtung hinter Windgeschwindigkeit (Zeile 1), Böen auf Zeile 2
            parts = wind_text.split("\n", 1)
            wind_display = f"{parts[0]}  {wind_dir}\n{parts[1]}"
        else:
            wind_display = f"{wind_text}  {wind_dir}"
    else:
        wind_display = wind_text

    stat_defs = [
        ("Niederschlag", data.get("current_precipitation_mm_text", "--"), "umbrella"),
        ("Feuchte",      data.get("current_humidity_text",         "--"), "humidity"),
        ("Wind",         wind_display,                                    "wind"),
        ("Luftdruck",    data.get("current_pressure_text",         "--"), "gauge"),
    ]
    for idx, (title, value, icon_name) in enumerate(stat_defs):
        sx = panel_left + 42 + idx * (stat_w + stat_gap)
        draw_stat_panel(img, (sx, stat_top, sx + stat_w, stat_top + stat_h),
                        title, value, icon_name, font_label, font_value, pal,
                        load_font=context.load_font)

    stat_bottom = stat_top + stat_h

    # Zone 4: Pollenleiste (optional – nur wenn Pollen-Region + Allergene konfiguriert)
    pollen_data       = data.get("pollen")
    font_pollen_title = context.load_font(24, True)
    font_pollen_label = context.load_font(19, True)
    font_pollen_small = context.load_font(18, False)

    next_zone_top = stat_bottom + 14
    if pollen_data:
        pollen_allergens = pollen_data.get("allergens", {})
        pollen_gap = 10
        pollen_h   = pollen_strip_height(pollen_allergens)
        pollen_top = next_zone_top
        draw_pollen_strip(
            img,
            (panel_left + 42, pollen_top, panel_right - 42, pollen_top + pollen_h),
            pollen_data, font_pollen_title, font_pollen_label, font_pollen_small, pal,
        )
        zone3_top = pollen_top + pollen_h + pollen_gap
    else:
        zone3_top = next_zone_top

    # Zone 5 + 6: Stundenverlauf & Prognose (responsiv)
    remaining      = (panel_bottom - 14) - zone3_top
    forecast_h     = max(110, min(140, int(remaining * 0.24)))
    hourly_alloc   = max(80, remaining - forecast_h - 10)
    hourly_top     = zone3_top
    hourly_bottom  = hourly_top + hourly_alloc
    forecast_top   = hourly_bottom + 10
    forecast_bottom = panel_bottom - 14

    draw_hourly_strip(
        draw,
        (panel_left + 42, hourly_top, panel_right - 42, hourly_bottom),
        data.get("hourly_forecast") or [],
        font_chart_title, font_chart_time, font_chart_temp,
        pal,
    )

    forecast_days = data.get("days", [])[:5]
    if forecast_days and forecast_bottom > forecast_top + 40:
        draw_compact_forecast_strip(
            img,
            (panel_left + 42, forecast_top, panel_right - 42, forecast_bottom),
            forecast_days,
            font_forecast_day, font_forecast_temp, font_forecast_meta,
            pal,
        )

    return img.convert("RGB")


def should_refresh_dwd_weather_module() -> bool:
    from .dwd import should_refresh_dwd_weather
    from .dwd_pollen import should_refresh_dwd_pollen
    from .dwd_uv import should_refresh_dwd_uv

    return (
        should_refresh_dwd_weather()
        or should_refresh_dwd_uv()
        or should_refresh_dwd_pollen()
    )

