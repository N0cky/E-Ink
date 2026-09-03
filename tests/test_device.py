"""
Gerätedienste: kompaktes 4-bpp-Bildformat, gehostete Firmware (Update über
den Server), erweitertes ACK mit Gesundheitsdaten und Gerätelog.
"""

from __future__ import annotations

import hashlib
import io
import tempfile
from pathlib import Path
from unittest.mock import patch
import unittest

from PIL import Image

from app import device, epd_format, server
from app.image_rendering import quantize_spectra6, SPECTRA6_COLORS


def _fake_firmware(version: str = "1.2.3", chip_id: int = 9, with_marker: bool = True) -> bytes:
    head = bytes([0xE9]) + bytes(11) + chip_id.to_bytes(2, "little") + bytes(2)
    body = b"\x00" * 200
    marker = (b"INKWALL_FW_VERSION=" + version.encode() + b"\0") if with_marker else b""
    return head + body + marker + b"\x00" * 100


class _TmpFirmware(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self._patches = [
            patch.object(device, "FIRMWARE_DIR", root / "fw"),
            patch.object(device, "FIRMWARE_BIN", root / "fw" / "firmware.bin"),
            patch.object(device, "FIRMWARE_META", root / "fw" / "firmware.json"),
            patch.object(device, "DEVICE_LOG_PATH", root / "device.log"),
        ]
        for p in self._patches:
            p.start()
        server._last_ack = {}

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()
        self._tmp.cleanup()
        server._last_ack = {}


class EpdFormatTest(unittest.TestCase):
    def test_roundtrip_and_nibble_order(self) -> None:
        img = Image.new("RGB", (4, 2))
        colors = [SPECTRA6_COLORS[c] for c in ("black", "white", "yellow", "red", "blue", "green", "white", "black")]
        img.putdata(colors)
        data = epd_format.encode_epd4(quantize_spectra6(img))
        self.assertEqual(len(data), epd_format.HEADER_SIZE + 4)
        self.assertEqual(data[:4], b"PLX6")
        width, height, codes = epd_format.decode_epd4(data)
        self.assertEqual((width, height), (4, 2))
        # Codes wie im Display: 0 Schwarz, 1 Weiß, 2 Gelb, 3 Rot, 5 Blau, 6 Grün; linkes Pixel im hohen Nibble
        self.assertEqual(codes, [0x0, 0x1, 0x2, 0x3, 0x5, 0x6, 0x1, 0x0])
        self.assertEqual(data[epd_format.HEADER_SIZE], 0x01, "erstes Byte = Schwarz<<4 | Weiß")

    def test_full_size_is_960k_plus_header(self) -> None:
        img = Image.new("RGB", (1200, 1600), (255, 255, 255))
        data = epd_format.encode_epd4(quantize_spectra6(img))
        self.assertEqual(len(data), epd_format.HEADER_SIZE + 1200 * 1600 // 2)

    def test_odd_width_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            epd_format.encode_epd4(quantize_spectra6(Image.new("RGB", (3, 2))))


class FirmwareInspectTest(unittest.TestCase):
    def test_reads_version_and_checksums(self) -> None:
        data = _fake_firmware("1.4.0")
        info = device.inspect_firmware(data)
        self.assertEqual(info["version"], "1.4.0")
        self.assertEqual(info["size"], len(data))
        self.assertEqual(info["md5"], hashlib.md5(data).hexdigest())

    def test_rejects_non_esp_image_wrong_chip_and_missing_marker(self) -> None:
        with self.assertRaises(ValueError):
            device.inspect_firmware(b"MZ" + bytes(300))
        with self.assertRaises(ValueError):
            device.inspect_firmware(_fake_firmware(chip_id=0))          # ESP32 classic
        with self.assertRaises(ValueError):
            device.inspect_firmware(_fake_firmware(with_marker=False))


class FirmwareHostingTest(_TmpFirmware):
    def test_store_serve_and_delete(self) -> None:
        client = server.app.test_client()
        self.assertEqual(client.get("/firmware.json").status_code, 404)
        self.assertEqual(client.get("/firmware.bin").status_code, 404)

        data = _fake_firmware("1.1.0")
        resp = client.post("/api/device/firmware", data={"file": (io.BytesIO(data), "Inkwall.ino.bin")},
                           content_type="multipart/form-data")
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertEqual(resp.get_json()["firmware"]["version"], "1.1.0")

        meta = client.get("/firmware.json").get_json()
        self.assertEqual(meta["version"], "1.1.0")
        binary = client.get("/firmware.bin")
        self.assertEqual(binary.status_code, 200)
        self.assertEqual(binary.data, data)
        self.assertEqual(binary.headers["x-MD5"], hashlib.md5(data).hexdigest(), "HTTPUpdate prüft diesen Header")
        binary.close()   # Windows: send_file hält die Datei offen, bis die Antwort geschlossen ist

        # meta.json kündigt die Firmware dem Gerät an
        with patch.object(server, "_esp32_state", {"hash": "abc", "format": "bmp", "state": "s", "media_type": "m", "rendered_at": ""}):
            m = client.get("/meta.json").get_json()
        self.assertEqual(m["firmware_version"], "1.1.0")
        self.assertEqual(m["firmware_url"], "/firmware.bin")

        self.assertEqual(client.delete("/api/device/firmware").status_code, 200)
        self.assertEqual(client.get("/firmware.json").status_code, 404)

    def test_upload_rejects_bad_files(self) -> None:
        client = server.app.test_client()
        resp = client.post("/api/device/firmware", data={"file": (io.BytesIO(b"MZ" + bytes(300)), "x.bin")},
                           content_type="multipart/form-data")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("ESP32", resp.get_json()["error"])
        tiny = client.post("/api/device/firmware", data={"file": (io.BytesIO(b"kurz"), "x.bin")},
                           content_type="multipart/form-data")
        self.assertEqual(tiny.status_code, 400)
        self.assertEqual(client.post("/api/device/firmware", data={}, content_type="multipart/form-data").status_code, 400)


class AckAndDeviceLogTest(_TmpFirmware):
    def test_ack_stores_health_and_log(self) -> None:
        client = server.app.test_client()
        with patch.object(server, "_esp32_state", {"hash": "abc", "format": "bmp", "state": "s", "media_type": "m", "rendered_at": ""}):
            resp = client.post("/ack", json={
                "device_id": "esp32-eink-01", "hash": "abc", "result": "updated", "fw_version": "1.1.0",
                "rssi": -71, "boot_count": 42, "free_psram_kb": 7900, "cycle_ms": 6100, "download_ms": 900,
                "refresh_ms": 4200, "image_format": "epd4", "wake_reason": "timer", "ip": "192.168.178.50",
                "log": ["== Inkwall 1.1.0 Boot #42 ==", "[WiFi] OK", "", "[EPD] Fertig!"],
            })
            self.assertEqual(resp.status_code, 200)
            self.assertIsNone(resp.get_json()["firmware"], "keine Firmware bereitgestellt")
            state = client.get("/api/display").get_json()
        dev = state["device"]
        self.assertEqual(dev["fw_version"], "1.1.0")
        self.assertEqual(dev["rssi"], -71)
        self.assertEqual(dev["rssi_label"], "brauchbar")
        self.assertEqual(dev["download_ms"], 900)
        self.assertEqual(dev["image_format"], "epd4")
        self.assertTrue(dev["hash_matches"])
        self.assertFalse(state["firmware"]["hosted"])
        self.assertTrue(state["firmware"]["device_supports_ota"])

        entries = client.get("/api/device/log").get_json()
        self.assertEqual([e["msg"] for e in entries], ["[EPD] Fertig!", "[WiFi] OK", "== Inkwall 1.1.0 Boot #42 =="])
        self.assertEqual(entries[0]["device"], "esp32-eink-01")
        self.assertEqual(client.delete("/api/device/log").status_code, 200)
        self.assertEqual(client.get("/api/device/log").get_json(), [])

    def test_update_pending_when_hosted_version_differs(self) -> None:
        device.store_firmware(_fake_firmware("1.2.0"))
        client = server.app.test_client()
        client.post("/ack", json={"device_id": "d", "hash": "x", "result": "unchanged", "fw_version": "1.1.0"})
        state = client.get("/api/display").get_json()
        self.assertTrue(state["firmware"]["update_pending"])
        self.assertEqual(state["firmware"]["version"], "1.2.0")
        client.post("/ack", json={"device_id": "d", "hash": "x", "result": "unchanged", "fw_version": "1.2.0"})
        self.assertFalse(client.get("/api/display").get_json()["firmware"]["update_pending"])

    def test_old_firmware_ack_still_works(self) -> None:
        client = server.app.test_client()
        resp = client.post("/ack", json={"device_id": "esp32-eink-01", "hash": "abc"})
        self.assertEqual(resp.status_code, 200)
        dev = client.get("/api/display").get_json()["device"]
        self.assertEqual(dev["device_id"], "esp32-eink-01")
        self.assertEqual(dev["fw_version"], "")
        self.assertIsNone(dev["rssi"])

    def test_meta_carries_time_clean_and_test_flag(self) -> None:
        client = server.app.test_client()
        with patch.object(device, "DEVICE_STATE_PATH", Path(self._tmp.name) / "state.json"), \
             patch.object(server, "_esp32_state", {"hash": "abc", "format": "bmp", "state": "s", "media_type": "m", "rendered_at": ""}):
            meta = client.get("/meta.json").get_json()
            self.assertGreater(meta["epoch"], 1_700_000_000)
            self.assertIn(meta["tz_offset_sec"] % 900, (0,))
            self.assertIn("clean_due", meta)
            self.assertNotIn("show_offline_test", meta)
            self.assertEqual(client.post("/api/device/test-banner").status_code, 200)
            self.assertTrue(client.get("/api/display").get_json()["panel"]["test_banner_pending"])
            self.assertTrue(client.get("/meta.json").get_json()["show_offline_test"])
            # Mit der Auslieferung verbraucht – ein zweites meta.json traegt den Auftrag nicht mehr
            self.assertNotIn("show_offline_test", client.get("/meta.json").get_json())
            self.assertFalse(client.get("/api/display").get_json()["panel"]["test_banner_pending"])
            # Das Gerät meldet sich → Probe verbraucht, Reinigung wird vermerkt, Offline-Zeit erzeugt ein Ereignis
            resp = client.post("/ack", json={"device_id": "d", "hash": "abc", "result": "test", "fw_version": "1.2.0",
                                              "cleaned": 1, "offline_s": 1900})
            self.assertEqual(resp.status_code, 200)
            self.assertNotIn("show_offline_test", client.get("/meta.json").get_json())
            panel = client.get("/api/display").get_json()["panel"]
            self.assertTrue(panel["last_clean_at"])
            self.assertFalse(panel["test_banner_pending"])

    def test_clean_due_logic(self) -> None:
        from datetime import datetime, timedelta, timezone
        with patch.object(device, "DEVICE_STATE_PATH", Path(self._tmp.name) / "state.json"):
            three_am = datetime(2026, 9, 4, 3, 10, tzinfo=timezone.utc)
            self.assertFalse(device.clean_due(three_am, 0, 3), "0 Tage = aus")
            self.assertFalse(device.clean_due(three_am.replace(hour=12), 14, 3), "falsche Stunde")
            self.assertTrue(device.clean_due(three_am, 14, 3), "noch nie gereinigt → fällig")
            device.mark_cleaned(three_am)
            self.assertFalse(device.clean_due(three_am + timedelta(days=1), 14, 3))
            self.assertTrue(device.clean_due(three_am + timedelta(days=14), 14, 3))

    def test_rssi_quality_bands(self) -> None:
        self.assertEqual(device.rssi_quality(-60)[1], "ok")
        self.assertEqual(device.rssi_quality(-80)[1], "warn")
        self.assertEqual(device.rssi_quality(-90)[1], "bad")
        self.assertEqual(device.rssi_quality(None), ("", ""))


if __name__ == "__main__":
    unittest.main()
