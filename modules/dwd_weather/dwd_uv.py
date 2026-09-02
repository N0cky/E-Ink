"""
DWD UV-Index-Abruf, -Parsing und -Caching.
API: https://opendata.dwd.de/climate_environment/health/alerts/uvi.json

Antwortstruktur (Stand 2026-04):
{
  "name": "UV-Gefahrenindex",
  "content": [
    {"city": "Frankfurt/Main", "forecast": {"today": 4, "tomorrow": 3, "dayafter_to": 3}},
    ...
  ]
}
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from app.logger import get_logger
from app.http_client import HTTP_SESSION, FETCH_RETRY_BACKOFF_SECONDS

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Konstanten
# ---------------------------------------------------------------------------

DWD_UV_API_URL       = "https://opendata.dwd.de/climate_environment/health/alerts/uvi.json"
DWD_UV_CACHE_SECONDS = 6 * 3600   # UV-Daten werden 1–2× täglich aktualisiert
UV_UPDATE_DELAY_SECONDS = 10 * 60


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

_UV_CACHE: dict  = {"fetched_at": 0.0, "last_attempt_at": 0.0, "city": "", "data": None, "next_refresh_at": 0.0}
_UV_LOCK  = threading.Lock()

# Separater Cache nur für die Städteliste (für Autocomplete)
_CITIES_CACHE: dict = {"fetched_at": 0.0, "cities": []}
_CITIES_LOCK  = threading.Lock()


# ---------------------------------------------------------------------------
# UV-Hilfsfunktionen (auch extern verwendbar)
# ---------------------------------------------------------------------------

def uv_level_label(uvi: float | None) -> str:
    """Gibt die Textklasse für einen UV-Index-Wert zurück."""
    if uvi is None:
        return "--"
    v = float(uvi)
    if v <= 2:  return "Gering"
    if v <= 5:  return "Mittel"
    if v <= 7:  return "Hoch"
    if v <= 10: return "Sehr hoch"
    return "Extrem"


def uv_level_color(uvi: float | None) -> tuple[int, int, int]:
    """Gibt die RGB-Farbe für einen UV-Index-Wert zurück."""
    if uvi is None:
        return (140, 145, 155)
    v = float(uvi)
    if v <= 2:  return (55,  180, 55)    # grün  – gering
    if v <= 5:  return (215, 185,  0)    # gelb  – mittel
    if v <= 7:  return (230, 110,  0)    # orange – hoch
    if v <= 10: return (210,  35, 35)    # rot   – sehr hoch
    return (150, 30, 200)               # violett – extrem


# ---------------------------------------------------------------------------
# Interner Payload-Zugriff
# ---------------------------------------------------------------------------

def _extract_content(payload) -> list:
    """
    Gibt die Städte-Liste aus dem API-Payload zurück.
    Erwartet ein dict mit 'content'-Key, toleriert aber auch direkte Listen.
    """
    if isinstance(payload, dict):
        content = payload.get("content")
        if isinstance(content, list):
            return content
    if isinstance(payload, list):
        return payload
    return []


def _find_city_entry(content: list, city_name: str) -> dict | None:
    """Sucht den API-Eintrag für die konfigurierte Stadt (Exakt → Teilstring)."""
    target = city_name.strip().lower()

    # 1. Exakter Treffer
    for entry in content:
        if not isinstance(entry, dict):
            continue
        if entry.get("city", "").strip().lower() == target:
            return entry

    # 2. Teilstring-Treffer (z. B. "Frankfurt" → "Frankfurt/Main")
    for entry in content:
        if not isinstance(entry, dict):
            continue
        name = entry.get("city", "").strip().lower()
        if target in name or name in target:
            return entry

    return None


def _parse_uv_days(entry: dict) -> list[float | None]:
    """
    Gibt [heute, morgen, übermorgen] als UV-Max-Werte zurück.
    Liest aus entry["forecast"]["today"], ["tomorrow"], ["dayafter_to"].
    """
    forecast = entry.get("forecast")
    if not isinstance(forecast, dict):
        return []

    def _f(key: str) -> float | None:
        v = forecast.get(key)
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    result: list[float | None] = []
    for key in ("today", "tomorrow", "dayafter_to"):
        result.append(_f(key))
    return result   # Index 0 = heute, 1 = morgen, 2 = übermorgen


def _get_local_timezone() -> ZoneInfo:
    from app.config import get_cfg
    return ZoneInfo(get_cfg().timezone or "Europe/Berlin")


def _parse_uv_update_timestamp(raw_value: str | None) -> datetime | None:
    if not raw_value:
        return None
    try:
        return datetime.fromisoformat(str(raw_value).strip()).replace(tzinfo=_get_local_timezone())
    except ValueError:
        return None


def _compute_day_shift(last_update_dt: datetime | None) -> int:
    if last_update_dt is None:
        return 0
    now_local = datetime.now(_get_local_timezone())
    return max(0, min(2, (now_local.date() - last_update_dt.date()).days))


def _shift_forecast_days(values: list[float | None], day_shift: int) -> list[float | None]:
    if day_shift <= 0:
        return list(values)
    shifted = list(values[day_shift:])
    while len(shifted) < 3:
        shifted.append(None)
    return shifted[:3]


def _compute_next_refresh_at(next_update_dt: datetime | None) -> float:
    if next_update_dt is None:
        return 0.0
    return next_update_dt.timestamp() + UV_UPDATE_DELAY_SECONDS


# ---------------------------------------------------------------------------
# Städteliste (für Autocomplete)
# ---------------------------------------------------------------------------

def fetch_uv_city_names() -> list[str]:
    """
    Gibt alle verfügbaren Städtenamen aus der DWD UV-API zurück (gecacht 6 h).
    """
    now = time.time()
    with _CITIES_LOCK:
        if now - _CITIES_CACHE["fetched_at"] < DWD_UV_CACHE_SECONDS:
            return list(_CITIES_CACHE["cities"])

    try:
        response = HTTP_SESSION.get(DWD_UV_API_URL, timeout=20)
        response.raise_for_status()
        payload = response.json()

        content = _extract_content(payload)
        if not content:
            log.warning(f"DWD UV API: keine 'content'-Liste gefunden (Typ: {type(payload).__name__})")
            return []

        cities = sorted({
            e.get("city", "").strip()
            for e in content
            if isinstance(e, dict) and e.get("city", "").strip()
        })

        with _CITIES_LOCK:
            _CITIES_CACHE["fetched_at"] = now
            _CITIES_CACHE["cities"]     = cities
        return cities

    except Exception as exc:
        log.error(f"fetch_uv_city_names: {exc}", exc_info=True)
        with _CITIES_LOCK:
            return list(_CITIES_CACHE["cities"])


# ---------------------------------------------------------------------------
# Fetch + Cache
# ---------------------------------------------------------------------------

def fetch_dwd_uv(force_refresh: bool = False) -> dict | None:
    """
    Gibt ein Dict zurück:
      {
        "city":        "Frankfurt/Main",
        "uvi_by_index": [4.0, 3.0, 3.0],   # Index 0 = heute, 1 = morgen, 2 = übermorgen
      }
    Gibt None zurück wenn keine Stadt konfiguriert oder Daten nicht verfügbar.
    """
    from app.config import get_setting
    city = get_setting("DWD_UV_CITY", "").strip()
    if not city:
        return None

    now = time.time()
    with _UV_LOCK:
        cached = _UV_CACHE["data"]
        if (not force_refresh
                and cached is not None
                and _UV_CACHE["city"] == city
                and now - _UV_CACHE["fetched_at"] < DWD_UV_CACHE_SECONDS
                and not (_UV_CACHE.get("next_refresh_at", 0.0) and now >= _UV_CACHE["next_refresh_at"] and _UV_CACHE["fetched_at"] < _UV_CACHE["next_refresh_at"])):
            return dict(cached)
        # Backoff nach Fehlschlag oder "Stadt nicht gefunden"
        if (not force_refresh
                and _UV_CACHE["city"] == city
                and now - _UV_CACHE["last_attempt_at"] < FETCH_RETRY_BACKOFF_SECONDS):
            return dict(cached) if isinstance(cached, dict) else None
        _UV_CACHE["last_attempt_at"] = now
        _UV_CACHE["city"] = city

    try:
        response = HTTP_SESSION.get(DWD_UV_API_URL, timeout=20)
        response.raise_for_status()
        payload = response.json()

        content = _extract_content(payload)
        if not content:
            log.warning(f"DWD UV API: unerwartetes Antwortformat ({type(payload).__name__})")
            return None

        entry = _find_city_entry(content, city)
        if entry is None:
            sample = [e.get("city", "") for e in content[:8] if isinstance(e, dict)]
            log.warning(f"DWD UV: Stadt '{city}' nicht gefunden. Verfügbare Einträge (Auszug): {sample} – "
                        f"nächster Versuch in {FETCH_RETRY_BACKOFF_SECONDS}s")
            return None

        last_update_dt = _parse_uv_update_timestamp(payload.get("last_update") if isinstance(payload, dict) else None)
        next_update_dt = _parse_uv_update_timestamp(payload.get("next_update") if isinstance(payload, dict) else None)
        day_shift = _compute_day_shift(last_update_dt)
        uvi_list = _shift_forecast_days(_parse_uv_days(entry), day_shift)
        found_city  = entry.get("city", city).strip() or city
        data = {
            "city": found_city,
            "uvi_by_index": uvi_list,
            "last_update": payload.get("last_update") if isinstance(payload, dict) else None,
            "next_update": payload.get("next_update") if isinstance(payload, dict) else None,
            "day_shift": day_shift,
        }

        with _UV_LOCK:
            _UV_CACHE["fetched_at"] = now
            _UV_CACHE["city"]       = city
            _UV_CACHE["data"]       = dict(data)
            _UV_CACHE["next_refresh_at"] = _compute_next_refresh_at(next_update_dt)
        return data

    except Exception as exc:
        log.warning(f"fetch_dwd_uv: {exc} – nächster Versuch in {FETCH_RETRY_BACKOFF_SECONDS}s")
        with _UV_LOCK:
            cached = _UV_CACHE["data"]
            return dict(cached) if isinstance(cached, dict) else None


def should_refresh_dwd_uv() -> bool:
    from app.config import get_setting
    city = get_setting("DWD_UV_CITY", "").strip()
    if not city:
        return False

    now = time.time()
    with _UV_LOCK:
        cached = _UV_CACHE
        if cached["city"] == city and now - cached["last_attempt_at"] < FETCH_RETRY_BACKOFF_SECONDS:
            return False
        if cached["data"] is None or cached["city"] != city:
            return True
        next_refresh_at = cached.get("next_refresh_at", 0.0)
        return (
            (now - cached["fetched_at"]) >= DWD_UV_CACHE_SECONDS
            or (next_refresh_at and now >= next_refresh_at and cached["fetched_at"] < next_refresh_at)
        )
