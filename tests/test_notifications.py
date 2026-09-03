"""
Tests für die reichen Benachrichtigungen: Discord-Embed (mit und ohne Bild),
Slack-Blocks, ntfy-Header mit RFC 2047 und Anhang, sowie die Ereignisse
(Entwarnung, Firmware, Rollback, Fehlerserie, Quelle down/up, Tagesbild,
Wochenbericht) mit ihren Merkern.
"""

from __future__ import annotations

import base64
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import app.device as device
import app.http_client as http_client
import app.notifications as nf

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
BERLIN = ZoneInfo("Europe/Berlin")


def _ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class _Capture:
    def __init__(self, status: int = 200):
        self.calls: list[dict] = []
        self.status = status

    def __call__(self, url, **kw):
        self.calls.append({"url": url, **kw})
        return SimpleNamespace(status_code=self.status, text="")


class DeliveryTest(unittest.TestCase):
    def _note(self, image: bool = False) -> nf.Notification:
        return nf.Notification("offline", "Display ausgefällen", "Seit 45 min nichts gehört.",
                               fields=[("Zuletzt", "12:00"), ("WLAN", "-70 dBm")], image_png=PNG if image else None,
                               link="http://server:8787/geraet", priority="high")

    def test_discord_embed(self) -> None:
        cap = _Capture()
        with patch.object(http_client.HTTP_SESSION, "post", side_effect=cap):
            self.assertTrue(nf.deliver("https://discord.com/api/webhooks/1/abc", self._note()))
        payload = cap.calls[0]["json"]
        self.assertEqual(payload["username"], nf.BOT_NAME)
        self.assertEqual(payload["avatar_url"], nf.DEFAULT_AVATAR_URL)
        embed = payload["embeds"][0]
        self.assertEqual(embed["title"], "Display ausgefällen")
        self.assertEqual(embed["color"], nf.COLORS["offline"])
        self.assertEqual(embed["url"], "http://server:8787/geraet")
        self.assertEqual(embed["fields"][1], {"name": "WLAN", "value": "-70 dBm", "inline": True})
        self.assertNotIn("image", embed)

    def test_discord_with_image_is_multipart(self) -> None:
        cap = _Capture()
        with patch.object(http_client.HTTP_SESSION, "post", side_effect=cap):
            self.assertTrue(nf.deliver("https://discord.com/api/webhooks/1/abc", self._note(image=True), avatar_url="https://x/logo.png"))
        call = cap.calls[0]
        self.assertNotIn("json", call)
        self.assertEqual(call["files"]["files[0]"][0], "display.png")
        self.assertEqual(call["files"]["files[0]"][1], PNG)
        payload = json.loads(call["data"]["payload_json"])
        self.assertEqual(payload["avatar_url"], "https://x/logo.png")
        self.assertEqual(payload["embeds"][0]["image"], {"url": "attachment://display.png"})

    def test_slack_blocks(self) -> None:
        cap = _Capture()
        with patch.object(http_client.HTTP_SESSION, "post", side_effect=cap):
            self.assertTrue(nf.deliver("https://hooks.slack.com/services/x", self._note(image=True), base_url="http://server:8787"))
        payload = cap.calls[0]["json"]
        types = [b["type"] for b in payload["blocks"]]
        self.assertEqual(types, ["header", "section", "section", "image", "context"])
        self.assertEqual(payload["blocks"][3]["image_url"], "http://server:8787/current.png")
        self.assertIn("*Zuletzt*\n12:00", payload["blocks"][2]["fields"][0]["text"])

    def test_ntfy_headers_and_attachment(self) -> None:
        cap = _Capture()
        with patch.object(http_client.HTTP_SESSION, "post", side_effect=cap):
            self.assertTrue(nf.deliver("https://ntfy.sh/topic", self._note()))
            self.assertTrue(nf.deliver("https://ntfy.sh/topic", self._note(image=True)))
        plain, attached = cap.calls
        self.assertEqual(plain["headers"]["Title"], "=?UTF-8?B?" + base64.b64encode("Display ausgefällen".encode()).decode() + "?=")
        self.assertEqual(plain["headers"]["Tags"], "warning")
        self.assertEqual(plain["headers"]["Priority"], "high")
        self.assertEqual(plain["headers"]["Click"], "http://server:8787/geraet")
        self.assertEqual(plain["headers"]["Icon"], nf.DEFAULT_AVATAR_URL)
        self.assertIn(b"WLAN: -70 dBm", plain["data"])
        self.assertEqual(attached["data"], PNG)
        self.assertEqual(attached["headers"]["Filename"], "display.png")
        self.assertTrue(attached["headers"]["Message"].startswith("=?UTF-8?B?"))

    def test_generic_text_and_failures(self) -> None:
        cap = _Capture()
        with patch.object(http_client.HTTP_SESSION, "post", side_effect=cap):
            self.assertTrue(nf.deliver("https://example.test/hook", self._note()))
        self.assertTrue(cap.calls[0]["data"].decode("utf-8").startswith("Display ausgefällen\n"))
        with patch.object(http_client.HTTP_SESSION, "post", side_effect=_Capture(status=403)):
            self.assertFalse(nf.deliver("https://discord.com/api/webhooks/1/abc", self._note()))
        with patch.object(http_client.HTTP_SESSION, "post", side_effect=RuntimeError("offline")):
            self.assertFalse(nf.deliver("https://ntfy.sh/topic", self._note()))
        self.assertFalse(nf.deliver("", self._note()))


class EventsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._state = patch.object(device, "DEVICE_STATE_PATH", Path(self._tmp.name) / "device_state.json")
        self._state.start()
        self.cap = _Capture()
        self._post = patch.object(http_client.HTTP_SESSION, "post", side_effect=self.cap)
        self._post.start()

    def tearDown(self) -> None:
        self._post.stop()
        self._state.stop()
        self._tmp.cleanup()

    def _notifier(self, events=("offline", "firmware", "errors", "sources"), **kw) -> nf.Notifier:
        return nf.Notifier("https://discord.com/api/webhooks/1/abc", events, 30, 7, "http://srv:8787", "", snapshot=lambda: PNG, **kw)

    def _embed(self, index: int) -> dict:
        call = self.cap.calls[index]
        payload = call["json"] if "json" in call else json.loads(call["data"]["payload_json"])
        return payload["embeds"][0]

    def test_offline_then_online_with_image(self) -> None:
        n = self._notifier()
        now = datetime(2026, 9, 3, 12, 0, tzinfo=BERLIN)
        ack = {"ack_at": _ts(now - timedelta(minutes=45)), "device_id": "esp"}
        self.assertEqual(n.on_cycle(ack, now), ["offline"])
        self.assertEqual(n.on_cycle(ack, now + timedelta(minutes=10)), [], "nur einmal")
        later = {"ack_at": _ts(now + timedelta(minutes=20)), "device_id": "esp", "fw_version": "1.2.3", "rssi": -66}
        self.assertEqual(n.on_ack(later, ack, now=now + timedelta(minutes=20)), ["online"])
        self.assertEqual(self._embed(0)["color"], nf.COLORS["offline"])
        self.assertIn("seit 45 min", self._embed(0)["description"])
        online = self._embed(1)
        self.assertEqual(online["title"], "esp ist wieder da")
        self.assertIn("20 min", online["description"])
        self.assertEqual(online["image"], {"url": "attachment://display.png"})
        self.assertIn(("Firmware", "1.2.3"), [(f["name"], f["value"]) for f in online["fields"]])
        self.assertNotIn("offline_at", device.load_device_state().get("notify", {}))

    def test_firmware_update_and_rollback(self) -> None:
        n = self._notifier()
        prev = {"fw_version": "1.2.2", "device_id": "esp"}
        self.assertEqual(n.on_ack({"fw_version": "1.2.3", "device_id": "esp", "result": "updated"}, prev), ["firmware"])
        self.assertEqual(self._embed(0)["title"], "esp läuft jetzt Firmware 1.2.3")
        rollback = {"fw_version": "1.2.2", "device_id": "esp", "result": "error", "error": "Firmware 1.2.3 zurueckgerollt: Start ohne Serverkontakt"}
        self.assertEqual(n.on_ack(rollback, {"fw_version": "1.2.2"}), ["rollback"])
        self.assertEqual(n.on_ack(rollback, {"fw_version": "1.2.2"}), [], "gleicher Rollback nicht doppelt")
        self.assertEqual(self._embed(1)["color"], nf.COLORS["rollback"])
        self.assertEqual(len(self.cap.calls), 2)
        self.assertEqual(self._notifier(events=("offline",)).on_ack({"fw_version": "2.0", "device_id": "esp"}, prev), [], "abgeschaltet")

    def test_error_streak_reported_once(self) -> None:
        n = self._notifier()
        err = {"device_id": "esp", "result": "error", "error": "download timeout"}
        self.assertEqual(n.on_ack(err, {}), [])
        self.assertEqual(n.on_ack(err, {}), [])
        self.assertEqual(n.on_ack(err, {}), ["errors"])
        self.assertEqual(n.on_ack(err, {}), [], "vierter Fehler meldet nicht erneut")
        self.assertEqual(n.on_ack({"device_id": "esp", "result": "updated"}, {}), [])
        self.assertEqual(device.load_device_state()["notify"]["error_streak"], 0)
        self.assertIn("3 Fehler in Folge", self._embed(0)["title"])

    def test_source_down_and_up(self) -> None:
        n = self._notifier()
        now = datetime(2026, 9, 3, 12, 0, tzinfo=BERLIN)
        stale = [("calendar", "Kalender", now - timedelta(hours=7)), ("garbage", "Müllabfuhr", now - timedelta(hours=1))]
        self.assertEqual(n.on_cycle({}, now, stale_sources=stale), ["source_down"], "nur der Kalender ist lang genug alt")
        self.assertEqual(n.on_cycle({}, now + timedelta(minutes=5), stale_sources=stale), [])
        self.assertEqual(n.on_cycle({}, now + timedelta(minutes=10), stale_sources=[stale[1]]), ["source_up"])
        self.assertIn("Kalender", self._embed(0)["title"])
        self.assertEqual(self._embed(1)["color"], nf.COLORS["source_up"])

    def test_daily_and_weekly_once(self) -> None:
        n = self._notifier(events=("daily", "weekly"))
        monday_6 = datetime(2026, 9, 7, 6, 30, tzinfo=BERLIN)
        self.assertEqual(n.on_cycle({}, monday_6, current={"module_name": "Wetter"}), [], "vor 7 Uhr nichts")
        monday_7 = monday_6 + timedelta(hours=1)
        sent = n.on_cycle({"device_id": "esp"}, monday_7, current={"module_name": "Wetter", "rendered_at": _ts(monday_7)},
                          weekly_stats=lambda: {"count": 2000, "longest_gap_s": 900, "gaps_over_threshold": 1, "errors": 0, "avg_cycle_ms": 8100, "rssi_min": -78, "rssi_avg": -66})
        self.assertEqual(sent, ["daily", "weekly"])
        self.assertEqual(n.on_cycle({"device_id": "esp"}, monday_7 + timedelta(hours=2), current={"module_name": "Wetter"}), [], "am selben Tag nicht nochmal")
        tuesday = monday_7 + timedelta(days=1)
        self.assertEqual(n.on_cycle({"device_id": "esp"}, tuesday, current={"module_name": "Wetter"}), ["daily"], "Dienstag nur das Tagesbild")
        daily, weekly = self._embed(0), self._embed(1)
        self.assertIn("Guten Morgen", daily["title"])
        self.assertEqual(daily["image"], {"url": "attachment://display.png"})
        self.assertIn("Wochenbericht KW 37", weekly["title"])
        self.assertIn(("Rückmeldungen", "2000"), [(f["name"], f["value"]) for f in weekly["fields"]])
        self.assertEqual(device.load_device_state()["notify"]["weekly_week"], "2026-W37")

    def test_test_note_has_fields_and_image(self) -> None:
        n = self._notifier(events=("offline",))
        self.assertTrue(n.send_test({"device_id": "esp"}, {"module_name": "Wetter"}))
        embed = self._embed(0)
        self.assertEqual(embed["title"], "Testnachricht")
        self.assertEqual(embed["url"], "http://srv:8787/geraet")
        self.assertIn(("Inhalt", "Wetter"), [(f["name"], f["value"]) for f in embed["fields"]])
        self.assertEqual(embed["image"], {"url": "attachment://display.png"})

    def test_legacy_offline_marker_is_honoured(self) -> None:
        device.save_device_state({"offline_notified_at": _ts(datetime(2026, 9, 3, 10, 0, tzinfo=timezone.utc))})
        n = self._notifier()
        self.assertEqual(n.on_ack({"device_id": "esp"}, {}, now=datetime(2026, 9, 3, 11, 0, tzinfo=timezone.utc)), ["online"])
        state = device.load_device_state()
        self.assertNotIn("offline_notified_at", state)
        self.assertIn("1 h", self._embed(0)["description"])


if __name__ == "__main__":
    unittest.main()
