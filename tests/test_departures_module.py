"""
Tests für das Abfahrten-Modul: Parsen der transport.rest-Antwort, Filter
(Verkehrsmittel, Fußweg), Haltestellen-Auflösung mit Merker, Cache und alter
Stand bei Ausfall, Rendering in allen Themes, Zusammenfassung und Prüfen.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from PIL import Image

import app.config as config
import app.http_client as http_client
from app.module_services import ModuleRenderServices
from modules.departures import data_source as ds
from modules.departures import module as departures
from modules.departures.renderer import render_departures_module

FIXTURES = Path(__file__).resolve().parent / "fixtures"
DEPARTURES = json.loads((FIXTURES / "departures_vbb.json").read_text(encoding="utf-8"))
LOCATIONS = json.loads((FIXTURES / "departures_locations.json").read_text(encoding="utf-8"))
NOW = datetime(2026, 9, 3, 23, 10, tzinfo=ZoneInfo("Europe/Berlin"))      # Fixture: Abfahrten 23:13 bis 23:19


def _response(payload, status: int = 200):
    def raise_for_status():
        if status >= 400:
            raise RuntimeError(f"HTTP {status}")
    return SimpleNamespace(status_code=status, json=lambda: payload, text=json.dumps(payload), raise_for_status=raise_for_status)


def _fake_get(url, params=None, **kw):
    if "/locations" in url:
        return _response(LOCATIONS if "Alexanderplatz" in (params or {}).get("query", "") else [])
    if "/departures" in url:
        return _response(DEPARTURES)
    return _response({}, 404)


class ParseTest(unittest.TestCase):
    def test_parse_departures(self) -> None:
        rows = ds.parse_departures(DEPARTURES)
        self.assertEqual(len(rows), 8)
        first = rows[0]
        self.assertEqual((first["line"], first["product"], first["delay_min"], first["platform"]), ("S3", "suburban", 4, "4"))
        self.assertEqual(first["when"].strftime("%H:%M"), "23:17")
        self.assertEqual(first["planned"].strftime("%H:%M"), "23:13")
        self.assertTrue(first["direction"].startswith("S Spandau"))
        self.assertEqual([r["when"].strftime("%H:%M") for r in rows], sorted(r["when"].strftime("%H:%M") for r in rows), "nach Zeit sortiert")
        self.assertIsNone(next(r for r in rows if r["line"] == "248")["delay_min"], "ohne Echtzeit keine Verspätung")

    def test_parse_stops_and_products(self) -> None:
        self.assertEqual(ds.parse_stops("Bahnhof|Wetzlar; 8006429; Bus|Zwirleinstr.; vier|x"), [("Bahnhof", "Wetzlar"), ("", "8006429"), ("Bus", "Zwirleinstr.")])
        self.assertEqual(ds.parse_stops(""), [])


class ContentTest(unittest.TestCase):
    def _stops(self, error: str = "", fetched_at: float = 0.0):
        return [{"label": "Alex", "id": "900100003", "name": "S+U Alexanderplatz Bhf (Berlin)",
                 "departures": ds.parse_departures(DEPARTURES), "error": error, "fetched_at": fetched_at}]

    def test_filters_and_minutes(self) -> None:
        content = ds.build_departures_content(self._stops(), NOW, ds.ALL_PRODUCT_KEYS, walk_minutes=0, max_per_stop=20)
        rows = content["sections"][0]["rows"]
        self.assertEqual(len(rows), 8)
        self.assertEqual(rows[0]["in_minutes"], 7)
        only_rail = ds.build_departures_content(self._stops(), NOW, ("suburban", "subway"), 0, 20)["sections"][0]["rows"]
        self.assertEqual({r["product"] for r in only_rail}, {"suburban", "subway"})
        walk = ds.build_departures_content(self._stops(), NOW, ds.ALL_PRODUCT_KEYS, walk_minutes=8, max_per_stop=20)["sections"][0]["rows"]
        self.assertTrue(all(r["in_minutes"] >= 8 for r in walk), "Abfahrten unter dem Fußweg fallen weg")
        capped = ds.build_departures_content(self._stops(), NOW, ds.ALL_PRODUCT_KEYS, 0, 3)["sections"][0]["rows"]
        self.assertEqual(len(capped), 3)
        self.assertEqual(content["stale_since"], "")

    def test_stale_and_error_sections(self) -> None:
        content = ds.build_departures_content(self._stops(error="HTTP 503", fetched_at=NOW.timestamp() - 600), NOW, ds.ALL_PRODUCT_KEYS, 0, 8)
        self.assertTrue(content["stale_since"])
        self.assertTrue(content["sections"][0]["rows"])
        dead = ds.build_departures_content([{"label": "Weg", "id": "", "name": "", "departures": None, "error": "Haltestelle nicht gefunden", "fetched_at": 0.0}],
                                           NOW, ds.ALL_PRODUCT_KEYS, 0, 8)
        self.assertEqual(dead["sections"][0]["error"], "Haltestelle nicht gefunden")


class LifecycleTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._stops_patch = patch.object(ds, "STOPS_FILE", Path(self._tmp.name) / "stops.json")
        self._stops_patch.start()
        ds.clear_cache()
        settings = dict(config.read_env_settings())
        settings.update({"IDLE_MODULES": "departures", "DEPARTURES_STOPS": "Alex|Alexanderplatz", "DEPARTURES_API_URL": "https://v6.vbb.transport.rest"})
        config.apply_runtime_config(settings)
        self.env = config.get_settings_values()

    def tearDown(self) -> None:
        ds.clear_cache()
        self._stops_patch.stop()
        self._tmp.cleanup()
        config.apply_runtime_config()

    def test_resolve_by_name_is_remembered_and_departures_cached(self) -> None:
        calls: list[str] = []

        def counting_get(url, params=None, **kw):
            calls.append(url)
            return _fake_get(url, params=params, **kw)

        with patch.object(http_client.HTTP_SESSION, "get", side_effect=counting_get), patch.object(ds, "now_local", return_value=NOW):
            content = departures.fetch_content(self.env)
            departures.fetch_content(self.env)
        self.assertIsNotNone(content)
        self.assertEqual(sum("/locations" in u for u in calls), 1, "Name wird einmal aufgelöst")
        self.assertEqual(sum("/departures" in u for u in calls), 1, "Abfahrten kommen aus dem Cache")
        self.assertTrue(calls[0].startswith("https://v6.vbb.transport.rest/"))
        section = content["sections"][0]
        self.assertEqual(section["label"], "Alex")
        self.assertEqual(section["id"], "900100003")
        self.assertEqual(section["name"], "S+U Alexanderplatz Bhf (Berlin)")
        self.assertEqual(len(section["rows"]), 8)
        self.assertTrue(ds.STOPS_FILE.exists(), "Auflösung wird gemerkt")
        key = departures.get_state_key(content)
        self.assertIn("S3|2317|4", key)

    def test_source_down_keeps_last_state(self) -> None:
        with patch.object(http_client.HTTP_SESSION, "get", side_effect=_fake_get), patch.object(ds, "now_local", return_value=NOW):
            self.assertIsNotNone(departures.fetch_content(self.env))
        with ds._LOCK:
            for entry in ds._CACHE.values():
                entry["fetched_at"] -= 3600
                entry["last_attempt_at"] -= 3600

        def failing(url, params=None, **kw):
            if "/departures" in url:
                return _response({"message": "down"}, 503)
            return _fake_get(url, params=params, **kw)

        with patch.object(http_client.HTTP_SESSION, "get", side_effect=failing), patch.object(ds, "now_local", return_value=NOW):
            content = departures.fetch_content(self.env)
        self.assertIsNotNone(content, "alter Stand statt leerer Seite")
        self.assertTrue(content["stale_since"])
        self.assertEqual(len(content["sections"][0]["rows"]), 8)

    def test_unknown_stop_yields_none_and_status(self) -> None:
        config.apply_runtime_config({**self.env, "DEPARTURES_STOPS": "Nirgendwo"})
        with patch.object(http_client.HTTP_SESSION, "get", side_effect=_fake_get), patch.object(ds, "now_local", return_value=NOW):
            self.assertIsNone(departures.fetch_content(config.get_settings_values()))
            probe = departures.probe(config.get_settings_values())
        self.assertFalse(probe["ok"])
        self.assertTrue(any("nichts gefunden" in d for d in probe["details"]))

    def test_probe_and_summary(self) -> None:
        with patch.object(http_client.HTTP_SESSION, "get", side_effect=_fake_get), patch.object(ds, "now_local", return_value=NOW):
            probe = departures.probe(self.env)
            summary = departures.summarize(self.env)
        self.assertTrue(probe["ok"], probe)
        self.assertIn("8 Abfahrten an 1 Haltestelle", probe["message"])
        self.assertTrue(any("Alex: S+U Alexanderplatz Bhf (Berlin) (900100003)" in d for d in probe["details"]), probe["details"])
        self.assertTrue(any(d.startswith("23:17 (+4) S3") for d in probe["details"]), probe["details"])
        self.assertIn("nächste S3 nach S Spandau", summary)
        self.assertIn("in 7 min", summary)

    def test_validation_and_status(self) -> None:
        self.assertEqual(departures.describe_status(self.env)["state"], "ready")
        self.assertEqual(departures.describe_status({**self.env, "DEPARTURES_STOPS": ""})["state"], "missing")
        errors = departures.validate_settings({}, {**self.env, "DEPARTURES_STOPS": "", "DEPARTURES_API_URL": "ftp://x"})
        self.assertEqual(len(errors), 2)
        self.assertEqual(departures.validate_settings({}, self.env), [])
        self.assertEqual(departures.get_next_wake_info(self.env, "x")["seconds"], 60)


class RenderTest(unittest.TestCase):
    def _content(self, stops: int = 1) -> dict:
        rows = ds.parse_departures(DEPARTURES)
        rows[2]["cancelled"] = True
        rows[3]["platform"] = "12"
        rows[3]["planned_platform"] = "3"
        stops_data = [{"label": f"Halt {i + 1}", "id": str(i), "name": "S+U Alexanderplatz Bhf (Berlin)",
                       "departures": rows, "error": "", "fetched_at": NOW.timestamp()} for i in range(stops)]
        content = ds.build_departures_content(stops_data, NOW, ds.ALL_PRODUCT_KEYS, 0, 8)
        content["stale_since"] = "2026-09-03T22:40:00+02:00"
        return content

    def test_renders_in_all_themes_and_sizes(self) -> None:
        for theme in config.AVAILABLE_THEMES:
            for (w, h) in ((1200, 1600), (1600, 1200), (600, 800)):
                services = ModuleRenderServices(render_width=w, render_height=h, display_theme=theme, load_font=config.load_font)
                img = render_departures_module(services, self._content(stops=2))
                self.assertIsInstance(img, Image.Image)
                self.assertEqual(img.size, (w, h))
            tile = ModuleRenderServices(render_width=1200, render_height=520, display_theme=theme, load_font=config.load_font)
            self.assertEqual(render_departures_module(tile, self._content(), compact=True).size, (1200, 520))

    def test_renders_empty_and_error(self) -> None:
        services = ModuleRenderServices(render_width=800, render_height=600, display_theme="eink", load_font=config.load_font)
        self.assertEqual(render_departures_module(services, {"sections": []}).size, (800, 600))
        content = ds.build_departures_content([{"label": "Weg", "id": "", "name": "", "departures": None, "error": "Haltestelle nicht gefunden", "fetched_at": 0.0}],
                                              NOW, ds.ALL_PRODUCT_KEYS, 0, 8)
        self.assertEqual(render_departures_module(services, content).size, (800, 600))


if __name__ == "__main__":
    unittest.main()
