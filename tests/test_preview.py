"""
Tests für die Modul-Vorschau: /api/preview/<module>.png rendert ein Modul
on-demand mit Theme-Override und optionaler 6-Farben-Simulation, ohne den
Display-State anzufassen.
"""

from __future__ import annotations

import io
import unittest
from unittest.mock import patch

from PIL import Image

import app.config as config
import app.server as server
from app.module_base import InkwallModule


class _PreviewModule(InkwallModule):
    MODULE_ID = "previewable"
    MODULE_NAME = "Previewable"
    MODULE_DESCRIPTION = "test"
    MODULE_PRIORITY = 100

    def __init__(self, content="x"):
        self._content = content
        self.seen_themes: list[str] = []

    def fetch_content(self, env):
        return self._content

    def render(self, env, content):
        cfg = config.get_cfg()
        self.seen_themes.append(cfg.display_theme)
        color = (240, 240, 240) if cfg.display_theme == "light" else (20, 20, 20)
        return Image.new("RGB", (cfg.render_width, cfg.render_height), color)


class OverrideRuntimeConfigTest(unittest.TestCase):
    def test_override_is_temporary_and_updates_settings_values(self) -> None:
        before = config.get_cfg()
        with config.override_runtime_config(display_theme="light") as cfg:
            self.assertEqual(cfg.display_theme, "light")
            self.assertEqual(config.get_cfg().display_theme, "light")
            self.assertEqual(config.get_settings_values()["DISPLAY_THEME"], "light")
        self.assertIs(config.get_cfg(), before)

    def test_override_restores_on_exception(self) -> None:
        before = config.get_cfg()
        with self.assertRaises(RuntimeError):
            with config.override_runtime_config(display_theme="light"):
                raise RuntimeError("boom")
        self.assertIs(config.get_cfg(), before)


class PreviewEndpointTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = server.app.test_client()
        self.mod = _PreviewModule()
        self._patch = patch.object(server._registry, "get_module_by_id",
                                   side_effect=lambda mid: self.mod if mid == "previewable" else None)
        self._patch.start()
        self.state_before = dict(server._esp32_state)

    def tearDown(self) -> None:
        self._patch.stop()

    def _png(self, response) -> Image.Image:
        # Fehlertext nur dekodieren, wenn es kein Bild ist (PNG-Bytes sind kein UTF-8)
        detail = None if response.status_code == 200 else response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200, detail)
        self.assertEqual(response.mimetype, "image/png")
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")
        return Image.open(io.BytesIO(response.data))

    def test_renders_module_without_touching_display_state(self) -> None:
        img = self._png(self.client.get("/api/preview/previewable.png"))
        cfg = config.get_cfg()
        self.assertEqual(img.size, (cfg.render_width, cfg.render_height))
        self.assertEqual(server._esp32_state, self.state_before)

    def test_theme_override_reaches_module_and_is_restored(self) -> None:
        configured = config.get_cfg().display_theme
        other = "light" if configured != "light" else "dark"
        self._png(self.client.get(f"/api/preview/previewable.png?theme={other}"))
        self.assertEqual(self.mod.seen_themes[-1], other)
        self.assertEqual(config.get_cfg().display_theme, configured)

    def test_device_mode_returns_six_colour_image(self) -> None:
        img = self._png(self.client.get("/api/preview/previewable.png?device=1&theme=light"))
        self.assertLessEqual(len(img.convert("RGB").getcolors(64) or []), 6)

    def test_unknown_theme_is_rejected(self) -> None:
        response = self.client.get("/api/preview/previewable.png?theme=neon")
        self.assertEqual(response.status_code, 400)

    def test_unknown_module_404(self) -> None:
        response = self.client.get("/api/preview/nope.png")
        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.get_json()["ok"])

    def test_module_without_content_404_with_message(self) -> None:
        self.mod._content = None
        response = self.client.get("/api/preview/previewable.png")
        self.assertEqual(response.status_code, 404)
        self.assertIn("keinen Inhalt", response.get_json()["error"])


if __name__ == "__main__":
    unittest.main()
