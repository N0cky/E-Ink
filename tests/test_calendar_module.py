"""
Tests für das Kalender-Modul: ICS-Parser (Zeitzonen, ganztägig, DURATION),
Wiederholungsregeln (DAILY/WEEKLY/MONTHLY/YEARLY, INTERVAL, COUNT, UNTIL,
BYDAY, EXDATE), Inhaltsaufbau und Rendering.
"""

from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

import app.config as config
import app.http_client as http_client
from app.module_services import ModuleRenderServices
from modules.calendar_ics import data_source as ds
from modules.calendar_ics import module as calendar
from modules.calendar_ics.renderer import render_calendar_module


def _ics(*events: str) -> str:
    body = "".join(f"BEGIN:VEVENT\r\n{e.strip()}\r\nEND:VEVENT\r\n" for e in events)
    return f"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:test\r\n{body}END:VCALENDAR\r\n"


def _local(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=config.local_tz())


NOW = _local(2026, 9, 10, 9, 0)      # Donnerstag


class ParserTest(unittest.TestCase):
    def test_all_day_and_timed_with_tzid_and_utc(self) -> None:
        text = _ics(
            "UID:a\r\nDTSTART;VALUE=DATE:20260912\r\nDTEND;VALUE=DATE:20260913\r\nSUMMARY:Ganztag",
            "UID:b\r\nDTSTART;TZID=Europe/Berlin:20260912T093000\r\nDTEND;TZID=Europe/Berlin:20260912T103000\r\nSUMMARY:Lokal",
            "UID:c\r\nDTSTART:20260912T120000Z\r\nDURATION:PT45M\r\nSUMMARY:UTC mit Dauer\r\nLOCATION:Raum 1\\, Haus 2",
        )
        events = ds.parse_ics_events(text)
        self.assertEqual(len(events), 3)
        a, b, c = events
        self.assertTrue(a["all_day"])
        self.assertEqual(a["start"], date(2026, 9, 12))
        self.assertFalse(b["all_day"])
        self.assertEqual(b["start"].hour, 9)
        self.assertEqual(b["end"] - b["start"], timedelta(hours=1))
        # 12:00 UTC ist im September 14:00 in Berlin
        self.assertEqual((c["start"].hour, c["start"].minute), (14, 0))
        self.assertEqual(c["end"] - c["start"], timedelta(minutes=45))
        self.assertEqual(c["location"], "Raum 1, Haus 2")

    def test_cancelled_and_untitled_events_are_dropped(self) -> None:
        text = _ics(
            "UID:x\r\nDTSTART;VALUE=DATE:20260912\r\nSUMMARY:Abgesagt\r\nSTATUS:CANCELLED",
            "UID:y\r\nDTSTART;VALUE=DATE:20260912",
            "UID:z\r\nDTSTART;VALUE=DATE:20260912\r\nSUMMARY:Bleibt",
        )
        self.assertEqual([e["summary"] for e in ds.parse_ics_events(text)], ["Bleibt"])

    def test_sources_accept_webcal(self) -> None:
        self.assertEqual(ds.parse_sources("Privat|webcal://x.test/a.ics"), [("Privat", "https://x.test/a.ics")])


class RecurrenceTest(unittest.TestCase):
    def _occ(self, event_text: str, window_start=date(2026, 9, 10), window_end=date(2026, 9, 30)) -> list:
        (event,) = ds.parse_ics_events(_ics(event_text))
        return ds.expand_occurrences(event, window_start, window_end)

    def test_daily_with_count(self) -> None:
        occ = self._occ("UID:d\r\nDTSTART;VALUE=DATE:20260909\r\nSUMMARY:Täglich\r\nRRULE:FREQ=DAILY;COUNT=4")
        # 09., 10., 11., 12. – Fenster ab 10. → 3
        self.assertEqual([o["start"] for o in occ], [date(2026, 9, 10), date(2026, 9, 11), date(2026, 9, 12)])

    def test_weekly_byday_with_until_and_exdate(self) -> None:
        occ = self._occ(
            "UID:w\r\nDTSTART;TZID=Europe/Berlin:20260901T180000\r\nDTEND;TZID=Europe/Berlin:20260901T190000\r\n"
            "SUMMARY:Training\r\nRRULE:FREQ=WEEKLY;BYDAY=TU,TH;UNTIL=20260920T000000Z\r\n"
            "EXDATE;TZID=Europe/Berlin:20260915T180000"
        )
        dates = [o["start"].date() for o in occ]
        # Di/Do ab 10.09. bis 20.09.: 10., 15.(EXDATE), 17. → 10., 17.
        self.assertEqual(dates, [date(2026, 9, 10), date(2026, 9, 17)])
        self.assertTrue(all(o["start"].hour == 18 for o in occ))

    def test_weekly_interval_two(self) -> None:
        occ = self._occ("UID:w2\r\nDTSTART;VALUE=DATE:20260903\r\nSUMMARY:Alle 2 Wochen\r\nRRULE:FREQ=WEEKLY;INTERVAL=2")
        self.assertEqual([o["start"] for o in occ], [date(2026, 9, 17)])

    def test_monthly_and_yearly(self) -> None:
        monthly = self._occ("UID:m\r\nDTSTART;VALUE=DATE:20260115\r\nSUMMARY:Miete\r\nRRULE:FREQ=MONTHLY")
        self.assertEqual([o["start"] for o in monthly], [date(2026, 9, 15)])
        yearly = self._occ("UID:y\r\nDTSTART;VALUE=DATE:20200920\r\nSUMMARY:Geburtstag\r\nRRULE:FREQ=YEARLY")
        self.assertEqual([o["start"] for o in yearly], [date(2026, 9, 20)])

    def test_monthly_skips_invalid_days(self) -> None:
        occ = self._occ("UID:m31\r\nDTSTART;VALUE=DATE:20260131\r\nSUMMARY:31.\r\nRRULE:FREQ=MONTHLY",
                        window_start=date(2026, 9, 1), window_end=date(2026, 10, 31))
        self.assertEqual([o["start"] for o in occ], [date(2026, 10, 31)])

    def test_multi_day_all_day_event_touches_window(self) -> None:
        occ = self._occ("UID:u\r\nDTSTART;VALUE=DATE:20260908\r\nDTEND;VALUE=DATE:20260912\r\nSUMMARY:Urlaub")
        self.assertEqual(len(occ), 1)


class ContentBuildTest(unittest.TestCase):
    def _events(self):
        return ds.parse_ics_events(_ics(
            "UID:1\r\nDTSTART;TZID=Europe/Berlin:20260910T080000\r\nDTEND;TZID=Europe/Berlin:20260910T083000\r\nSUMMARY:Vorbei",
            "UID:2\r\nDTSTART;TZID=Europe/Berlin:20260910T140000\r\nDTEND;TZID=Europe/Berlin:20260910T150000\r\nSUMMARY:Heute später",
            "UID:3\r\nDTSTART;VALUE=DATE:20260910\r\nSUMMARY:Ganztag heute",
            "UID:4\r\nDTSTART;VALUE=DATE:20260912\r\nDTEND;VALUE=DATE:20260914\r\nSUMMARY:Wochenende weg",
            "UID:5\r\nDTSTART;TZID=Europe/Berlin:20260925T100000\r\nSUMMARY:Außerhalb",
        ))

    def test_today_always_present_and_past_hidden(self) -> None:
        content = ds.build_calendar_content([("Privat", "blue", self._events())], NOW, 7, 14)
        self.assertEqual(content["today"], "2026-09-10")
        today = content["days"][0]
        self.assertEqual(today["in_days"], 0)
        titles = [e["summary"] for e in today["events"]]
        self.assertNotIn("Vorbei", titles)
        self.assertEqual(titles, ["Ganztag heute", "Heute später"], "ganztägig zuerst, dann nach Uhrzeit")
        weekend_days = [d for d in content["days"] if d["events"] and d["events"][0]["summary"] == "Wochenende weg"]
        self.assertEqual([d["date"] for d in weekend_days], [date(2026, 9, 12), date(2026, 9, 13)])
        self.assertTrue(weekend_days[1]["events"][0]["continues"])
        self.assertNotIn("Außerhalb", [e["summary"] for d in content["days"] for e in d["events"]])

    def test_show_past_today_when_configured(self) -> None:
        content = ds.build_calendar_content([("P", "blue", self._events())], NOW, 7, 14, hide_past_today=False)
        self.assertIn("Vorbei", [e["summary"] for e in content["days"][0]["events"]])

    def test_max_events_caps_and_reports_hidden(self) -> None:
        many = ds.parse_ics_events(_ics(*[
            f"UID:{i}\r\nDTSTART;VALUE=DATE:20260911\r\nSUMMARY:Termin {i}" for i in range(6)
        ]))
        content = ds.build_calendar_content([("P", "blue", many)], NOW, 7, 3)
        day = [d for d in content["days"] if d["in_days"] == 1][0]
        self.assertEqual(len(day["events"]), 3)
        self.assertEqual(day["hidden"], 3)


class LifecycleTest(unittest.TestCase):
    def setUp(self) -> None:
        ds.clear_cache()
        settings = dict(config.read_env_settings())
        settings.update({"IDLE_MODULES": "calendar",
                         "CALENDAR_ICS_URLS": "Familie|https://cal.test/a.ics; Arbeit|https://cal.test/b.ics"})
        config.apply_runtime_config(settings)
        self.env = config.get_settings_values()

    def tearDown(self) -> None:
        ds.clear_cache()
        config.apply_runtime_config()

    def test_fetch_merges_sources_with_colours_and_caches(self) -> None:
        calls: list[str] = []

        def fake_get(url, **kw):
            calls.append(url)
            text = _ics(f"UID:{url}\r\nDTSTART;VALUE=DATE:20260911\r\nSUMMARY:Aus {url[-5:]}")
            return SimpleNamespace(status_code=200, text=text, raise_for_status=lambda: None)

        with patch.object(http_client.HTTP_SESSION, "get", side_effect=fake_get), \
             patch.object(ds, "now_local", return_value=NOW):
            content = calendar.fetch_content(self.env)
            calendar.fetch_content(self.env)
        self.assertEqual(len(calls), 2, "jede Quelle einmal, dann Cache")
        self.assertEqual([s["label"] for s in content["sources"]], ["Familie", "Arbeit"])
        colours = {e["color"] for d in content["days"] for e in d["events"]}
        self.assertEqual(colours, {"blue", "green"})
        self.assertTrue(calendar.get_state_key(content).startswith("2026-09-10:"))

    def test_is_enabled_and_validation(self) -> None:
        self.assertTrue(calendar.is_enabled(self.env))
        self.assertFalse(calendar.is_enabled({**self.env, "CALENDAR_ICS_URLS": ""}))
        errors = calendar.validate_settings({}, {**self.env, "CALENDAR_ICS_URLS": ""})
        self.assertTrue(any("ICS-Adresse" in e for e in errors))
        self.assertEqual(calendar.validate_settings({}, self.env), [])


class RenderTest(unittest.TestCase):
    def _content(self) -> dict:
        events = ds.parse_ics_events(_ics(
            "UID:1\r\nDTSTART;TZID=Europe/Berlin:20260910T140000\r\nDTEND;TZID=Europe/Berlin:20260910T150000\r\nSUMMARY:Zahnarzt\r\nLOCATION:Praxis Dr. Müller",
            "UID:2\r\nDTSTART;VALUE=DATE:20260910\r\nSUMMARY:Geburtstag Oma",
            "UID:3\r\nDTSTART;TZID=Europe/Berlin:20260911T093000\r\nDTEND;TZID=Europe/Berlin:20260911T113000\r\nSUMMARY:Teammeeting mit einem sehr langen Titel der gekürzt werden muss",
            "UID:4\r\nDTSTART;VALUE=DATE:20260912\r\nDTEND;VALUE=DATE:20260914\r\nSUMMARY:Wochenende in Hamburg",
        ))
        content = ds.build_calendar_content([("Familie", "blue", events[:2]), ("Arbeit", "green", events[2:])], NOW, 7, 14)
        content["sources"] = [{"label": "Familie", "color": "blue"}, {"label": "Arbeit", "color": "green"}]
        return content

    def test_renders_in_all_themes_and_sizes(self) -> None:
        content = self._content()
        for theme in config.AVAILABLE_THEMES:
            for (w, h) in ((1200, 1600), (1600, 1200), (600, 800)):
                services = ModuleRenderServices(render_width=w, render_height=h, display_theme=theme, load_font=config.load_font)
                img = render_calendar_module(services, content)
                self.assertIsInstance(img, Image.Image)
                self.assertEqual(img.size, (w, h))

    def test_renders_empty(self) -> None:
        services = ModuleRenderServices(render_width=800, render_height=600, display_theme="eink", load_font=config.load_font)
        self.assertEqual(render_calendar_module(services, {"days": [], "sources": []}).size, (800, 600))


if __name__ == "__main__":
    unittest.main()
