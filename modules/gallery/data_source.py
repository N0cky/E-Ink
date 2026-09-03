from __future__ import annotations

import os
import random
import time
from pathlib import Path

from app.config import get_cfg, get_int_setting, get_setting
from app.logger import get_logger

log = get_logger(__name__)

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
SCAN_CACHE_SECONDS = 60

# Freigegebene Wurzelordner (Prozess-Umgebung, nicht über die Oberfläche änderbar).
# Gesetzt → Bildordner müssen darunter liegen; leer → keine Einschränkung (Heimnetz).
GALLERY_ROOTS_ENV = "PLEXINK_GALLERY_ROOTS"

_scan_cache: dict[tuple[tuple[str, ...], bool], tuple[float, list[Path]]] = {}
_recent_choice_cache: dict[tuple[int, int, int], int] = {}
_warned_paths: set[str] = set()


def allowed_gallery_roots() -> tuple[Path, ...]:
    """Wurzelordner aus PLEXINK_GALLERY_ROOTS (Semikolon oder Zeilenumbruch, unter Linux auch Doppelpunkt)."""
    raw = os.environ.get(GALLERY_ROOTS_ENV, "").strip()
    if os.name != "nt":
        raw = raw.replace(":", ";")
    roots: list[Path] = []
    for chunk in raw.replace("\n", ";").split(";"):
        chunk = chunk.strip().strip('"')
        if chunk:
            roots.append(Path(chunk).expanduser())
    return tuple(roots)


def _resolved(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path.absolute()


def is_path_allowed(path: Path, roots: tuple[Path, ...] | None = None) -> bool:
    """True, wenn keine Wurzeln gesetzt sind oder der (aufgelöste) Pfad unter einer Wurzel liegt."""
    roots = allowed_gallery_roots() if roots is None else roots
    if not roots:
        return True
    target = _resolved(path)
    for root in roots:
        base = _resolved(root)
        if target == base or target.is_relative_to(base):
            return True
    return False


def parse_gallery_paths(raw_value: str) -> tuple[Path, ...]:
    parts: list[Path] = []
    for chunk in (raw_value or "").replace("\n", ";").split(";"):
        raw = chunk.strip().strip('"')
        if not raw:
            continue
        path = Path(raw).expanduser()
        if path not in parts:
            parts.append(path)
    return tuple(parts)


def list_gallery_images(paths: tuple[Path, ...], recursive: bool) -> list[Path]:
    cache_key = (tuple(str(p) for p in paths), recursive)
    now = time.time()
    cached = _scan_cache.get(cache_key)
    if cached and cached[0] > now:
        return list(cached[1])

    roots = allowed_gallery_roots()
    images: list[Path] = []
    for base in paths:
        if not base.exists() or not base.is_dir():
            continue
        if not is_path_allowed(base, roots):
            if str(base) not in _warned_paths:
                _warned_paths.add(str(base))
                log.warning(f"Gallery: Ordner {base} liegt außerhalb von {GALLERY_ROOTS_ENV} und wird übersprungen")
            continue
        iterator = base.rglob("*") if recursive else base.glob("*")
        for path in iterator:
            if path.is_file() and path.suffix.lower() in ALLOWED_EXTENSIONS:
                # Symlinks, die aus den freigegebenen Wurzeln hinausführen, bleiben draußen
                if roots and not is_path_allowed(path, roots):
                    continue
                images.append(path)

    images = sorted(set(images), key=lambda p: str(p).lower())
    _scan_cache[cache_key] = (now + SCAN_CACHE_SECONDS, images)
    return list(images)


def get_gallery_interval_seconds() -> int:
    cfg = get_cfg()
    mode = get_setting("GALLERY_INTERVAL_MODE", "idle_rotation").strip().lower()
    if mode == "custom":
        return get_int_setting("GALLERY_INTERVAL_SECONDS", 300, 30, 86400)
    return cfg.idle_module_rotation_seconds


def get_gallery_recent_avoidance_count() -> int:
    return get_int_setting("GALLERY_AVOID_RECENT_COUNT", 5, 0, 50)


def choose_random_index(num_images: int, slot: int, avoid_recent_count: int) -> int:
    cache_key = (num_images, slot, avoid_recent_count)
    cached = _recent_choice_cache.get(cache_key)
    if cached is not None:
        return cached

    if num_images <= 1:
        _recent_choice_cache[cache_key] = 0
        return 0

    effective_avoid = min(max(0, avoid_recent_count), max(0, num_images - 1), slot)
    if effective_avoid <= 0:
        choice = random.Random(slot).randrange(num_images)
        _recent_choice_cache[cache_key] = choice
        return choice

    recent_slots = effective_avoid
    start_slot = max(0, slot - recent_slots)
    start_key = (num_images, start_slot, avoid_recent_count)
    if start_key not in _recent_choice_cache:
        _recent_choice_cache[start_key] = random.Random(start_slot).randrange(num_images)

    for current_slot in range(start_slot + 1, slot + 1):
        current_key = (num_images, current_slot, avoid_recent_count)
        if current_key in _recent_choice_cache:
            continue

        local_recent = min(max(0, avoid_recent_count), max(0, num_images - 1), current_slot)
        recent_indices = {
            _recent_choice_cache[(num_images, prev_slot, avoid_recent_count)]
            for prev_slot in range(current_slot - local_recent, current_slot)
            if (num_images, prev_slot, avoid_recent_count) in _recent_choice_cache
        }
        if len(recent_indices) >= num_images:
            choice = random.Random(current_slot).randrange(num_images)
            _recent_choice_cache[current_key] = choice
            continue

        attempt = 0
        while True:
            candidate = random.Random(f"{current_slot}:{attempt}").randrange(num_images)
            if candidate not in recent_indices:
                _recent_choice_cache[current_key] = candidate
                break
            attempt += 1

    return _recent_choice_cache[cache_key]


def choose_gallery_image(paths: tuple[Path, ...], recursive: bool, order: str) -> dict | None:
    images = list_gallery_images(paths, recursive)
    if not images:
        return None

    interval_seconds = max(1, get_gallery_interval_seconds())
    slot = int(time.time() // interval_seconds)
    normalized_order = (order or "random").strip().lower()
    avoid_recent_count = get_gallery_recent_avoidance_count()

    if normalized_order == "random":
        index = choose_random_index(len(images), slot, avoid_recent_count)
    else:
        index = slot % len(images)

    selected = images[index]
    try:
        stat = selected.stat()
        mtime_ns = getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))
    except OSError:
        mtime_ns = 0

    return {
        "image_path": selected,
        "slot": slot,
        "interval_seconds": interval_seconds,
        "order": normalized_order,
        "avoid_recent_count": avoid_recent_count,
        "total_images": len(images),
        "mtime_ns": mtime_ns,
        "caption_filename": selected.stem,
        "caption_folder": selected.parent.name,
    }
