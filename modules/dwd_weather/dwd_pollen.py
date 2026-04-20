"""
DWD-Pollenflug-Datenabruf, -Parsing und -Caching.

Endpoint: https://opendata.dwd.de/climate_environment/health/alerts/s31fg.json
Aktualisierung durch DWD: einmal täglich (~11 Uhr).
Cache-TTL: 6 Stunden (weit über dem DWD-Updatezyklus, spart Requests).

Region-Konfiguration: nur die region_id als Zahl, z. B. "100" für Hessen.
Die API enthält pro region_id ggf. mehrere Einträge (Teilregionen); dann wird
der erste passende Eintrag genutzt.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import get_cfg, get_csv_setting, get_setting
from app.logger import get_logger
from app.http_client import HTTP_SESSION

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Konstanten
# ---------------------------------------------------------------------------

DWD_POLLEN_URL = "https://opendata.dwd.de/climate_environment/health/alerts/s31fg.json"

DEFAULT_POLLEN_CACHE_SECONDS: int = 6 * 3600  # 6 h
POLLEN_UPDATE_DELAY_SECONDS: int = 15 * 60

# Roh-String → numerischer Mittelwert 0..3
_LOAD_MAP: dict[str, float] = {
    "0":   0.0,
    "0-1": 0.5,
    "1":   1.0,
    "1-2": 1.5,
    "2":   2.0,
    "2-3": 2.5,
    "3":   3.0,
}

# Alle von der DWD-API gelieferten Allergene (API-Schreibweise)
ALL_ALLERGENS: list[str] = [
    "Birke", "Esche", "Hasel", "Erle",
    "Graeser", "Roggen", "Beifuss", "Ambrosia",
]

# Anzeigenamen für die UI / das Bild
ALLERGEN_LABELS: dict[str, str] = {
    "Birke":    "Birke",
    "Esche":    "Esche",
    "Hasel":    "Hasel",
    "Erle":     "Erle",
    "Graeser":  "Gräser",
    "Roggen":   "Roggen",
    "Beifuss":  "Beifuß",
    "Ambrosia": "Ambrosia",
}

# ---------------------------------------------------------------------------
# Cache (Thread-sicher)
# ---------------------------------------------------------------------------

_POLLEN_CACHE: dict = {"fetched_at": 0.0, "region_key": "", "data": None, "next_refresh_at": 0.0}
_POLLEN_LOCK  = threading.Lock()


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def parse_load(raw: str | None) -> float | None:
    """Wandelt DWD-Laststring ("0", "1-2", …) in Float um. -1 → None."""
    if raw is None:
        return None
    s = str(raw).strip()
    if s == "-1":
        return None
    return _LOAD_MAP.get(s)


def _find_region(content: list, region_id: int) -> dict | None:
    """Findet den ersten API-Eintrag mit der gegebenen region_id."""
    for entry in content:
        if entry.get("region_id") == region_id:
            return entry
    return None


def _get_local_timezone() -> ZoneInfo:
    return ZoneInfo(get_cfg().timezone or "Europe/Berlin")


def _parse_pollen_update_timestamp(raw_value: str | None) -> datetime | None:
    if not raw_value:
        return None
    cleaned = str(raw_value).strip().replace(" Uhr", "")
    try:
        return datetime.strptime(cleaned, "%Y-%m-%d %H:%M").replace(tzinfo=_get_local_timezone())
    except ValueError:
        return None


def _compute_day_shift(last_update_dt: datetime | None) -> int:
    if last_update_dt is None:
        return 0
    now_local = datetime.now(_get_local_timezone())
    return max(0, min(2, (now_local.date() - last_update_dt.date()).days))


def _shift_pollen_days(days: dict[str, float | None], day_shift: int) -> dict[str, float | None]:
    ordered = [days.get("today"), days.get("tomorrow"), days.get("dayafter_to")]
    if day_shift > 0:
        ordered = ordered[day_shift:]
    while len(ordered) < 3:
        ordered.append(None)
    return {
        "today": ordered[0],
        "tomorrow": ordered[1],
        "dayafter_to": ordered[2],
    }


def _compute_next_refresh_at(next_update_dt: datetime | None) -> float:
    if next_update_dt is None:
        return 0.0
    return next_update_dt.timestamp() + POLLEN_UPDATE_DELAY_SECONDS


def _build_summary(entry: dict, selected: tuple[str, ...]) -> dict | None:
    """
    Baut das Pollen-Summary-Dict.
    selected leer → gibt None zurück (keine Anzeige gewünscht).
    """
    if not selected:
        return None                          # leere Auswahl = nichts anzeigen

    pollen_raw = entry.get("Pollen", {})
    allergens: dict[str, dict] = {}
    for allergen in selected:
        raw = pollen_raw.get(allergen)
        if raw is None:
            continue
        allergens[allergen] = {
            "today":       parse_load(raw.get("today")),
            "tomorrow":    parse_load(raw.get("tomorrow")),
            "dayafter_to": parse_load(raw.get("dayafter_to")),
        }
    return {
        "region_name":     entry.get("region_name", ""),
        "partregion_name": entry.get("partregion_name", ""),
        "allergens":       allergens,
    }


# ---------------------------------------------------------------------------
# Öffentliche API
# ---------------------------------------------------------------------------

def fetch_dwd_pollen(force_refresh: bool = False) -> dict | None:
    """
    Liefert Pollen-Zusammenfassung für die konfigurierte Region oder None.

    Gibt None zurück wenn:
    - keine Region konfiguriert
    - keine Allergene ausgewählt
    - Region nicht in API gefunden
    - Netzwerkfehler (sofern kein Cache vorhanden)
    """
    region_key = get_setting("DWD_POLLEN_REGION", "").strip()
    if not region_key:
        return None

    selected_allergens = get_csv_setting("DWD_POLLEN_ALLERGENS")
    if not selected_allergens:
        return None                          # nichts ausgewählt → kein Strip

    # Region-ID parsen – nur die erste Zahl zählt (z. B. "100" oder "100:-1")
    try:
        region_id = int(region_key.split(":")[0])
    except (ValueError, AttributeError):
        log.warning(f"Ungültige Region-Konfiguration: {region_key!r}")
        return None

    with _POLLEN_LOCK:
        now = time.time()
        cached = _POLLEN_CACHE

        if (not force_refresh
                and cached["data"] is not None
                and cached["region_key"] == region_key
                and (now - cached["fetched_at"]) < DEFAULT_POLLEN_CACHE_SECONDS
                and not (cached.get("next_refresh_at", 0.0) and now >= cached["next_refresh_at"] and cached["fetched_at"] < cached["next_refresh_at"])):
            # Cache gültig – aber Allergen-Selektion könnte sich geändert haben,
            # daher nochmal filtern bevor wir zurückgeben.
            return _filter_cached(cached["data"], selected_allergens)

        try:
            resp = HTTP_SESSION.get(DWD_POLLEN_URL, timeout=15)
            resp.raise_for_status()
            js = resp.json()
        except Exception as exc:
            log.error(f"Pollen fetch-Fehler: {exc}", exc_info=True)
            if cached.get("data"):
                return _filter_cached(cached["data"], selected_allergens)
            return None

        content = js.get("content", [])
        entry = _find_region(content, region_id)
        if entry is None:
            log.warning(f"region_id={region_id} nicht in der DWD-API gefunden. "
                  f"Verfügbare IDs: {sorted({e.get('region_id') for e in content})}")
            return None

        last_update_dt = _parse_pollen_update_timestamp(js.get("last_update"))
        next_update_dt = _parse_pollen_update_timestamp(js.get("next_update"))
        day_shift = _compute_day_shift(last_update_dt)

        # Alle Allergen-Daten cachen (ohne Filterung → gilt für alle Allergen-Kombis)
        full_summary = {
            "region_name":     entry.get("region_name", ""),
            "partregion_name": entry.get("partregion_name", ""),
            "allergens_all":   _extract_all_allergens(entry, day_shift),
            "last_update":     js.get("last_update"),
            "next_update":     js.get("next_update"),
            "day_shift":       day_shift,
        }
        _POLLEN_CACHE["fetched_at"] = now
        _POLLEN_CACHE["region_key"] = region_key
        _POLLEN_CACHE["data"]       = full_summary
        _POLLEN_CACHE["next_refresh_at"] = _compute_next_refresh_at(next_update_dt)
        return _filter_cached(full_summary, selected_allergens)


def _extract_all_allergens(entry: dict, day_shift: int = 0) -> dict[str, dict]:
    """Extrahiert alle Allergen-Daten aus einem API-Eintrag (ungefiltert)."""
    pollen_raw = entry.get("Pollen", {})
    result: dict[str, dict] = {}
    for allergen in ALL_ALLERGENS:
        raw = pollen_raw.get(allergen)
        if raw is None:
            continue
        result[allergen] = _shift_pollen_days({
            "today":       parse_load(raw.get("today")),
            "tomorrow":    parse_load(raw.get("tomorrow")),
            "dayafter_to": parse_load(raw.get("dayafter_to")),
        }, day_shift)
    return result


def _filter_cached(full_summary: dict, selected: tuple[str, ...]) -> dict | None:
    """Filtert den Cache auf die aktuell ausgewählten Allergene."""
    if not selected:
        return None
    all_data = full_summary.get("allergens_all", {})
    filtered = {a: v for a, v in all_data.items() if a in selected}
    return {
        "region_name":     full_summary["region_name"],
        "partregion_name": full_summary["partregion_name"],
        "allergens":       filtered,
        "last_update":     full_summary.get("last_update"),
        "next_update":     full_summary.get("next_update"),
        "day_shift":       full_summary.get("day_shift", 0),
    }


def should_refresh_dwd_pollen() -> bool:
    with _POLLEN_LOCK:
        if not get_setting("DWD_POLLEN_REGION", "") or not get_csv_setting("DWD_POLLEN_ALLERGENS"):
            return False
        cached = _POLLEN_CACHE
        if cached["data"] is None:
            return True
        next_refresh_at = cached.get("next_refresh_at", 0.0)
        return (
            (time.time() - cached["fetched_at"]) >= DEFAULT_POLLEN_CACHE_SECONDS
            or (next_refresh_at and time.time() >= next_refresh_at and cached["fetched_at"] < next_refresh_at)
        )
