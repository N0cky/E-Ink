"""
Render-Historie: die letzten Bilder, die das Display bekommen hat.

Jedes neue Bild (nicht die „unverändert“-Durchläufe) wird verkleinert als
PNG unter data/output/history/ abgelegt, dazu ein kleiner Index mit
Zeitpunkt, Inhalt und Hash. So lässt sich auf der Anzeige-Seite nachsehen,
was das Display um 7:30 gezeigt hat, und ob die Rotation oder ein Live-Inhalt
etwas Unerwartetes gebracht hat. Die Liste ist bewusst kurz (HISTORY_KEEP),
alte Einträge samt Datei fallen hinten raus.
"""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from app.config import DATA_DIR
from app.logger import get_logger

log = get_logger(__name__)

HISTORY_DIR = DATA_DIR / "history"
HISTORY_INDEX = HISTORY_DIR / "history.json"
HISTORY_KEEP = 24              # so viele Bilder bleiben erhalten
THUMB_MAX_EDGE = 800           # längste Kante der gespeicherten Kopie (px)

_ENTRY_ID = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{8}$")
_lock = threading.Lock()


def _read_index() -> list[dict]:
    try:
        if not HISTORY_INDEX.exists():
            return []
        raw = json.loads(HISTORY_INDEX.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning(f"Render-Historie nicht lesbar: {exc}")
        return []
    return [e for e in raw if isinstance(e, dict) and _ENTRY_ID.match(str(e.get("id", "")))] if isinstance(raw, list) else []


def _write_index(entries: list[dict]) -> None:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    tmp = HISTORY_INDEX.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, HISTORY_INDEX)


def _thumbnail(image: Image.Image) -> Image.Image:
    thumb = image.convert("RGB")
    longest = max(thumb.size)
    if longest > THUMB_MAX_EDGE:
        scale = THUMB_MAX_EDGE / float(longest)
        thumb = thumb.resize((max(1, int(thumb.width * scale)), max(1, int(thumb.height * scale))), Image.LANCZOS)
    return thumb


def record(image: Image.Image, module_id: str, module_name: str, image_hash: str,
           rendered_at: datetime | None = None, keep: int = HISTORY_KEEP) -> dict | None:
    """
    Legt ein Bild in der Historie ab und entfernt die ältesten Einträge.
    Gibt den neuen Eintrag zurück; Fehler brechen das Rendern nie ab.
    """
    when = rendered_at or datetime.now(timezone.utc)
    entry = {
        "id":          f"{when:%Y%m%d-%H%M%S}-{(image_hash or '0' * 8)[:8]}",
        "rendered_at": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "module_id":   module_id,
        "module_name": module_name,
        "hash":        image_hash,
        "width":       image.width,
        "height":      image.height,
    }
    try:
        thumb = _thumbnail(image)
        with _lock:
            HISTORY_DIR.mkdir(parents=True, exist_ok=True)
            path = HISTORY_DIR / f"{entry['id']}.png"
            tmp = path.with_suffix(".png.tmp")
            thumb.save(tmp, "PNG", optimize=True)
            os.replace(tmp, path)
            entries = [e for e in _read_index() if e.get("id") != entry["id"]]
            entries.append(entry)
            entries.sort(key=lambda e: e.get("rendered_at", ""))
            for old in entries[:-max(1, keep)] if len(entries) > keep else []:
                try:
                    (HISTORY_DIR / f"{old['id']}.png").unlink()
                except FileNotFoundError:
                    pass
            entries = entries[-max(1, keep):]
            _write_index(entries)
    except Exception as exc:
        log.warning(f"Render-Historie nicht speicherbar: {exc}")
        return None
    return entry


def list_entries() -> list[dict]:
    """Einträge, neueste zuerst. Einträge ohne Datei werden übersprungen."""
    with _lock:
        entries = _read_index()
    out: list[dict] = []
    for entry in reversed(entries):
        if (HISTORY_DIR / f"{entry['id']}.png").exists():
            out.append({**entry, "url": f"/history/{entry['id']}.png"})
    return out


def image_path(entry_id: str) -> Path | None:
    """Pfad zum gespeicherten Bild, None bei unbekannter oder ungültiger Kennung."""
    if not _ENTRY_ID.match(entry_id or ""):
        return None
    path = HISTORY_DIR / f"{entry_id}.png"
    return path if path.exists() else None


def clear() -> int:
    """Alle Einträge löschen. Gibt die Anzahl entfernter Bilder zurück."""
    with _lock:
        entries = _read_index()
        removed = 0
        for entry in entries:
            try:
                (HISTORY_DIR / f"{entry['id']}.png").unlink()
                removed += 1
            except FileNotFoundError:
                pass
        try:
            _write_index([])
        except Exception as exc:
            log.warning(f"Render-Historie nicht löschbar: {exc}")
    return removed
