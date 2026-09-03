"""
Tests für Phase C des UI-Konzepts: die Seiten Inhalte, Gerät, System, die
Weiterleitungen der alten Adressen, Export/Import und die neuen Feldtypen
(Liste, Zuordnung, Dauer) in der Karten-Schnittstelle.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import app.config as config
import app.display_api as api
import app.server as server


class PagesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = server.app.test_client()

    def test_new_pages_render_and_old_urls_redirect(self) -> None:
        for path, marker in (("/", "Programm"), ("/inhalte", "Live-Inhalte"), ("/geraet", "Client"), ("/system", "Ereignisse")):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertIn(marker, response.get_data(as_text=True), path)
        self.assertEqual(self.client.get("/settings").status_code, 302)
        self.assertTrue(self.client.get("/settings").headers["Location"].endswith("/inhalte"))
        self.assertEqual(self.client.get("/logs").status_code, 302)
        self.assertTrue(self.client.get("/logs").headers["Location"].endswith("/system"))
        self.assertEqual(self.client.get("/static/fields.js").status_code, 200)

    def test_health_reports_version_and_password_state(self) -> None:
        data = self.client.get("/health").get_json()
        self.assertEqual(data["version"], config.APP_VERSION)
        self.assertIn("ui_password", data)


class FieldTypesTest(unittest.TestCase):
    def test_list_field_view_and_roundtrip(self) -> None:
        field = {"name": "X_URLS", "type": "list", "item_fields": [{"name": "label"}, {"name": "url"}]}
        view = api._field_view(field, {"X_URLS": "Zuhause|https://a; https://b"})
        self.assertEqual(view["type"], "list")
        self.assertEqual(view["value"], [{"label": "Zuhause", "url": "https://a"}, {"label": "", "url": "https://b"}])
        joined = api._join_list_value([{"label": "Zuhause", "url": "https://a"}, {"label": "", "url": "https://b"}, {"label": "", "url": ""}], field)
        self.assertEqual(joined, "Zuhause|https://a; https://b")

    def test_single_column_list(self) -> None:
        field = {"name": "GALLERY_PATHS", "type": "list", "item_fields": [{"name": "path"}]}
        view = api._field_view(field, {"GALLERY_PATHS": r"C:\Bilder;D:\Frames"})
        self.assertEqual(view["value"], [{"path": r"C:\Bilder"}, {"path": r"D:\Frames"}])
        self.assertEqual(api._join_list_value([{"path": "/a"}, {"path": " /b "}], field), "/a; /b")

    def test_mapping_field_view_and_roundtrip(self) -> None:
        field = {"name": "COLORS", "type": "mapping"}
        view = api._field_view(field, {"COLORS": "bio=green, papier=blue"})
        self.assertEqual(view["value"], [{"key": "bio", "value": "green"}, {"key": "papier", "value": "blue"}])
        self.assertEqual(api._join_mapping_value([{"key": "bio", "value": "green"}, {"key": "", "value": "red"}]), "bio=green")

    def test_seconds_fields_are_presented_as_duration(self) -> None:
        view = api._field_view({"name": "X_CACHE_SECONDS", "type": "number", "label": "Cache"}, {"X_CACHE_SECONDS": "21600"})
        self.assertEqual(view["type"], "duration")
        self.assertEqual(view["value"], "21600")

    def test_module_updates_serialize_lists_and_mappings(self) -> None:
        with patch.object(api, "get_settings_values", return_value={}):
            updates = api.module_updates_from_values("garbage", {
                "GARBAGE_ICS_URLS": [{"label": "Zuhause", "url": "https://x/{year}.ics"}],
                "GARBAGE_TYPE_COLORS": [{"key": "bio", "value": "green"}],
                "GARBAGE_CACHE_SECONDS": "7200",
            })
        self.assertEqual(updates["GARBAGE_ICS_URLS"], "Zuhause|https://x/{year}.ics")
        self.assertEqual(updates["GARBAGE_TYPE_COLORS"], "bio=green")
        self.assertEqual(updates["GARBAGE_CACHE_SECONDS"], "7200")

    def test_real_module_list_fields_render_from_stored_strings(self) -> None:
        with patch.object(api, "get_settings_values", return_value={**config.get_settings_values(), "GARBAGE_ICS_URLS": "A|https://a; https://b"}):
            payload = api.build_module_settings("garbage")
        by_name = {f["name"]: f for f in payload["fields"]}
        self.assertEqual(by_name["GARBAGE_ICS_URLS"]["type"], "list")
        self.assertEqual(len(by_name["GARBAGE_ICS_URLS"]["value"]), 2)
        self.assertEqual(by_name["GARBAGE_TYPE_COLORS"]["type"], "mapping")
        self.assertTrue(by_name["GARBAGE_TYPE_COLORS"]["value_options"])


class ExportImportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = server.app.test_client()

    def test_export_hides_secrets_unless_requested(self) -> None:
        with patch.object(api, "get_settings_values", return_value={**config.get_settings_values(), "PLEX_TOKEN": "geheim", "RENDER_WIDTH": "1200"}):
            plain = self.client.get("/api/settings/export").get_json()
            full = self.client.get("/api/settings/export?secrets=1").get_json()
        self.assertEqual(plain["format"], "inkwall-settings")
        self.assertNotIn("PLEX_TOKEN", plain["values"])
        self.assertEqual(plain["values"]["RENDER_WIDTH"], "1200")
        self.assertEqual(full["values"]["PLEX_TOKEN"], "geheim")

    def test_import_applies_known_keys_and_skips_unknown_and_empty_secrets(self) -> None:
        with patch.object(server, "write_env_settings") as write_env, patch.object(server, "request_render"):
            response = self.client.post("/api/settings/import", json={
                "values": {"RENDER_WIDTH": "800", "RENDER_HEIGHT": "600", "IDLE_MODULES": "dwd_weather,tagesschau",
                           "PLEX_TOKEN": "", "NOPE": "x"},
            })
        self.assertEqual(response.status_code, 200, response.get_json())
        data = response.get_json()
        self.assertEqual(data["applied"], 3)
        self.assertEqual(data["ignored"], ["NOPE"])
        written = write_env.call_args[0][0]
        self.assertEqual(written, {"RENDER_WIDTH": "800", "RENDER_HEIGHT": "600", "IDLE_MODULES": "dwd_weather,tagesschau"})

    def test_import_rejects_invalid_values(self) -> None:
        with patch.object(server, "write_env_settings") as write_env, patch.object(server, "request_render"):
            response = self.client.post("/api/settings/import", json={"values": {"RENDER_WIDTH": "abc"}})
        self.assertEqual(response.status_code, 400)
        write_env.assert_not_called()

    def test_import_rejects_garbage(self) -> None:
        self.assertEqual(self.client.post("/api/settings/import", json=[1, 2]).status_code, 400)
        self.assertEqual(self.client.post("/api/settings/import", json={"values": {"NOPE": "x"}}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
