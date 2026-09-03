"""
Tests für die Render-Historie: Ablage und Beschneidung der Liste, Verkleinerung,
ungültige Kennungen, die Routen /api/history und /history/<id>.png und die
Anbindung an _save_image (nur echte neue Bilder landen im Verlauf).
"""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import app.history as history
import app.server as server


class HistoryStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name) / "history"
        self._patches = [patch.object(history, "HISTORY_DIR", root),
                         patch.object(history, "HISTORY_INDEX", root / "history.json")]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in self._patches:
            p.stop()
        self._tmp.cleanup()

    def _record(self, i: int, keep: int = history.HISTORY_KEEP) -> dict:
        when = datetime(2026, 9, 3, 7, 0, i, tzinfo=timezone.utc)
        return history.record(Image.new("RGB", (1200, 1600), (i, 0, 0)), "dwd_weather", "Wetter",
                              f"{i:08x}deadbeef", rendered_at=when, keep=keep)

    def test_record_shrinks_image_and_lists_newest_first(self) -> None:
        first = self._record(1)
        second = self._record(2)
        self.assertEqual(first["id"], "20260903-070001-00000001")
        entries = history.list_entries()
        self.assertEqual([e["id"] for e in entries], [second["id"], first["id"]])
        self.assertEqual(entries[0]["url"], f"/history/{second['id']}.png")
        self.assertEqual((entries[0]["width"], entries[0]["height"]), (1200, 1600), "Originalgröße im Index")
        with Image.open(history.image_path(second["id"])) as img:
            self.assertEqual(max(img.size), history.THUMB_MAX_EDGE, "Kopie ist verkleinert")

    def test_keep_limit_removes_oldest_files(self) -> None:
        ids = [self._record(i, keep=3)["id"] for i in range(1, 6)]
        listed = [e["id"] for e in history.list_entries()]
        self.assertEqual(listed, [ids[4], ids[3], ids[2]])
        self.assertIsNone(history.image_path(ids[0]), "ältestes Bild ist gelöscht")
        self.assertFalse((history.HISTORY_DIR / f"{ids[1]}.png").exists())

    def test_invalid_ids_are_rejected(self) -> None:
        self._record(1)
        for bad in ("", "../history.json", "20260903-070001-zzzzzzzz", "x" * 40):
            self.assertIsNone(history.image_path(bad), bad)

    def test_clear_removes_everything(self) -> None:
        self._record(1)
        self._record(2)
        self.assertEqual(history.clear(), 2)
        self.assertEqual(history.list_entries(), [])


class HistoryRoutesTest(HistoryStoreTest):
    def setUp(self) -> None:
        super().setUp()
        self.client = server.app.test_client()

    def test_api_lists_entries_and_serves_images(self) -> None:
        entry = self._record(1)
        data = self.client.get("/api/history").get_json()
        self.assertEqual(data["keep"], history.HISTORY_KEEP)
        self.assertEqual([e["id"] for e in data["entries"]], [entry["id"]])
        self.assertEqual(data["entries"][0]["module_name"], "Wetter")
        response = self.client.get(data["entries"][0]["url"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "image/png")
        self.assertIn(b"PNG", response.get_data()[:8])
        response.close()
        self.assertEqual(self.client.get("/history/20260903-070001-ffffffff.png").status_code, 404)
        self.assertEqual(self.client.get("/history/..%2Fhistory.json.png").status_code, 404)

    def test_delete_clears_history(self) -> None:
        self._record(1)
        self.assertEqual(self.client.delete("/api/history").get_json()["removed"], 1)
        self.assertEqual(self.client.get("/api/history").get_json()["entries"], [])


class _Cfg:
    output_format = "png"
    display_rotation = "0"
    display_theme = "dark"
    show_render_time = False


class SaveImageRecordsHistoryTest(HistoryStoreTest):
    def setUp(self) -> None:
        super().setUp()
        tmp = Path(self._tmp.name)
        self._server_patches = [
            patch.object(server, "CURRENT_IMAGE_PATH", tmp / "current.png"),
            patch.object(server, "CURRENT_BMP_PATH", tmp / "current.bmp"),
            patch.object(server, "CURRENT_EPD_PATH", tmp / "current.epd"),
            patch.object(server, "STATE_PATH", tmp / "state.txt"),
            patch.object(server, "get_cfg", return_value=_Cfg()),
        ]
        for p in self._server_patches:
            p.start()
        server._esp32_state = {"hash": "", "format": "png", "state": "idle", "media_type": "idle", "rendered_at": ""}

    def tearDown(self) -> None:
        for p in self._server_patches:
            p.stop()
        super().tearDown()

    def test_only_changed_images_are_recorded(self) -> None:
        red = Image.new("RGB", (8, 8), (255, 0, 0))
        server._save_image(red, "dwd_weather:a:1", "dwd_weather")
        server._save_image(red, "dwd_weather:a:2", "dwd_weather")     # gleiches Bild, neuer Slot
        server._save_image(Image.new("RGB", (8, 8), (0, 0, 255)), "tagesschau:b:3", "tagesschau")
        entries = history.list_entries()
        self.assertEqual([e["module_id"] for e in entries], ["tagesschau", "dwd_weather"])
        self.assertTrue(entries[0]["hash"] and entries[1]["hash"] and entries[0]["hash"] != entries[1]["hash"])
        self.assertEqual(entries[0]["hash"], server._esp32_state["hash"])
        self.assertTrue(all(e["module_name"] for e in entries))


if __name__ == "__main__":
    unittest.main()
