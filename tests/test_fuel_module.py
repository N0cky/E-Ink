"""
Tests für das Tankpreise-Modul: Parsen der Tankerkönig-Antwort, Einstellungen
(Koordinaten, Kraftstoffe, feste Stationen), Inhalt (Sortierung, Alarm,
Ersparnis), Historie mit Tagesaggregaten und Statistiken, Rendering in allen
Themes samt Kachel, Zusammenfassung, Prüfen und Validierung.
"""

from __future__ import annotations

import json
import math
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import app.config as config
import app.http_client as http_client
from app.module_services import ModuleRenderServices
from modules.fuel_prices import data_source as ds
from modules.fuel_prices import history
from modules.fuel_prices import module as fuel
from modules.fuel_prices.renderer import format_cents, format_price, render_fuel_module, split_price

FIXTURES = Path(__file__).resolve().parent / "fixtures"
LIST = json.loads((FIXTURES / "tankerkoenig_list.json").read_text(encoding="utf-8"))
TZ = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 9, 4, 14, 35, tzinfo=TZ)
API_KEY = "12345678-1234-1234-1234-123456789abc"
JET = "e1a15081-24c2-9107-e040-0b0a3dfe563c"
ARAL = "51d4b660-a095-1aa0-e100-80009459e03a"


def _response(payload, status: int = 200):
    def raise_for_status():
        if status >= 400:
            raise RuntimeError(f"HTTP {status}")
    return SimpleNamespace(status_code=status, json=lambda: payload, text=json.dumps(payload), raise_for_status=raise_for_status)


def _fake_get(url, params=None, **kw):
    params = params or {}
    if params.get("apikey") != API_KEY:
        return _response({"ok": False, "message": "apikey nicht gültig"})
    if "list.php" in url:
        return _response(LIST)
    if "prices.php" in url:
        prices = {}
        for s in LIST["stations"]:
            if s["id"] in params.get("ids", ""):
                prices[s["id"]] = {"status": "open" if s["isOpen"] else "closed", "e5": s["e5"], "e10": s["e10"], "diesel": s["diesel"]}
        return _response({"ok": True, "prices": prices})
    if "detail.php" in url:
        station = next((s for s in LIST["stations"] if s["id"] == params.get("id")), None)
        return _response({"ok": True, "station": station} if station else {"ok": False, "message": "station not found"})
    return _response({}, 404)


class _TempHistory(unittest.TestCase):
    """Historie und Stationsmerker in ein Temp-Verzeichnis umbiegen."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self._patches = [
            patch.object(history, "HISTORY_FILE", root / "fuel_history.json"),
            patch.object(ds, "STATIONS_FILE", root / "fuel_stations.json"),
        ]
        for p in self._patches:
            p.start()
        history.clear()
        ds.clear_cache()

    def tearDown(self) -> None:
        history.clear()
        ds.clear_cache()
        for p in self._patches:
            p.stop()
        self._tmp.cleanup()


def _settings(**extra) -> dict:
    base = {**config.read_env_settings(), "FUEL_API_KEY": API_KEY, "FUEL_LOCATION": "50.5556, 8.5045", "FUEL_RADIUS_KM": "5",
            "FUEL_TYPES": "e5,diesel", "FUEL_PRIMARY": "e5", "IDLE_MODULES": "fuel_prices", "TIMEZONE": "Europe/Berlin"}
    base.update(extra)
    return base


# ---------------------------------------------------------------------------
# Parsen und Einstellungen
# ---------------------------------------------------------------------------

class ParseTest(unittest.TestCase):
    def test_parse_station_normalises_names_and_prices(self) -> None:
        aral = ds.parse_station(LIST["stations"][0])
        self.assertEqual((aral["name"], aral["street"], aral["place"], aral["dist_km"]), ("Aral", "Hermannsteiner Str. 47", "Wetzlar", 1.2))
        self.assertEqual(aral["prices"], {"e5": 1.729, "e10": 1.669, "diesel": 1.659})
        total = ds.parse_station(LIST["stations"][4])
        self.assertIsNone(total["prices"]["diesel"], "false → kein Preis")
        self.assertEqual(total["name"], "TotalEnergies", "gemischte Schreibweise bleibt")
        self.assertFalse(ds.parse_station(LIST["stations"][5])["is_open"])
        self.assertIsNone(ds.parse_station({"name": "ohne id"}))

    def test_parse_location(self) -> None:
        self.assertEqual(ds.parse_location("50.5556, 8.5045"), (50.5556, 8.5045))
        self.assertEqual(ds.parse_location("50.5556 8.5045"), (50.5556, 8.5045))
        self.assertEqual(ds.parse_location("50,5556 8,5045"), (50.5556, 8.5045), "Dezimalkomma mit Leerzeichen")
        self.assertEqual(ds.parse_location("50,5556, 8,5045"), (50.5556, 8.5045), "Dezimalkomma mit Komma-Trenner")
        self.assertEqual(ds.parse_location("50.5556,8.5045"), (50.5556, 8.5045))
        self.assertEqual(ds.parse_location("50,5556,8,5045"), (50.5556, 8.5045))
        self.assertIsNone(ds.parse_location("Wetzlar"))
        self.assertIsNone(ds.parse_location("95, 8"))
        self.assertIsNone(ds.parse_location(""))

    def test_parse_fuels_stations_price_sections(self) -> None:
        self.assertEqual(ds.parse_fuels("diesel,e10,unsinn"), ("diesel", "e10"))
        self.assertEqual(ds.parse_fuels(""), ("e5", "diesel"))
        self.assertEqual(ds.parse_stations(f"Jet|{JET}; {ARAL.upper()}; kaputt|123"), [("Jet", JET), ("", ARAL)])
        self.assertEqual(ds.parse_price("1,65"), 1.65)
        self.assertIsNone(ds.parse_price("abc"))
        self.assertIsNone(ds.parse_price("9"))
        self.assertEqual(ds.parse_sections(""), ds.SECTION_KEYS)
        self.assertEqual(ds.parse_sections("", unset_means_all=False), ())
        self.assertEqual(ds.parse_sections("day,stats,x"), ("day", "stats"))

    def test_price_formatting(self) -> None:
        self.assertEqual(split_price(1.729), ("1,72", "9"))
        self.assertEqual(split_price(1.7), ("1,70", "0"))
        self.assertEqual(split_price(None), ("–", ""))
        self.assertEqual(format_price(1.659), "1,659")
        self.assertEqual(format_cents(3.0), "3")
        self.assertEqual(format_cents(-5.7), "5,7")


# ---------------------------------------------------------------------------
# Inhalt
# ---------------------------------------------------------------------------

class ContentTest(unittest.TestCase):
    def setUp(self) -> None:
        self.stations = [ds.parse_station(s) for s in LIST["stations"]]

    def test_sorted_by_primary_open_first_and_capped(self) -> None:
        content = ds.build_content(self.stations, NOW, ("e5", "diesel"), "e5", 6, None, ds.SECTION_KEYS, radius=5)
        names = [s["name"] for s in content["stations"]]
        self.assertEqual(names, ["JET", "Aral", "Esso", "TotalEnergies", "Shell", "Freie Tankstelle Nauborn"])
        self.assertTrue(content["stations"][0]["is_cheapest"])
        self.assertTrue(content["stations"][4]["is_priciest"], "geschlossene Station ist nie die teuerste")
        self.assertEqual(content["cheapest"]["e5"], {"price": 1.719, "station": "JET"})
        self.assertEqual(content["cheapest"]["diesel"], {"price": 1.649, "station": "JET"})
        self.assertAlmostEqual(content["saving_ct"], 5.0)
        self.assertFalse(content["alert"])
        capped = ds.build_content(self.stations, NOW, ("e5",), "e5", 3, None, (), radius=5)
        self.assertEqual(len(capped["stations"]), 3)
        self.assertEqual(capped["total"], 6)

    def test_primary_diesel_puts_station_without_diesel_last(self) -> None:
        content = ds.build_content(self.stations, NOW, ("diesel",), "diesel", 6, None, (), radius=5)
        self.assertEqual(content["stations"][0]["name"], "JET", "kurze Marken bleiben groß")
        self.assertIn(content["stations"][-1]["name"], ("TotalEnergies", "Freie Tankstelle Nauborn"))

    def test_alert_and_stale(self) -> None:
        content = ds.build_content(self.stations, NOW, ("e5",), "e5", 6, 1.72, (), radius=5)
        self.assertTrue(content["alert"])
        self.assertFalse(ds.build_content(self.stations, NOW, ("e5",), "e5", 6, 1.70, (), radius=5)["alert"])
        stale = ds.build_content(self.stations, NOW, ("e5",), "e5", 6, None, (), fetched_at=NOW.timestamp() - 1800, error="HTTP 503")
        self.assertTrue(stale["stale_since"].startswith("2026-09-04T14:05"))
        self.assertEqual(stale["error"], "", "mit altem Stand keine Fehlermeldung statt Liste")


# ---------------------------------------------------------------------------
# Historie und Statistik
# ---------------------------------------------------------------------------

def _fill_history(days: int = 30, end: datetime = NOW) -> None:
    start = (end - timedelta(days=days - 1)).replace(hour=0, minute=0)
    t = start
    with patch.object(history, "_save"):     # 8.000 Punkte – nicht jeden einzeln auf Platte schreiben
        while t <= end:
            weekday_effect = {0: 0.0, 1: -0.01, 2: -0.008, 3: -0.006, 4: 0.004, 5: 0.006, 6: 0.01}[t.weekday()]
            hour_effect = 0.04 * math.cos((t.hour - 7) / 24 * 2 * math.pi)
            price = round(1.72 + weekday_effect + hour_effect, 3)
            history.record(t, {"e5": (price, "Jet")})
            t += timedelta(minutes=5)


class HistoryTest(_TempHistory):
    def test_record_aggregates_and_gap(self) -> None:
        self.assertTrue(history.record(NOW, {"e5": (1.729, "Jet"), "diesel": (1.649, "Jet")}))
        self.assertFalse(history.record(NOW + timedelta(minutes=2), {"e5": (1.699, "Aral")}), "zu kurz nach dem letzten Punkt")
        self.assertTrue(history.record(NOW + timedelta(minutes=5), {"e5": (1.699, "Aral")}))
        day = history.last_days("e5", NOW.date(), 1)[0]
        self.assertEqual((day["min"], day["max"], day["n"], day["min_at"], day["min_station"]), (1.699, 1.729, 2, "14:40", "Aral"))
        self.assertAlmostEqual(day["avg"], 1.714)
        self.assertEqual(len(history.day_points("e5", NOW.date(), TZ)), 2)
        self.assertEqual(history.days_collected("e5"), 1)
        self.assertFalse(history.stats_ready("e5"))
        self.assertEqual(history.stats_ready_on("e5"), NOW.date() + timedelta(days=14))
        # Datei geschrieben und wieder lesbar
        history.clear()
        self.assertEqual(history.days_collected("diesel"), 1)

    def test_trend_uses_morning_reference(self) -> None:
        for hour, price in ((5, 1.75), (7, 1.76), (10, 1.74), (14, 1.70)):
            history.record(NOW.replace(hour=hour, minute=0), {"e5": (price, "Jet")})
        trend = history.trend("e5", NOW)
        self.assertEqual((trend["now"], trend["reference"], trend["reference_at"]), (1.70, 1.76, "07:00"))
        self.assertAlmostEqual(trend["delta_ct"], -6.0)
        self.assertIsNone(history.trend("diesel", NOW))

    def test_statistics_after_thirty_days(self) -> None:
        _fill_history(30)
        self.assertTrue(history.stats_ready("e5"))
        stats = history.build_stats("e5", NOW)
        self.assertEqual(len(stats["week"]), 7)
        self.assertEqual(len(stats["month"]), 30)
        self.assertTrue(all(d["min"] is not None for d in stats["month"]))
        weekday = stats["weekday_avg"]
        self.assertEqual(weekday.index(min(weekday)), 1, "Dienstag ist im Muster am günstigsten")
        hours = stats["hour_profile"]
        self.assertEqual(hours.index(min(v for v in hours if v is not None)), 19, "19 Uhr ist im Muster am günstigsten")
        best = stats["best_time"]
        self.assertIn(1, best["weekdays"])
        self.assertIn(best["hour_start"], (18, 19))
        self.assertEqual(best["hour_end"], best["hour_start"] + 2)
        lows = stats["lows"]
        self.assertLessEqual(lows["month"]["min"], lows["week"]["min"])
        self.assertEqual(lows["week"]["min_station"], "Jet")

    def test_raw_points_pruned_after_seven_days(self) -> None:
        _fill_history(10)
        state = history._snapshot()
        oldest = min(ts for ts, _ in state["raw"]["e5"])
        self.assertGreaterEqual(oldest, int(NOW.timestamp()) - history.RAW_DAYS * 86400)
        self.assertEqual(history.days_collected("e5"), 10, "Tagesaggregate bleiben")


# ---------------------------------------------------------------------------
# Datenquelle mit Netz-Attrappe
# ---------------------------------------------------------------------------

class FetchTest(_TempHistory):
    def setUp(self) -> None:
        super().setUp()
        self._http = patch.object(http_client.HTTP_SESSION, "get", side_effect=_fake_get)
        self._http.start()
        config.apply_runtime_config(_settings())

    def tearDown(self) -> None:
        self._http.stop()
        config.apply_runtime_config()
        super().tearDown()

    def test_radius_fetch_records_history_and_caches(self) -> None:
        with patch.object(ds, "now_local", return_value=NOW):
            content = ds.fetch_fuel_content()
        self.assertEqual(len(content["stations"]), 6)
        self.assertEqual(content["cheapest"]["e5"]["station"], "JET")
        self.assertEqual(history.days_collected("e5"), 1)
        self.assertEqual(history.days_collected("diesel"), 1)
        self.assertEqual(history.days_collected("e10"), 0, "nur gewählte Kraftstoffe")
        self.assertFalse(ds.should_refresh())
        with patch.object(http_client.HTTP_SESSION, "get", side_effect=AssertionError("kein zweiter Aufruf")):
            ds.fetch_fuel_content()

    def test_fixed_stations_use_prices_and_details(self) -> None:
        config.apply_runtime_config(_settings(FUEL_STATIONS=f"Meine Aral|{ARAL}; {JET}"))
        with patch.object(ds, "now_local", return_value=NOW):
            content = ds.fetch_fuel_content()
        names = [s["name"] for s in content["stations"]]
        self.assertEqual(names, ["JET", "Meine Aral"])
        self.assertEqual(content["stations"][1]["street"], "Hermannsteiner Str. 47")
        self.assertTrue(content["fixed"])
        ds.clear_cache()
        self.assertEqual(ds.station_detail(ARAL)["name"], "Aral", "Details liegen auf Platte")

    def test_error_keeps_last_state(self) -> None:
        with patch.object(ds, "now_local", return_value=NOW):
            ds.fetch_fuel_content()
        ds._CACHE["fetched_at"] -= 1800      # Cache abgelaufen, aber ein alter Stand ist da
        ds._CACHE["last_attempt_at"] = 0.0
        with patch.object(http_client.HTTP_SESSION, "get", side_effect=lambda *a, **k: _response({}, 503)):
            content = ds.fetch_fuel_content()
        self.assertEqual(len(content["stations"]), 6)
        self.assertTrue(content["stale_since"])

    def test_wrong_key_gives_no_content(self) -> None:
        config.apply_runtime_config(_settings(FUEL_API_KEY="falsch"))
        self.assertIsNone(ds.fetch_fuel_content())


# ---------------------------------------------------------------------------
# Modul, Rendering, Oberfläche
# ---------------------------------------------------------------------------

class ModuleTest(_TempHistory):
    def setUp(self) -> None:
        super().setUp()
        self._http = patch.object(http_client.HTTP_SESSION, "get", side_effect=_fake_get)
        self._http.start()
        config.apply_runtime_config(_settings(FUEL_ALERT_PRICE="1,72"))
        self.env = config.get_settings_values()

    def tearDown(self) -> None:
        self._http.stop()
        config.apply_runtime_config()
        super().tearDown()

    def _content(self, fill_days: int = 0, sections=ds.SECTION_KEYS) -> dict:
        if fill_days:
            _fill_history(fill_days)
        stations = [ds.parse_station(s) for s in LIST["stations"]]
        return ds.build_content(stations, NOW, ("e5", "diesel"), "e5", 6, 1.72, sections, radius=5,
                                stats=history.build_stats("e5", NOW))

    def test_render_all_themes_full_and_tile(self) -> None:
        content = self._content(30)
        for theme in ("dark", "light", "eink"):
            services = ModuleRenderServices(render_width=1200, render_height=1600, display_theme=theme, load_font=config.load_font)
            img = render_fuel_module(services, content)
            self.assertEqual((img.size, img.mode), ((1200, 1600), "RGB"))
            tile = ModuleRenderServices(render_width=600, render_height=300, display_theme=theme, load_font=config.load_font)
            self.assertEqual(render_fuel_module(tile, content, compact=True).size, (600, 300))

    def test_render_first_day_and_without_sections(self) -> None:
        history.record(NOW - timedelta(minutes=10), {"e5": (1.729, "Jet")})
        services = ModuleRenderServices(render_width=600, render_height=800, display_theme="dark", load_font=config.load_font)
        self.assertEqual(render_fuel_module(services, self._content()).size, (600, 800))
        self.assertEqual(render_fuel_module(services, self._content(sections=())).size, (600, 800))
        self.assertEqual(render_fuel_module(services, {}).size, (600, 800), "leerer Inhalt rendert einen Hinweis")

    def test_module_hooks(self) -> None:
        self.assertTrue(fuel.is_enabled(self.env))
        self.assertTrue(fuel.supports_tile())
        self.assertEqual(fuel.get_background_poll_seconds(self.env), 300)
        self.assertEqual(fuel.describe_status(self.env), {"state": "ready", "reason": ""})
        self.assertEqual(fuel.describe_status({**self.env, "FUEL_API_KEY": ""})["reason"], "API-Key fehlt")
        self.assertEqual(fuel.describe_status({**self.env, "FUEL_LOCATION": ""})["reason"], "Koordinaten fehlen")
        with patch.object(ds, "now_local", return_value=NOW):
            content = fuel.fetch_content(self.env)
            self.assertTrue(fuel.is_urgent(self.env), "1,719 liegt unter dem Alarm 1,72")
            summary = fuel.summarize(self.env)
        self.assertIn("E5 ab 1,719 (JET)", summary)
        self.assertIn("Preisalarm", summary)
        key = fuel.get_state_key(content)
        self.assertIn("alert", key)
        self.assertIn("2026-09-04T14", key)
        self.assertEqual(fuel.render_tile(self.env, content, 400, 240).size, (400, 240))
        self.assertIn("Umkreis 5 km", fuel.get_runtime_summary(self.env)["Tankpreise"])

    def test_probe_lists_stations_with_ids(self) -> None:
        with patch.object(ds, "now_local", return_value=NOW):
            result = fuel.probe(self.env)
        self.assertTrue(result["ok"])
        self.assertIn("E5 ab 1,719 bei JET", result["message"])
        text = "\n".join(result["details"])
        self.assertIn(f"ID {JET}", text)
        self.assertIn("geschlossen", text)
        self.assertIn("Historie für E5: 1 Tage", text)
        self.assertEqual(fuel.probe({**self.env, "FUEL_API_KEY": ""})["ok"], False)

    def test_validation(self) -> None:
        errors = fuel.validate_settings({}, {**self.env, "FUEL_LOCATION": "Wetzlar"})
        self.assertTrue(any("Koordinaten" in e for e in errors))
        errors = fuel.validate_settings({}, {**self.env, "FUEL_LOCATION": "", "FUEL_STATIONS": ""})
        self.assertTrue(any("Ohne Koordinaten" in e for e in errors))
        errors = fuel.validate_settings({}, {**self.env, "FUEL_STATIONS": "Aral|nicht-die-id"})
        self.assertTrue(any("Tankerkönig-ID" in e for e in errors))
        errors = fuel.validate_settings({}, {**self.env, "FUEL_PRIMARY": "e10"})
        self.assertTrue(any("Hauptkraftstoff" in e for e in errors))
        errors = fuel.validate_settings({"FUEL_TYPES": ""}, {**self.env, "FUEL_TYPES": ""})
        self.assertTrue(any("mindestens einen Kraftstoff" in e for e in errors))
        errors = fuel.validate_settings({}, {**self.env, "FUEL_ALERT_PRICE": "17"})
        self.assertTrue(any("Preisalarm" in e for e in errors))
        errors = fuel.validate_settings({}, {**self.env, "FUEL_CACHE_SECONDS": "60"})
        self.assertTrue(any("300 und 3600" in e for e in errors))
        self.assertEqual(fuel.validate_settings({}, self.env), [])
        self.assertEqual(fuel.validate_settings({}, {**self.env, "IDLE_MODULES": "", "FUEL_API_KEY": "", "FUEL_LOCATION": ""}), [],
                         "inaktiv darf unvollständig sein")


if __name__ == "__main__":
    unittest.main()
