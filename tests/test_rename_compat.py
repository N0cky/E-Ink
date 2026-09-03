"""
Rückwärtskompatibilität nach der Umbenennung in Inkwall: alter Präfix PLEXINK_
für Prozessvariablen, alte Firmware-Marke PLEXEINK_FW_VERSION=, alter
Klassenname PlexInkModule.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import app.config as config
import app.device as device
import app.module_base as module_base
import app.server as server


class RenameCompatTest(unittest.TestCase):
    def test_process_env_prefers_new_prefix_and_accepts_old(self) -> None:
        with patch.dict(os.environ, {"INKWALL_UI_PASSWORD": "neu", "PLEXINK_UI_PASSWORD": "alt"}):
            self.assertEqual(config.process_env("UI_PASSWORD"), "neu")
            self.assertEqual(server._ui_password(), "neu")
        with patch.dict(os.environ, {"INKWALL_UI_PASSWORD": "", "PLEXINK_UI_PASSWORD": "alt"}):
            self.assertEqual(config.process_env("UI_PASSWORD"), "alt")
        with patch.dict(os.environ, {"INKWALL_UI_PASSWORD": "", "PLEXINK_UI_PASSWORD": ""}):
            self.assertEqual(config.process_env("UI_PASSWORD", "leer"), "leer")

    def test_gallery_roots_via_old_prefix(self) -> None:
        from modules.gallery import data_source as ds
        with patch.dict(os.environ, {"INKWALL_GALLERY_ROOTS": "", "PLEXINK_GALLERY_ROOTS": "C:/alt;D:/zwei" if os.name == "nt" else "/alt;/zwei"}):
            self.assertEqual(len(ds.allowed_gallery_roots()), 2)

    def test_firmware_marker_old_and_new(self) -> None:
        head = bytes([0xE9]) + b"\0" * 11 + (9).to_bytes(2, "little") + b"\0" * 50
        for marker in (b"INKWALL_FW_VERSION=", b"PLEXEINK_FW_VERSION="):
            info = device.inspect_firmware(head + marker + b"1.3.0\0" + b"\0" * 20)
            self.assertEqual(info["version"], "1.3.0", marker)
        with self.assertRaises(ValueError):
            device.inspect_firmware(head + b"\0" * 40)

    def test_module_base_alias(self) -> None:
        self.assertIs(module_base.PlexInkModule, module_base.InkwallModule)

        class Old(module_base.PlexInkModule):
            MODULE_ID = "old"

            def fetch_content(self, env):
                return None

            def render(self, env, content):
                raise NotImplementedError

        self.assertIsInstance(Old(), module_base.InkwallModule)


if __name__ == "__main__":
    unittest.main()
