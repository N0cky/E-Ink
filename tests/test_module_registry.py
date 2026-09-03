from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

from app.module_registry import discover_modules


class ModuleRegistrySmokeTest(unittest.TestCase):
    def _write_module(self, root: Path, name: str, body: str) -> None:
        module_dir = root / name
        module_dir.mkdir(parents=True, exist_ok=True)
        (module_dir / "__init__.py").write_text(textwrap.dedent(body), encoding="utf-8")

    def test_discovers_valid_modules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "__init__.py").write_text("", encoding="utf-8")
            self._write_module(
                root,
                "alpha",
                """
                from app.module_base import InkwallModule
                from PIL import Image

                class Alpha(InkwallModule):
                    MODULE_ID = "alpha"
                    MODULE_NAME = "Alpha"
                    MODULE_DESCRIPTION = "alpha module"
                    MODULE_PRIORITY = 50
                    SETTINGS_FIELDS = [{"name": "ALPHA_ENABLED", "type": "text"}]

                    def fetch_content(self, env):
                        return {"ok": True}

                    def render(self, env, content):
                        return Image.new("RGB", (1, 1), (0, 0, 0))

                module = Alpha()
                """,
            )

            modules = discover_modules(root)
            self.assertEqual([m.MODULE_ID for m in modules], ["alpha"])

    def test_rejects_duplicate_module_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "__init__.py").write_text("", encoding="utf-8")

            template = """
                from app.module_base import InkwallModule
                from PIL import Image

                class Demo(InkwallModule):
                    MODULE_ID = "dup"
                    MODULE_NAME = "{name}"
                    MODULE_DESCRIPTION = "demo"
                    MODULE_PRIORITY = 100

                    def fetch_content(self, env):
                        return None

                    def render(self, env, content):
                        return Image.new("RGB", (1, 1), (0, 0, 0))

                module = Demo()
            """
            self._write_module(root, "one", template.format(name="One"))
            self._write_module(root, "two", template.format(name="Two"))

            modules = discover_modules(root)
            self.assertEqual(len(modules), 1)
            self.assertEqual(modules[0].MODULE_ID, "dup")

    def test_rejects_duplicate_field_names_across_modules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "__init__.py").write_text("", encoding="utf-8")

            template = """
                from app.module_base import InkwallModule
                from PIL import Image

                class Demo(InkwallModule):
                    MODULE_ID = "{module_id}"
                    MODULE_NAME = "{module_name}"
                    MODULE_DESCRIPTION = "demo"
                    MODULE_PRIORITY = 100
                    SETTINGS_FIELDS = [{{"name": "SHARED_FIELD", "type": "text"}}]

                    def fetch_content(self, env):
                        return None

                    def render(self, env, content):
                        return Image.new("RGB", (1, 1), (0, 0, 0))

                module = Demo()
            """
            self._write_module(root, "one", template.format(module_id="one", module_name="One"))
            self._write_module(root, "two", template.format(module_id="two", module_name="Two"))

            modules = discover_modules(root)
            self.assertEqual(len(modules), 1)
            self.assertEqual(modules[0].MODULE_ID, "one")

    def test_skips_broken_modules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "__init__.py").write_text("", encoding="utf-8")
            self._write_module(
                root,
                "broken",
                """
                raise RuntimeError("boom")
                """,
            )

            modules = discover_modules(root)
            self.assertEqual(modules, [])


if __name__ == "__main__":
    unittest.main()
