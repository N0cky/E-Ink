"""
Plex-Modul für PlexImageE-Ink.

Prioritätsmodul (MODULE_PRIORITY = 0): wird angezeigt sobald eine aktive
Plex-Wiedergabe erkannt wird – überschreibt alle Idle-Module.

Unterstützte Medientypen: Filme, Serien/Episoden, Musik.
Unterstützte Themes: dark (Artwork-Blur-Hintergrund), light (Cover oben, Text unten).
"""

from __future__ import annotations

import time
from typing import Any

from PIL import Image

from app.module_base import PlexInkModule
from app.logger import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Settings-Felder dieses Moduls
# ---------------------------------------------------------------------------

SETTINGS_FIELDS: list[dict] = [
    {
        "name":        "PLEX_BASE_URL",
        "label":       "Plex Base URL",
        "type":        "text",
        "wide":        True,
        "default":     "",
        "placeholder": "http://192.168.178.6:32400",
        "help":        "Adresse deines Plex-Servers (ohne abschließenden Slash).",
    },
    {
        "name":        "PLEX_TOKEN",
        "label":       "Plex Token",
        "type":        "password",
        "wide":        False,
        "default":     "",
        "placeholder": "",
        "help":        "Wird für alle API-Zugriffe auf Plex benötigt.",
    },
    {
        "name":        "ALLOWED_PLEX_USERS",
        "label":       "Erlaubte Plex-User",
        "type":        "text",
        "wide":        True,
        "default":     "",
        "placeholder": "User 1, Gast",
        "help":        "Kommagetrennte Liste erlaubter Benutzernamen. Leer = alle User.",
    },
    {
        "name":    "PLEX_MODULE_ENABLED",
        "label":   "Plex-Modul aktiv",
        "type":    "select",
        "wide":    False,
        "default": "true",
        "options": [
            ("true",  "Aktiv – Plex-Wiedergabe wird angezeigt"),
            ("false", "Deaktiviert – immer Idle-Module"),
        ],
        "help": "Wenn deaktiviert, wird Plex komplett ignoriert und stets ein Idle-Modul angezeigt.",
    },
    {
        "name":    "SESSION_PRIORITY",
        "label":   "Aktive Medientypen & Reihenfolge",
        "type":    "priority_list",
        "wide":    True,
        "default": "movie,episode,track",
        "options": [
            ("movie",   "🎬  Filme"),
            ("episode", "📺  Serien & Episoden"),
            ("track",   "🎵  Musik / Tracks"),
        ],
        "help": (
            "Aktivierte Typen werden angezeigt, deaktivierte ignoriert. "
            "Die Reihenfolge bestimmt die Priorität wenn mehrere Typen gleichzeitig laufen. "
            "Per Drag-and-Drop umsortieren."
        ),
    },
    {
        "name":    "SHOW_UPDATED_TIMESTAMP",
        "label":   "Aktualisierungs-Zeitstempel",
        "type":    "select",
        "wide":    False,
        "default": "true",
        "options": [("true", "Anzeigen"), ("false", "Ausblenden")],
        "help":    "Blendet den Zeitstempel der letzten Aktualisierung im Bild ein.",
    },
    {
        "name":    "SHOW_PROGRESS_BAR",
        "label":   "Fortschrittsbalken",
        "type":    "select",
        "wide":    False,
        "default": "true",
        "options": [("true", "Anzeigen"), ("false", "Ausblenden")],
        "help":    "Zeigt den Wiedergabe-Fortschritt als Balken am unteren Bildrand.",
    },
    {
        "name":    "MOVIE_ARTWORK_SOURCE",
        "label":   "Film-Bildquelle",
        "type":    "select",
        "wide":    False,
        "default": "movie_thumb",
        "options": [
            ("movie_thumb", "Poster"),
            ("movie_art",   "Hintergrundgrafik"),
            ("auto",        "Automatisch"),
        ],
        "help": "Bevorzugte Bildquelle für Filme.",
    },
    {
        "name":    "EPISODE_ARTWORK_SOURCE",
        "label":   "Serien-Bildquelle",
        "type":    "select",
        "wide":    False,
        "default": "series_thumb",
        "options": [
            ("series_thumb",  "Seriencover"),
            ("series_art",    "Seriengrafik"),
            ("season_thumb",  "Staffelcover"),
            ("season_art",    "Staffelgrafik"),
            ("episode_thumb", "Episodenbild"),
            ("episode_art",   "Episode Art"),
            ("auto",          "Automatisch"),
        ],
        "help": "Bevorzugte Bildquelle für Episoden.",
    },
]

SETTINGS_GROUPS: list[dict] = [
    {
        "title":  "Verbindung",
        "desc":   "Serveradresse, Token und Benutzerfilter für den Plex-Zugriff.",
        "fields": ["PLEX_BASE_URL", "PLEX_TOKEN", "ALLOWED_PLEX_USERS"],
    },
    {
        "title":  "Modul & Medientypen",
        "desc":   "Aktivierung des Plex-Moduls und welche Medientypen angezeigt werden.",
        "fields": ["PLEX_MODULE_ENABLED", "SESSION_PRIORITY"],
    },
    {
        "title":  "Wiedergabe-Overlay",
        "desc":   "Zusatzinfos und Bilder die im Plex-Wiedergabebild eingeblendet werden.",
        "fields": [
            "SHOW_UPDATED_TIMESTAMP", "SHOW_PROGRESS_BAR",
            "MOVIE_ARTWORK_SOURCE", "EPISODE_ARTWORK_SOURCE",
        ],
    },
]


# ---------------------------------------------------------------------------
# Modul-Implementierung
# ---------------------------------------------------------------------------

class PlexModule(PlexInkModule):
    MODULE_ID          = "plex"
    MODULE_NAME        = "Plex"
    MODULE_DESCRIPTION = (
        "Zeigt aktuelle Plex-Wiedergabe an – Filme, Serien und Musik mit Cover-Art, "
        "Metadaten und Fortschrittsbalken. Unterstützt Dark- und Light-Theme."
    )
    MODULE_PRIORITY  = 0   # Höchste Priorität – überschreibt alle Idle-Module
    SETTINGS_FIELDS  = SETTINGS_FIELDS
    SETTINGS_GROUPS  = SETTINGS_GROUPS

    # ── Lifecycle ────────────────────────────────────────────────────────────

    @staticmethod
    def is_configured(env: dict[str, str]) -> bool:
        return bool(env.get("PLEX_BASE_URL", "").strip() and env.get("PLEX_TOKEN", "").strip())

    def is_enabled(self, env: dict[str, str]) -> bool:
        # Ohne URL und Token ist das Modul nicht nutzbar – dann gar nicht erst
        # pollen (sonst ein Fehler pro Tick ab Erstinstallation).
        enabled = env.get("PLEX_MODULE_ENABLED", "true").strip().lower() == "true"
        return enabled and self.is_configured(env)

    def fetch_content(self, env: dict[str, str]) -> dict | None:
        """
        Ruft die aktive Plex-Session ab.
        Rückgabe: Session-Dict wenn etwas abgespielt wird, sonst None.
        Kein Artwork-Download – das passiert erst in render().
        """
        from app.plex import get_active_session
        try:
            return get_active_session()
        except Exception as exc:
            log.error(f"PlexModule.fetch_content: {exc}", exc_info=True)
            return None

    def render(self, env: dict[str, str], content: Any) -> Image.Image:
        """
        Lädt Artwork und rendert das Plex-Wiedergabebild.
        Kein Artwork verfügbar → minimales Fallback-Bild mit Metadaten.
        """
        from app.plex import download_session_artwork
        from app.image_rendering import (
            create_centered_cover_canvas,
            create_light_cover_canvas,
            draw_video_overlay,
            draw_video_overlay_light,
            draw_music_overlay,
            draw_music_overlay_light,
        )
        from app.config import get_cfg

        session = content
        cfg     = get_cfg()
        artwork = download_session_artwork(session)
        media_category = session.get("mediaCategory")

        if artwork is None:
            artwork = self._make_fallback_artwork(cfg.render_width, cfg.render_height, cfg.display_theme)

        if cfg.display_theme == "light":
            base, cover_bottom = create_light_cover_canvas(artwork, cfg.render_width, cfg.render_height)
            if media_category == "music":
                return draw_music_overlay_light(base, session, cover_bottom)
            return draw_video_overlay_light(base, session, cover_bottom)
        else:
            base = create_centered_cover_canvas(artwork, cfg.render_width, cfg.render_height)
            if media_category == "music":
                return draw_music_overlay(base, session)
            return draw_video_overlay(base, session)

    def should_refresh(self, env: dict[str, str]) -> bool:
        return False   # Neurender wird über get_state_key gesteuert

    def get_state_key(self, content: Any) -> str:
        """
        State-Key enthält ratingKey + playerState.
        Bei aktiver Wiedergabe wird der Key zeitbasiert quantisiert damit
        das Framework regelmäßig neu rendert (Fortschrittsbalken, Zeitstempel).
        """
        session      = content
        rating_key   = session.get("ratingKey", "")
        player_state = session.get("playerState", "unknown")

        if player_state in ("playing", "buffering"):
            from app.config import get_cfg
            interval = max(get_cfg().refresh_interval, 10)
            slot = int(time.time() // interval)
            return f"{rating_key}:{player_state}:{slot}"

        return f"{rating_key}:{player_state}"

    def get_runtime_summary(self, env: dict[str, str]) -> dict[str, str]:
        from app.config import get_bool_setting, get_setting, parse_session_priority

        session_priority = parse_session_priority(get_setting("SESSION_PRIORITY", "movie,episode,track"))
        return {
            "plex_enabled": "Aktiv" if get_bool_setting("PLEX_MODULE_ENABLED", True) else "Deaktiviert",
            "priority": " > ".join(session_priority) if session_priority else "Keine",
        }

    def get_health_status(self, env: dict[str, str]) -> dict[str, object] | None:
        return {
            "ok": True,
            "enabled": self.is_enabled(env),
            "configured": self.is_configured(env),
        }

    def validate_settings(self, updates: dict[str, str], env: dict[str, str]) -> list[str]:
        errors: list[str] = []
        enabled = env.get("PLEX_MODULE_ENABLED", "true").strip().lower() == "true"
        if not enabled:
            return errors

        base_url = env.get("PLEX_BASE_URL", "").strip()
        token = env.get("PLEX_TOKEN", "").strip()
        session_priority = env.get("SESSION_PRIORITY", "").strip()

        if base_url and not base_url.startswith(("http://", "https://")):
            errors.append("Plex Base URL muss mit http:// oder https:// beginnen.")
        if not session_priority:
            errors.append("Aktive Medientypen & Reihenfolge: Bitte mindestens einen Medientyp aktiv lassen.")
        if (base_url and not token) or (token and not base_url):
            errors.append("Plex-Zugang: Base URL und Token sollten gemeinsam gesetzt sein.")
        return errors

    # ── Hilfsmethoden ────────────────────────────────────────────────────────

    @staticmethod
    def _make_fallback_artwork(w: int, h: int, theme: str) -> Image.Image:
        """Einfacher einfarbiger Hintergrund wenn kein Artwork geladen werden kann."""
        if theme == "light":
            return Image.new("RGB", (w, h), (238, 234, 228))
        return Image.new("RGB", (w, h), (18, 18, 18))


module = PlexModule()
