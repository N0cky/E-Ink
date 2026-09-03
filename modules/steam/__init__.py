"""
Steam-Modul für PlexImageE-Ink.

Prioritätsmodul: zeigt das aktuell auf Steam gespielte Spiel an,
wenn das konfigurierte Profil gerade ingame ist.
"""

from __future__ import annotations

import time
from typing import Any

from PIL import Image

from app.config import get_bool_setting, get_cfg, get_setting
from app.http_client import download_image_cached
from app.logger import get_logger
from app.module_base import PlexInkModule

log = get_logger(__name__)


SETTINGS_FIELDS: list[dict] = [
    {
        "name":        "STEAM_PROFILE",
        "label":       "Steam-Profil",
        "type":        "text",
        "wide":        True,
        "default":     "",
        "placeholder": "7656119... oder deinVanityName oder https://steamcommunity.com/id/...",
        "help":        "SteamID64, Vanity-Name oder vollständige Steam-Community-URL des gewünschten Profils.",
    },
    {
        "name":        "STEAM_API_KEY",
        "label":       "Steam Web API Key",
        "type":        "password",
        "wide":        False,
        "default":     "",
        "placeholder": "",
        "help":        "Benötigt für ResolveVanityURL und GetPlayerSummaries.",
        "link_href":   "https://steamcommunity.com/dev/apikey",
        "link_label":  "Steam API-Key verwalten",
    },
    {
        "name":    "STEAM_MODULE_ENABLED",
        "label":   "Steam-Modul aktiv",
        "type":    "select",
        "wide":    False,
        "default": "false",
        "options": [
            ("true", "Aktiv – aktuelles Steam-Spiel anzeigen"),
            ("false", "Deaktiviert – Steam ignorieren"),
        ],
        "help": "Wenn deaktiviert, wird das Modul vollständig übersprungen.",
    },
    {
        "name":    "STEAM_SHOW_UPDATED_TIMESTAMP",
        "label":   "Aktualisierungs-Zeitstempel",
        "type":    "select",
        "wide":    False,
        "default": "true",
        "options": [("true", "Anzeigen"), ("false", "Ausblenden")],
        "help":    "Blendet den Zeitstempel der letzten Bildaktualisierung ein.",
    },
]

SETTINGS_GROUPS: list[dict] = [
    {
        "title":  "Profil & API",
        "desc":   "Welches Steam-Profil geprüft wird und mit welchem API-Key der Abruf erfolgt.",
        "fields": ["STEAM_PROFILE", "STEAM_API_KEY", "STEAM_MODULE_ENABLED"],
    },
    {
        "title":  "Darstellung",
        "desc":   "Optionen für die Anzeige des Steam-Bildes.",
        "fields": ["STEAM_SHOW_UPDATED_TIMESTAMP"],
    },
]


class SteamModule(PlexInkModule):
    MODULE_ID = "steam"
    MODULE_NAME = "Steam"
    MODULE_DESCRIPTION = (
        "Zeigt das aktuell auf Steam gespielte Spiel eines konfigurierten Profils "
        "mit Artwork, Avatar und Status an."
    )
    MODULE_PRIORITY = 1
    SETTINGS_FIELDS = SETTINGS_FIELDS
    SETTINGS_GROUPS = SETTINGS_GROUPS

    ENABLED_KEY = "STEAM_MODULE_ENABLED"

    def is_enabled(self, env: dict[str, str]) -> bool:
        return env.get("STEAM_MODULE_ENABLED", "false").strip().lower() == "true"

    def describe_status(self, env: dict[str, str]) -> dict[str, str]:
        if not env.get("STEAM_PROFILE", "").strip():
            return {"state": "missing", "reason": "Steam-Profil fehlt"}
        if not env.get("STEAM_API_KEY", "").strip():
            return {"state": "missing", "reason": "API-Key fehlt"}
        return {"state": "ready", "reason": ""}

    def summarize(self, env: dict[str, str]) -> str:
        profile = env.get("STEAM_PROFILE", "").strip().rstrip("/")
        return profile.rsplit("/", 1)[-1] if profile else ""

    def probe(self, env: dict[str, str]) -> dict:
        from .steam import get_player_summary
        try:
            summary = get_player_summary()
        except Exception as exc:
            return {"ok": False, "message": f"Steam nicht erreichbar: {exc}"}
        if not summary:
            return {"ok": False, "message": "Profil nicht gefunden oder API-Key ungültig"}
        game = summary.get("gameextrainfo")
        return {"ok": True, "message": f"Verbunden als {summary.get('personaname', '?')}" + (f", spielt {game}" if game else ", spielt gerade nicht")}

    def fetch_content(self, env: dict[str, str]) -> dict | None:
        from .steam import get_active_game

        try:
            return get_active_game()
        except Exception as exc:
            log.error(f"SteamModule.fetch_content: {exc}", exc_info=True)
            return None

    def render(self, env: dict[str, str], content: Any) -> Image.Image:
        from .steam import download_steam_artwork
        from .renderer import render_steam_dark, render_steam_light

        cfg = get_cfg()
        artwork = download_steam_artwork(content.get("gameid", ""), content.get("avatarfull", ""))
        avatar = download_image_cached(content.get("avatarfull", ""), ttl_seconds=6 * 3600)
        if artwork is None and avatar is not None:
            artwork = avatar
        if artwork is None:
            artwork = Image.new("RGB", (cfg.render_width, cfg.render_height), (22, 28, 36))

        show_timestamp = get_bool_setting("STEAM_SHOW_UPDATED_TIMESTAMP", True)
        if cfg.display_theme in ("light", "eink"):
            return render_steam_light(cfg.render_width, cfg.render_height, content, artwork, avatar,
                                      show_timestamp, theme=cfg.display_theme)
        return render_steam_dark(cfg.render_width, cfg.render_height, content, artwork, avatar, show_timestamp)

    def get_state_key(self, content: Any) -> str:
        game_id = str(content.get("gameid", "")).strip()
        persona = str(content.get("personaname", "")).strip()
        interval = max(get_cfg().refresh_interval, 10)
        slot = int(time.time() // interval)
        return f"{game_id}:{persona}:{slot}"

    def get_runtime_summary(self, env: dict[str, str]) -> dict[str, str]:
        profile_value = get_setting("STEAM_PROFILE", "").strip()
        return {
            "Steam-Modul":  "Aktiv" if get_bool_setting("STEAM_MODULE_ENABLED", False) else "Deaktiviert",
            "Steam-Profil": profile_value or "Nicht gesetzt",
        }

    def get_health_status(self, env: dict[str, str]) -> dict[str, object] | None:
        profile_value = env.get("STEAM_PROFILE", "").strip()
        api_key = env.get("STEAM_API_KEY", "").strip()
        return {
            "ok": True,
            "enabled": self.is_enabled(env),
            "configured": bool(profile_value and api_key),
            "profile": profile_value,
        }

    def get_next_wake_info(self, env: dict[str, str], state: str) -> dict[str, object] | None:
        interval = max(get_cfg().refresh_interval, 10)
        return {
            "seconds": interval,
            "reason": "Steam aktiv – Refresh-Intervall",
        }

    def validate_settings(self, updates: dict[str, str], env: dict[str, str]) -> list[str]:
        from .steam import parse_steam_profile_input

        errors: list[str] = []
        enabled = env.get("STEAM_MODULE_ENABLED", "false").strip().lower() == "true"
        if not enabled:
            return errors

        profile_value = env.get("STEAM_PROFILE", "").strip()
        api_key = env.get("STEAM_API_KEY", "").strip()
        if not profile_value:
            errors.append("Steam-Profil: Bitte SteamID64, Vanity-Name oder Profil-URL angeben.")
        elif parse_steam_profile_input(profile_value) is None:
            errors.append("Steam-Profil: Ungültiges Profilformat.")
        if not api_key:
            errors.append("Steam Web API Key: Bitte einen gültigen API-Key hinterlegen.")
        return errors


module = SteamModule()
