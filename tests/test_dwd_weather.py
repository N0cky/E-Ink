from __future__ import annotations

import unittest

from modules.dwd_weather.dwd import build_dwd_weather_summary


class DwdWeatherSummaryTest(unittest.TestCase):
    def test_build_summary_includes_sorted_warnings(self) -> None:
        payload = {
            "10532": {
                "forecast1": {
                    "start": 1_780_000_000_000,
                    "timeStep": 3_600_000,
                    "temperature": [129, 126],
                    "icon": [4, 7],
                    "precipitationTotal": [0, 12],
                    "humidity": [686, 729],
                    "surfacePressure": [10223, 10225],
                },
                "days": [
                    {
                        "dayDate": "2026-05-29",
                        "temperatureMin": 78,
                        "temperatureMax": 291,
                        "sunrise": 1_780_024_873_000,
                        "sunset": 1_780_082_739_000,
                        "moonrise": 1_780_077_977_000,
                        "moonset": 1_780_019_254_000,
                        "moonPhase": 3,
                    }
                ],
                "warnings": [
                    {
                        "warnId": "later",
                        "type": 1,
                        "level": 2,
                        "start": 1_780_081_000_000,
                        "end": 1_780_090_000_000,
                        "event": "WINDBÖEN",
                        "headline": "Amtliche WARNUNG vor WINDBÖEN",
                        "descriptionText": "  Erste  Warnung \n mit Zeilenumbruch ",
                        "instruction": " Fenster sichern ",
                    },
                    {
                        "warnId": "earlier",
                        "type": 1,
                        "level": 3,
                        "start": 1_780_080_840_000,
                        "end": 1_780_090_200_000,
                        "event": "STURMBÖEN",
                        "headline": "Amtliche WARNUNG vor STURMBÖEN",
                        "description": " Zweite Warnung ",
                        "instruction": " Draußen auf Äste achten ",
                    },
                ],
            }
        }

        summary = build_dwd_weather_summary(payload, "10532")

        self.assertIsNotNone(summary)
        warnings = summary["warnings"]
        self.assertEqual(len(warnings), 2)
        self.assertEqual(warnings[0]["warn_id"], "earlier")
        self.assertEqual(warnings[0]["level"], 3)
        self.assertEqual(warnings[0]["event"], "STURMBÖEN")
        self.assertEqual(warnings[0]["description"], "Zweite Warnung")
        self.assertEqual(warnings[1]["warn_id"], "later")
        self.assertEqual(warnings[1]["description"], "Erste Warnung mit Zeilenumbruch")
        self.assertEqual(warnings[1]["instruction"], "Fenster sichern")


if __name__ == "__main__":
    unittest.main()
