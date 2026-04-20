"""
Basisklasse für alle PlexImageE-Ink-Anzeigemodule.

Jedes Modul liegt in einem eigenen Unterordner unter modules/ und stellt
eine Datei __init__.py bereit, die ein `module`-Attribut exportiert
(Instanz einer PlexInkModule-Unterklasse).

Prioritäten:
  MODULE_PRIORITY < 10   → Prioritätsmodul  (z. B. Plex: wird angezeigt
                           sobald es aktiven Inhalt meldet, überschreibt Idle)
  MODULE_PRIORITY >= 10  → Idle-Modul (wird rotiert wenn kein Prioritäts-
                           modul aktiv ist)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from PIL import Image


class PlexInkModule(ABC):
    """Basisklasse für alle Anzeigemodule."""

    # ── Pflichtfelder ─────────────────────────────────────────────────────────
    MODULE_ID: str          = ""
    MODULE_NAME: str        = ""
    MODULE_DESCRIPTION: str = ""
    MODULE_PRIORITY: int    = 100   # kleiner = höhere Priorität

    # ── Settings-Deklaration ─────────────────────────────────────────────────
    # Gleiche Struktur wie SETTINGS_FIELDS in app/config.py.
    # Das Feld 'section' kann weggelassen werden – das Framework setzt es
    # automatisch auf MODULE_ID.
    SETTINGS_FIELDS: list[dict] = []

    # Optionale Untergruppen für die Settings-Seite
    # [{"title": "...", "desc": "...", "fields": ["KEY_A", "KEY_B"]}, ...]
    # Leere Liste → alle Felder werden ohne Untergruppen dargestellt.
    SETTINGS_GROUPS: list[dict] = []

    # ── Lifecycle-Methoden ────────────────────────────────────────────────────

    def is_enabled(self, env: dict[str, str]) -> bool:
        """
        Schnelle Konfigurationsprüfung ohne IO.
        Gibt False zurück → Framework überspringt dieses Modul vollständig.
        Standard: immer aktiv.
        """
        return True

    @abstractmethod
    def fetch_content(self, env: dict[str, str]) -> Any | None:
        """
        Daten abrufen. Darf IO machen (API-Calls, Cache-Zugriff, …).
        Rückgabe None  → Modul hat gerade keinen Inhalt, nächstes wird versucht.
        Rückgabe !None → Inhalt vorhanden; render() wird aufgerufen.
        """

    @abstractmethod
    def render(self, env: dict[str, str], content: Any) -> Image.Image:
        """
        Inhalt als PIL-Bild rendern.
        Wird nur aufgerufen wenn fetch_content() != None zurückgegeben hat.
        """

    def should_refresh(self, env: dict[str, str]) -> bool:
        """
        True  → Framework rendert neu, auch wenn get_state_key() gleich geblieben ist.
                Nützlich z. B. nach Cache-Ablauf bei Wetter-Daten.
        False → Nur neu rendern wenn get_state_key() sich geändert hat (Standard).
        """
        return False

    def get_state_key(self, content: Any) -> str:
        """
        Eindeutiger String für den aktuellen Inhalt.
        Ändert sich der Key zwischen zwei Ticks → Framework rendert neu.
        Standard: MODULE_ID (immer neu rendern wenn Modul wechselt).
        """
        return self.MODULE_ID

    def get_field_options(self, field_name: str, env: dict[str, str]) -> list | None:
        """
        Optionale dynamische Feldwerte für Settings-Formulare.
        Beispiel: Autocomplete- oder Select-Werte aus einer API.
        """
        return None

    def get_runtime_summary(self, env: dict[str, str]) -> dict[str, str]:
        """
        Optionale Laufzeit-Zusammenfassung für Dashboard / Settings.
        Rückgabe wird mit der Framework-Zusammenfassung zusammengeführt.
        """
        return {}

    def validate_settings(self, updates: dict[str, str], env: dict[str, str]) -> list[str]:
        """
        Optionale modul-spezifische Settings-Validierung.
        updates enthält die Formularwerte dieses Requests, env den daraus
        abgeleiteten Gesamtzustand.
        """
        return []

    def handle_api_action(self, action: str, env: dict[str, str]) -> tuple[Any, int] | None:
        """
        Optionale modul-spezifische API-Aktion.
        Rückgabe: (payload, status_code) oder None wenn die Aktion unbekannt ist.
        """
        return None

    def get_health_status(self, env: dict[str, str]) -> dict[str, Any] | None:
        """
        Optionale Health-Informationen des Moduls für Status-/Health-Endpunkte.
        """
        return None

    def get_next_wake_seconds(self, env: dict[str, str], state: str) -> int | None:
        """
        Optionale modul-spezifische Wake-Empfehlung für /meta.json.
        None -> Framework-Standardlogik verwenden.
        """
        return None

    def get_next_wake_info(self, env: dict[str, str], state: str) -> dict[str, Any] | None:
        """
        Optionale modul-spezifische Wake-Metadaten für /meta.json.
        Erwartete Keys:
        - seconds: int
        - reason: str (optional)
        """
        return None

    def get_background_poll_seconds(self, env: dict[str, str]) -> int | None:
        """
        Optionales Poll-Intervall für den Background-Worker.
        None -> Framework-Standardlogik verwenden.
        """
        return None
