"""
Test-Paket. Isoliert die Tests von der lokalen Entwickler-Konfiguration:

- INKWALL_CONFIG_FILE zeigt auf eine Kopie von config/settings.env.example
  in einem Temp-Verzeichnis (nie auf die echte config/settings.env)
- INKWALL_OUTPUT_DIR und INKWALL_LOGS_DIR zeigen ebenfalls ins Temp-Verzeichnis,
  damit Tests weder data/output noch logs/ des Projekts beschreiben

Das muss VOR dem ersten Import von app.config passieren, deshalb hier im
Paket-Init (unittest discover importiert das Paket zuerst).
"""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from pathlib import Path

_PROJECT_DIR = Path(__file__).resolve().parents[1]
_TMP = Path(tempfile.mkdtemp(prefix="inkwall-tests-"))

_config_file = _TMP / "settings.env"
_example = _PROJECT_DIR / "config" / "settings.env.example"
if _example.exists():
    shutil.copy(_example, _config_file)
else:
    _config_file.write_text("", encoding="utf-8")

os.environ["INKWALL_CONFIG_FILE"] = str(_config_file)
os.environ["INKWALL_OUTPUT_DIR"] = str(_TMP / "output")
os.environ["INKWALL_LOGS_DIR"] = str(_TMP / "logs")
os.environ.pop("INKWALL_UI_PASSWORD", None)


def _cleanup() -> None:
    shutil.rmtree(_TMP, ignore_errors=True)


atexit.register(_cleanup)
