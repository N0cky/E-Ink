"""
DWD-Wetter-Modul für PlexImageE-Ink.

Idle-Modul (MODULE_PRIORITY = 100): wird angezeigt wenn kein Prioritätsmodul
(z. B. Plex) aktiven Inhalt meldet.

Zeigt aktuelles Wetter, Stundenverlauf, Mehrtagesprognose, UV-Index und
Pollenflug basierend auf Daten des Deutschen Wetterdienstes (DWD).
"""

from __future__ import annotations

from typing import Any

from PIL import Image

from app.module_base import PlexInkModule
from app.module_services import ModuleFetchServices, ModuleRenderServices
from app.logger import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Settings-Felder dieses Moduls
# ---------------------------------------------------------------------------

SETTINGS_FIELDS: list[dict] = [
    {
        "name":        "DWD_WEATHER_STATION_ID",
        "label":       "DWD-Station-ID",
        "type":        "text",
        "wide":        False,
        "default":     "10532",
        "placeholder": "10532",
        "help":        "Stations-ID für das DWD-Wettermodul, z. B. 10532 für Gießen.",
        "link_href":   (
            "https://www.dwd.de/DE/leistungen/klimadatendeutschland/statliste/"
            "statlex_html.html?view=nasPublication&nn=16102"
        ),
        "link_label":  "Stationsliste des DWD öffnen",
        "link_note":   (
            "Bitte auf das Enddatum achten: In der Liste stehen auch ältere, "
            "inzwischen geschlossene Stationen."
        ),
    },
    {
        "name":        "DWD_WEATHER_CACHE_SECONDS",
        "label":       "Wetter-Cache (s)",
        "type":        "number",
        "wide":        False,
        "default":     "900",
        "placeholder": "900",
        "min":         60,
        "max":         86400,
        "help":        "Wie lange DWD-Wetterdaten gecacht werden bevor ein neuer Abruf erfolgt.",
    },
    {
        "name":    "DWD_HOURLY_START",
        "label":   "Verlauf-Startpunkt",
        "type":    "select",
        "wide":    True,
        "default": "day_start",
        "options": [
            ("day_start",    "Ab Tagesbeginn (00:00) – aktueller Tag plus etwas Folgetag"),
            ("current_hour", "Ab aktueller voller Stunde – gleicher Umfang, aber ab jetzt"),
        ],
        "help": (
            "'Ab Tagesbeginn' startet um 00:00 und zeigt den aktuellen Tag plus etwas vom nächsten. "
            "'Ab aktueller Stunde' startet bei der letzten vollen Stunde."
        ),
    },
    {
        "name":    "DWD_HOURLY_INTERVAL_HOURS",
        "label":   "Verlauf-Intervall",
        "type":    "select",
        "wide":    False,
        "default": "2",
        "options": [
            ("1", "1 Stunde"),
            ("2", "2 Stunden"),
            ("3", "3 Stunden"),
            ("4", "4 Stunden"),
        ],
        "help": "Abstand zwischen Datenpunkten im Stundenverlauf.",
    },
    {
        "name":         "DWD_UV_CITY",
        "label":        "UV-Index-Stadt",
        "type":         "text",
        "wide":         False,
        "default":      "",
        "placeholder":  "z. B. Frankfurt/Main",
        "datalist_url": "/api/module-field-options/dwd_weather/DWD_UV_CITY",
        "help":         (
            "Stadtname für den DWD UV-Index. Tippen und Vorschlag auswählen. "
            "Leer = UV-Anzeige deaktiviert."
        ),
        "link_href":  "https://opendata.dwd.de/climate_environment/health/alerts/uvi.json",
        "link_label": "DWD UV-Index-API ansehen",
    },
    {
        "name":    "DWD_POLLEN_REGION",
        "label":   "Pollen-Region",
        "type":    "select",
        "wide":    True,
        "default": "",
        "options": [
            ("",       "Keine Pollenanzeige"),
            ("10:-1",  "Schleswig-Holstein und Hamburg"),
            ("11:-1",  "Schleswig-Holstein und Hamburg – Inseln und Marschen"),
            ("12:-1",  "Schleswig-Holstein und Hamburg – Geest, SH und HH"),
            ("30:-1",  "Niedersachsen und Bremen"),
            ("31:-1",  "Niedersachsen und Bremen – Westl. Niedersachsen/Bremen"),
            ("32:-1",  "Niedersachsen und Bremen – Östl. Niedersachsen"),
            ("40:-1",  "Nordrhein-Westfalen"),
            ("41:-1",  "Nordrhein-Westfalen – Rhein.-Westfäl. Tiefland"),
            ("42:-1",  "Nordrhein-Westfalen – Ostwestfalen"),
            ("43:-1",  "Mittelgebirge NRW"),
            ("50:-1",  "Brandenburg und Berlin"),
            ("60:-1",  "Sachsen-Anhalt"),
            ("61:-1",  "Sachsen-Anhalt – Tiefland"),
            ("62:-1",  "Sachsen-Anhalt – Harz"),
            ("70:-1",  "Thüringen"),
            ("71:-1",  "Thüringen – Tiefland"),
            ("72:-1",  "Thüringen – Mittelgebirge"),
            ("80:-1",  "Sachsen"),
            ("81:-1",  "Sachsen – Tiefland"),
            ("82:-1",  "Sachsen – Mittelgebirge"),
            ("90:-1",  "Hessen"),
            ("91:-1",  "Hessen – Nordhessen und hess. Mittelgebirge"),
            ("92:-1",  "Hessen – Rhein-Main"),
            ("100:-1", "Rheinland-Pfalz und Saarland"),
            ("101:-1", "Rheinland-Pfalz und Saarland – Rhein, Pfalz, Nahe, Mosel"),
            ("102:-1", "Rheinland-Pfalz und Saarland – Mittelgebirge"),
            ("103:-1", "Rheinland-Pfalz und Saarland – Saarland"),
            ("110:-1", "Baden-Württemberg"),
            ("111:-1", "Baden-Württemberg – Oberrhein und unteres Neckartal"),
            ("112:-1", "Baden-Württemberg – Hohenlohe/mittlerer Neckar/Oberschwaben"),
            ("113:-1", "Baden-Württemberg – Mittelgebirge"),
            ("120:-1", "Bayern"),
            ("121:-1", "Bayern – Allgäu/Oberbayern/Bay. Wald"),
            ("122:-1", "Bayern – Donauniederungen"),
            ("123:-1", "Bayern – n. der Donau, o. Bayr. Wald, o. Mainfranken"),
            ("124:-1", "Bayern – Mainfranken"),
        ],
        "help": (
            "Region für die DWD-Pollenflug-Vorhersage. Leer = Pollenanzeige deaktiviert. "
            "Daten werden vom DWD einmal täglich aktualisiert."
        ),
        "link_href":  "https://opendata.dwd.de/climate_environment/health/alerts/s31fg.json",
        "link_label": "DWD-Pollen-API ansehen",
    },
    {
        "name":    "DWD_POLLEN_ALLERGENS",
        "label":   "Angezeigte Pollen",
        "type":    "checkbox_group",
        "wide":    True,
        "default": "",
        "options": [
            ("Birke",    "Birke"),
            ("Esche",    "Esche"),
            ("Hasel",    "Hasel"),
            ("Erle",     "Erle"),
            ("Graeser",  "Gräser"),
            ("Roggen",   "Roggen"),
            ("Beifuss",  "Beifuß"),
            ("Ambrosia", "Ambrosia"),
        ],
        "help": (
            "Welche Pollen im Wetter-Modul angezeigt werden. "
            "Nichts ausgewählt = kein Pollenstreifen."
        ),
    },
]

SETTINGS_GROUPS: list[dict] = [
    {
        "title":  "Wetterstation",
        "desc":   "DWD-Station und Cache-Einstellungen.",
        "fields": ["DWD_WEATHER_STATION_ID", "DWD_WEATHER_CACHE_SECONDS"],
    },
    {
        "title":  "Stundenverlauf",
        "desc":   "Darstellung des Temperaturverlaufs.",
        "fields": ["DWD_HOURLY_START", "DWD_HOURLY_INTERVAL_HOURS"],
    },
    {
        "title":  "UV & Pollen",
        "desc":   "Gesundheitsdaten: UV-Belastung und Pollenflug.",
        "fields": ["DWD_UV_CITY", "DWD_POLLEN_REGION", "DWD_POLLEN_ALLERGENS"],
    },
]


# ---------------------------------------------------------------------------
# Modul-Implementierung
# ---------------------------------------------------------------------------

class DWDWeatherModule(PlexInkModule):
    MODULE_ID          = "dwd_weather"
    MODULE_NAME        = "DWD Wetter"
    MODULE_DESCRIPTION = (
        "Zeigt aktuelles Wetter, Stundenverlauf, Mehrtagesprognose sowie optional "
        "UV-Index und Pollenflug basierend auf Daten des Deutschen Wetterdienstes."
    )
    MODULE_PRIORITY  = 100
    SETTINGS_FIELDS  = SETTINGS_FIELDS
    SETTINGS_GROUPS  = SETTINGS_GROUPS

    def is_enabled(self, env: dict[str, str]) -> bool:
        idle = {x.strip() for x in env.get("IDLE_MODULES", "").split(",") if x.strip()}
        return self.MODULE_ID in idle

    def fetch_content(self, env: dict[str, str]) -> dict | None:
        from .renderer import fetch_dwd_weather_content, has_dwd_weather_content
        from .dwd import fetch_dwd_weather, should_refresh_dwd_weather
        from modules.tagesschau.data_source import (
            fetch_tagesschau_news,
            should_refresh_tagesschau_news,
        )
        services = ModuleFetchServices(
            fetch_tagesschau_news=fetch_tagesschau_news,
            should_refresh_tagesschau_news=should_refresh_tagesschau_news,
            fetch_dwd_weather=fetch_dwd_weather,
            should_refresh_dwd_weather=should_refresh_dwd_weather,
        )
        content = fetch_dwd_weather_content(services)
        return content if has_dwd_weather_content(content) else None

    def render(self, env: dict[str, str], content: Any) -> Image.Image:
        from .renderer import render_dwd_weather_module
        from app.config import get_cfg, load_font
        from modules.tagesschau.data_source import fetch_tagesschau_image
        from app.image_rendering import create_rounded_thumbnail
        cfg = get_cfg()
        services = ModuleRenderServices(
            render_width=cfg.render_width,
            render_height=cfg.render_height,
            load_font=load_font,
            fetch_tagesschau_image=fetch_tagesschau_image,
            create_rounded_thumbnail=create_rounded_thumbnail,
            display_theme=cfg.display_theme,
        )
        return render_dwd_weather_module(services, content)

    def should_refresh(self, env: dict[str, str]) -> bool:
        from .renderer import should_refresh_dwd_weather_module
        from .dwd import fetch_dwd_weather, should_refresh_dwd_weather
        from modules.tagesschau.data_source import (
            fetch_tagesschau_news,
            should_refresh_tagesschau_news,
        )
        services = ModuleFetchServices(
            fetch_tagesschau_news=fetch_tagesschau_news,
            should_refresh_tagesschau_news=should_refresh_tagesschau_news,
            fetch_dwd_weather=fetch_dwd_weather,
            should_refresh_dwd_weather=should_refresh_dwd_weather,
        )
        return should_refresh_dwd_weather_module(services)

    def get_state_key(self, content: Any) -> str:
        # Eindeutig über Station-ID; should_refresh() löst den Neu-Render aus
        if isinstance(content, dict):
            return content.get("station_id", "dwd")
        return "dwd_weather"

    def get_field_options(self, field_name: str, env: dict[str, str]) -> list | None:
        if field_name != "DWD_UV_CITY":
            return None
        from .dwd_uv import fetch_uv_city_names
        return fetch_uv_city_names()

    def handle_api_action(self, action: str, env: dict[str, str]) -> tuple[object, int] | None:
        if action != "uv-cities":
            return None
        return {"options": self.get_field_options("DWD_UV_CITY", env) or []}, 200

    def get_runtime_summary(self, env: dict[str, str]) -> dict[str, str]:
        from app.config import get_int_setting, get_setting
        from .dwd import resolve_dwd_station_name

        station_id = get_setting("DWD_WEATHER_STATION_ID", "10532").strip() or "10532"
        return {
            "dwd_station": resolve_dwd_station_name(station_id),
            "dwd_cache": f"{get_int_setting('DWD_WEATHER_CACHE_SECONDS', 900, 60, 86400)}s",
            "dwd_hourly_interval": f"{get_int_setting('DWD_HOURLY_INTERVAL_HOURS', 2, 1, 4)}h",
        }

    def get_health_status(self, env: dict[str, str]) -> dict[str, object] | None:
        station_id = env.get("DWD_WEATHER_STATION_ID", "").strip() or "10532"
        return {
            "ok": True,
            "enabled": self.is_enabled(env),
            "station_id": station_id,
            "uv_enabled": bool(env.get("DWD_UV_CITY", "").strip()),
            "pollen_enabled": bool(env.get("DWD_POLLEN_REGION", "").strip()),
        }

    def validate_settings(self, updates: dict[str, str], env: dict[str, str]) -> list[str]:
        errors: list[str] = []
        station_id = env.get("DWD_WEATHER_STATION_ID", "").strip()
        hourly_start = env.get("DWD_HOURLY_START", "day_start").strip()
        if station_id and not station_id.isdigit():
            errors.append("DWD-Station-ID: Bitte nur numerische Stations-IDs verwenden.")
        if hourly_start not in {"day_start", "current_hour"}:
            errors.append("Verlauf-Startpunkt: Ungültige Auswahl.")
        return errors


module = DWDWeatherModule()
