"""
Tagesschau-Nachrichten-Modul für PlexImageE-Ink.

Idle-Modul (MODULE_PRIORITY = 110): wird angezeigt wenn kein Prioritätsmodul
und kein höherpriorisiertes Idle-Modul aktiven Inhalt meldet.

Zeigt aktuelle Nachrichten der Tagesschau mit Thumbnails und Teasertexten.
"""

from __future__ import annotations

from typing import Any

from PIL import Image

from app.module_base import PlexInkModule
from app.module_services import ModuleRenderServices
from app.logger import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Settings-Felder dieses Moduls
# ---------------------------------------------------------------------------

SETTINGS_FIELDS: list[dict] = [
    {
        "name":        "TAGESSCHAU_IDLE_CACHE_SECONDS",
        "label":       "Nachrichten-Refresh (s)",
        "type":        "number",
        "wide":        False,
        "default":     "900",
        "placeholder": "900",
        "min":         60,
        "max":         86400,
        "help":        "Intervall in Sekunden für die Aktualisierung des Tagesschau-Newsfeeds.",
    },
]

SETTINGS_GROUPS: list[dict] = []   # Kein Untergruppen-Bedarf bei einem Feld


# ---------------------------------------------------------------------------
# Modul-Implementierung
# ---------------------------------------------------------------------------

class TagesschauModule(PlexInkModule):
    MODULE_ID          = "tagesschau"
    MODULE_NAME        = "Tagesschau"
    MODULE_DESCRIPTION = (
        "Zeigt aktuelle Nachrichten der Tagesschau mit Bildern und Teasertexten. "
        "Nachrichten werden automatisch im konfigurierten Intervall aktualisiert."
    )
    MODULE_PRIORITY  = 110
    SETTINGS_FIELDS  = SETTINGS_FIELDS
    SETTINGS_GROUPS  = SETTINGS_GROUPS

    def is_enabled(self, env: dict[str, str]) -> bool:
        idle = {x.strip() for x in env.get("IDLE_MODULES", "").split(",") if x.strip()}
        return self.MODULE_ID in idle

    def fetch_content(self, env: dict[str, str]) -> list | None:
        from .data_source import fetch_tagesschau_news
        try:
            news = fetch_tagesschau_news(False)
            return news if news else None
        except Exception as exc:
            log.error(f"TagesschauModule.fetch_content: {exc}", exc_info=True)
            return None

    def render(self, env: dict[str, str], content: Any) -> Image.Image:
        from .renderer import render_tagesschau_module
        return render_tagesschau_module(ModuleRenderServices.from_runtime(), content)

    def should_refresh(self, env: dict[str, str]) -> bool:
        from .data_source import should_refresh_tagesschau_news
        return should_refresh_tagesschau_news()

    def get_state_key(self, content: Any) -> str:
        # Ersten Artikel-Titel als Fingerprint nutzen
        if isinstance(content, list) and content:
            first = content[0]
            return first.get("externalId") or first.get("title", "tagesschau")
        return "tagesschau"

    def get_runtime_summary(self, env: dict[str, str]) -> dict[str, str]:
        from app.config import get_int_setting
        return {
            "Nachrichten-Refresh": f"{get_int_setting('TAGESSCHAU_IDLE_CACHE_SECONDS', 900, 60, 86400)}s",
        }

    def get_health_status(self, env: dict[str, str]) -> dict[str, object] | None:
        return {
            "ok": True,
            "enabled": self.is_enabled(env),
            "refresh_seconds": env.get("TAGESSCHAU_IDLE_CACHE_SECONDS", "900"),
        }

    def validate_settings(self, updates: dict[str, str], env: dict[str, str]) -> list[str]:
        errors: list[str] = []
        raw = env.get("TAGESSCHAU_IDLE_CACHE_SECONDS", "").strip()
        if raw and not raw.isdigit():
            errors.append("Nachrichten-Refresh (s): Muss eine ganze Zahl sein.")
        return errors


module = TagesschauModule()
