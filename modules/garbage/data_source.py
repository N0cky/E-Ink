"""
Müllabfuhr-Datenquelle: liest einen oder mehrere ICS-Kalender (wie sie fast
jede Kommune anbietet), filtert die nächsten Abfuhrtermine und ordnet jeder
Tonne eine Farbe zu.

Kein externes ICS-Paket: Abfuhrkalender sind flache VEVENT-Listen ohne
Wiederholungsregeln, ein kleiner Parser reicht und hält die Abhängigkeiten klein.
"""

from __future__ import annotations

import re
import threading
import time
from datetime import date, timedelta

from app.config import get_int_setting, get_setting, now_local
from app.http_client import HTTP_SESSION, FETCH_RETRY_BACKOFF_SECONDS
from app.logger import get_logger

log = get_logger(__name__)

DEFAULT_CACHE_SECONDS = 6 * 3600
DEFAULT_DAYS_AHEAD = 14
LOOKAHEAD_NEXT_YEAR_DAYS = 45      # so früh vor Jahresende auch den Folgejahres-Kalender laden
YEAR_PLACEHOLDER = "{year}"

# Stichwort (kleingeschrieben, Teilstring) → Farbschlüssel. Reihenfolge zählt:
# spezifische Begriffe vor allgemeinen ("restmüll" vor "müll").
DEFAULT_TYPE_COLORS: tuple[tuple[str, str], ...] = (
    ("restmüll",   "black"),
    ("restmuell",  "black"),
    ("restabfall", "black"),
    ("hausmüll",   "black"),
    ("bio",        "green"),
    ("grün",       "green"),
    ("gruen",      "green"),
    ("garten",     "green"),
    ("gelb",       "yellow"),
    ("wertstoff",  "yellow"),
    ("verpack",    "yellow"),
    ("leichtverp", "yellow"),
    ("papier",     "blue"),
    ("pappe",      "blue"),
    ("karton",     "blue"),
    ("glas",       "green"),
    ("sperr",      "red"),
    ("schadstoff", "red"),
    ("problem",    "red"),
    ("weihnacht",  "green"),
    ("tannenbaum", "green"),
)
VALID_COLORS = ("black", "green", "yellow", "blue", "red")

_CACHE: dict[str, dict] = {}     # url → {"fetched_at", "last_attempt_at", "events"}
_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Settings-Parsing
# ---------------------------------------------------------------------------

def parse_sources(raw: str) -> list[tuple[str, str]]:
    """
    'Label|URL; Label2|URL2' oder nur 'URL'. Trenner: Semikolon oder Zeilenumbruch.
    Gibt [(label, url), …] zurück. Label darf leer sein.
    """
    sources: list[tuple[str, str]] = []
    for chunk in re.split(r"[;\n]+", raw or ""):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "|" in chunk:
            label, url = chunk.split("|", 1)
            label, url = label.strip(), url.strip()
        else:
            label, url = "", chunk
        if url.lower().startswith(("http://", "https://")):
            sources.append((label, url))
    return sources


def parse_type_overrides(raw: str) -> list[tuple[str, str]]:
    """'restmüll=black, bio=green' → [(stichwort, farbe), …]. Unbekannte Farben werden ignoriert."""
    overrides: list[tuple[str, str]] = []
    for chunk in (raw or "").split(","):
        if "=" not in chunk:
            continue
        keyword, color = chunk.split("=", 1)
        keyword, color = keyword.strip().lower(), color.strip().lower()
        if keyword and color in VALID_COLORS:
            overrides.append((keyword, color))
    return overrides


def expand_year(url: str, year: int) -> str:
    return url.replace(YEAR_PLACEHOLDER, str(year))


def classify_type(summary: str, overrides: list[tuple[str, str]] | None = None) -> str:
    text = (summary or "").lower()
    for keyword, color in (overrides or []):
        if keyword in text:
            return color
    for keyword, color in DEFAULT_TYPE_COLORS:
        if keyword in text:
            return color
    return "black"


# ---------------------------------------------------------------------------
# ICS-Parser (RFC 5545, nur was Abfuhrkalender brauchen)
# ---------------------------------------------------------------------------

def unfold_ics_lines(text: str) -> list[str]:
    """Fortsetzungszeilen (beginnen mit Leerzeichen/Tab) an die Vorzeile hängen."""
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


_DATE_RE = re.compile(r"(\d{4})(\d{2})(\d{2})")


def _parse_ics_date(value: str) -> date | None:
    match = _DATE_RE.match((value or "").strip())
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _unescape(value: str) -> str:
    return (value or "").replace("\\n", " ").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\").strip()


def parse_ics_events(text: str) -> list[dict]:
    """Gibt [{'date': date, 'summary': str, 'description': str, 'uid': str}, …] zurück."""
    events: list[dict] = []
    current: dict | None = None
    for line in unfold_ics_lines(text):
        if line == "BEGIN:VEVENT":
            current = {}
            continue
        if line == "END:VEVENT":
            if current is not None and current.get("date") and current.get("summary"):
                events.append(current)
            current = None
            continue
        if current is None or ":" not in line:
            continue
        name_part, value = line.split(":", 1)
        name = name_part.split(";", 1)[0].upper()
        if name == "DTSTART":
            current["date"] = _parse_ics_date(value)
        elif name == "SUMMARY":
            current["summary"] = _unescape(value)
        elif name == "DESCRIPTION":
            current["description"] = _unescape(value)
        elif name == "UID":
            current["uid"] = value.strip()
    return events


# ---------------------------------------------------------------------------
# Fetch + Cache pro URL
# ---------------------------------------------------------------------------

def fetch_ics_events(url: str, force_refresh: bool = False) -> list[dict] | None:
    """Events einer URL, gecacht. None nur, wenn nie erfolgreich geladen wurde."""
    cache_seconds = get_int_setting("GARBAGE_CACHE_SECONDS", DEFAULT_CACHE_SECONDS, 300, 7 * 86400)
    now = time.time()
    with _LOCK:
        entry = _CACHE.get(url)
        if entry is not None and not force_refresh:
            if entry["events"] is not None and now - entry["fetched_at"] < cache_seconds:
                return list(entry["events"])
            if now - entry["last_attempt_at"] < FETCH_RETRY_BACKOFF_SECONDS:
                return list(entry["events"]) if entry["events"] is not None else None
        _CACHE[url] = {
            "fetched_at": entry["fetched_at"] if entry else 0.0,
            "last_attempt_at": now,
            "events": entry["events"] if entry else None,
        }

    try:
        response = HTTP_SESSION.get(url, timeout=30, headers={"User-Agent": "PlexImageE-Ink/1.0"})
        response.raise_for_status()
        events = parse_ics_events(response.text)
        with _LOCK:
            _CACHE[url] = {"fetched_at": now, "last_attempt_at": now, "events": events}
        log.info(f"Müllkalender geladen: {len(events)} Termine")
        return list(events)
    except Exception as exc:
        log.warning(f"Müllkalender nicht ladbar: {exc} – nächster Versuch in {FETCH_RETRY_BACKOFF_SECONDS}s")
        with _LOCK:
            cached = _CACHE.get(url, {}).get("events")
        return list(cached) if cached is not None else None


def should_refresh_garbage() -> bool:
    cache_seconds = get_int_setting("GARBAGE_CACHE_SECONDS", DEFAULT_CACHE_SECONDS, 300, 7 * 86400)
    now = time.time()
    with _LOCK:
        if not _CACHE:
            return False
        for entry in _CACHE.values():
            if now - entry["last_attempt_at"] < FETCH_RETRY_BACKOFF_SECONDS:
                continue
            if now - entry["fetched_at"] >= cache_seconds:
                return True
    return False


def clear_cache() -> None:
    with _LOCK:
        _CACHE.clear()


# ---------------------------------------------------------------------------
# Inhalt fürs Rendering
# ---------------------------------------------------------------------------

def relative_day_label(days: int) -> str:
    if days <= 0:
        return "Heute"
    if days == 1:
        return "Morgen"
    if days == 2:
        return "Übermorgen"
    return f"In {days} Tagen"


def build_garbage_content(all_events: list[dict], today: date, days_ahead: int,
                          overrides: list[tuple[str, str]] | None = None) -> dict | None:
    """
    Gruppiert Termine nach Tag. 'days' enthält das Fenster [heute, heute+days_ahead];
    'next' ist der nächste Abfuhrtag – notfalls auch jenseits des Fensters (bis 1 Jahr),
    damit das Display nie leer bleibt.
    """
    seen: set[tuple[date, str, str]] = set()
    future: list[dict] = []
    for ev in all_events:
        d = ev.get("date")
        if not isinstance(d, date) or d < today or (d - today).days > 366:
            continue
        key = (d, ev.get("summary", ""), ev.get("label", ""))
        if key in seen:
            continue
        seen.add(key)
        future.append({
            "date": d,
            "in_days": (d - today).days,
            "summary": ev.get("summary", ""),
            "label": ev.get("label", ""),
            "color": classify_type(ev.get("summary", ""), overrides),
        })
    if not future:
        return None

    future.sort(key=lambda e: (e["date"], e["summary"], e["label"]))
    by_day: dict[date, list[dict]] = {}
    for ev in future:
        by_day.setdefault(ev["date"], []).append(ev)
    all_days = [
        {"date": d, "in_days": (d - today).days, "relative": relative_day_label((d - today).days), "events": evs}
        for d, evs in sorted(by_day.items())
    ]
    window = [day for day in all_days if day["in_days"] <= days_ahead]
    return {
        "today": today.isoformat(),
        "days_ahead": days_ahead,
        "days": window,
        "next": all_days[0],
        "next_outside_window": bool(all_days and all_days[0]["in_days"] > days_ahead),
    }


def fetch_garbage_content(force_refresh: bool = False) -> dict | None:
    sources = parse_sources(get_setting("GARBAGE_ICS_URLS", ""))
    if not sources:
        return None
    today = now_local().date()
    days_ahead = get_int_setting("GARBAGE_DAYS_AHEAD", DEFAULT_DAYS_AHEAD, 1, 90)
    overrides = parse_type_overrides(get_setting("GARBAGE_TYPE_COLORS", ""))

    years = [today.year]
    if (date(today.year, 12, 31) - today).days <= LOOKAHEAD_NEXT_YEAR_DAYS:
        years.append(today.year + 1)

    all_events: list[dict] = []
    any_loaded = False
    for label, url in sources:
        # Ohne {year}-Platzhalter gibt es nur eine URL; mit Platzhalter je Jahr eine
        urls = [expand_year(url, y) for y in years] if YEAR_PLACEHOLDER in url else [url]
        for expanded in urls:
            events = fetch_ics_events(expanded, force_refresh)
            if events is None:
                continue
            any_loaded = True
            for ev in events:
                all_events.append({**ev, "label": label})

    if not any_loaded:
        return None
    content = build_garbage_content(all_events, today, days_ahead, overrides)
    if content is not None:
        content["sources"] = [label or "Abfuhrkalender" for label, _ in sources]
    return content
