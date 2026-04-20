"""
Gemeinsamer HTTP-Client für alle PlexImageE-Ink-Module.

HTTP_SESSION  – requests.Session mit Retry-Logik (shared singleton)
download_image – lädt eine Bild-URL und gibt ein PIL-Image zurück

Dieses Modul ist ein reines Framework-Utility und hat keine
Abhängigkeiten zu Modul-spezifischem Code.
"""

from __future__ import annotations

import io

import requests
from PIL import Image
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.logger import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Globale HTTP-Session (wird von allen Modulen geteilt)
# ---------------------------------------------------------------------------

HTTP_SESSION = requests.Session()
_retry = Retry(total=2, backoff_factor=0.5, status_forcelist=[502, 503, 504])
HTTP_SESSION.mount("http://",  HTTPAdapter(max_retries=_retry))
HTTP_SESSION.mount("https://", HTTPAdapter(max_retries=_retry))


# ---------------------------------------------------------------------------
# Bild-Download
# ---------------------------------------------------------------------------

def download_image(url: str | None) -> Image.Image | None:
    """Lädt eine Bild-URL und gibt ein RGB-PIL-Image zurück. None bei Fehler."""
    if not url:
        return None
    try:
        response = HTTP_SESSION.get(url, timeout=20)
        response.raise_for_status()
        return Image.open(io.BytesIO(response.content)).convert("RGB")
    except Exception as exc:
        log.error(f"download_image: {exc}", exc_info=True)
        return None
