"""
Wächter: Die Suite muss gegen die Temp-Kopie der Konfiguration laufen, nie gegen
die echte config/settings.env. Das stellt tests/__init__.py sicher – aber nur,
wenn `tests` als Paket importiert wird:

    python -m unittest discover -s tests -t .

Ohne `-t .` wird das Paket übersprungen, Tests lesen (und schreiben!) dann die
Entwickler-Konfiguration, und Validierungstests scheitern rätselhaft mit 200 != 400.
Dieser Test macht daraus eine klare Meldung.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

HINT = "Testsuite bitte mit `python -m unittest discover -s tests -t .` starten (siehe CONTRIBUTING.md)."


class IsolationTest(unittest.TestCase):
    def test_config_file_is_a_temp_copy(self) -> None:
        config_file = os.environ.get("INKWALL_CONFIG_FILE", "")
        self.assertTrue(config_file, "INKWALL_CONFIG_FILE ist nicht gesetzt – tests/__init__.py lief nicht. " + HINT)
        tmp_root = Path(tempfile.gettempdir()).resolve()
        self.assertTrue(
            Path(config_file).resolve().is_relative_to(tmp_root),
            f"INKWALL_CONFIG_FILE zeigt nicht ins Temp-Verzeichnis: {config_file}. " + HINT,
        )

    def test_runtime_config_was_built_from_the_temp_copy(self) -> None:
        import app.config as config

        used = Path(config.resolve_env_file_path()).resolve()
        expected = Path(os.environ.get("INKWALL_CONFIG_FILE", "")).resolve()
        self.assertEqual(used, expected, "Die Laufzeitkonfiguration liest eine andere Datei als die Temp-Kopie. " + HINT)
        # Die Beispiel-Konfiguration hat keine Zugangsdaten – die echte Datei sehr wahrscheinlich schon
        values = config.get_settings_values()
        for key in ("PLEX_TOKEN", "STEAM_API_KEY", "GALLERY_PATHS"):
            # Der Wert selbst darf nicht in der Meldung landen (Zugangsdaten)
            self.assertTrue(not values.get(key, ""), f"{key} ist gesetzt – die Tests laufen gegen die echte settings.env. " + HINT)
