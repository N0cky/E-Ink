from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import app.server as server_module
from app.config import get_settings_values


class SettingsValidationFlowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = server_module.app.test_client()

    @staticmethod
    def _apply_gallery_form_defaults(form_data: dict[str, str]) -> dict[str, str]:
        form_data.setdefault("GALLERY_PATHS", "")
        form_data.setdefault("GALLERY_RECURSIVE", "true")
        form_data.setdefault("GALLERY_ORDER", "random")
        form_data.setdefault("GALLERY_INTERVAL_MODE", "idle_rotation")
        form_data.setdefault("GALLERY_INTERVAL_SECONDS", "300")
        form_data.setdefault("GALLERY_AVOID_RECENT_COUNT", "5")
        form_data.setdefault("GALLERY_FIT_MODE", "fit_blur_bg")
        form_data.setdefault("GALLERY_OVERLAY_MODE", "none")
        return form_data

    def test_invalid_module_settings_block_save(self) -> None:
        form_data = self._apply_gallery_form_defaults(dict(get_settings_values()))
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
        form_data = self._apply_gallery_form_defaults(dict(get_settings_values()))
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
        form_data = self._apply_gallery_form_defaults(dict(get_settings_values()))
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
        ):
            self.assertEqual(server_module._get_background_poll_seconds(), 30)

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


if __name__ == "__main__":
    unittest.main()
