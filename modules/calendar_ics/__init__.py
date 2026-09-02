"""
Kalender-Modul für PlexImageE-Ink.

Idle-Modul (MODULE_PRIORITY = 106). Liest einen oder mehrere ICS-Kalender
(Google, Nextcloud, iCloud, Outlook – der private ICS-Link reicht) und zeigt
die Termine von heute und der nächsten Tage, inklusive Wiederholungen.
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
        "name":        "CALENDAR_ICS_URLS",
        "label":       "ICS-Kalender",
        "type":        "text",
        "wide":        True,
        "placeholder": "Familie|https://calendar.google.com/calendar/ical/…/basic.ics; Arbeit|https://…",
        "help": (
            "Eine oder mehrere ICS-Adressen, getrennt durch Semikolon, optional mit Label 'Label|URL'. "
            "Google: Kalender-Einstellungen → 'Privatadresse im iCal-Format'. Nextcloud: Kalender teilen → Link. "
            "webcal:// wird automatisch zu https://."
        ),
    },
    {
        "name":        "CALENDAR_DAYS_AHEAD",
        "label":       "Zeitraum (Tage)",
        "type":        "number",
        "wide":        False,
        "default":     "7",
        "placeholder": "7",
        "min":         1,
        "max":         60,
        "help":        "Wie viele Tage im Voraus gezeigt werden.",
    },
    {
        "name":        "CALENDAR_MAX_EVENTS",
        "label":       "Max. Termine",
        "type":        "number",
        "wide":        False,
        "default":     "14",
        "placeholder": "14",
        "min":         1,
        "max":         60,
        "help":        "Obergrenze für die Anzahl der gezeigten Termine (heute wird immer gezeigt).",
    },
    {
        "name":        "CALENDAR_CACHE_SECONDS",
        "label":       "Kalender-Refresh (s)",
        "type":        "number",
        "wide":        False,
        "default":     "900",
        "placeholder": "900",
        "min":         60,
        "max":         86400,
        "help":        "Wie oft die ICS-Dateien neu geladen werden.",
    },
    {
        "name":    "CALENDAR_HIDE_PAST_TODAY",
        "label":   "Vergangene Termine von heute",
        "type":    "select",
        "wide":    False,
        "default": "true",
        "options": [("true", "Ausblenden, sobald sie vorbei sind"), ("false", "Den ganzen Tag zeigen")],
        "help":    "Ganztägige Termine bleiben immer sichtbar.",
    },
]

SETTINGS_GROUPS: list[dict] = []


class CalendarModule(PlexInkModule):
    MODULE_ID          = "calendar"
    MODULE_NAME        = "Kalender"
    MODULE_DESCRIPTION = (
        "Termine von heute und den nächsten Tagen aus ICS-Kalendern – "
        "mit Wiederholungen, mehreren Kalendern und Farbe je Quelle."
    )
    MODULE_PRIORITY  = 106
    SETTINGS_FIELDS  = SETTINGS_FIELDS
    SETTINGS_GROUPS  = SETTINGS_GROUPS

    def is_enabled(self, env: dict[str, str]) -> bool:
        from .data_source import parse_sources
        idle = {x.strip() for x in env.get("IDLE_MODULES", "").split(",") if x.strip()}
        return self.MODULE_ID in idle and bool(parse_sources(env.get("CALENDAR_ICS_URLS", "")))

    def fetch_content(self, env: dict[str, str]) -> dict | None:
        from .data_source import fetch_calendar_content
        try:
            return fetch_calendar_content(False)
        except Exception as exc:
            log.error(f"CalendarModule.fetch_content: {exc}", exc_info=True)
            return None

    def render(self, env: dict[str, str], content: Any) -> Image.Image:
        from .renderer import render_calendar_module
        return render_calendar_module(ModuleRenderServices.from_runtime(), content)

    def should_refresh(self, env: dict[str, str]) -> bool:
        from .data_source import should_refresh_calendar
        return should_refresh_calendar()

    def get_state_key(self, content: Any) -> str:
        # Tag + Fingerprint der sichtbaren Termine: neue/vorbei Termine → neues Bild
        if isinstance(content, dict):
            parts = []
            for day in content.get("days", []):
                for ev in day.get("events", []):
                    s = ev.get("start")
                    parts.append(f"{day['date']}|{s.strftime('%H%M') if hasattr(s, 'strftime') and not ev.get('all_day') else 'A'}|{ev.get('summary', '')[:30]}")
            return f"{content.get('today', '')}:" + ";".join(parts)
        return "calendar"

    def get_runtime_summary(self, env: dict[str, str]) -> dict[str, str]:
        from .data_source import parse_sources
        sources = parse_sources(env.get("CALENDAR_ICS_URLS", ""))
        return {
            "Kalender-Quellen": (", ".join(label or f"Kalender {i + 1}" for i, (label, _) in enumerate(sources))
                                 if sources else "Nicht konfiguriert"),
            "Kalender-Zeitraum": f"{env.get('CALENDAR_DAYS_AHEAD', '7')} Tage",
        }

    def get_health_status(self, env: dict[str, str]) -> dict[str, object] | None:
        from .data_source import parse_sources
        return {
            "ok": True,
            "enabled": self.is_enabled(env),
            "sources": len(parse_sources(env.get("CALENDAR_ICS_URLS", ""))),
        }

    def validate_settings(self, updates: dict[str, str], env: dict[str, str]) -> list[str]:
        from .data_source import parse_sources
        errors: list[str] = []
        raw = env.get("CALENDAR_ICS_URLS", "").strip()
        idle = {x.strip() for x in env.get("IDLE_MODULES", "").split(",") if x.strip()}
        if self.MODULE_ID in idle and not raw:
            errors.append("Kalender: Bitte mindestens eine ICS-Adresse angeben, wenn das Modul aktiv ist.")
        if raw and not parse_sources(raw):
            errors.append("Kalender: Keine gültige ICS-Adresse gefunden (http://, https:// oder webcal://).")
        for key, label in (("CALENDAR_DAYS_AHEAD", "Zeitraum (Tage)"), ("CALENDAR_MAX_EVENTS", "Max. Termine")):
            value = env.get(key, "").strip()
            if value and not value.isdigit():
                errors.append(f"{label}: Muss eine ganze Zahl sein.")
        return errors


module = CalendarModule()
