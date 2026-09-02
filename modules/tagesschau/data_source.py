"""
Tagesschau-Datenabruf, -Parsing und -Caching.
"""

from __future__ import annotations

import re
import threading
import time
from datetime import datetime

from PIL import Image

from app.config import get_int_setting
from app.logger import get_logger
from app.http_client import HTTP_SESSION, download_image, FETCH_RETRY_BACKOFF_SECONDS

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Cache-Konstante
# ---------------------------------------------------------------------------

TAGESSCHAU_API_URL                     = "https://www.tagesschau.de/api2u/homepage/"
DEFAULT_TAGESSCHAU_IDLE_COUNT          = 3
DEFAULT_TAGESSCHAU_IMAGE_CACHE_SECONDS = 1800
MAX_IMAGE_CACHE_ENTRIES                = 20


# ---------------------------------------------------------------------------
# News-Cache
# ---------------------------------------------------------------------------

TAGESSCHAU_NEWS_CACHE: dict = {"fetched_at": 0.0, "last_attempt_at": 0.0, "items": []}
TAGESSCHAU_NEWS_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Bild-Cache (mit Größen-Limit und TOCTOU-Schutz)
# ---------------------------------------------------------------------------

TAGESSCHAU_IMAGE_CACHE: dict[str, dict] = {}
TAGESSCHAU_IMAGE_LOCK = threading.Lock()
_TAGESSCHAU_FETCH_EVENTS: dict[str, threading.Event] = {}
_TAGESSCHAU_FETCH_EVENTS_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Text-Verarbeitung
# ---------------------------------------------------------------------------

def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def normalize_display_text(text: str) -> str:
    normalized_lines = []
    last_was_blank = False
    for raw_line in (text or "").splitlines():
        line = normalize_whitespace(raw_line)
        if line:
            normalized_lines.append(line)
            last_was_blank = False
        elif normalized_lines and not last_was_blank:
            normalized_lines.append("")
            last_was_blank = True
    return "\n".join(normalized_lines).strip()


def strip_html_tags(text: str) -> str:
    text = text or ""
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<(ul|ol)\b[^>]*>\s*<li\b[^>]*>", "\n\n- ", text, flags=re.IGNORECASE)
    text = re.sub(r"<li\b[^>]*>", "\n- ", text, flags=re.IGNORECASE)
    text = re.sub(r"</li\s*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"</?(ul|ol|p|div|h1|h2|h3|h4|h5|h6)\b[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return normalize_display_text(text)


def collect_tagesschau_content_fragments(item: dict) -> list[str]:
    fragments = []
    for entry in (item.get("content") or []):
        if isinstance(entry, dict) and entry.get("type") == "text":
            text_value = strip_html_tags(str(entry.get("value") or ""))
            if len(text_value) >= 40:
                fragments.append(text_value)
    return fragments


def merge_tagesschau_fragments(fragments: list[str], max_length: int = 900) -> str:
    if not fragments:
        return ""
    unique_fragments: list[str] = []
    seen: set[str] = set()
    for fragment in fragments:
        key = fragment.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique_fragments.append(fragment)
        if len("\n\n".join(unique_fragments)) >= max_length:
            break

    summary = ""
    for fragment in unique_fragments:
        if not summary:
            summary = fragment
            continue
        separator = "\n\n" if fragment.startswith("- ") or summary.endswith(":") else " "
        summary = f"{summary}{separator}{fragment}"
    return summary.strip()


def extract_tagesschau_summary(item: dict) -> str:
    summary_text = merge_tagesschau_fragments(collect_tagesschau_content_fragments(item))
    if summary_text:
        return summary_text
    for candidate in [item.get("firstSentence"), item.get("topline")]:
        cleaned = strip_html_tags(str(candidate or ""))
        if cleaned:
            return cleaned
    return ""


def format_tagesschau_timestamp(raw_value: str) -> str:
    if not raw_value:
        return ""
    try:
        return datetime.fromisoformat(raw_value).strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return raw_value.strip()


def select_tagesschau_image_url(item: dict) -> str:
    teaser_image = item.get("teaserImage")
    if not isinstance(teaser_image, dict):
        return ""
    variants = teaser_image.get("imageVariants")
    if not isinstance(variants, dict):
        return ""
    preferred_keys = [
        "16x9-1280", "16x9-960", "16x9-640", "16x9-512", "16x9-384",
        "1x1-840", "1x1-640", "1x1-432", "1x1-256",
    ]
    for key in preferred_keys:
        value = variants.get(key)
        if value:
            return str(value).strip()
    for value in variants.values():
        if value:
            return str(value).strip()
    return ""


def extract_tagesschau_items(payload: dict) -> list[dict]:
    news_items = payload.get("news")
    if not isinstance(news_items, list):
        return []
    items = []
    for item in news_items[:DEFAULT_TAGESSCHAU_IDLE_COUNT]:
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or "").strip()
        if not title:
            continue
        summary = extract_tagesschau_summary(item)
        topline = (item.get("topline") or "").strip()
        published_at = (item.get("date") or "").strip()
        meta_parts = [p for p in [topline, format_tagesschau_timestamp(published_at)] if p]
        items.append({
            "title":       title,
            "summary":     summary,
            "topline":     topline,
            "published_at": published_at,
            "meta":        " | ".join(meta_parts),
            "url":         (item.get("shareURL") or item.get("detailsweb") or item.get("details") or "").strip(),
            "image_url":   select_tagesschau_image_url(item),
            "image_alt":   ((item.get("teaserImage") or {}).get("alttext") or "").strip(),
        })
    return items


# ---------------------------------------------------------------------------
# News-Fetch
# ---------------------------------------------------------------------------

def fetch_tagesschau_news(force_refresh: bool = False) -> list[dict]:
    now = time.time()
    cache_seconds = get_int_setting("TAGESSCHAU_IDLE_CACHE_SECONDS", 900, 60, 86400)
    with TAGESSCHAU_NEWS_LOCK:
        cache_age = now - TAGESSCHAU_NEWS_CACHE["fetched_at"]
        if not force_refresh and TAGESSCHAU_NEWS_CACHE["items"] and cache_age < cache_seconds:
            return list(TAGESSCHAU_NEWS_CACHE["items"])
        # Backoff nach Fehlschlag: nicht im Poll-Takt gegen die API hämmern
        if not force_refresh and now - TAGESSCHAU_NEWS_CACHE["last_attempt_at"] < FETCH_RETRY_BACKOFF_SECONDS:
            return list(TAGESSCHAU_NEWS_CACHE["items"])
        TAGESSCHAU_NEWS_CACHE["last_attempt_at"] = now
    try:
        response = HTTP_SESSION.get(TAGESSCHAU_API_URL, timeout=20)
        response.raise_for_status()
        items = extract_tagesschau_items(response.json())
        with TAGESSCHAU_NEWS_LOCK:
            TAGESSCHAU_NEWS_CACHE["fetched_at"] = now
            TAGESSCHAU_NEWS_CACHE["items"] = items
        return list(items)
    except Exception as exc:
        log.warning(f"fetch_tagesschau_news: {exc} – nächster Versuch in {FETCH_RETRY_BACKOFF_SECONDS}s")
        with TAGESSCHAU_NEWS_LOCK:
            return list(TAGESSCHAU_NEWS_CACHE["items"])


def should_refresh_tagesschau_news() -> bool:
    cache_seconds = get_int_setting("TAGESSCHAU_IDLE_CACHE_SECONDS", 900, 60, 86400)
    now = time.time()
    with TAGESSCHAU_NEWS_LOCK:
        if now - TAGESSCHAU_NEWS_CACHE["last_attempt_at"] < FETCH_RETRY_BACKOFF_SECONDS:
            return False
        return now - TAGESSCHAU_NEWS_CACHE["fetched_at"] >= cache_seconds


# ---------------------------------------------------------------------------
# Bild-Fetch mit Cache (max. MAX_IMAGE_CACHE_ENTRIES Einträge, TOCTOU-sicher)
# ---------------------------------------------------------------------------

def fetch_tagesschau_image(url: str) -> Image.Image | None:
    if not url:
        return None
    now = time.time()

    with TAGESSCHAU_IMAGE_LOCK:
        cached = TAGESSCHAU_IMAGE_CACHE.get(url)
        if cached and now - cached.get("fetched_at", 0.0) < DEFAULT_TAGESSCHAU_IMAGE_CACHE_SECONDS:
            img = cached.get("image")
            return img.copy() if img is not None else None

    # Deduplizierung: nur der erste Thread fetcht, weitere warten auf das Event.
    with _TAGESSCHAU_FETCH_EVENTS_LOCK:
        if url in _TAGESSCHAU_FETCH_EVENTS:
            wait_event = _TAGESSCHAU_FETCH_EVENTS[url]
            should_fetch = False
        else:
            wait_event = threading.Event()
            _TAGESSCHAU_FETCH_EVENTS[url] = wait_event
            should_fetch = True

    if not should_fetch:
        wait_event.wait(timeout=30)
        with TAGESSCHAU_IMAGE_LOCK:
            cached = TAGESSCHAU_IMAGE_CACHE.get(url)
            if cached:
                img = cached.get("image")
                return img.copy() if img is not None else None
        return None

    try:
        image = download_image(url)
        with TAGESSCHAU_IMAGE_LOCK:
            TAGESSCHAU_IMAGE_CACHE[url] = {
                "fetched_at": now,
                "image": image.copy() if image is not None else None,
            }
            # Cache-Größe begrenzen: ältesten Eintrag entfernen
            if len(TAGESSCHAU_IMAGE_CACHE) > MAX_IMAGE_CACHE_ENTRIES:
                oldest = min(TAGESSCHAU_IMAGE_CACHE,
                             key=lambda k: TAGESSCHAU_IMAGE_CACHE[k]["fetched_at"])
                del TAGESSCHAU_IMAGE_CACHE[oldest]
        return image
    finally:
        with _TAGESSCHAU_FETCH_EVENTS_LOCK:
            _TAGESSCHAU_FETCH_EVENTS.pop(url, None)
        wait_event.set()
