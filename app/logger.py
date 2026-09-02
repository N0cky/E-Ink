"""
Zentrales Logging für PlexImageE-Ink.

Verwendung in jedem Modul:
    from app.logger import get_logger
    log = get_logger(__name__)

Log-Dateien liegen in <project_root>/logs/ (tägl. Rotation, 7 Tage).
Format der Dateien: JSON-Lines (eine JSON-Zeile pro Eintrag) – für einfaches
Parsen durch den /api/logs-Endpunkt.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Pfade
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Log-Pfad: per PLEXINK_LOGS_DIR überschreibbar (Docker: /logs)
import os as _os
_logs_env = _os.environ.get("PLEXINK_LOGS_DIR", "").strip()
LOGS_DIR  = Path(_logs_env) if _logs_env else PROJECT_ROOT / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOGS_DIR / "app.jsonl"


# ---------------------------------------------------------------------------
# Formatter
# ---------------------------------------------------------------------------

import re as _re

# Query-Parameter, deren Werte nie im Log landen dürfen (Plex-Token, Steam-Key, …).
_SECRET_PARAM_RE = _re.compile(
    r"([?&](?:X-Plex-Token|key|api_key|apikey|token|access_token|password|secret)=)[^&\s'\"]+",
    _re.IGNORECASE,
)


def redact_secrets(text: str) -> str:
    """Maskiert Secret-Werte in URLs. Wird auf jede Log-Zeile angewendet."""
    if not text:
        return text
    return _SECRET_PARAM_RE.sub(r"\1***", text)


class _JsonLineFormatter(logging.Formatter):
    """Serialisiert jeden Log-Eintrag als einzelne JSON-Zeile (UTF-8)."""

    def format(self, record: logging.LogRecord) -> str:
        msg = record.getMessage()
        if record.exc_info:
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            msg = f"{msg}\n{record.exc_text}"
        msg = redact_secrets(msg)

        # Komponentenname kürzen
        name = record.name
        if name.startswith("plex_ink."):
            name = name[len("plex_ink."):]
        elif name == "plex_ink":
            name = "server"

        return json.dumps({
            "ts":    datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "name":  name,
            "msg":   msg,
        }, ensure_ascii=False)


class _RedactingConsoleFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact_secrets(super().format(record))


_CONSOLE_FMT = _RedactingConsoleFormatter(
    "%(asctime)s  %(levelname)-8s  %(name)-22s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


# ---------------------------------------------------------------------------
# Setup (einmalig beim ersten Import)
# ---------------------------------------------------------------------------

def _setup() -> logging.Logger:
    root = logging.getLogger("plex_ink")
    if root.handlers:
        return root          # bereits initialisiert (z. B. durch Auto-Reload)

    root.setLevel(logging.DEBUG)

    # Datei-Handler: JSON-Lines, täglich rotiert, 7 Tage Aufbewahrung
    fh = logging.handlers.TimedRotatingFileHandler(
        LOG_FILE,
        when="midnight",
        backupCount=7,
        encoding="utf-8",
        utc=False,
    )
    fh.setFormatter(_JsonLineFormatter())
    # Datei auf INFO: DEBUG-Rauschen (Cover-Probing, Cache-Treffer) bläht die
    # JSONL auf und macht /api/logs langsam. Konsole bleibt DEBUG für die Entwicklung.
    fh.setLevel(logging.INFO)
    root.addHandler(fh)

    # Konsolen-Handler: menschenlesbar
    ch = logging.StreamHandler()
    ch.setFormatter(_CONSOLE_FMT)
    ch.setLevel(logging.DEBUG)
    root.addHandler(ch)

    # Flask/Werkzeug-Logs nicht doppelt ausgeben
    logging.getLogger("werkzeug").propagate = False

    return root


_root_logger = _setup()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_logger(name: str) -> logging.Logger:
    """
    Gibt einen benannten Child-Logger zurück.

    Empfohlene Verwendung:
        from app.logger import get_logger
        log = get_logger(__name__)

    Der Modul-Pfad ``app.foo.bar`` wird automatisch zu ``plex_ink.foo.bar``
    umbenannt, damit alle Einträge unter dem ``plex_ink``-Baum landen.
    """
    if name.startswith("app."):
        clean = "plex_ink." + name[4:]
    elif not name.startswith("plex_ink"):
        clean = f"plex_ink.{name}"
    else:
        clean = name
    return logging.getLogger(clean)
