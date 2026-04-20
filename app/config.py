"""
Konfiguration, Konstanten, RuntimeConfig und Env-IO für PlexImageE-Ink.

Dieses Modul enthält ausschließlich Framework-Einstellungen (Render-Größe,
Rotation, Theme, Ausgabeformat, Idle-Verwaltung, Zeitzone).
Modul-spezifische Einstellungen (Plex, DWD, Tagesschau …) sind in den
jeweiligen modules/*/SETTINGS_FIELDS definiert.

WICHTIG: Dieses Modul darf NICHT von app.plex oder app.image_rendering
importieren – es steht am Anfang der Dependency-Chain.
"""

from __future__ import annotations

import functools
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values, load_dotenv
from PIL import ImageFont


# ---------------------------------------------------------------------------
# Verzeichnisse
# ---------------------------------------------------------------------------

BASE_DIR    = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
CONFIG_DIR = PROJECT_DIR / "config"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def resolve_env_file_path() -> Path:
    configured = os.environ.get("PLEXINK_CONFIG_FILE", "").strip()
    if configured:
        return Path(configured).expanduser()
    return CONFIG_DIR / "settings.env"


ENV_FILE_PATH = resolve_env_file_path()
load_dotenv(ENV_FILE_PATH)

# Ausgabepfad: per PLEXINK_OUTPUT_DIR überschreibbar (Docker: /output)
_output_env = os.environ.get("PLEXINK_OUTPUT_DIR", "").strip()
DATA_DIR = Path(_output_env) if _output_env else PROJECT_DIR / "data" / "output"
DATA_DIR.mkdir(parents=True, exist_ok=True)

CURRENT_IMAGE_PATH = DATA_DIR / "current.png"
CURRENT_BMP_PATH   = DATA_DIR / "current.bmp"
STATE_PATH         = DATA_DIR / "state.txt"


# ---------------------------------------------------------------------------
# Anwendungskonstanten
# ---------------------------------------------------------------------------

DEFAULT_SESSION_PRIORITY              = ["movie", "episode", "track"]
TAGESSCHAU_API_URL                    = "https://www.tagesschau.de/api2u/homepage/"
DWD_STATION_OVERVIEW_URL              = "https://app-prod-ws.warnwetter.de/v30/stationOverviewExtended?stationIds={station_id}"
DEFAULT_TAGESSCHAU_IDLE_COUNT         = 3
DEFAULT_TAGESSCHAU_IDLE_CACHE_SECONDS = 900
DEFAULT_TAGESSCHAU_IMAGE_CACHE_SECONDS = 1800
DEFAULT_DWD_WEATHER_CACHE_SECONDS     = 900

DWD_STATION_NAMES = {
    "10532": "Gießen",
}

PLAYBACK_LABELS = {
    "playing":   "Now Playing",
    "paused":    "Pausiert",
    "buffering": "Lädt",
    "stopped":   "Gestoppt",
}

PLAYER_STATE_PRIORITY = {
    "playing":   0,
    "buffering": 1,
    "paused":    2,
    "stopped":   3,
    "unknown":   4,
}

VIDEO_SESSION_FIELDS = {
    "mediaCategory":    "video",
    "type":             "video",
    "title":            "Unbekannt",
    "grandparentTitle": "",
    "parentTitle":      "",
    "parentIndex":      "",
    "index":            "",
    "year":             "",
    "thumb":            "",
    "art":              "",
    "parentThumb":      "",
    "grandparentThumb": "",
    "parentArt":        "",
    "grandparentArt":   "",
    "ratingKey":        "",
    "duration":         "",
    "viewOffset":       "",
}

TRACK_SESSION_FIELDS = {
    "mediaCategory":    "music",
    "type":             "track",
    "title":            "Unbekannt",
    "grandparentTitle": "",
    "parentTitle":      "",
    "parentIndex":      "",
    "index":            "",
    "year":             "",
    "thumb":            "",
    "art":              "",
    "ratingKey":        "",
    "duration":         "",
    "viewOffset":       "",
}

ARTWORK_FIELD_ORDERS = {
    "movie": {
        "movie_thumb": ["thumb", "art"],
        "movie_art":   ["art", "thumb"],
        "auto":        ["thumb", "art"],
    },
    "episode": {
        "series_thumb":  ["grandparentThumb", "parentThumb", "thumb", "grandparentArt", "parentArt", "art"],
        "series_art":    ["grandparentArt", "parentArt", "art", "grandparentThumb", "parentThumb", "thumb"],
        "season_thumb":  ["parentThumb", "grandparentThumb", "thumb", "parentArt", "grandparentArt", "art"],
        "season_art":    ["parentArt", "grandparentArt", "art", "parentThumb", "grandparentThumb", "thumb"],
        "episode_thumb": ["thumb", "grandparentThumb", "parentThumb", "art", "grandparentArt", "parentArt"],
        "episode_art":   ["art", "thumb", "grandparentArt", "parentArt", "grandparentThumb", "parentThumb"],
        "auto":          ["grandparentThumb", "parentThumb", "thumb", "grandparentArt", "parentArt", "art"],
    },
    "default": {
        "auto": ["thumb", "art"],
    },
}

SESSION_PRIORITY_ALIASES = {
    "film": "movie", "filme": "movie", "movie": "movie", "movies": "movie",
    "serie": "episode", "serien": "episode", "series": "episode", "episode": "episode", "episodes": "episode",
    "musik": "track", "music": "track", "track": "track", "tracks": "track",
}

DISPLAY_ROTATION_ALIASES = {
    "0": 0, "90": 90, "180": 180, "270": 270,
    "portrait-right": 90, "portrait-left": 270,
    "landscape": 0, "landscape-flipped": 180,
}

EPISODE_ARTWORK_SOURCE_ALIASES = {
    "auto": "auto",
    "episode_thumb": "episode_thumb", "thumbnail": "episode_thumb", "thumb": "episode_thumb",
    "episode_art": "episode_art", "art": "episode_art",
    "series_thumb": "series_thumb", "series_cover": "series_thumb", "show_thumb": "series_thumb",
    "series_art": "series_art", "show_art": "series_art",
    "season_thumb": "season_thumb", "season_cover": "season_thumb",
    "season_art": "season_art",
}

MOVIE_ARTWORK_SOURCE_ALIASES = {
    "auto": "auto",
    "movie_thumb": "movie_thumb", "poster": "movie_thumb", "cover": "movie_thumb", "thumb": "movie_thumb",
    "movie_art": "movie_art", "background": "movie_art", "backdrop": "movie_art", "art": "movie_art",
}

# ---------------------------------------------------------------------------
# Framework-Settings-Felder
# Modulspezifische Felder liegen in modules/*/SETTINGS_FIELDS.
# ---------------------------------------------------------------------------

SETTINGS_FIELDS: list[dict] = [
    # ── Render-Grundeinstellungen ────────────────────────────────────────────
    {
        "name":        "REFRESH_INTERVAL",
        "label":       "Refresh-Intervall (s)",
        "type":        "number",
        "section":     "framework",
        "wide":        False,
        "placeholder": "60",
        "min":         10,
        "max":         3600,
        "help":        "Intervall in Sekunden für den Hintergrund-Prüfzyklus.",
    },
    {
        "name":        "RENDER_WIDTH",
        "label":       "Render-Breite (px)",
        "type":        "number",
        "section":     "framework",
        "wide":        False,
        "placeholder": "1600",
        "min":         400,
        "max":         3840,
        "help":        "Basisbreite vor optionaler Rotation.",
    },
    {
        "name":        "RENDER_HEIGHT",
        "label":       "Render-Höhe (px)",
        "type":        "number",
        "section":     "framework",
        "wide":        False,
        "placeholder": "1200",
        "min":         300,
        "max":         2160,
        "help":        "Basishöhe vor optionaler Rotation.",
    },
    {
        "name":    "DISPLAY_ROTATION",
        "label":   "Display-Ausrichtung",
        "type":    "select",
        "section": "framework",
        "wide":    False,
        "options": [("0", "0°"), ("90", "90°"), ("180", "180°"), ("270", "270°")],
        "help":    "90 und 270 rendern im Hochformat. 180 und 270 sind auf dem Kopf.",
    },
    {
        "name":    "DISPLAY_THEME",
        "label":   "Display-Theme",
        "type":    "select",
        "section": "framework",
        "wide":    True,
        "options": [
            ("dark",  "🌑 Dark – verschwommenes Artwork, weißer Text"),
            ("light", "☀️ Light – heller Hintergrund für E-Ink-Farbdisplay (Spectra 6, 1600×1200)"),
        ],
        "help": (
            "Steuert das Aussehen aller generierten Bilder. "
            "Dark: Artwork-Blur-Hintergrund mit weißem Text. "
            "Light: cremefarbener Hintergrund – optimiert für Waveshare 13,3″ Spectra 6."
        ),
    },
    {
        "name":    "OUTPUT_FORMAT",
        "label":   "Ausgabeformat",
        "type":    "select",
        "section": "framework",
        "wide":    True,
        "options": [
            ("png", "PNG – Vollfarb, für HDMI- oder Web-Displays"),
            ("bmp", "BMP – Spectra 6 Dithering, für Waveshare 13,3″ E-Ink-Farbdisplay"),
        ],
        "help": (
            "PNG: Vollfarb-RGB. BMP: Floyd-Steinberg-Dithering auf 6 Spectra-Farben "
            "für das Waveshare Spectra 6 E-Ink-Display."
        ),
    },
    # ── Lokalisierung ────────────────────────────────────────────────────────
    {
        "name":        "TIMEZONE",
        "label":       "Zeitzone",
        "type":        "text",
        "section":     "framework",
        "wide":        False,
        "placeholder": "Europe/Berlin",
        "help":        "IANA-Zeitzonenname (z. B. Europe/Berlin, Europe/Vienna).",
        "link_href":   "https://en.wikipedia.org/wiki/List_of_tz_database_time_zones",
        "link_label":  "Liste aller Zeitzonen",
    },
    # ── Idle-Verwaltung ──────────────────────────────────────────────────────
    {
        "name":    "IDLE_MODULES",
        "label":   "Aktive Idle-Module",
        "type":    "checkbox_group",
        "section": "framework",
        "wide":    True,
        "options": [],   # wird zur Laufzeit aus der Registry befüllt
        "help":    (
            "Welche Idle-Module aktiv sind. "
            "Wenn mehrere aktiv sind, wird zwischen ihnen rotiert."
        ),
    },
    {
        "name":        "IDLE_MODULE_ROTATION_SECONDS",
        "label":       "Idle-Rotation (s)",
        "type":        "number",
        "section":     "framework",
        "wide":        False,
        "placeholder": "120",
        "min":         30,
        "max":         3600,
        "help":        "Intervall in Sekunden für die Rotation zwischen mehreren Idle-Modulen.",
    },
]

SETTINGS_FIELD_ORDER = [f["name"] for f in SETTINGS_FIELDS]

# Framework-Untergruppen für die Settings-Seite
SETTINGS_GROUPS: list[dict] = [
    {
        "title":  "Render-Ausgabe",
        "desc":   "Größe, Rotation, Theme und Dateiformat des erzeugten Bildes.",
        "fields": [
            "REFRESH_INTERVAL",
            "RENDER_WIDTH", "RENDER_HEIGHT",
            "DISPLAY_ROTATION", "DISPLAY_THEME", "OUTPUT_FORMAT",
        ],
    },
    {
        "title":  "Lokalisierung",
        "desc":   "Zeitzone für Uhrzeiten und lokale Daten.",
        "fields": ["TIMEZONE"],
    },
    {
        "title":  "Idle-Verwaltung",
        "desc":   "Welche Idle-Module angezeigt werden und wie zwischen ihnen rotiert wird.",
        "fields": ["IDLE_MODULES", "IDLE_MODULE_ROTATION_SECONDS"],
    },
]


# ---------------------------------------------------------------------------
# Parse-Hilfsfunktionen
# ---------------------------------------------------------------------------

def parse_idle_module_ids(raw_value: str) -> tuple[str, ...]:
    # Gültige IDs kommen jetzt aus der Registry – wir akzeptieren alles
    # (Registry prüft beim Laden ob das Modul existiert)
    parsed = []
    for item in (raw_value or "").split(","):
        mid = item.strip().lower()
        if mid and mid not in parsed:
            parsed.append(mid)
    return tuple(parsed)


def parse_session_priority(raw_value: str) -> tuple[str, ...]:
    if not raw_value.strip():
        return tuple(DEFAULT_SESSION_PRIORITY)
    parsed = []
    for item in raw_value.split(","):
        normalized = SESSION_PRIORITY_ALIASES.get(item.strip().lower())
        if normalized and normalized not in parsed:
            parsed.append(normalized)
    for fallback in DEFAULT_SESSION_PRIORITY:
        if fallback not in parsed:
            parsed.append(fallback)
    return tuple(parsed)


def parse_display_rotation(raw_value: str) -> int:
    return DISPLAY_ROTATION_ALIASES.get(raw_value.strip().lower(), 0)


def parse_episode_artwork_source(raw_value: str) -> str:
    return EPISODE_ARTWORK_SOURCE_ALIASES.get(raw_value.strip().lower(), "series_thumb")


def parse_movie_artwork_source(raw_value: str) -> str:
    return MOVIE_ARTWORK_SOURCE_ALIASES.get(raw_value.strip().lower(), "movie_thumb")


def parse_allowed_users(raw_value: str) -> frozenset[str]:
    if not raw_value.strip():
        return frozenset()
    return frozenset(u.strip().lower() for u in raw_value.split(",") if u.strip())


def get_effective_render_size(base_w: int, base_h: int, rotation: int) -> tuple[int, int]:
    if rotation in {90, 270}:
        return base_h, base_w
    return base_w, base_h


def should_flip_output(rotation: int) -> bool:
    return rotation in {180, 270}


def parse_bool_env(raw_value: str | None, default: bool) -> bool:
    if raw_value is None:
        return default
    return raw_value.strip().lower() == "true"


def as_env_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip()


def get_env_value(settings: dict[str, str], key: str, default: str) -> str:
    value = settings.get(key)
    if value is None or value == "":
        return default
    return str(value).strip()


def _parse_int(settings: dict, key: str, default: int,
               min_val: int | None = None, max_val: int | None = None) -> int:
    try:
        v = int(get_env_value(settings, key, str(default)))
        if min_val is not None:
            v = max(min_val, v)
        if max_val is not None:
            v = min(max_val, v)
        return v
    except ValueError:
        try:
            from app.logger import get_logger as _gl
            _gl("config").warning(f"Ungültiger Wert für {key}, nutze Default {default}")
        except Exception:
            import sys
            print(f"[WARN] Ungültiger Wert für {key}, nutze Default {default}", file=sys.stderr)
        return default


# ---------------------------------------------------------------------------
# RuntimeConfig – thread-sichere Konfiguration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RuntimeConfig:
    # Framework
    base_render_width:  int  = 1600
    base_render_height: int  = 1200
    refresh_interval:   int  = 60
    display_rotation:   int  = 0
    display_theme:      str  = "dark"
    output_format:      str  = "png"
    render_width:       int  = 1600
    render_height:      int  = 1200
    timezone:           str  = "Europe/Berlin"
    # Idle-Verwaltung
    idle_module_ids:               tuple = ()
    idle_module_rotation_seconds:  int   = 120
    # Vollständige Settingsmap inkl. Modul-Feldern
    settings_values: dict[str, str] = field(default_factory=dict)


_cfg: RuntimeConfig = RuntimeConfig()


def get_cfg() -> RuntimeConfig:
    """Immer per Funktionsaufruf lesen – niemals _cfg direkt importieren!"""
    return _cfg


def get_setting(name: str, default: str = "") -> str:
    value = _cfg.settings_values.get(name)
    if value is None or value == "":
        return default
    return str(value)


def get_bool_setting(name: str, default: bool = False) -> bool:
    raw = _cfg.settings_values.get(name)
    return parse_bool_env(raw, default)


def get_int_setting(
    name: str,
    default: int,
    min_val: int | None = None,
    max_val: int | None = None,
) -> int:
    raw = _cfg.settings_values.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(str(raw).strip())
    except ValueError:
        return default
    if min_val is not None:
        value = max(min_val, value)
    if max_val is not None:
        value = min(max_val, value)
    return value


def get_csv_setting(name: str) -> tuple[str, ...]:
    raw = get_setting(name, "")
    if not raw:
        return ()
    seen: list[str] = []
    for item in raw.split(","):
        cleaned = item.strip()
        if cleaned and cleaned not in seen:
            seen.append(cleaned)
    return tuple(seen)


# ---------------------------------------------------------------------------
# Env-IO
# ---------------------------------------------------------------------------

def read_env_settings() -> dict[str, str]:
    if not ENV_FILE_PATH.exists():
        return {}
    return {
        key: as_env_value(value)
        for key, value in dotenv_values(ENV_FILE_PATH).items()
        if value is not None
    }


def write_env_settings(updates: dict[str, str]) -> None:
    """Schreibt die aktive Env-Konfigurationsdatei atomar via Temp-Datei + rename."""
    ENV_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = ENV_FILE_PATH.read_text(encoding="utf-8").splitlines() if ENV_FILE_PATH.exists() else []
    remaining = dict(updates)
    new_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            new_lines.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in remaining:
            new_lines.append(f"{key}={remaining.pop(key)}")
        else:
            new_lines.append(line)

    for key in SETTINGS_FIELD_ORDER:
        if key in remaining:
            new_lines.append(f"{key}={remaining.pop(key)}")

    for key, value in remaining.items():
        new_lines.append(f"{key}={value}")

    content = "\n".join(new_lines).rstrip() + "\n"
    tmp = ENV_FILE_PATH.with_suffix(".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(ENV_FILE_PATH)


def validate_settings(updates: dict[str, str], all_fields: list[dict] | None = None) -> list[str]:
    """Serverseitige Validierung. Gibt Liste mit Fehlermeldungen zurück."""
    errors: list[str] = []

    fields_to_check = (all_fields or []) + SETTINGS_FIELDS
    field_map = {f["name"]: f for f in fields_to_check}
    for key, raw in updates.items():
        f = field_map.get(key)
        if not f or f.get("type") != "number":
            continue
        try:
            v = int(raw)
            if "min" in f and v < f["min"]:
                errors.append(f"{f['label']}: Mindestwert ist {f['min']}.")
            if "max" in f and v > f["max"]:
                errors.append(f"{f['label']}: Maximalwert ist {f['max']}.")
        except ValueError:
            errors.append(f"{f['label']}: Muss eine ganze Zahl sein.")

    return errors


def apply_runtime_config(settings: dict[str, str] | None = None) -> None:
    """Baut eine neue RuntimeConfig und ersetzt _cfg atomar."""
    global _cfg
    settings = settings or read_env_settings()

    base_w   = _parse_int(settings, "RENDER_WIDTH",  1600, 400, 3840)
    base_h   = _parse_int(settings, "RENDER_HEIGHT", 1200, 300, 2160)
    rotation = parse_display_rotation(get_env_value(settings, "DISPLAY_ROTATION", "0"))
    render_w, render_h = get_effective_render_size(base_w, base_h, rotation)

    idle_modules_raw = get_env_value(settings, "IDLE_MODULES", "")
    # Backward-compat: alter Key TAGESSCHAU_IDLE_ENABLED
    if not idle_modules_raw and parse_bool_env(settings.get("TAGESSCHAU_IDLE_ENABLED"), False):
        idle_modules_raw = "tagesschau"

    refresh_interval = _parse_int(settings, "REFRESH_INTERVAL", 60, 10, 3600)
    output_format = get_env_value(settings, "OUTPUT_FORMAT", "png")
    display_theme = get_env_value(settings, "DISPLAY_THEME", "dark")
    timezone_name = get_env_value(settings, "TIMEZONE", "Europe/Berlin")
    idle_module_ids = parse_idle_module_ids(idle_modules_raw)
    idle_rotation_seconds = _parse_int(settings, "IDLE_MODULE_ROTATION_SECONDS", 120, 30, 3600)

    normalized_settings = {
        key: as_env_value(value)
        for key, value in settings.items()
        if value is not None
    }
    normalized_settings.update({
        "REFRESH_INTERVAL": as_env_value(refresh_interval),
        "RENDER_WIDTH": as_env_value(base_w),
        "RENDER_HEIGHT": as_env_value(base_h),
        "DISPLAY_ROTATION": as_env_value(rotation),
        "DISPLAY_THEME": as_env_value(display_theme),
        "OUTPUT_FORMAT": as_env_value(output_format),
        "TIMEZONE": as_env_value(timezone_name),
        "IDLE_MODULES": as_env_value(",".join(idle_module_ids)),
        "IDLE_MODULE_ROTATION_SECONDS": as_env_value(idle_rotation_seconds),
    })

    _cfg = RuntimeConfig(
        base_render_width=base_w,
        base_render_height=base_h,
        refresh_interval=refresh_interval,
        display_rotation=rotation,
        display_theme=display_theme,
        output_format=output_format,
        render_width=render_w,
        render_height=render_h,
        timezone=timezone_name,
        idle_module_ids=idle_module_ids,
        idle_module_rotation_seconds=idle_rotation_seconds,
        settings_values=normalized_settings,
    )

    for key, value in normalized_settings.items():
        os.environ[key] = as_env_value(value)


def get_settings_values() -> dict[str, str]:
    """Gibt alle aktuellen Konfigurationswerte als String-Dict zurück."""
    return dict(_cfg.settings_values)


def collect_settings_form_data(form, all_fields: list[dict]) -> dict[str, str]:
    """
    Liest alle Formularfelder aus und gibt ein dict[str, str] für write_env_settings zurück.
    all_fields: kombinierte Liste aus Framework-Feldern + Modul-Feldern.
    """
    updates: dict[str, str] = {}
    current_values = get_settings_values()
    for f in all_fields:
        name = f["name"]
        if name == "PLEX_TOKEN" and not form.get(name, "").strip():
            updates[name] = current_values.get(name, "")
        elif f.get("type") in ("checkbox_group", "priority_list"):
            updates[name] = ",".join(form.getlist(name))
        else:
            updates[name] = as_env_value(form.get(name, ""))

    # Backward-compat
    selected = {item for item in updates.get("IDLE_MODULES", "").split(",") if item}
    updates["TAGESSCHAU_IDLE_ENABLED"] = "true" if "tagesschau" in selected else "false"
    return updates


def get_settings_runtime_summary() -> dict[str, str]:
    cfg = _cfg
    return {
        "render_size":         f"{cfg.render_width}x{cfg.render_height}",
        "rotation":            str(cfg.display_rotation),
        "theme":               "Light" if cfg.display_theme == "light" else "Dark",
        "output_format":       "BMP (Spectra 6)" if cfg.output_format == "bmp" else "PNG",
        "idle_modules":        ", ".join(cfg.idle_module_ids) if cfg.idle_module_ids else "Keine",
        "idle_rotation":       f"{cfg.idle_module_rotation_seconds}s",
    }


# ---------------------------------------------------------------------------
# Font-Loading mit Cache
# ---------------------------------------------------------------------------

@functools.lru_cache(maxsize=64)
def load_font(size: int, is_bold: bool = False):
    if os.name == "nt":
        candidates = (
            ["C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/calibrib.ttf", "C:/Windows/Fonts/segoeuib.ttf"]
            if is_bold else
            ["C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/calibri.ttf", "C:/Windows/Fonts/segoeui.ttf"]
        )
    else:
        # fonts-dejavu-core (Debian/Ubuntu) oder ttf-dejavu (Arch)
        candidates = (
            [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
            ]
            if is_bold else
            [
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/TTF/DejaVuSans.ttf",
                "/usr/share/fonts/dejavu/DejaVuSans.ttf",
            ]
        )
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    # Kein TrueType-Font gefunden – Bitmap-Fallback (kein anchor-Support!)
    import logging as _logging
    _logging.getLogger("plex_ink.config").warning(
        f"load_font({size}, bold={is_bold}): kein TrueType-Font gefunden "
        f"(Kandidaten: {candidates}). Bitmap-Fallback aktiv – "
        f"anchor-Parameter in draw.text() funktioniert NICHT."
    )
    return ImageFont.load_default()


# Initiale Konfiguration laden
apply_runtime_config()
