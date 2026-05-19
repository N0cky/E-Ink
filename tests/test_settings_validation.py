from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from pathlib import Path

import app.server as server_module
from app.config import CONFIG_DIR, get_settings_values, resolve_env_file_path


class SettingsValidationFlowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = server_module.app.test_client()

    @staticmethod
    def _build_valid_form_data() -> dict[str, str]:
        sections = server_module._build_settings_sections()
        all_fields = server_module._all_fields_from_sections(sections)
        current = dict(get_settings_values())
        form_data: dict[str, str] = {}

        for field in all_fields:
            name = field["name"]
            value = current.get(name)
            if value in (None, ""):
                value = field.get("default", "")
            form_data[name] = str(value)

        return form_data

    def test_invalid_module_settings_block_save(self) -> None:
        form_data = self._build_valid_form_data()
        form_data["DWD_WEATHER_STATION_ID"] = "abc"

        with (
            patch("app.server.write_env_settings") as write_env,
            patch("app.server.apply_runtime_config") as apply_cfg,
            patch("app.server.render_image") as render_image,
        ):
            response = self.client.post("/settings", data=form_data)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Bitte Eingaben korrigieren", response.get_data(as_text=True))
        self.assertIn("DWD-Station-ID: Bitte nur numerische Stations-IDs verwenden.", response.get_data(as_text=True))
        write_env.assert_not_called()
        apply_cfg.assert_not_called()
        render_image.assert_not_called()

    def test_gallery_enabled_without_paths_blocks_save(self) -> None:
        form_data = self._build_valid_form_data()
        idle_modules = [item for item in form_data.get("IDLE_MODULES", "").split(",") if item]
        if "gallery" not in idle_modules:
            idle_modules.append("gallery")
        form_data["IDLE_MODULES"] = ",".join(idle_modules)
        form_data["GALLERY_PATHS"] = ""

        with (
            patch("app.server.write_env_settings") as write_env,
            patch("app.server.apply_runtime_config") as apply_cfg,
            patch("app.server.render_image") as render_image,
        ):
            response = self.client.post("/settings", data=form_data)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Bitte Eingaben korrigieren", response.get_data(as_text=True))
        self.assertIn(
            "Bildordner: Bitte mindestens einen lokalen Ordner angeben, wenn Gallery aktiv ist.",
            response.get_data(as_text=True),
        )
        write_env.assert_not_called()
        apply_cfg.assert_not_called()
        render_image.assert_not_called()

    def test_valid_settings_submit_redirects(self) -> None:
        form_data = self._build_valid_form_data()
        with tempfile.TemporaryDirectory() as tmp:
            form_data["GALLERY_PATHS"] = tmp

            with (
                patch("app.server.write_env_settings") as write_env,
                patch("app.server.apply_runtime_config") as apply_cfg,
                patch("app.server.render_image") as render_image,
            ):
                response = self.client.post("/settings", data=form_data, follow_redirects=False)

            self.assertEqual(response.status_code, 302)
            self.assertIn("/settings?saved=1", response.headers.get("Location", ""))
            write_env.assert_called_once()
            apply_cfg.assert_called_once()
            render_image.assert_called_once()

    def test_steam_enabled_without_profile_or_key_blocks_save(self) -> None:
        form_data = self._build_valid_form_data()
        form_data["STEAM_MODULE_ENABLED"] = "true"
        form_data["STEAM_PROFILE"] = ""
        form_data["STEAM_API_KEY"] = ""

        with (
            patch("app.server.write_env_settings") as write_env,
            patch("app.server.apply_runtime_config") as apply_cfg,
            patch("app.server.render_image") as render_image,
        ):
            response = self.client.post("/settings", data=form_data)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Steam-Profil: Bitte SteamID64, Vanity-Name oder Profil-URL angeben.", response.get_data(as_text=True))
        self.assertIn("Steam Web API Key: Bitte einen gültigen API-Key hinterlegen.", response.get_data(as_text=True))
        write_env.assert_not_called()
        apply_cfg.assert_not_called()
        render_image.assert_not_called()

    def test_night_mode_fixed_module_must_be_active_idle_module(self) -> None:
        form_data = self._build_valid_form_data()
        form_data["NIGHT_MODE_ENABLED"] = "true"
        form_data["NIGHT_MODE_IDLE_BEHAVIOR"] = "fixed"
        form_data["NIGHT_MODE_FIXED_MODULE"] = "gallery"
        form_data["IDLE_MODULES"] = "dwd_weather,tagesschau"

        with (
            patch("app.server.write_env_settings") as write_env,
            patch("app.server.apply_runtime_config") as apply_cfg,
            patch("app.server.render_image") as render_image,
        ):
            response = self.client.post("/settings", data=form_data)

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "Festes Nachtmodul: Das Modul muss auch in den aktiven Idle-Modulen enthalten sein.",
            response.get_data(as_text=True),
        )
        write_env.assert_not_called()
        apply_cfg.assert_not_called()
        render_image.assert_not_called()

    def test_meta_json_uses_gallery_custom_next_wake(self) -> None:
        with patch.dict(
            server_module._esp32_state,
            {
                "state": "gallery:12:C:\\images\\frame.jpg:123",
                "format": "png",
                "media_type": "gallery",
                "hash": "abc123",
                "rendered_at": "2026-04-20T09:00:00Z",
            },
            clear=True,
        ), patch(
            "app.server.get_settings_values",
            return_value={
                "GALLERY_INTERVAL_MODE": "custom",
                "GALLERY_INTERVAL_SECONDS": "420",
            },
        ), patch(
            "app.server._get_night_mode_state",
            return_value={"active": False, "seconds_until_end": 0, "label": ""},
        ):
            response = self.client.get("/meta.json")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["next_wake_sec"], 420)
        self.assertEqual(payload["next_wake_reason"], "Gallery – eigenes Bildwechsel-Intervall")

    def test_background_poll_uses_module_specific_interval(self) -> None:
        gallery = SimpleNamespace(
            is_enabled=lambda env: True,
            get_background_poll_seconds=lambda env: 30,
        )
        with (
            patch("app.server.get_settings_values", return_value={}),
            patch("app.server.get_cfg", return_value=SimpleNamespace(refresh_interval=60)),
            patch("app.server._registry.get_modules", return_value=[gallery]),
            patch("app.server._get_night_mode_state", return_value={"active": False, "seconds_until_end": 0, "label": ""}),
        ):
            self.assertEqual(server_module._get_background_poll_seconds(), 30)

    def test_night_mode_clamps_next_wake_to_mode_end(self) -> None:
        cfg = SimpleNamespace(
            idle_module_rotation_seconds=180,
            night_mode_interval_seconds=900,
            night_mode_end="07:00",
            refresh_interval=60,
        )
        with (
            patch("app.server.get_cfg", return_value=cfg),
            patch("app.server._get_night_mode_state", return_value={"active": True, "seconds_until_end": 120, "label": "23:00–07:00"}),
        ):
            seconds, reason = server_module._suggest_next_wake("__no_content__", "idle")

        self.assertEqual(seconds, 120)
        self.assertIn("07:00", reason)

    def test_plex_next_wake_ignores_night_mode(self) -> None:
        cfg = SimpleNamespace(
            refresh_interval=60,
            idle_module_rotation_seconds=180,
        )
        with (
            patch("app.server.get_cfg", return_value=cfg),
            patch("app.server._get_night_mode_state", return_value={"active": True, "seconds_until_end": 120, "label": "23:00–07:00"}),
        ):
            seconds, reason = server_module._suggest_next_wake("plex:123:playing:slot", "plex")

        self.assertEqual(seconds, 60)
        self.assertIn("Plex playing", reason)

    def test_night_mode_can_pin_a_single_idle_module(self) -> None:
        dwd = SimpleNamespace(MODULE_ID="dwd_weather", is_enabled=lambda env: True)
        tagesschau = SimpleNamespace(MODULE_ID="tagesschau", is_enabled=lambda env: True)
        cfg = SimpleNamespace(
            idle_module_rotation_seconds=180,
            night_mode_idle_behavior="fixed",
            night_mode_fixed_module_id="tagesschau",
            night_mode_interval_seconds=900,
        )
        with (
            patch("app.server.get_cfg", return_value=cfg),
            patch("app.server._get_night_mode_state", return_value={"active": True, "seconds_until_end": 3600, "label": "23:00–07:00"}),
            patch("app.server._registry.get_idle_modules", return_value=[dwd, tagesschau]),
        ):
            modules, rotation = server_module._get_effective_idle_modules({})

        self.assertEqual([m.MODULE_ID for m in modules], ["tagesschau"])
        self.assertEqual(rotation, 900)

    def test_ensure_runtime_started_is_idempotent(self) -> None:
        fake_thread = SimpleNamespace(start=lambda: None)
        with (
            patch("app.server._runtime_started", False),
            patch("app.server._worker_thread", None),
            patch("app.server.log_startup_config") as log_startup,
            patch("app.server.render_image") as render_image,
            patch("pathlib.Path.exists", return_value=False),
            patch("app.server._registry.get_modules", return_value=[]),
            patch("app.server.threading.Thread", return_value=fake_thread) as thread_ctor,
        ):
            server_module.ensure_runtime_started()
            server_module.ensure_runtime_started()

        log_startup.assert_called_once()
        render_image.assert_called_once()
        thread_ctor.assert_called_once()

    def test_default_config_file_path_points_to_config_directory(self) -> None:
        with patch.dict("os.environ", {}, clear=False):
            self.assertEqual(resolve_env_file_path(), CONFIG_DIR / "settings.env")

    def test_custom_config_file_path_is_respected(self) -> None:
        custom = Path("/tmp/custom-settings.env")
        with patch.dict("os.environ", {"PLEXINK_CONFIG_FILE": str(custom)}, clear=False):
            self.assertEqual(resolve_env_file_path(), custom)


if __name__ == "__main__":
    unittest.main()
