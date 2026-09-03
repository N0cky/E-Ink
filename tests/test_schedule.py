"""
Tests für den Zeitplan (app/schedule.py): Text ↔ Fenster, Wochentage,
Auswertung (über Mitternacht, Wochentag des Beginns, Reihenfolge), Sekunden
bis zur nächsten Änderung, alter Nachtmodus als Fenster, Prüfung.
"""

from __future__ import annotations

import unittest
from datetime import datetime
from types import SimpleNamespace

from app import schedule as s


def _dt(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm)


class ParseTest(unittest.TestCase):
    def test_days(self) -> None:
        self.assertEqual(s.parse_days("*"), s.ALL_DAYS)
        self.assertEqual(sorted(s.parse_days("Mo-Fr")), [0, 1, 2, 3, 4])
        self.assertEqual(sorted(s.parse_days("Sa,So")), [5, 6])
        self.assertEqual(sorted(s.parse_days("Fr-Mo")), [0, 4, 5, 6])
        self.assertEqual(sorted(s.parse_days("mo, mi ,fr")), [0, 2, 4])
        self.assertIsNone(s.parse_days("Mo-Xy"))
        self.assertEqual(s.describe_days([0, 1, 2, 3, 4]), "Mo–Fr")
        self.assertEqual(s.describe_days([5, 6]), "Sa, So")
        self.assertEqual(s.describe_days(range(7)), "täglich")
        self.assertEqual(s.describe_days([0, 1, 2, 4]), "Mo–Mi, Fr")

    def test_round_trip(self) -> None:
        raw = "Morgens|Mo-Fr|06:00-09:00|rotation|120|dwd_weather,garbage; Nachts|*|23:00-07:00||900|; Sonntag|So|10:00-18:00|dashboard||gallery:60,calendar"
        windows = s.parse_windows(raw)
        self.assertEqual([w.name for w in windows], ["Morgens", "Nachts", "Sonntag"])
        self.assertEqual(windows[0].content, (("dwd_weather", 0), ("garbage", 0)))
        self.assertEqual(windows[1].days, s.ALL_DAYS)
        self.assertEqual((windows[1].start, windows[1].end, windows[1].interval_seconds), (23 * 60, 7 * 60, 900))
        self.assertEqual(windows[2].content, (("gallery", 60), ("calendar", 0)))
        self.assertEqual(windows[2].layout, "dashboard")
        self.assertEqual(s.serialize_windows(windows),
                         "Morgens|Mo,Di,Mi,Do,Fr|06:00-09:00|rotation|120|dwd_weather,garbage; "
                         "Nachts|*|23:00-07:00||900|; Sonntag|So|10:00-18:00|dashboard||gallery:60,calendar")
        self.assertEqual(s.parse_windows(s.serialize_windows(windows)), windows)

    def test_broken_entries_are_skipped_and_reported(self) -> None:
        raw = "Gut|*|08:00-10:00|||; Kaputt|Mo-Xy|08:00-10:00|||; NochKaputt|*|8-10|||"
        self.assertEqual([w.name for w in s.parse_windows(raw)], ["Gut"])
        errors = s.validate_raw(raw)
        self.assertEqual(len(errors), 2)
        self.assertTrue(all(e.startswith("Zeitplan:") for e in errors))

    def test_dict_round_trip_and_validation(self) -> None:
        data = {"name": "Abends", "days": [0, 1, 2, 3, 4], "start": "18:00", "end": "22:30", "layout": "dashboard",
                "interval_seconds": 600, "content": [{"id": "calendar", "height": 60}, {"id": "tagesschau", "height": None}]}
        w = s.window_from_dict(data)
        self.assertEqual(w.to_dict()["content"], [{"id": "calendar", "height": 60}, {"id": "tagesschau", "height": None}])
        self.assertEqual(w.to_dict()["days_text"], "Mo–Fr")
        self.assertEqual(s.validate_windows([w], {"calendar", "tagesschau"}), [])
        bad = s.window_from_dict({"name": "x|y", "days": [], "start": "25:00", "end": "07:00", "interval_seconds": "abc",
                                  "content": [{"id": "nope"}]})
        errors = s.validate_windows([bad], {"calendar"})
        self.assertEqual(bad.name, "x y")
        self.assertTrue(any("Wochentag" in e for e in errors))
        self.assertTrue(any("HH:MM" in e for e in errors))
        self.assertTrue(any("Takt" in e for e in errors))
        self.assertTrue(any("nope" in e for e in errors))
        same = s.window_from_dict({"name": "Gleich", "days": [0], "start": "08:00", "end": "08:00"})
        self.assertTrue(any("nicht gleich" in e for e in s.validate_windows([same])))


class EvaluationTest(unittest.TestCase):
    MORNING = s.Window("Morgens", frozenset(range(5)), 6 * 60, 9 * 60, "rotation", 120, (("dwd_weather", 0),))
    NIGHT = s.Window("Nachts", s.ALL_DAYS, 23 * 60, 7 * 60, "", 900, ())
    SUNDAY = s.Window("Sonntag", frozenset({6}), 10 * 60, 18 * 60, "dashboard", 0, (("gallery", 60),))
    WINDOWS = [MORNING, NIGHT, SUNDAY]

    def test_first_matching_window_wins(self) -> None:
        # Donnerstag 06:30: Morgens vor Nachts (Nachts endet erst 07:00)
        active, seconds, upcoming = s.active_window(self.WINDOWS, _dt(2026, 9, 10, 6, 30))
        self.assertEqual(active.name, "Morgens")
        self.assertEqual(seconds, 150 * 60, "Ende von Morgens um 09:00")
        # Samstag 06:30: Morgens gilt nicht (Mo–Fr), Nachts läuft noch (begann Freitag 23:00)
        active, seconds, upcoming = s.active_window(self.WINDOWS, _dt(2026, 9, 12, 6, 30))
        self.assertEqual(active.name, "Nachts")
        self.assertEqual(seconds, 30 * 60)

    def test_wrap_past_midnight_uses_start_day(self) -> None:
        weeknight = s.Window("Werktagsnacht", frozenset(range(5)), 23 * 60, 7 * 60)
        # Samstag 02:00 gehört zur Nacht von Freitag → aktiv
        self.assertIsNotNone(s.active_window([weeknight], _dt(2026, 9, 12, 2, 0))[0])
        # Sonntag 02:00 gehört zur Nacht von Samstag → nicht aktiv
        self.assertIsNone(s.active_window([weeknight], _dt(2026, 9, 13, 2, 0))[0])
        # Sonntag 23:30 → aktiv? Sonntag ist kein Werktag → nein
        self.assertIsNone(s.active_window([weeknight], _dt(2026, 9, 13, 23, 30))[0])
        # Montag 23:30 → aktiv
        self.assertIsNotNone(s.active_window([weeknight], _dt(2026, 9, 14, 23, 30))[0])

    def test_seconds_until_next_start_when_nothing_is_active(self) -> None:
        # Donnerstag 12:00: nächstes Fenster ist Nachts um 23:00
        active, seconds, upcoming = s.active_window(self.WINDOWS, _dt(2026, 9, 10, 12, 0))
        self.assertIsNone(active)
        self.assertEqual(upcoming.name, "Nachts")
        self.assertEqual(seconds, 11 * 3600)
        # Sonntag 09:30: Sonntag-Fenster beginnt 10:00, vor Nachts
        active, seconds, upcoming = s.active_window(self.WINDOWS, _dt(2026, 9, 13, 9, 30))
        self.assertEqual(upcoming.name, "Sonntag")
        self.assertEqual(seconds, 30 * 60)

    def test_active_window_ends_early_when_a_later_start_comes_first(self) -> None:
        # Sonntag 17:00: Sonntag-Fenster aktiv bis 18:00, Nachts beginnt 23:00 → Änderung in 1 h
        active, seconds, _ = s.active_window(self.WINDOWS, _dt(2026, 9, 13, 17, 0))
        self.assertEqual(active.name, "Sonntag")
        self.assertEqual(seconds, 3600)

    def test_no_windows(self) -> None:
        self.assertEqual(s.active_window([], _dt(2026, 9, 10, 12, 0)), (None, 0, None))

    def test_legacy_night_mode_becomes_a_window(self) -> None:
        cfg = SimpleNamespace(schedule_windows=(), night_mode_enabled=True, night_mode_start_minutes=23 * 60,
                              night_mode_end_minutes=7 * 60, night_mode_interval_seconds=900,
                              night_mode_idle_behavior="fixed", night_mode_fixed_module_id="tagesschau")
        (w,) = s.effective_windows(cfg)
        self.assertEqual((w.name, w.start, w.end, w.interval_seconds, w.content), ("Nachts", 1380, 420, 900, (("tagesschau", 0),)))
        cfg.night_mode_idle_behavior = "rotate"
        self.assertEqual(s.effective_windows(cfg)[0].content, ())
        cfg.night_mode_enabled = False
        self.assertEqual(s.effective_windows(cfg), [])
        cfg.schedule_windows = (self.MORNING,)
        cfg.night_mode_enabled = True
        self.assertEqual(s.effective_windows(cfg), [self.MORNING], "gespeicherter Zeitplan hat Vorrang")

    def test_describe_window(self) -> None:
        text = s.describe_window(self.SUNDAY, {"gallery": "Gallery"})
        self.assertEqual(text, "So 10:00–18:00 · Dashboard · Gallery 60 %")
        self.assertEqual(s.describe_window(self.NIGHT), "täglich 23:00–07:00 · alle Inhalte des Programms · alle 15 min")


if __name__ == "__main__":
    unittest.main()
