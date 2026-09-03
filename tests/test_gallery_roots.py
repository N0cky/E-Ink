"""
Tests für die Gallery-Freigabe (INKWALL_GALLERY_ROOTS): ohne Wurzeln keine
Einschränkung, mit Wurzeln werden fremde Ordner beim Speichern abgelehnt,
beim Scannen übersprungen und im Status gemeldet.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import app.config as config
from modules.gallery import data_source as ds
from modules.gallery import module as gallery


class GalleryRootsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.allowed = root / "allowed"
        self.other = root / "other"
        for folder in (self.allowed, self.other):
            folder.mkdir()
            Image.new("RGB", (40, 30), (200, 80, 40)).save(folder / "a.jpg")
        ds._scan_cache.clear()
        ds._warned_paths.clear()
        self.env = {**config.read_env_settings(), "IDLE_MODULES": "gallery",
                    "GALLERY_PATHS": f"{self.allowed}; {self.other}"}

    def tearDown(self) -> None:
        ds._scan_cache.clear()
        self._tmp.cleanup()

    def test_without_roots_everything_is_allowed(self) -> None:
        with patch.dict(os.environ, {ds.GALLERY_ROOTS_ENV: ""}):
            self.assertEqual(ds.allowed_gallery_roots(), ())
            self.assertTrue(ds.is_path_allowed(self.other))
            images = ds.list_gallery_images((self.allowed, self.other), recursive=False)
            self.assertEqual(len(images), 2)
            self.assertEqual(gallery.validate_settings({}, self.env), [])
            self.assertEqual(gallery.describe_status(self.env)["state"], "ready")

    def test_roots_restrict_scan_validation_and_status(self) -> None:
        with patch.dict(os.environ, {ds.GALLERY_ROOTS_ENV: str(self.allowed)}):
            self.assertEqual(ds.allowed_gallery_roots(), (self.allowed,))
            self.assertTrue(ds.is_path_allowed(self.allowed / "sub"))
            self.assertFalse(ds.is_path_allowed(self.other))
            self.assertFalse(ds.is_path_allowed(self.allowed / ".." / "other"), "Aufwärts-Pfade werden aufgelöst")
            images = ds.list_gallery_images((self.allowed, self.other), recursive=False)
            self.assertEqual([p.parent.name for p in images], ["allowed"])
            errors = gallery.validate_settings({}, self.env)
            self.assertEqual(len(errors), 1)
            self.assertIn("außerhalb der freigegebenen Ordner", errors[0])
            self.assertIn(str(self.other), errors[0])
            self.assertEqual(gallery.describe_status(self.env)["state"], "ready", "ein erlaubter Ordner reicht")
            only_other = {**self.env, "GALLERY_PATHS": str(self.other)}
            status = gallery.describe_status(only_other)
            self.assertEqual(status["state"], "error")
            self.assertIn("nicht freigegeben", status["reason"])

    def test_several_roots(self) -> None:
        with patch.dict(os.environ, {ds.GALLERY_ROOTS_ENV: f"{self.other};{self.allowed}"}):
            self.assertEqual(len(ds.allowed_gallery_roots()), 2)
            self.assertTrue(ds.is_path_allowed(self.other))
            self.assertEqual(len(ds.list_gallery_images((self.allowed, self.other), recursive=False)), 2)


if __name__ == "__main__":
    unittest.main()
