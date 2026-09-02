"""
Müllabfuhr-Modul für PlexImageE-Ink.

Idle-Modul (MODULE_PRIORITY = 105). Liest ICS-Abfuhrkalender (eine oder
mehrere Adressen), zeigt den nächsten Abfuhrtag groß und die Termine der
nächsten Tage als Liste. Tonnenfarben werden aus dem Terminnamen abgeleitet
und lassen sich pro Stichwort überschreiben.
"""

from __future__ import annotations

from typing import Any

from PIL import Image

from app.logger import get_logger
from app.module_base import PlexInkModule
from app.module_services import ModuleRenderServices

log = get_logger(__name__)


SETTINGS_FIELDS: list[dict] = [
    {
        "name":        "GARBAGE_ICS_URLS",
        "label":       "ICS-Kalender",
        "type":        "text",
        "wide":        True,
        "placeholder": "Zuhause|https://…/abfuhrtermine-{year}.php?…&icalDownload=true",
        "help": (
            "Eine oder mehrere ICS-Adressen, getrennt durch Semikolon. Optional mit Label: "
            "'Label|URL'. Steht das Jahr in der URL, ersetze es durch {year} – dann lädt das "
            "Modul jedes Jahr automatisch den passenden Kalender und ab Ende November zusätzlich das Folgejahr."
        ),
    },
    {
        "name":        "GARBAGE_DAYS_AHEAD",
        "label":       "Zeitraum (Tage)",
        "type":        "number",
        "wide":        False,
        "default":     "14",
        "placeholder": "14",
        "min":         1,
        "max":         90,
        "help":        "Wie viele Tage im Voraus die Terminliste zeigt.",
    },
    {
        "name":        "GARBAGE_CACHE_SECONDS",
        "label":       "Kalender-Refresh (s)",
        "type":        "number",
        "wide":        False,
        "default":     "21600",
        "placeholder": "21600",
        "min":         300,
        "max":         604800,
        "help":        "Wie oft die ICS-Dateien neu geladen werden. Abfuhrkalender ändern sich selten.",
    },
    {
        "name":        "GARBAGE_TYPE_COLORS",
        "label":       "Tonnenfarben",
        "type":        "text",
        "wide":        True,
        "placeholder": "restmüll=black, bio=green, gelb=yellow, papier=blue, sperr=red",
        "help": (
            "Optional: Stichwort=Farbe, kommagetrennt. Farben: black, green, yellow, blue, red. "
            "Ohne Angabe gilt die eingebaute Zuordnung (Restmüll schwarz, Bio grün, Gelbe Tonne gelb, Papier blau)."
        ),
    },
]

SETTINGS_GROUPS: list[dict] = []


class GarbageModule(PlexInkModule):
    MODULE_ID          = "garbage"
    MODULE_NAME        = "Müllabfuhr"
    MODULE_DESCRIPTION = (
        "Zeigt die nächsten Abfuhrtermine aus ICS-Kalendern der Kommune – "
        "nächster Termin groß mit Tonne, dann die Liste der kommenden Tage."
    )
    MODULE_PRIORITY  = 105
    SETTINGS_FIELDS  = SETTINGS_FIELDS
    SETTINGS_GROUPS  = SETTINGS_GROUPS

    def is_enabled(self, env: dict[str, str]) -> bool:
        from .data_source import parse_sources
        idle = {x.strip() for x in env.get("IDLE_MODULES", "").split(",") if x.strip()}
        return self.MODULE_ID in idle and bool(parse_sources(env.get("GARBAGE_ICS_URLS", "")))

    def fetch_content(self, env: dict[str, str]) -> dict | None:
        from .data_source import fetch_garbage_content
        try:
            return fetch_garbage_content(False)
        except Exception as exc:
            log.error(f"GarbageModule.fetch_content: {exc}", exc_info=True)
            return None

    def render(self, env: dict[str, str], content: Any) -> Image.Image:
        from .renderer import render_garbage_module
        return render_garbage_module(ModuleRenderServices.from_runtime(), content)

    def render_tile(self, env: dict[str, str], content: Any, width: int, height: int) -> Image.Image | None:
        from .renderer import render_garbage_module
        base = ModuleRenderServices.from_runtime()
        services = ModuleRenderServices(render_width=width, render_height=height,
                                        display_theme=base.display_theme, load_font=base.load_font)
        return render_garbage_module(services, content, compact=True)

    def should_refresh(self, env: dict[str, str]) -> bool:
        from .data_source import should_refresh_garbage
        return should_refresh_garbage()

    def get_state_key(self, content: Any) -> str:
        # Tag + nächster Termin: neuer Tag → neues Bild ("Morgen" wird "Heute")
        if isinstance(content, dict):
            nxt = content.get("next") or {}
            names = ",".join(ev.get("summary", "") for ev in nxt.get("events", []))
            return f"{content.get('today', '')}:{nxt.get('date', '')}:{names}"
        return "garbage"

    def get_runtime_summary(self, env: dict[str, str]) -> dict[str, str]:
        from .data_source import parse_sources
        sources = parse_sources(env.get("GARBAGE_ICS_URLS", ""))
        return {
            "Müll-Kalender": f"{len(sources)} Quelle{'n' if len(sources) != 1 else ''}" if sources else "Nicht konfiguriert",
            "Müll-Zeitraum": f"{env.get('GARBAGE_DAYS_AHEAD', '14')} Tage",
        }

    def get_health_status(self, env: dict[str, str]) -> dict[str, object] | None:
        from .data_source import parse_sources
        sources = parse_sources(env.get("GARBAGE_ICS_URLS", ""))
        return {
            "ok": True,
            "enabled": self.is_enabled(env),
            "sources": len(sources),
        }

    def validate_settings(self, updates: dict[str, str], env: dict[str, str]) -> list[str]:
        from .data_source import parse_sources, parse_type_overrides, VALID_COLORS
        errors: list[str] = []
        raw = env.get("GARBAGE_ICS_URLS", "").strip()
        idle = {x.strip() for x in env.get("IDLE_MODULES", "").split(",") if x.strip()}
        if self.MODULE_ID in idle and not raw:
            errors.append("Müllabfuhr: Bitte mindestens eine ICS-Adresse angeben, wenn das Modul aktiv ist.")
        if raw and not parse_sources(raw):
            errors.append("Müllabfuhr: Keine gültige ICS-Adresse gefunden (muss mit http:// oder https:// beginnen).")
        colors_raw = env.get("GARBAGE_TYPE_COLORS", "").strip()
        if colors_raw:
            chunks = [c for c in colors_raw.split(",") if c.strip()]
            if len(parse_type_overrides(colors_raw)) != len(chunks):
                errors.append(f"Tonnenfarben: Format 'stichwort=farbe', Farben: {', '.join(VALID_COLORS)}.")
        days = env.get("GARBAGE_DAYS_AHEAD", "").strip()
        if days and not days.isdigit():
            errors.append("Zeitraum (Tage): Muss eine ganze Zahl sein.")
        return errors


module = GarbageModule()
