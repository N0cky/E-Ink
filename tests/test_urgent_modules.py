"""
Dringende Idle-Module (is_urgent): Reihenfolge in der Rotation und im Dashboard.
"""

from __future__ import annotations

import unittest

from PIL import Image

from app import server
from app.module_base import PlexInkModule


class _Mod(PlexInkModule):
    MODULE_PRIORITY = 100

    def __init__(self, module_id: str, urgent: bool = False):
        self.MODULE_ID = module_id
        self.MODULE_NAME = module_id
        self._urgent = urgent

    def is_enabled(self, env):
        return True

    def fetch_content(self, env):
        return {"id": self.MODULE_ID}

    def render(self, env, content):
        return Image.new("RGB", (4, 4))

    def should_refresh(self, env):
        return False

    def is_urgent(self, env):
        return self._urgent

    def render_tile(self, env, content, width, height):
        return Image.new("RGB", (width, height))


class RotationSequenceTest(unittest.TestCase):
    def test_without_urgent_modules_order_is_unchanged(self) -> None:
        mods = [_Mod("a"), _Mod("b"), _Mod("c")]
        self.assertEqual([m.MODULE_ID for m in server._rotation_sequence(mods, {})], ["a", "b", "c"])

    def test_urgent_module_comes_before_every_other(self) -> None:
        mods = [_Mod("wetter"), _Mod("muell", urgent=True), _Mod("news")]
        seq = [m.MODULE_ID for m in server._rotation_sequence(mods, {})]
        self.assertEqual(seq, ["muell", "wetter", "muell", "news"])

    def test_only_urgent_modules_stay_as_they_are(self) -> None:
        mods = [_Mod("muell", urgent=True)]
        self.assertEqual([m.MODULE_ID for m in server._rotation_sequence(mods, {})], ["muell"])

    def test_default_hook_is_false(self) -> None:
        self.assertFalse(PlexInkModule.is_urgent(_Mod("x"), {}))


class DashboardUrgentOrderTest(unittest.TestCase):
    def test_urgent_tile_moves_to_the_top(self) -> None:
        from app import dashboard
        from app.config import get_cfg, override_runtime_config
        mods = [_Mod("wetter"), _Mod("muell", urgent=True), _Mod("news")]
        with override_runtime_config(dashboard_tiles=[("wetter", 40), ("muell", 30), ("news", 30)],
                                     idle_layout="dashboard", display_theme="eink"):
            result = dashboard.compose_dashboard({}, get_cfg(), mods, width=600, height=800)
        self.assertIsNotNone(result)
        _, state_key = result
        ids = [part.split("=")[0] for part in state_key.split(":", 2)[2].split("|")]
        self.assertEqual(ids[0], "muell")
        self.assertEqual(ids[1:], ["wetter", "news"])


if __name__ == "__main__":
    unittest.main()
