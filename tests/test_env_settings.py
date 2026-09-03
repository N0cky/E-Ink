"""
Tests für das Schreiben/Lesen der Settings-Datei, das Verhalten von
Passwort-Feldern im Formular und den optionalen UI-Passwortschutz.
"""

from __future__ import annotations

import base64
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app.config as config
import app.server as server
from app.logger import redact_secrets


class EnvRoundtripTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.env_path = Path(self._tmpdir.name) / "settings.env"
        self._patch = patch.object(config, "ENV_FILE_PATH", self.env_path)
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
        self._tmpdir.cleanup()

    def _roundtrip(self, values: dict[str, str]) -> dict[str, str]:
        config.write_env_settings(values)
        return config.read_env_settings()

    def test_plain_values_are_written_unquoted(self) -> None:
        config.write_env_settings({"RENDER_WIDTH": "1200", "DISPLAY_THEME": "light"})
        text = self.env_path.read_text(encoding="utf-8")
        self.assertIn("RENDER_WIDTH=1200\n", text)
        self.assertIn("DISPLAY_THEME=light\n", text)

    def test_special_characters_survive_roundtrip(self) -> None:
        cases = {
            "A_HASH":      "Wert mit # Kommentar",
            "A_QUOTE":     'Er sagte "Hallo"',
            "A_BACKSLASH": r"C:\Pfad\zu\Bildern",
            "A_SPACE":     "  außen Leerzeichen  ",
            "A_DOLLAR":    "${HOME}/nicht/expandieren",
            "A_UMLAUT":    "Gießen – Straße",
            "A_EMPTY":     "",
        }
        result = self._roundtrip(cases)
        for key, expected in cases.items():
            # as_env_value strippt Leerzeichen am Rand – das ist gewollt
            self.assertEqual(result.get(key), expected.strip(), key)

    def test_newline_cannot_inject_new_keys(self) -> None:
        config.write_env_settings({"GALLERY_PATHS": "/pics\nHTTPS_PROXY=http://evil"})
        result = config.read_env_settings()
        self.assertNotIn("HTTPS_PROXY", result)
        self.assertEqual(result["GALLERY_PATHS"], "/pics HTTPS_PROXY=http://evil")

    def test_invalid_key_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            config.write_env_settings({"bad key": "x"})
        with self.assertRaises(ValueError):
            config.write_env_settings({"X=Y": "x"})

    def test_existing_lines_and_comments_are_preserved(self) -> None:
        self.env_path.write_text("# Kommentar\nRENDER_WIDTH=800\nOTHER=keep\n", encoding="utf-8")
        config.write_env_settings({"RENDER_WIDTH": "1200"})
        text = self.env_path.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("# Kommentar\n"))
        self.assertIn("RENDER_WIDTH=1200\n", text)
        self.assertIn("OTHER=keep\n", text)

    def test_settings_are_not_exported_to_process_environment(self) -> None:
        marker = "PLEXINK_TEST_MARKER_KEY"
        os.environ.pop(marker, None)
        config.write_env_settings({marker: "should-stay-in-file"})
        config.apply_runtime_config()
        self.assertNotIn(marker, os.environ)


class PasswordFieldTest(unittest.TestCase):
    def test_empty_password_keeps_current_value(self) -> None:
        fields = [{"name": "PLEX_TOKEN", "type": "password"}, {"name": "STEAM_API_KEY", "type": "password"}]

        class _Form(dict):
            def getlist(self, k):
                return []

        with patch.object(config, "get_settings_values", return_value={"PLEX_TOKEN": "geheim", "STEAM_API_KEY": "k"}):
            updates = config.collect_settings_form_data(_Form({"PLEX_TOKEN": "", "STEAM_API_KEY": "neu"}), fields)
        self.assertEqual(updates["PLEX_TOKEN"], "geheim")
        self.assertEqual(updates["STEAM_API_KEY"], "neu")

    def test_settings_api_never_returns_secret_values(self) -> None:
        import app.display_api as api
        client = server.app.test_client()
        with patch.object(api, "get_settings_values", return_value={
            **config.get_settings_values(),
            "PLEX_TOKEN": "SUPERSECRETTOKEN123",
            "STEAM_API_KEY": "STEAMKEYXYZ",
        }):
            plex = client.get("/api/settings/plex").get_data(as_text=True)
            steam = client.get("/api/settings/steam").get_data(as_text=True)
            export = client.get("/api/settings/export").get_data(as_text=True)
        for body in (plex, steam, export):
            self.assertNotIn("SUPERSECRETTOKEN123", body)
            self.assertNotIn("STEAMKEYXYZ", body)
        self.assertIn('"is_set":true', plex.replace(" ", ""))


class RedactSecretsTest(unittest.TestCase):
    def test_masks_known_query_params(self) -> None:
        text = "GET http://plex:32400/x?X-Plex-Token=abc123&foo=1 and http://api?key=K9&steamids=1"
        out = redact_secrets(text)
        self.assertNotIn("abc123", out)
        self.assertNotIn("K9", out)
        self.assertIn("X-Plex-Token=***", out)
        self.assertIn("key=***", out)
        self.assertIn("foo=1", out)
        self.assertIn("steamids=1", out)


class UiPasswordTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = server.app.test_client()

    def _auth(self, pw: str) -> dict:
        return {"Authorization": "Basic " + base64.b64encode(f"user:{pw}".encode()).decode()}

    def test_no_password_means_open_ui(self) -> None:
        with patch.dict(os.environ, {"PLEXINK_UI_PASSWORD": ""}):
            self.assertEqual(self.client.get("/").status_code, 200)

    def test_password_protects_ui_but_not_esp32_endpoints(self) -> None:
        with patch.dict(os.environ, {"PLEXINK_UI_PASSWORD": "pw123"}):
            self.assertEqual(self.client.get("/").status_code, 401)
            self.assertEqual(self.client.get("/settings").status_code, 401)
            self.assertEqual(self.client.get("/api/status").status_code, 401)
            self.assertIn("WWW-Authenticate", self.client.get("/").headers)

            self.assertEqual(self.client.get("/", headers=self._auth("falsch")).status_code, 401)
            self.assertEqual(self.client.get("/", headers=self._auth("pw123")).status_code, 200)

            # ESP32-Pfade bleiben offen
            self.assertNotEqual(self.client.get("/hash").status_code, 401)
            self.assertNotEqual(self.client.get("/meta.json").status_code, 401)
            self.assertNotEqual(self.client.get("/health").status_code, 401)


if __name__ == "__main__":
    unittest.main()
