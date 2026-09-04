"""
Preis-Historie fürs Tankpreise-Modul.

Tankerkönig liefert nur den aktuellen Stand, deshalb sammelt das Modul bei
jeder Abfrage (alle fünf Minuten) den günstigsten Preis je Kraftstoff unter
den eigenen Stationen:

- Rohwerte der letzten RAW_DAYS Tage (für den Tagesverlauf und den Trend)
- Tagesaggregate dauerhaft: Tiefst-, Höchst-, Durchschnittspreis, Uhrzeit und
  Station des Tiefstpreises (für 7-Tage-, 30-Tage- und Wochentagsstatistik)
- Stundensummen dauerhaft: Durchschnittspreis je Stunde (für das Uhrzeit-Profil)

Alles liegt in einer kleinen JSON-Datei im Datenordner. Die Statistiken sind
bewusst ehrlich: Wochentag- und Stundenprofil gibt es erst ab MIN_STATS_DAYS
Tagen, vorher zeigt das Panel „Statistik ab …“.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import date, datetime, timedelta

from app.config import DATA_DIR
from app.logger import get_logger

log = get_logger(__name__)

HISTORY_FILE = DATA_DIR / "fuel_history.json"
RAW_DAYS = 7                    # Rohwerte so lange behalten
MAX_DAYS = 400                  # Tagesaggregate so lange behalten
MIN_STATS_DAYS = 14             # Wochentag- und Stundenprofil erst ab so vielen Tagen
RECORD_MIN_GAP_SECONDS = 240    # kein zweiter Punkt kurz nach dem letzten
WEEKDAY_WEEKS = 8               # Wochentagsdurchschnitt über so viele Wochen
MORNING_HOUR = 7                # Bezugszeit für den Trendpfeil

_lock = threading.Lock()
_state: dict | None = None


def _empty() -> dict:
    return {"version": 1, "raw": {}, "days": {}, "hours": {}}


def _load() -> dict:
    global _state
    if _state is not None:
        return _state
    try:
        if HISTORY_FILE.exists():
            raw = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("days"), dict):
                raw.setdefault("raw", {})
                raw.setdefault("hours", {})
                _state = raw
                return _state
    except Exception as exc:
        log.warning(f"Tankpreise: Historie nicht lesbar, beginne neu: {exc}")
    _state = _empty()
    return _state


def _save(state: dict) -> None:
    try:
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = HISTORY_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(tmp, HISTORY_FILE)
    except Exception as exc:
        log.warning(f"Tankpreise: Historie nicht speicherbar: {exc}")


def clear(delete_file: bool = False) -> None:
    """Für Tests: Zustand vergessen, optional die Datei löschen."""
    global _state
    with _lock:
        _state = None
        if delete_file:
            try:
                HISTORY_FILE.unlink(missing_ok=True)
            except Exception:
                pass


def _prune(state: dict, now_ts: int) -> None:
    cutoff_raw = now_ts - RAW_DAYS * 86400
    for fuel, points in state["raw"].items():
        state["raw"][fuel] = [p for p in points if p[0] >= cutoff_raw]
    if len(state["days"]) > MAX_DAYS:
        for key in sorted(state["days"])[:-MAX_DAYS]:
            del state["days"][key]


# ---------------------------------------------------------------------------
# Schreiben
# ---------------------------------------------------------------------------

def record(now: datetime, prices: dict[str, tuple[float, str]]) -> bool:
    """
    prices: {kraftstoff: (preis, stationsname)} – der günstigste Preis je Kraftstoff.
    Gibt True zurück, wenn mindestens ein Punkt geschrieben wurde.
    """
    ts = int(now.timestamp())
    day_key = now.strftime("%Y-%m-%d")
    with _lock:
        state = _load()
        written = False
        for fuel, (price, station) in prices.items():
            if price is None or price <= 0:
                continue
            price = round(float(price), 3)
            points = state["raw"].setdefault(fuel, [])
            if points and ts - points[-1][0] < RECORD_MIN_GAP_SECONDS:
                continue
            points.append([ts, price])
            day = state["days"].setdefault(day_key, {}).get(fuel)
            if day is None:
                day = {"min": price, "max": price, "sum": 0.0, "n": 0, "min_at": now.strftime("%H:%M"), "min_station": station}
                state["days"][day_key][fuel] = day
            if price < day["min"]:
                day.update(min=price, min_at=now.strftime("%H:%M"), min_station=station)
            if price > day["max"]:
                day["max"] = price
            day["sum"] = round(day["sum"] + price, 3)
            day["n"] += 1
            hours = state["hours"].setdefault(fuel, [[0.0, 0] for _ in range(24)])
            hours[now.hour][0] = round(hours[now.hour][0] + price, 3)
            hours[now.hour][1] += 1
            written = True
        if written:
            _prune(state, ts)
            _save(state)
        return written


# ---------------------------------------------------------------------------
# Lesen
# ---------------------------------------------------------------------------

def _snapshot() -> dict:
    with _lock:
        return _load()


def day_points(fuel: str, day: date, tz) -> list[tuple[datetime, float]]:
    """Rohwerte eines Tages als (Zeitpunkt, Preis), zeitlich sortiert."""
    out: list[tuple[datetime, float]] = []
    for ts, price in _snapshot()["raw"].get(fuel, []):
        when = datetime.fromtimestamp(ts, tz=tz)
        if when.date() == day:
            out.append((when, float(price)))
    return out


def _day_entry(state: dict, fuel: str, day: date) -> dict | None:
    entry = state["days"].get(day.strftime("%Y-%m-%d"), {}).get(fuel)
    if not entry or not entry.get("n"):
        return None
    return {
        "date": day, "min": float(entry["min"]), "max": float(entry["max"]),
        "avg": round(float(entry["sum"]) / int(entry["n"]), 3), "n": int(entry["n"]),
        "min_at": entry.get("min_at", ""), "min_station": entry.get("min_station", ""),
    }


def last_days(fuel: str, today: date, n: int) -> list[dict]:
    """Die letzten n Tage bis heute; Tage ohne Daten als {"date", "min": None, "avg": None}."""
    state = _snapshot()
    out = []
    for offset in range(n - 1, -1, -1):
        day = today - timedelta(days=offset)
        out.append(_day_entry(state, fuel, day) or {"date": day, "min": None, "max": None, "avg": None, "n": 0, "min_at": "", "min_station": ""})
    return out


def days_collected(fuel: str) -> int:
    state = _snapshot()
    return sum(1 for entries in state["days"].values() if entries.get(fuel, {}).get("n"))


def first_day(fuel: str) -> date | None:
    state = _snapshot()
    keys = sorted(k for k, entries in state["days"].items() if entries.get(fuel, {}).get("n"))
    if not keys:
        return None
    try:
        return date.fromisoformat(keys[0])
    except ValueError:
        return None


def stats_ready(fuel: str) -> bool:
    return days_collected(fuel) >= MIN_STATS_DAYS


def stats_ready_on(fuel: str) -> date | None:
    """Ab welchem Tag das Wochentag- und Stundenprofil belastbar ist (None ohne Daten)."""
    start = first_day(fuel)
    return start + timedelta(days=MIN_STATS_DAYS) if start else None


def weekday_averages(fuel: str, today: date, weeks: int = WEEKDAY_WEEKS) -> list[float | None]:
    """Durchschnitt der Tagesdurchschnitte je Wochentag (Mo..So) über die letzten Wochen."""
    sums = [0.0] * 7
    counts = [0] * 7
    for entry in last_days(fuel, today, weeks * 7):
        if entry["avg"] is None:
            continue
        idx = entry["date"].weekday()
        sums[idx] += entry["avg"]
        counts[idx] += 1
    return [round(sums[i] / counts[i], 3) if counts[i] else None for i in range(7)]


def hour_profile(fuel: str) -> list[float | None]:
    hours = _snapshot()["hours"].get(fuel)
    if not hours:
        return [None] * 24
    return [round(s / n, 3) if n else None for s, n in hours]


def lows(fuel: str, today: date) -> dict:
    """Tiefstpreis der letzten 7 und 30 Tage mit Datum und Station."""
    out: dict[str, dict | None] = {}
    for key, n in (("week", 7), ("month", 30)):
        best = None
        for entry in last_days(fuel, today, n):
            if entry["min"] is None:
                continue
            if best is None or entry["min"] < best["min"]:
                best = entry
        out[key] = best
    return out


def trend(fuel: str, now: datetime) -> dict | None:
    """Aktueller Preis gegenüber dem Morgen (erster Punkt ab MORNING_HOUR, sonst erster des Tages)."""
    points = day_points(fuel, now.date(), now.tzinfo)
    if not points:
        return None
    current = points[-1][1]
    reference = next((p for p in points if p[0].hour >= MORNING_HOUR), points[0])
    if reference is points[-1] and len(points) > 1:
        reference = points[0]
    delta_ct = round((current - reference[1]) * 100, 1)
    return {"now": current, "reference": reference[1], "reference_at": reference[0].strftime("%H:%M"), "delta_ct": delta_ct}


def best_time(fuel: str, today: date) -> dict | None:
    """
    Günstigste Wochentage (alle, die höchstens 0,5 ct über dem Minimum liegen) und
    das günstigste Zwei-Stunden-Fenster aus dem Stundenprofil. None, solange die
    Statistik nicht belastbar ist.
    """
    if not stats_ready(fuel):
        return None
    weekdays = weekday_averages(fuel, today)
    known = [(i, v) for i, v in enumerate(weekdays) if v is not None]
    hours = hour_profile(fuel)
    if len(known) < 3 or sum(1 for h in hours if h is not None) < 6:
        return None
    lowest = min(v for _, v in known)
    cheap_days = [i for i, v in known if v - lowest <= 0.005]
    best_window = None
    for start in range(24):
        pair = [hours[start], hours[(start + 1) % 24]]
        if any(v is None for v in pair):
            continue
        avg = sum(pair) / 2
        if best_window is None or avg < best_window[1]:
            best_window = (start, avg)
    if best_window is None:
        return None
    return {"weekdays": cheap_days, "hour_start": best_window[0], "hour_end": (best_window[0] + 2) % 24,
            "hour_avg": round(best_window[1], 3), "weekday_lowest": round(lowest, 3)}


def build_stats(fuel: str, now: datetime) -> dict:
    """Alles, was der Renderer für Diagramme und Kennzahlen braucht."""
    today = now.date()
    return {
        "fuel": fuel,
        "days_collected": days_collected(fuel),
        "stats_ready": stats_ready(fuel),
        "stats_ready_on": stats_ready_on(fuel),
        "day_points": day_points(fuel, today, now.tzinfo),
        "week": last_days(fuel, today, 7),
        "month": last_days(fuel, today, 30),
        "weekday_avg": weekday_averages(fuel, today),
        "hour_profile": hour_profile(fuel),
        "lows": lows(fuel, today),
        "trend": trend(fuel, now),
        "best_time": best_time(fuel, today),
    }
