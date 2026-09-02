"""
Konfiguration, Konstanten, RuntimeConfig und Env-IO für PlexImageE-Ink.

Dieses Modul enthält ausschließlich Framework-Einstellungen (Render-Größe,
Rotation, Theme, Ausgabeformat, Idle-Verwaltung, Zeitzone).
Modul-spezifische Einstellungen (Plex, DWD, Tagesschau …) sind in den
jeweiligen modules/*/SETTINGS_FIELDS definiert.

WICHTIG: Dieses Modul darf NICHT von modules/* oder app.image_rendering
importieren – es steht am Anfang der Dependency-Chain.
"""

from __future__ import annotations

import contextlib
import functools
import os
import re
from dataclasses import dataclass, field, replace as _dc_replace
from pathlib import Path

from dotenv import dotenv_values
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
# Bewusst KEIN load_dotenv(): Settings leben ausschließlich in RuntimeConfig,
# nicht in os.environ. Sonst könnte ein Wert wie HTTPS_PROXY aus der
# Settings-Datei das Verhalten von requests beeinflussen.

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

DISPLAY_ROTATION_ALIASES = {
    "0": 0, "90": 90, "180": 180, "270": 270,
    "portrait-right": 90, "portrait-left": 270,
    "landscape": 0, "landscape-flipped": 180,
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
    {
        "name":    "NIGHT_MODE_ENABLED",
        "label":   "Nachtmodus",
        "type":    "select",
        "section": "framework",
        "wide":    False,
        "default": "false",
        "options": [("false", "Deaktiviert"), ("true", "Aktiviert")],
        "help":    "Reduziert nachts das Update-Intervall und kann die Idle-Auswahl begrenzen.",
    },
    {
        "name":        "NIGHT_MODE_START",
        "label":       "Nachtmodus ab",
        "type":        "text",
        "section":     "framework",
        "wide":        False,
        "default":     "23:00",
        "placeholder": "23:00",
        "help":        "Lokale Uhrzeit im Format HH:MM, ab der der Nachtmodus aktiv wird.",
        "show_when":   {"NIGHT_MODE_ENABLED": "true"},
    },
    {
        "name":        "NIGHT_MODE_END",
        "label":       "Nachtmodus bis",
        "type":        "text",
        "section":     "framework",
        "wide":        False,
        "default":     "07:00",
        "placeholder": "07:00",
        "help":        "Lokale Uhrzeit im Format HH:MM, bis zu der der Nachtmodus aktiv bleibt.",
        "show_when":   {"NIGHT_MODE_ENABLED": "true"},
    },
    {
        "name":        "NIGHT_MODE_INTERVAL_MINUTES",
        "label":       "Update-Intervall nachts (min)",
        "type":        "number",
        "section":     "framework",
        "wide":        False,
        "default":     "15",
        "placeholder": "15",
        "min":         1,
        "max":         720,
        "help":        "Wie oft Idle-Inhalte nachts aktualisiert werden sollen.",
        "show_when":   {"NIGHT_MODE_ENABLED": "true"},
    },
    {
        "name":    "NIGHT_MODE_IDLE_BEHAVIOR",
        "label":   "Idle-Verhalten nachts",
        "type":    "select",
        "section": "framework",
        "wide":    True,
        "default": "rotate",
        "options": [
            ("rotate", "Weiter zwischen aktiven Idle-Modulen rotieren"),
            ("fixed", "Nur ein festes Idle-Modul verwenden"),
        ],
        "help":    "Legt fest, ob nachts weiter rotiert wird oder nur ein einzelnes Idle-Modul aktiv ist.",
        "show_when": {"NIGHT_MODE_ENABLED": "true"},
    },
    {
        "name":    "NIGHT_MODE_FIXED_MODULE",
        "label":   "Festes Nachtmodul",
        "type":    "select",
        "section": "framework",
        "wide":    False,
        "default": "",
        "options": [],
        "help":    "Dieses Idle-Modul bleibt nachts dauerhaft aktiv.",
        "show_when": {"NIGHT_MODE_ENABLED": "true", "NIGHT_MODE_IDLE_BEHAVIOR": "fixed"},
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
        "fields": [
            "IDLE_MODULES",
            "IDLE_MODULE_ROTATION_SECONDS",
            "NIGHT_MODE_ENABLED",
            "NIGHT_MODE_START",
            "NIGHT_MODE_END",
            "NIGHT_MODE_INTERVAL_MINUTES",
            "NIGHT_MODE_IDLE_BEHAVIOR",
            "NIGHT_MODE_FIXED_MODULE",
        ],
    },
]


TIME_OF_DAY_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def parse_time_of_day_to_minutes(raw_value: str) -> int | None:
    value = (raw_value or "").strip()
    if not TIME_OF_DAY_RE.match(value):
        return None
    hour, minute = value.split(":", 1)
    return int(hour) * 60 + int(minute)


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


def parse_display_rotation(raw_value: str) -> int:
    return DISPLAY_ROTATION_ALIASES.get(raw_value.strip().lower(), 0)


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
    night_mode_enabled:            bool  = False
    night_mode_start:              str   = "23:00"
    night_mode_end:                str   = "07:00"
    night_mode_start_minutes:      int   = 1380
    night_mode_end_minutes:        int   = 420
    night_mode_interval_minutes:   int   = 15
    night_mode_interval_seconds:   int   = 900
    night_mode_idle_behavior:      str   = "rotate"
    night_mode_fixed_module_id:    str   = ""
    # Vollständige Settingsmap inkl. Modul-Feldern
    settings_values: dict[str, str] = field(default_factory=dict)


_cfg: RuntimeConfig = RuntimeConfig()


def get_cfg() -> RuntimeConfig:
    """Immer per Funktionsaufruf lesen – niemals _cfg direkt importieren!"""
    return _cfg


# Alle Display-Themes, die Module kennen müssen (Settings-Select + Vorschau)
AVAILABLE_THEMES: tuple[str, ...] = ("dark", "light")


@contextlib.contextmanager
def override_runtime_config(**changes):
    """
    Ersetzt die RuntimeConfig vorübergehend (z. B. display_theme für eine
    Vorschau). Nur unter dem Render-Lock des Servers verwenden, damit kein
    paralleler Render die Änderung sieht. Stellt beim Verlassen die alte
    Config wieder her, auch bei Exceptions.
    """
    global _cfg
    previous = _cfg
    if not changes:
        yield previous
        return
    settings = dict(previous.settings_values)
    if "display_theme" in changes:
        settings["DISPLAY_THEME"] = str(changes["display_theme"])
    _cfg = _dc_replace(previous, settings_values=settings, **changes)
    try:
        yield _cfg
    finally:
        _cfg = previous


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

_ENV_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
# Zeichen, bei denen der Wert in Anführungszeichen muss, damit dotenv ihn
# unverändert zurückliest (# wäre sonst ein Kommentar, Leerzeichen am Rand
# gingen verloren, Quotes/Backslashes würden interpretiert).
_ENV_NEEDS_QUOTING_RE = re.compile(r"""[#"'\\\s$`]""")


def format_env_value(value) -> str:
    """Formatiert einen Wert für eine KEY=VALUE-Zeile, sodass dotenv ihn exakt zurückliest."""
    text = as_env_value(value)
    # Zeilenumbrüche würden neue Keys injizieren – niemals durchlassen
    text = text.replace("\r", " ").replace("\n", " ")
    if text == "" or not _ENV_NEEDS_QUOTING_RE.search(text):
        return text
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def read_env_settings() -> dict[str, str]:
    if not ENV_FILE_PATH.exists():
        return {}
    return {
        key: as_env_value(value)
        # interpolate=False: ein "${HOME}" im Wert bleibt Text
        for key, value in dotenv_values(ENV_FILE_PATH, interpolate=False).items()
        if value is not None
    }


def write_env_settings(updates: dict[str, str]) -> None:
    """Schreibt die aktive Env-Konfigurationsdatei atomar via Temp-Datei + rename."""
    ENV_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = ENV_FILE_PATH.read_text(encoding="utf-8").splitlines() if ENV_FILE_PATH.exists() else []

    for key in updates:
        if not _ENV_KEY_RE.match(key):
            raise ValueError(f"Ungültiger Settings-Key: {key!r}")

    remaining = dict(updates)
    new_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            new_lines.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in remaining:
            new_lines.append(f"{key}={format_env_value(remaining.pop(key))}")
        else:
            new_lines.append(line)

    for key in SETTINGS_FIELD_ORDER:
        if key in remaining:
            new_lines.append(f"{key}={format_env_value(remaining.pop(key))}")

    for key, value in remaining.items():
        new_lines.append(f"{key}={format_env_value(value)}")

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

    if parse_bool_env(updates.get("NIGHT_MODE_ENABLED"), False):
        start_raw = get_env_value(updates, "NIGHT_MODE_START", "23:00")
        end_raw = get_env_value(updates, "NIGHT_MODE_END", "07:00")
        start_minutes = parse_time_of_day_to_minutes(start_raw)
        end_minutes = parse_time_of_day_to_minutes(end_raw)
        if start_minutes is None:
            errors.append("Nachtmodus ab: Bitte Uhrzeit im Format HH:MM angeben.")
        if end_minutes is None:
            errors.append("Nachtmodus bis: Bitte Uhrzeit im Format HH:MM angeben.")
        if start_minutes is not None and end_minutes is not None and start_minutes == end_minutes:
            errors.append("Nachtmodus: Start und Ende dürfen nicht identisch sein.")

        behavior = get_env_value(updates, "NIGHT_MODE_IDLE_BEHAVIOR", "rotate")
        if behavior not in {"rotate", "fixed"}:
            errors.append("Idle-Verhalten nachts: Ungültige Auswahl.")
        if behavior == "fixed":
            fixed_module = get_env_value(updates, "NIGHT_MODE_FIXED_MODULE", "")
            active_idle = parse_idle_module_ids(get_env_value(updates, "IDLE_MODULES", ""))
            if not fixed_module:
                errors.append("Festes Nachtmodul: Bitte ein Idle-Modul auswählen.")
            elif fixed_module not in active_idle:
                errors.append("Festes Nachtmodul: Das Modul muss auch in den aktiven Idle-Modulen enthalten sein.")

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
    refresh_interval = _parse_int(settings, "REFRESH_INTERVAL", 60, 10, 3600)
    output_format = get_env_value(settings, "OUTPUT_FORMAT", "png")
    display_theme = get_env_value(settings, "DISPLAY_THEME", "dark")
    timezone_name = get_env_value(settings, "TIMEZONE", "Europe/Berlin")
    idle_module_ids = parse_idle_module_ids(idle_modules_raw)
    idle_rotation_seconds = _parse_int(settings, "IDLE_MODULE_ROTATION_SECONDS", 120, 30, 3600)
    night_mode_enabled = parse_bool_env(settings.get("NIGHT_MODE_ENABLED"), False)
    night_mode_start = get_env_value(settings, "NIGHT_MODE_START", "23:00")
    night_mode_end = get_env_value(settings, "NIGHT_MODE_END", "07:00")
    night_mode_start_minutes = parse_time_of_day_to_minutes(night_mode_start)
    if night_mode_start_minutes is None:
        night_mode_start = "23:00"
        night_mode_start_minutes = 23 * 60
    night_mode_end_minutes = parse_time_of_day_to_minutes(night_mode_end)
    if night_mode_end_minutes is None:
        night_mode_end = "07:00"
        night_mode_end_minutes = 7 * 60
    night_mode_interval_minutes = _parse_int(settings, "NIGHT_MODE_INTERVAL_MINUTES", 15, 1, 720)
    night_mode_idle_behavior = get_env_value(settings, "NIGHT_MODE_IDLE_BEHAVIOR", "rotate")
    if night_mode_idle_behavior not in {"rotate", "fixed"}:
        night_mode_idle_behavior = "rotate"
    night_mode_fixed_module_id = get_env_value(settings, "NIGHT_MODE_FIXED_MODULE", "")

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
        "NIGHT_MODE_ENABLED": as_env_value(night_mode_enabled),
        "NIGHT_MODE_START": as_env_value(night_mode_start),
        "NIGHT_MODE_END": as_env_value(night_mode_end),
        "NIGHT_MODE_INTERVAL_MINUTES": as_env_value(night_mode_interval_minutes),
        "NIGHT_MODE_IDLE_BEHAVIOR": as_env_value(night_mode_idle_behavior),
        "NIGHT_MODE_FIXED_MODULE": as_env_value(night_mode_fixed_module_id),
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
        night_mode_enabled=night_mode_enabled,
        night_mode_start=night_mode_start,
        night_mode_end=night_mode_end,
        night_mode_start_minutes=night_mode_start_minutes,
        night_mode_end_minutes=night_mode_end_minutes,
        night_mode_interval_minutes=night_mode_interval_minutes,
        night_mode_interval_seconds=night_mode_interval_minutes * 60,
        night_mode_idle_behavior=night_mode_idle_behavior,
        night_mode_fixed_module_id=night_mode_fixed_module_id,
        settings_values=normalized_settings,
    )


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
        if f.get("type") == "password" and not form.get(name, "").strip():
            # Passwort-Felder werden leer ausgeliefert; leer abschicken = beibehalten
            updates[name] = current_values.get(name, "")
        elif f.get("type") in ("checkbox_group", "priority_list"):
            updates[name] = ",".join(form.getlist(name))
        else:
            updates[name] = as_env_value(form.get(name, ""))
    return updates


def get_settings_runtime_summary() -> dict[str, str]:
    cfg = _cfg
    return {
        "render_size":         f"{cfg.render_width}x{cfg.render_height}",
        "rotation":            f"{cfg.display_rotation}°",
        "theme":               "Light" if cfg.display_theme == "light" else "Dark",
        "output_format":       "BMP (Spectra 6)" if cfg.output_format == "bmp" else "PNG",
        "idle_modules":        ", ".join(cfg.idle_module_ids) if cfg.idle_module_ids else "Keine",
        "idle_rotation":       f"{cfg.idle_module_rotation_seconds}s",
        "night_mode":          (
            f"Aktiv {cfg.night_mode_start}–{cfg.night_mode_end}, alle {cfg.night_mode_interval_minutes} min"
            if cfg.night_mode_enabled else "Deaktiviert"
        ),
    }


# ---------------------------------------------------------------------------
# Lokale Zeit (Container laufen in UTC – nie datetime.now() ohne TZ nutzen)
# ---------------------------------------------------------------------------

WEEKDAYS_DE = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")


def local_tz():
    """ZoneInfo der konfigurierten Zeitzone, Fallback Europe/Berlin, dann UTC."""
    from datetime import timezone as _tz
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    name = (_cfg.timezone if _cfg is not None else "") or "Europe/Berlin"
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        try:
            return ZoneInfo("Europe/Berlin")
        except ZoneInfoNotFoundError:
            return _tz.utc


def now_local():
    """Aktuelle Zeit als tz-aware datetime in der konfigurierten Zeitzone."""
    from datetime import datetime as _dt
    return _dt.now(local_tz())


def format_weekday_short(d) -> str:
    """'Mi' für einen date/datetime – unabhängig vom System-Locale."""
    return WEEKDAYS_DE[d.weekday()]


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
