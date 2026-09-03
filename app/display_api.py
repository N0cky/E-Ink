"""
JSON-Schnittstelle für die Oberfläche.

- Anzeige:   was das Display zeigt, das Programm (Inhalte, Reihenfolge,
             Höhen, Schalter), Live-Inhalte, Nachtplan, Gerät
- Karten:    Felder eines Moduls lesen/schreiben mit Fehlern je Feld
- Prüfen:    eine Quelle einmal abrufen

Alle Schreibzugriffe landen in der bekannten Env-Datei; die Oberfläche
schreibt IDLE_MODULES, DASHBOARD_TILES, *_MODULE_ENABLED usw., damit
handgepflegte Dateien und alte Formulare weiter funktionieren.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.config import (
    SETTINGS_FIELDS as FRAMEWORK_FIELDS,
    SETTINGS_GROUPS as FRAMEWORK_GROUPS,
    get_cfg,
    get_settings_values,
    parse_dashboard_tiles,
)
from app.logger import get_logger
import app.module_registry as _registry

log = get_logger(__name__)

# Framework-Felder, die die Anzeige-Seite verwaltet (nicht mehr als Formularfeld)
DISPLAY_MANAGED_KEYS = {
    "IDLE_MODULES", "IDLE_LAYOUT", "DASHBOARD_TILES", "IDLE_MODULE_ROTATION_SECONDS",
    "NIGHT_MODE_ENABLED", "NIGHT_MODE_START", "NIGHT_MODE_END",
    "NIGHT_MODE_INTERVAL_MINUTES", "NIGHT_MODE_IDLE_BEHAVIOR", "NIGHT_MODE_FIXED_MODULE",
}
DEVICE_KEYS = {"RENDER_WIDTH", "RENDER_HEIGHT", "DISPLAY_ROTATION", "DISPLAY_THEME", "OUTPUT_FORMAT"}


# ---------------------------------------------------------------------------
# Hilfen
# ---------------------------------------------------------------------------

def _is_true(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return str(value).strip().lower() == "true"


def _module_enabled(mod, env: dict[str, str]) -> bool:
    if mod.ENABLED_KEY:
        default = mod.is_enabled({**env, mod.ENABLED_KEY: "true"}) and _is_true(env.get(mod.ENABLED_KEY), True)
        return _is_true(env.get(mod.ENABLED_KEY), default)
    idle = {x.strip() for x in env.get("IDLE_MODULES", "").split(",") if x.strip()}
    return mod.MODULE_ID in idle


def _safe(callable_, default):
    try:
        return callable_()
    except Exception as exc:
        log.warning(f"display_api: {exc}")
        return default


def _module_entry(mod, env: dict[str, str], active_module_id: str, heights: dict[str, int]) -> dict[str, Any]:
    status = _safe(lambda: mod.describe_status(env), {"state": "ready", "reason": ""})
    return {
        "id":             mod.MODULE_ID,
        "name":           mod.MODULE_NAME,
        "description":    mod.MODULE_DESCRIPTION,
        "kind":           "live" if mod.MODULE_PRIORITY < 10 else "content",
        "enabled":        _module_enabled(mod, env),
        "status":         {"state": status.get("state", "ready"), "reason": status.get("reason", "")},
        "summary":        _safe(lambda: mod.summarize(env), ""),
        "tile_supported": mod.supports_tile(),
        "height":         heights.get(mod.MODULE_ID),
        "active_now":     mod.MODULE_ID == active_module_id,
    }


# ---------------------------------------------------------------------------
# Anzeige
# ---------------------------------------------------------------------------

def build_display_state(esp32_state: dict, last_ack: dict, next_wake: tuple[int, str]) -> dict[str, Any]:
    env = get_settings_values()
    cfg = get_cfg()
    tiles = dict(cfg.dashboard_tiles)
    order = [mid for mid, _ in cfg.dashboard_tiles]
    active_id = str(esp32_state.get("media_type", ""))

    content_mods = _registry.get_idle_modules()
    live_mods = _registry.get_priority_modules()
    # Reihenfolge: erst wie in DASHBOARD_TILES, dann der Rest nach Priorität
    ordered = [m for mid in order for m in content_mods if m.MODULE_ID == mid]
    ordered += [m for m in content_mods if m not in ordered]

    active_mod = _registry.get_module_by_id(active_id)
    if active_id == "dashboard":
        active_name = "Dashboard"
    elif active_mod is not None:
        active_name = active_mod.MODULE_NAME
    elif active_id in ("none", "idle", ""):
        active_name = "Kein Inhalt"
    else:
        active_name = active_id

    ack_at = last_ack.get("ack_at", "")
    seconds_since_ack = None
    if ack_at:
        try:
            ack_dt = datetime.strptime(ack_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            seconds_since_ack = int((datetime.now(timezone.utc) - ack_dt).total_seconds())
        except ValueError:
            seconds_since_ack = None

    night_fixed = _registry.get_module_by_id(cfg.night_mode_fixed_module_id)
    return {
        "layout":           cfg.idle_layout,
        "rotation_seconds": cfg.idle_module_rotation_seconds,
        "theme":            cfg.display_theme,
        "night": {
            "enabled":          cfg.night_mode_enabled,
            "start":            cfg.night_mode_start,
            "end":              cfg.night_mode_end,
            "interval_minutes": cfg.night_mode_interval_minutes,
            "behavior":         cfg.night_mode_idle_behavior,
            "fixed_module":     cfg.night_mode_fixed_module_id,
            "fixed_module_name": night_fixed.MODULE_NAME if night_fixed else "",
        },
        "current": {
            "module_id":   active_id,
            "module_name": active_name,
            "rendered_at": esp32_state.get("rendered_at", ""),
            "hash":        esp32_state.get("hash", ""),
            "state":       esp32_state.get("state", ""),
            "format":      esp32_state.get("format", ""),
        },
        "next": {"seconds": int(next_wake[0]), "reason": str(next_wake[1])},
        "device": {
            "device_id":        last_ack.get("device_id", ""),
            "ack_at":           ack_at,
            "remote":           last_ack.get("remote", ""),
            "seconds_since_ack": seconds_since_ack,
            "hash_matches":     bool(ack_at) and last_ack.get("hash") == esp32_state.get("hash"),
        },
        "content": [_module_entry(m, env, active_id, tiles) for m in ordered],
        "live":    [_module_entry(m, env, active_id, tiles) for m in live_mods],
    }


def display_updates_from_payload(payload: dict) -> dict[str, str]:
    """
    Übersetzt die Anzeige-Änderung in Settings-Keys. Fehlende Teile bleiben
    unverändert (es werden nur Keys geliefert, die im Payload vorkommen).
    """
    updates: dict[str, str] = {}
    known = {m.MODULE_ID: m for m in _registry.get_modules()}

    if "layout" in payload:
        layout = str(payload["layout"]).strip().lower()
        updates["IDLE_LAYOUT"] = layout if layout in {"rotation", "dashboard"} else "rotation"
    if "rotation_seconds" in payload:
        updates["IDLE_MODULE_ROTATION_SECONDS"] = str(payload["rotation_seconds"]).strip()

    if isinstance(payload.get("content"), list):
        enabled_ids: list[str] = []
        tiles: list[str] = []
        for item in payload["content"]:
            mid = str(item.get("id", "")).strip()
            mod = known.get(mid)
            if mod is None or mod.MODULE_PRIORITY < 10:
                continue
            if item.get("enabled"):
                enabled_ids.append(mid)
                height = item.get("height")
                try:
                    pct = int(height) if height not in (None, "", "auto") else 0
                except (TypeError, ValueError):
                    pct = 0
                tiles.append(f"{mid}:{pct}" if pct > 0 else mid)
        updates["IDLE_MODULES"] = ",".join(enabled_ids)
        updates["DASHBOARD_TILES"] = ", ".join(tiles)

    if isinstance(payload.get("live"), list):
        for item in payload["live"]:
            mod = known.get(str(item.get("id", "")).strip())
            if mod is not None and mod.ENABLED_KEY:
                updates[mod.ENABLED_KEY] = "true" if item.get("enabled") else "false"

    night = payload.get("night")
    if isinstance(night, dict):
        mapping = {
            "enabled": "NIGHT_MODE_ENABLED", "start": "NIGHT_MODE_START", "end": "NIGHT_MODE_END",
            "interval_minutes": "NIGHT_MODE_INTERVAL_MINUTES", "behavior": "NIGHT_MODE_IDLE_BEHAVIOR",
            "fixed_module": "NIGHT_MODE_FIXED_MODULE",
        }
        for key, env_key in mapping.items():
            if key in night:
                value = night[key]
                updates[env_key] = ("true" if value else "false") if isinstance(value, bool) else str(value).strip()
    return updates


# ---------------------------------------------------------------------------
# Karten (Modul-Einstellungen)
# ---------------------------------------------------------------------------

def _field_view(field: dict, values: dict[str, str]) -> dict[str, Any]:
    name = field["name"]
    raw = values.get(name)
    if raw in (None, ""):
        raw = field.get("default", "")
    view = {
        "name":        name,
        "label":       field.get("label", name),
        "type":        field.get("type", "text"),
        "help":        field.get("help", ""),
        "placeholder": field.get("placeholder", ""),
        "wide":        bool(field.get("wide", False)),
        "options":     [list(o) if isinstance(o, (list, tuple)) else [o, o] for o in field.get("options", [])],
        "show_when":   field.get("show_when"),
        "link_href":   field.get("link_href", ""),
        "link_label":  field.get("link_label", ""),
        "min":         field.get("min"),
        "max":         field.get("max"),
        "managed_by_display": name in DISPLAY_MANAGED_KEYS,
    }
    if field.get("type") == "password":
        view["value"] = ""
        view["is_set"] = bool(values.get(name, "").strip())
    elif field.get("type") in ("checkbox_group", "priority_list"):
        view["value"] = [x.strip() for x in str(raw).split(",") if x.strip()]
    else:
        view["value"] = str(raw)
    return view


def _fields_for(module_id: str) -> tuple[list[dict], list[dict], Any]:
    if module_id == "framework":
        return list(FRAMEWORK_FIELDS), list(FRAMEWORK_GROUPS), None
    mod = _registry.get_module_by_id(module_id)
    if mod is None:
        raise LookupError(module_id)
    return list(mod.SETTINGS_FIELDS), list(mod.SETTINGS_GROUPS), mod


def build_module_settings(module_id: str) -> dict[str, Any]:
    fields, groups, mod = _fields_for(module_id)
    values = get_settings_values()
    env = values
    payload: dict[str, Any] = {
        "id":     module_id,
        "name":   mod.MODULE_NAME if mod else "Gerät & System",
        "fields": [_field_view(f, values) for f in fields],
        "groups": [{"title": g.get("title", ""), "desc": g.get("desc", ""), "fields": list(g.get("fields", []))} for g in groups],
    }
    if mod is not None:
        payload["status"]  = _safe(lambda: mod.describe_status(env), {"state": "ready", "reason": ""})
        payload["summary"] = _safe(lambda: mod.summarize(env), "")
        payload["enabled"] = _module_enabled(mod, env)
        payload["kind"]    = "live" if mod.MODULE_PRIORITY < 10 else "content"
    return payload


def module_updates_from_values(module_id: str, incoming: dict) -> dict[str, str]:
    """Formwerte → Settings-Keys. Leere Passwörter behalten den gespeicherten Wert."""
    fields, _, _ = _fields_for(module_id)
    current = get_settings_values()
    updates: dict[str, str] = {}
    for field in fields:
        name = field["name"]
        if name not in incoming:
            continue
        value = incoming[name]
        if field.get("type") == "password":
            text = str(value or "").strip()
            updates[name] = text if text else current.get(name, "")
        elif field.get("type") in ("checkbox_group", "priority_list"):
            if isinstance(value, (list, tuple)):
                updates[name] = ",".join(str(v).strip() for v in value if str(v).strip())
            else:
                updates[name] = str(value or "").strip()
        elif isinstance(value, bool):
            updates[name] = "true" if value else "false"
        else:
            updates[name] = str(value if value is not None else "").strip()
    return updates


def map_errors_to_fields(errors: list[str], fields: list[dict]) -> dict[str, Any]:
    """'Label: Nachricht' → {"fields": {name: Nachricht}, "general": [...]}."""
    by_label = {str(f.get("label", "")).strip(): f["name"] for f in fields if f.get("label")}
    result: dict[str, Any] = {"fields": {}, "general": []}
    for error in errors:
        label, sep, message = error.partition(":")
        name = by_label.get(label.strip()) if sep else None
        if name and name not in result["fields"]:
            result["fields"][name] = message.strip()
        else:
            result["general"].append(error)
    return result


def probe_module(module_id: str) -> dict[str, Any]:
    mod = _registry.get_module_by_id(module_id)
    if mod is None:
        raise LookupError(module_id)
    result = _safe(lambda: mod.probe(get_settings_values()), {"ok": False, "message": "Prüfung fehlgeschlagen"})
    return {"ok": bool(result.get("ok")), "message": str(result.get("message", ""))}
