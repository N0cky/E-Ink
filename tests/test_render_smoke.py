"""
Render-Smoke-Tests: jedes reale Modul rendert mit aufgezeichneten API-Fixtures
(tests/fixtures/*.json) in beiden Themes ein Bild in der konfigurierten Größe.

Das ist das Sicherheitsnetz für Refactorings an Renderern und Services:
kein Netzwerk, keine echte Config, aber die echten Code-Pfade.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

import app.config as config
import app.http_client as http_client
import app.server as server

FIXTURES = Path(__file__).resolve().parent / "fixtures"
RENDER_W, RENDER_H = 600, 800


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _png_bytes(size=(320, 480), color=(90, 120, 200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def _fake_http_get(url, params=None, timeout=None, **kwargs):
    """Ersetzt HTTP_SESSION.get: routet auf Fixtures, Bild-URLs liefern ein PNG."""
    if "warnwetter.de" in url:
        payload = _load("dwd_station_10532.json")
    elif "tagesschau.de/api2u" in url:
        payload = _load("tagesschau_homepage.json")
    elif "s31fg.json" in url:
        payload = _load("dwd_pollen.json")
    elif "uvi.json" in url:
        payload = _load("dwd_uv.json")
    elif "transport.rest" in url:
        payload = _load("departures_vbb.json" if "/departures" in url else "departures_locations.json")
    else:
        png = _png_bytes()
        return SimpleNamespace(status_code=200, content=png, text="", json=lambda: {}, raise_for_status=lambda: None)
    body = json.dumps(payload).encode("utf-8")
    return SimpleNamespace(status_code=200, content=body, text=body.decode("utf-8"),
                           json=lambda: payload, raise_for_status=lambda: None)


def _pollen_region_key() -> str:
    content = _load("dwd_pollen.json").get("content", [])
    if not content:
        return ""
    first = content[0]
    region_id = first.get("region_id")
    part_id = first.get("partregion_id")
    if part_id is not None:
        return f"{region_id}:{part_id}"
    return str(region_id)


def _uv_city() -> str:
    payload = _load("dwd_uv.json")
    content = payload.get("content", []) if isinstance(payload, dict) else payload
    for entry in content:
        if isinstance(entry, dict) and entry.get("city"):
            return str(entry["city"])
    return ""


def _clear_module_caches() -> None:
    from modules.dwd_weather import dwd, dwd_pollen, dwd_uv
    from modules.tagesschau import data_source as ts
    dwd.DWD_WEATHER_CACHE.update({"fetched_at": 0.0, "last_attempt_at": 0.0, "station_id": "", "timezone": "", "data": None})
    dwd_pollen._POLLEN_CACHE.update({"fetched_at": 0.0, "last_attempt_at": 0.0, "region_key": "", "data": None, "next_refresh_at": 0.0})
    dwd_uv._UV_CACHE.update({"fetched_at": 0.0, "last_attempt_at": 0.0, "city": "", "data": None, "next_refresh_at": 0.0})
    ts.TAGESSCHAU_NEWS_CACHE.update({"fetched_at": 0.0, "last_attempt_at": 0.0, "items": []})
    ts.TAGESSCHAU_IMAGE_CACHE.clear()
    http_client.clear_image_cache()


class _SmokeBase(unittest.TestCase):
    theme = "dark"

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls.gallery_dir = Path(cls._tmpdir.name) / "gallery"
        cls.gallery_dir.mkdir()
        Image.new("RGB", (800, 600), (200, 80, 40)).save(cls.gallery_dir / "a.jpg")
        Image.new("RGB", (400, 900), (40, 160, 90)).save(cls.gallery_dir / "b.png")

        settings = dict(config.read_env_settings())
        settings.update({
            "RENDER_WIDTH": str(RENDER_W),
            "RENDER_HEIGHT": str(RENDER_H),
            "DISPLAY_ROTATION": "0",
            "DISPLAY_THEME": cls.theme,
            "OUTPUT_FORMAT": "png",
            "TIMEZONE": "Europe/Berlin",
            "IDLE_MODULES": "dwd_weather,tagesschau,gallery,departures",
            "DEPARTURES_STOPS": "Alex|900100003",
            "DWD_WEATHER_STATION_ID": "10532",
            "DWD_POLLEN_REGION": _pollen_region_key(),
            "DWD_POLLEN_ALLERGENS": "Graeser,Birke,Beifuss",
            "DWD_UV_CITY": _uv_city(),
            "GALLERY_PATHS": str(cls.gallery_dir),
            "PLEX_BASE_URL": "http://plex.test:32400",
            "PLEX_TOKEN": "testtoken",
            "PLEX_MODULE_ENABLED": "true",
            "STEAM_PROFILE": "https://steamcommunity.com/id/test",
            "STEAM_API_KEY": "k",
            "STEAM_MODULE_ENABLED": "true",
        })
        config.apply_runtime_config(settings)
        cls.env = config.get_settings_values()

        cls._http_patch = patch.object(http_client.HTTP_SESSION, "get", side_effect=_fake_http_get)
        cls._http_patch.start()
        _clear_module_caches()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._http_patch.stop()
        _clear_module_caches()
        config.apply_runtime_config()
        cls._tmpdir.cleanup()

    def _assert_image(self, img) -> None:
        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.size, (RENDER_W, RENDER_H))
        self.assertEqual(img.mode, "RGB")

    # ── Module ────────────────────────────────────────────────────────────────

    def test_dwd_weather(self) -> None:
        from modules.dwd_weather import module
        content = module.fetch_content(self.env)
        self.assertIsNotNone(content, "DWD-Fixture muss Inhalt liefern")
        self.assertTrue(content.get("hourly_forecast"), "Stundenverlauf fehlt")
        self.assertIn("pollen", content, "Pollen-Fixture wurde nicht eingebettet")
        self._assert_image(module.render(self.env, content))
        self.assertTrue(module.get_state_key(content))

    def test_tagesschau(self) -> None:
        from modules.tagesschau import module
        content = module.fetch_content(self.env)
        self.assertIsNotNone(content)
        self.assertGreaterEqual(len(content), 3)
        self._assert_image(module.render(self.env, content))

    def test_departures(self) -> None:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from modules.departures import data_source as ds
        from modules.departures import module
        ds.clear_cache()
        with patch.object(ds, "now_local", return_value=datetime(2026, 9, 3, 23, 10, tzinfo=ZoneInfo("Europe/Berlin"))):
            content = module.fetch_content(self.env)
        self.assertIsNotNone(content, "Abfahrten-Fixture muss Inhalt liefern")
        self.assertTrue(content["sections"][0]["rows"])
        self._assert_image(module.render(self.env, content))
        self.assertEqual(module.render_tile(self.env, content, 600, 300).size, (600, 300))
        ds.clear_cache()

    def test_gallery(self) -> None:
        from modules.gallery import module
        content = module.fetch_content(self.env)
        self.assertIsNotNone(content)
        for fit_mode in ("fit_blur_bg", "cover"):
            env = dict(self.env, GALLERY_FIT_MODE=fit_mode, GALLERY_OVERLAY_MODE="filename_folder")
            self._assert_image(module.render(env, content))

    def test_plex_video_and_music(self) -> None:
        from modules.plex import module
        video = {
            "mediaCategory": "video", "type": "episode", "title": "Pilot",
            "grandparentTitle": "Eine Serie", "parentTitle": "Staffel 1",
            "parentIndex": "1", "index": "1", "year": "2024",
            "thumb": "/library/metadata/1/thumb/1", "art": "/library/metadata/1/art/1",
            "parentThumb": "", "grandparentThumb": "/library/metadata/2/thumb/1",
            "duration": "2700000", "viewOffset": "600000", "playerState": "playing", "user": "tester",
        }
        music = {
            "mediaCategory": "music", "type": "track", "title": "Ein Lied",
            "grandparentTitle": "Eine Band", "parentTitle": "Ein Album",
            "parentIndex": "1", "index": "3", "year": "2020",
            "thumb": "/library/metadata/9/thumb/1", "art": "", "ratingKey": "9",
            "duration": "240000", "viewOffset": "30000", "playerState": "paused", "user": "tester",
        }
        self._assert_image(module.render(self.env, video))
        self._assert_image(module.render(self.env, music))
        self.assertIn("playing", module.get_state_key(video))

    def test_plex_without_artwork_uses_fallback(self) -> None:
        from modules.plex import module
        session = {"mediaCategory": "video", "type": "movie", "title": "Ohne Cover",
                   "duration": "1000", "viewOffset": "0", "playerState": "playing", "user": "t"}
        with patch("modules.plex.plex.download_session_artwork", return_value=None):
            self._assert_image(module.render(self.env, session))

    def test_steam(self) -> None:
        from modules.steam import module
        content = {
            "steamid": "76561198000000000", "profileurl": "https://steamcommunity.com/id/test",
            "personaname": "Tester", "personastate": 1, "personastate_label": "Online",
            "avatar": "https://avatars.test/a.jpg", "avatarmedium": "https://avatars.test/m.jpg",
            "avatarfull": "https://avatars.test/f.jpg",
            "gameid": "620", "gamename": "Portal 2", "lastlogoff": "",
        }
        self._assert_image(module.render(self.env, content))

    # ── Framework ────────────────────────────────────────────────────────────

    def test_placeholder(self) -> None:
        self._assert_image(server.render_no_content_image())

    def test_bmp_output_path_produces_device_and_preview(self) -> None:
        from app.image_rendering import convert_to_spectra6
        img = Image.new("RGB", (RENDER_W, RENDER_H), (120, 60, 200))
        device, preview = convert_to_spectra6(img)
        self.assertEqual(device.size, img.size)
        self.assertEqual(preview.size, img.size)
        # Device-Bild darf nur die 6 Gerätefarben enthalten
        self.assertLessEqual(len(device.getcolors(16) or []), 6)


class DarkThemeSmokeTest(_SmokeBase):
    theme = "dark"


class LightThemeSmokeTest(_SmokeBase):
    theme = "light"


class EinkThemeSmokeTest(_SmokeBase):
    theme = "eink"

    def test_eink_renders_stay_mostly_within_spectra_palette(self) -> None:
        """Flache Flächen müssen exakt auf Spectra-Farben liegen, sonst dithert es.
        Fotos (Gallery/Plex-Cover) sind ausgenommen, DWD und Tagesschau-Chrome nicht."""
        from app.image_rendering import SPECTRA6_COLORS
        from modules.dwd_weather import module as dwd
        content = dwd.fetch_content(self.env)
        img = dwd.render(self.env, content).convert("RGB")
        palette = set(SPECTRA6_COLORS.values())
        total = img.width * img.height
        exact = sum(count for count, color in (img.getcolors(total) or []) if color in palette)
        # Text-Antialiasing und Icons erzeugen Zwischentöne – aber der Großteil
        # des Bildes (Hintergrund, Panels, Flächen) muss exakt auf der Palette liegen.
        self.assertGreater(exact / total, 0.85, f"nur {exact / total:.0%} der Pixel auf Spectra-Farben")


# Basisklasse nicht als eigenständigen Test ausführen
del _SmokeBase


if __name__ == "__main__":
    unittest.main()
