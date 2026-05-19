"""
PlexImageE-Ink Webservice – Framework-Orchestrator.

Bindet Module-Registry, Config, Bild-Rendering und Flask-Routes zusammen.
Module werden beim Start automatisch aus dem modules/-Verzeichnis geladen.
"""

from __future__ import annotations

import copy
import hashlib
import json as _json
import time
import threading
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import Flask, redirect, render_template, request, send_file, jsonify, url_for
from PIL import Image, ImageDraw

from app.logger import get_logger, LOGS_DIR

log = get_logger(__name__)

# ── Framework-Module ─────────────────────────────────────────────────────────
from app.config import (
    get_cfg,
    PROJECT_DIR,
    CURRENT_IMAGE_PATH,
    CURRENT_BMP_PATH,
    STATE_PATH,
    SETTINGS_FIELDS        as FRAMEWORK_SETTINGS_FIELDS,
    SETTINGS_GROUPS        as FRAMEWORK_SETTINGS_GROUPS,
    apply_runtime_config,
    collect_settings_form_data,
    get_settings_values,
    get_settings_runtime_summary,
    validate_settings,
    write_env_settings,
    should_flip_output,
)
from app.image_rendering import convert_to_spectra6
import app.module_registry as _registry

# ── Flask-App ────────────────────────────────────────────────────────────────
app = Flask(__name__, template_folder=str(PROJECT_DIR / "templates"))

# Module beim Import laden (deckt sowohl 'python app/server.py' als auch
# 'flask run' und WSGI-Server ab – reload_modules() ist idempotent)
_registry.reload_modules()


# ---------------------------------------------------------------------------
# ESP32 API – globaler Render-Zustand
# ---------------------------------------------------------------------------

_esp32_state: dict = {
    "hash":        "",
    "format":      "png",
    "state":       "idle",
    "media_type":  "idle",
    "rendered_at": "",
}
_last_ack: dict = {}
_runtime_lock = threading.Lock()
_runtime_started = False
_worker_thread: threading.Thread | None = None


def _get_local_now() -> datetime:
    cfg = get_cfg()
    try:
        tz = ZoneInfo(cfg.timezone)
    except ZoneInfoNotFoundError:
        tz = timezone.utc
    return datetime.now(tz)


def _get_night_mode_state(now_local: datetime | None = None) -> dict[str, int | bool | str]:
    cfg = get_cfg()
    if not cfg.night_mode_enabled or cfg.night_mode_start_minutes == cfg.night_mode_end_minutes:
        return {"active": False, "seconds_until_end": 0, "label": ""}

    now_local = now_local or _get_local_now()
    current_minutes = now_local.hour * 60 + now_local.minute
    start_minutes = cfg.night_mode_start_minutes
    end_minutes = cfg.night_mode_end_minutes

    if start_minutes < end_minutes:
        active = start_minutes <= current_minutes < end_minutes
        end_day_offset = 0
    else:
        active = current_minutes >= start_minutes or current_minutes < end_minutes
        end_day_offset = 1 if current_minutes >= start_minutes else 0

    if not active:
        return {"active": False, "seconds_until_end": 0, "label": f"{cfg.night_mode_start}–{cfg.night_mode_end}"}

    end_time = now_local.replace(
        hour=end_minutes // 60,
        minute=end_minutes % 60,
        second=0,
        microsecond=0,
    )
    if end_day_offset:
        from datetime import timedelta
        end_time = end_time + timedelta(days=1)

    seconds_until_end = max(1, int((end_time - now_local).total_seconds()))
    return {
        "active": True,
        "seconds_until_end": seconds_until_end,
        "label": f"{cfg.night_mode_start}–{cfg.night_mode_end}",
    }


def _apply_night_mode_interval(base_seconds: int, base_reason: str) -> tuple[int, str]:
    cfg = get_cfg()
    night_state = _get_night_mode_state()
    if not night_state["active"]:
        return max(10, int(base_seconds)), base_reason

    effective = max(10, max(int(base_seconds), int(cfg.night_mode_interval_seconds)))
    seconds_until_end = int(night_state["seconds_until_end"])
    if seconds_until_end < effective:
        return max(10, seconds_until_end), f"Nachtmodus endet um {cfg.night_mode_end} – pünktlicher Wechsel in den Tagesmodus"
    return effective, f"Nachtmodus aktiv ({night_state['label']}) – reduziertes Update-Intervall"


def _get_effective_idle_modules(env: dict[str, str]) -> tuple[list, int]:
    cfg = get_cfg()
    enabled_idle = [m for m in _registry.get_idle_modules() if m.is_enabled(env)]
    if not enabled_idle:
        return [], max(cfg.idle_module_rotation_seconds, 1)

    night_state = _get_night_mode_state()
    if not night_state["active"]:
        return enabled_idle, max(cfg.idle_module_rotation_seconds, 1)

    if cfg.night_mode_idle_behavior == "fixed" and cfg.night_mode_fixed_module_id:
        fixed = next((m for m in enabled_idle if m.MODULE_ID == cfg.night_mode_fixed_module_id), None)
        if fixed is not None:
            return [fixed], max(cfg.night_mode_interval_seconds, 1)
        log.warning(
            f"Nachtmodus: festes Modul '{cfg.night_mode_fixed_module_id}' ist nicht aktiv, nutze normale Idle-Rotation"
        )

    return enabled_idle, max(cfg.night_mode_interval_seconds, 1)


def _compute_image_hash() -> str:
    cfg  = get_cfg()
    path = CURRENT_BMP_PATH if cfg.output_format == "bmp" else CURRENT_IMAGE_PATH
    if not path.exists():
        return ""
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_priority_media_type(media_type: str) -> bool:
    mod = _registry.get_module_by_id(media_type)
    return bool(mod is not None and mod.MODULE_PRIORITY < 10)


def _suggest_next_wake(state: str, media_type: str) -> tuple[int, str]:
    cfg = get_cfg()
    if media_type == "plex":
        state_parts = state.split(":")
        player_state = state_parts[2] if len(state_parts) >= 3 else (state_parts[1] if len(state_parts) >= 2 else "unknown")
        if player_state in ("playing", "buffering"):
            return cfg.refresh_interval, f"Plex {player_state} – Refresh-Intervall"
        if player_state == "paused":
            return cfg.refresh_interval * 3, "Plex pausiert – verlangsamter Refresh"
        return cfg.refresh_interval * 5, "Plex unbekannt/inaktiv – konservativer Fallback"

    if state in ("idle", "__no_content__"):
        return _apply_night_mode_interval(cfg.idle_module_rotation_seconds, "Kein aktiver Inhalt – Idle-Rotation")

    mod = _registry.get_module_by_id(media_type)
    if mod is not None:
        env = get_settings_values()
        info = mod.get_next_wake_info(env, state)
        if info is not None:
            seconds = max(10, int(info.get("seconds", cfg.idle_module_rotation_seconds)))
            reason = str(info.get("reason", f"{mod.MODULE_NAME} bestimmt das Wake-Intervall")).strip()
            if mod.MODULE_PRIORITY < 10:
                return seconds, reason
            return _apply_night_mode_interval(seconds, reason)
        custom = mod.get_next_wake_seconds(env, state)
        if custom is not None:
            if mod.MODULE_PRIORITY < 10:
                return max(10, int(custom)), f"{mod.MODULE_NAME} bestimmt das Wake-Intervall"
            return _apply_night_mode_interval(max(10, int(custom)), f"{mod.MODULE_NAME} bestimmt das Wake-Intervall")
        if mod.MODULE_PRIORITY < 10:
            return cfg.refresh_interval, f"{mod.MODULE_NAME} aktiv – Refresh-Intervall"

    return _apply_night_mode_interval(cfg.idle_module_rotation_seconds, "Idle-Modul – Standard-Rotation")


# ---------------------------------------------------------------------------
# Placeholder-Bild (kein Modul aktiv)
# ---------------------------------------------------------------------------

def render_no_content_image() -> Image.Image:
    """Platzhalterbild wenn kein einziges Modul aktiven Inhalt liefert."""
    from app.config import load_font
    cfg = get_cfg()
    w, h = cfg.render_width, cfg.render_height

    if cfg.display_theme == "light":
        bg_col     = (238, 234, 228)
        text_col   = (24, 20, 14)
        muted_col  = (110, 101, 92)
        border_col = (200, 195, 188)
    else:
        bg_col     = (15, 15, 14)
        text_col   = (240, 237, 232)
        muted_col  = (125, 117, 108)
        border_col = (42, 42, 40)

    img  = Image.new("RGB", (w, h), bg_col)
    draw = ImageDraw.Draw(img)

    box_w, box_h = min(680, w - 80), 280
    bx = (w - box_w) // 2
    by = (h - box_h) // 2
    draw.rounded_rectangle((bx, by, bx + box_w, by + box_h),
                            radius=24, outline=border_col, width=1)

    cx        = w // 2
    font_head = load_font(36, True)
    font_sub  = load_font(22, False)
    font_hint = load_font(18, False)

    draw.text((cx, by + 72),  "Keine aktiven Module",
              font=font_head, fill=text_col, anchor="mm")
    draw.text((cx, by + 130), "Aktiviere ein Modul über",
              font=font_sub, fill=muted_col, anchor="mm")
    draw.text((cx, by + 160), "Einstellungen → Idle-Module",
              font=font_sub, fill=muted_col, anchor="mm")
    draw.text((cx, by + 220), "oder aktiviere das Plex-Modul unter Einstellungen → Plex",
              font=font_hint, fill=muted_col, anchor="mm")
    return img


# ---------------------------------------------------------------------------
# Bild speichern + ESP32-State aktualisieren
# ---------------------------------------------------------------------------

def _save_image(image: Image.Image, state_key: str, module_id: str) -> None:
    cfg = get_cfg()

    if should_flip_output(cfg.display_rotation):
        image = image.transpose(Image.Transpose.ROTATE_180)

    if cfg.output_format == "bmp":
        device_img, preview_img = convert_to_spectra6(image)
        device_img.save(str(CURRENT_BMP_PATH), "BMP")
        preview_img.save(str(CURRENT_IMAGE_PATH), "PNG")
    else:
        image.save(str(CURRENT_IMAGE_PATH), "PNG")

    STATE_PATH.write_text(state_key, encoding="utf-8")

    global _esp32_state
    _esp32_state = {
        "hash":        _compute_image_hash(),
        "format":      cfg.output_format,
        "state":       state_key,
        "media_type":  module_id,
        "rendered_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    log.info(
        f"Rendered [{module_id}] state={state_key[:40]} "
        f"theme={cfg.display_theme} fmt={cfg.output_format} "
        f"hash={_esp32_state['hash'][:8]}…"
    )


# ---------------------------------------------------------------------------
# Kern-Rendering-Logik (wird von periodic_worker + /refresh genutzt)
# ---------------------------------------------------------------------------

def render_if_changed(last_state_key: str | None) -> str:
    """
    Iteriert Module in Prioritätsreihenfolge, rendert wenn Inhalt vorhanden
    und der State-Key sich geändert hat (oder should_refresh() True ist).
    Gibt den aktuellen State-Key zurück.
    """
    env = get_settings_values()
    cfg = get_cfg()

    # ── 1. Prioritätsmodule (MODULE_PRIORITY < 10, z. B. Plex) ───────────────
    for mod in _registry.get_priority_modules():
        if not mod.is_enabled(env):
            continue
        try:
            content = mod.fetch_content(env)
        except Exception as exc:
            log.error(f"fetch_content [{mod.MODULE_ID}]: {exc}", exc_info=True)
            continue

        if content is None:
            continue

        state_key = f"{mod.MODULE_ID}:{mod.get_state_key(content)}"
        if state_key != last_state_key or mod.should_refresh(env):
            try:
                image = mod.render(env, content)
                _save_image(image, state_key, mod.MODULE_ID)
            except Exception as exc:
                log.error(f"render [{mod.MODULE_ID}]: {exc}", exc_info=True)
        return state_key

    # ── 2. Idle-Module in Rotation (MODULE_PRIORITY >= 10) ───────────────────
    enabled_idle, rotation_seconds = _get_effective_idle_modules(env)
    if enabled_idle:
        slot = int(time.time() // rotation_seconds)

        for offset in range(len(enabled_idle)):
            mod = enabled_idle[(slot + offset) % len(enabled_idle)]
            try:
                content = mod.fetch_content(env)
            except Exception as exc:
                log.error(f"fetch_content [{mod.MODULE_ID}]: {exc}", exc_info=True)
                continue

            if content is None:
                continue

            state_key = f"{mod.MODULE_ID}:{mod.get_state_key(content)}:{slot}"
            if state_key != last_state_key or mod.should_refresh(env):
                try:
                    image = mod.render(env, content)
                    _save_image(image, state_key, mod.MODULE_ID)
                except Exception as exc:
                    log.error(f"render [{mod.MODULE_ID}]: {exc}", exc_info=True)
            return state_key

    # ── 3. Kein Modul hat Inhalt → Placeholder ───────────────────────────────
    if last_state_key != "__no_content__":
        try:
            _save_image(render_no_content_image(), "__no_content__", "none")
        except Exception as exc:
            log.error(f"render placeholder: {exc}", exc_info=True)
    return "__no_content__"


def render_image() -> str:
    """Erzwingt einen Neu-Render (ignoriert last_state_key). Gibt State-Key zurück."""
    return render_if_changed(object())   # object() != irgendein str → immer neu


def _get_background_poll_seconds() -> int:
    cfg = get_cfg()
    env = get_settings_values()
    candidates = [max(1, int(cfg.refresh_interval))]

    for mod in _registry.get_modules():
        if not mod.is_enabled(env):
            continue
        custom = mod.get_background_poll_seconds(env)
        if custom is not None:
            candidates.append(max(1, int(custom)))

    base_poll = min(candidates)
    if _is_priority_media_type(_esp32_state.get("media_type", "")):
        return base_poll

    night_state = _get_night_mode_state()
    if not night_state["active"]:
        return base_poll

    return min(base_poll, max(1, int(night_state["seconds_until_end"])))


# ---------------------------------------------------------------------------
# Background-Worker
# ---------------------------------------------------------------------------

def periodic_worker() -> None:
    last_state_key: str | None = None

    while True:
        try:
            last_state_key = render_if_changed(last_state_key)
        except Exception as exc:
            log.error(f"periodic_worker: {exc}", exc_info=True)

        time.sleep(_get_background_poll_seconds())


# ---------------------------------------------------------------------------
# Settings-Hilfsfunktionen
# ---------------------------------------------------------------------------

def _build_settings_sections() -> list[dict]:
    """
    Gibt eine geordnete Liste von Section-Dicts zurück:
    [{key, title, eyebrow, desc, fields, groups}, …]
    Framework-Section zuerst, dann alle Module in Prioritätsreihenfolge.
    """
    # Idle-Modul-Optionen für IDLE_MODULES-Checkbox dynamisch befüllen
    idle_opts = [
        (m.MODULE_ID, m.MODULE_NAME)
        for m in _registry.get_idle_modules()
    ]
    framework_fields = []
    for f in FRAMEWORK_SETTINGS_FIELDS:
        field = dict(f)
        if field["name"] == "IDLE_MODULES" and not field.get("options"):
            field = dict(field, options=idle_opts)
        if field["name"] == "NIGHT_MODE_FIXED_MODULE" and not field.get("options"):
            field = dict(field, options=[("", "– Bitte wählen –"), *idle_opts])
        framework_fields.append(field)

    sections = [
        {
            "key":     "framework",
            "title":   "Kern-Einstellungen",
            "eyebrow": "Framework",
            "desc":    (
                "Render-Grundkonfiguration: Bildgröße, Rotation, Theme, Ausgabeformat "
                "und die Verwaltung der Idle-Module."
            ),
            "fields":  framework_fields,
            "groups":  FRAMEWORK_SETTINGS_GROUPS,
        }
    ]

    for mod in _registry.get_modules():
        mod_fields = [dict(f, section=mod.MODULE_ID) for f in mod.SETTINGS_FIELDS]
        sections.append({
            "key":      mod.MODULE_ID,
            "title":    mod.MODULE_NAME,
            "eyebrow":  "Modul" if mod.MODULE_PRIORITY >= 10 else "Prioritätsmodul",
            "desc":     mod.MODULE_DESCRIPTION,
            "fields":   mod_fields,
            "groups":   list(mod.SETTINGS_GROUPS),
            "priority": mod.MODULE_PRIORITY,
        })

    return sections


def _all_fields_from_sections(sections: list[dict]) -> list[dict]:
    """Flache Liste aller Felder aus allen Sections."""
    fields: list[dict] = []
    seen: set[str] = set()
    for sec in sections:
        for f in sec["fields"]:
            if f["name"] not in seen:
                fields.append(f)
                seen.add(f["name"])
    return fields


def _build_runtime_summary() -> dict[str, str]:
    env = get_settings_values()
    summary = dict(get_settings_runtime_summary())
    for mod in _registry.get_modules():
        try:
            summary.update(mod.get_runtime_summary(env))
        except Exception as exc:
            log.warning(f"runtime_summary [{mod.MODULE_ID}]: {exc}")
    return summary


def _build_module_health() -> dict[str, dict]:
    env = get_settings_values()
    health: dict[str, dict] = {}
    for mod in _registry.get_modules():
        try:
            payload = mod.get_health_status(env)
        except Exception as exc:
            log.warning(f"module_health [{mod.MODULE_ID}]: {exc}")
            payload = {"ok": False, "error": str(exc)}
        if payload is not None:
            health[mod.MODULE_ID] = payload
    return health


def _build_effective_settings(updates: dict[str, str]) -> dict[str, str]:
    env = get_settings_values()
    env.update(updates)
    return env


def _validate_all_settings(updates: dict[str, str], all_fields: list[dict]) -> list[str]:
    errors = list(validate_settings(updates, all_fields))
    effective_env = _build_effective_settings(updates)
    for mod in _registry.get_modules():
        try:
            errors.extend(mod.validate_settings(updates, effective_env))
        except Exception as exc:
            log.error(f"validate_settings [{mod.MODULE_ID}]: {exc}", exc_info=True)
            errors.append(f"{mod.MODULE_NAME}: Fehler in der Modul-Validierung.")
    return errors


# ---------------------------------------------------------------------------
# Flask-Routes
# ---------------------------------------------------------------------------

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "modules": _build_module_health()})


@app.route("/logo.png", methods=["GET"])
def logo_png():
    return send_file(str(PROJECT_DIR / "logo.png"), mimetype="image/png", max_age=3600)


@app.route("/favicon.png", methods=["GET"])
def favicon_png():
    return send_file(str(PROJECT_DIR / "logo.png"), mimetype="image/png", max_age=3600)


@app.route("/current.png", methods=["GET"])
def current_png():
    if not CURRENT_IMAGE_PATH.exists():
        try:
            render_image()
        except Exception as exc:
            log.error(f"current_png render: {exc}", exc_info=True)
            return "Bild konnte nicht gerendert werden.", 500
    return send_file(str(CURRENT_IMAGE_PATH), mimetype="image/png", max_age=0)


@app.route("/current.bmp", methods=["GET"])
def current_bmp():
    cfg = get_cfg()
    if cfg.output_format != "bmp":
        return "BMP-Ausgabe ist nicht aktiv. Bitte OUTPUT_FORMAT=bmp setzen.", 404
    if not CURRENT_BMP_PATH.exists():
        try:
            render_image()
        except Exception as exc:
            log.error(f"current_bmp render: {exc}", exc_info=True)
            return "BMP konnte nicht gerendert werden.", 500
    return send_file(str(CURRENT_BMP_PATH), mimetype="image/bmp", max_age=0)


# ── ESP32-Endpunkte ──────────────────────────────────────────────────────────

@app.route("/hash", methods=["GET"])
def image_hash():
    h = _esp32_state.get("hash") or _compute_image_hash()
    return h, 200, {"Content-Type": "text/plain; charset=utf-8"}


@app.route("/meta.json", methods=["GET"])
def meta_json():
    state = _esp32_state.get("state", "idle")
    fmt   = _esp32_state.get("format", get_cfg().output_format)
    media_type = _esp32_state.get("media_type", "idle")
    next_wake_sec, next_wake_reason = _suggest_next_wake(state, media_type)
    return jsonify({
        "hash":          _esp32_state.get("hash", ""),
        "format":        fmt,
        "state":         state,
        "media_type":    media_type,
        "rendered_at":   _esp32_state.get("rendered_at", ""),
        "next_wake_sec": next_wake_sec,
        "next_wake_reason": next_wake_reason,
        "image_url":     f"/current.{fmt}",
    })


@app.route("/ack", methods=["POST"])
def ack():
    global _last_ack
    body = request.get_json(silent=True) or {}
    _last_ack = {
        **body,
        "ack_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "remote": request.remote_addr,
    }
    hash_short = str(body.get("hash", ""))[:8] or "–"
    device     = body.get("device_id", request.remote_addr)
    log.info(f"ACK {device} – hash={hash_short}… | {_last_ack['ack_at']}")
    return jsonify({"ok": True, "ack_at": _last_ack["ack_at"]})


# ── Settings ─────────────────────────────────────────────────────────────────

@app.route("/settings", methods=["GET", "POST"])
def settings_page():
    sections   = _build_settings_sections()
    all_fields = _all_fields_from_sections(sections)

    base_kwargs = dict(
        sections=sections,
        values=get_settings_values(),
        runtime=_build_runtime_summary(),
        modules=_registry.get_module_info_list(),
    )

    if request.method == "POST":
        updates = collect_settings_form_data(request.form, all_fields)
        errors  = _validate_all_settings(updates, all_fields)

        if errors:
            return render_template("settings.html", **base_kwargs, errors=errors, saved=False)

        write_env_settings(updates)
        apply_runtime_config(updates)

        try:
            render_image()
        except Exception as exc:
            log.error(f"settings render: {exc}", exc_info=True)

        return redirect(url_for("settings_page", saved=1))

    return render_template(
        "settings.html",
        **base_kwargs,
        errors=[],
        saved=request.args.get("saved") == "1",
    )


@app.route("/refresh", methods=["GET", "POST"])
def refresh():
    try:
        render_image()
        return jsonify({"ok": True, "message": "refreshed"})
    except Exception as exc:
        log.error(f"refresh: {exc}", exc_info=True)
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/rescan-modules", methods=["POST"])
def api_rescan_modules():
    """Scannt das modules/-Verzeichnis neu ohne Server-Neustart."""
    try:
        modules = _registry.reload_modules()
        log.info(f"Modul-Rescan abgeschlossen: {[m.MODULE_ID for m in modules]}")
        return jsonify({
            "ok":      True,
            "modules": _registry.get_module_info_list(),
            "count":   len(modules),
        })
    except Exception as exc:
        log.error(f"api_rescan_modules: {exc}", exc_info=True)
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/modules", methods=["GET"])
def api_modules():
    """Gibt alle aktuell geladenen Module zurück."""
    return jsonify(_registry.get_module_info_list())


@app.route("/api/module-field-options/<module_id>/<field_name>", methods=["GET"])
def api_module_field_options(module_id: str, field_name: str):
    try:
        options = _registry.get_module_field_options(module_id, field_name, get_settings_values())
        if options is None:
            return jsonify([]), 404
        return jsonify(options)
    except Exception as exc:
        log.error(f"api_module_field_options [{module_id}.{field_name}]: {exc}", exc_info=True)
        return jsonify([]), 500


@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        payload = request.form.get("payload")
        log.info(f"Webhook: {(payload or '')[:300] or '(kein Payload)'}")
        render_image()
        return jsonify({"ok": True})
    except Exception as exc:
        log.error(f"webhook: {exc}", exc_info=True)
        return jsonify({"ok": False, "error": str(exc)}), 500


# ── Dashboard ────────────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def dashboard():
    return render_template("index.html")


# ── Log-Viewer ───────────────────────────────────────────────────────────────

@app.route("/logs", methods=["GET"])
def logs_page():
    return render_template("logs.html")


@app.route("/api/logs", methods=["GET"])
def api_logs():
    level_filter = request.args.get("level", "ALL").upper()
    try:
        limit = min(int(request.args.get("limit", "500")), 5000)
    except ValueError:
        limit = 500
    search = request.args.get("search", "").lower()

    level_order = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "WARN": 30, "ERROR": 40, "CRITICAL": 50}
    min_level   = level_order.get(level_filter, 0) if level_filter != "ALL" else 0

    entries: list[dict] = []
    for lf in sorted(LOGS_DIR.glob("app.jsonl*"), key=lambda f: f.stat().st_mtime):
        try:
            for line in lf.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = _json.loads(line)
                    if level_order.get(entry.get("level", "DEBUG"), 0) < min_level:
                        continue
                    if search and search not in (entry.get("msg") or "").lower() \
                               and search not in (entry.get("name") or "").lower():
                        continue
                    entries.append(entry)
                except _json.JSONDecodeError:
                    pass
        except Exception as exc:
            log.warning(f"api_logs: Fehler beim Lesen von {lf.name}: {exc}")

    return jsonify(entries[-limit:])


@app.route("/api/status", methods=["GET"])
def api_status():
    return jsonify({
        "esp32_state": dict(_esp32_state),
        "last_ack":    dict(_last_ack),
        "modules":     _registry.get_module_info_list(),
        "background_poll_sec": _get_background_poll_seconds(),
        "module_health": _build_module_health(),
    })


@app.route("/api/module-action/<module_id>/<action>", methods=["GET"])
def api_module_action(module_id: str, action: str):
    mod = _registry.get_module_by_id(module_id)
    if mod is None:
        return jsonify({"ok": False, "error": "unknown module"}), 404
    try:
        result = mod.handle_api_action(action, get_settings_values())
        if result is None:
            return jsonify({"ok": False, "error": "unknown action"}), 404
        payload, status = result
        return jsonify(payload), status
    except Exception as exc:
        log.error(f"api_module_action [{module_id}.{action}]: {exc}", exc_info=True)
        return jsonify({"ok": False, "error": str(exc)}), 500


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

def log_startup_config() -> None:
    cfg = get_cfg()
    log.info(f"RENDER_SIZE          = {cfg.render_width}x{cfg.render_height}")
    log.info(f"DISPLAY_ROTATION     = {cfg.display_rotation}")
    log.info(f"DISPLAY_THEME        = {cfg.display_theme}")
    log.info(f"OUTPUT_FORMAT        = {cfg.output_format}")
    log.info(f"REFRESH_INTERVAL     = {cfg.refresh_interval}s")
    log.info(f"IDLE_MODULES         = {', '.join(cfg.idle_module_ids) or 'keine'}")
    log.info(f"IDLE_ROTATION        = {cfg.idle_module_rotation_seconds}s")
    log.info(
        "NIGHT_MODE           = %s",
        (
            f"{cfg.night_mode_start}-{cfg.night_mode_end} / {cfg.night_mode_interval_minutes}min / {cfg.night_mode_idle_behavior}"
            if cfg.night_mode_enabled else "deaktiviert"
        ),
    )
    env = get_settings_values()
    log.info(f"PLEX_BASE_URL        = {env.get('PLEX_BASE_URL', '')}")
    log.info(f"PLEX_TOKEN gesetzt   = {bool(env.get('PLEX_TOKEN', ''))}")
    log.info(f"PLEX_MODULE_ENABLED  = {env.get('PLEX_MODULE_ENABLED', 'true')}")
    log.info(f"SESSION_PRIORITY     = {env.get('SESSION_PRIORITY', 'movie,episode,track')}")
    log.info(f"STEAM_PROFILE        = {env.get('STEAM_PROFILE', '')}")
    log.info(f"STEAM_API_KEY gesetzt= {bool(env.get('STEAM_API_KEY', ''))}")
    log.info(f"STEAM_MODULE_ENABLED = {env.get('STEAM_MODULE_ENABLED', 'true')}")
    log.info(f"DWD_STATION          = {env.get('DWD_WEATHER_STATION_ID', '10532')}")


def ensure_runtime_started() -> None:
    """
    Startet Initial-Render und Background-Worker genau einmal pro Prozess.
    Wichtig für WSGI-Server wie Gunicorn, bei denen __main__ nicht ausgeführt wird.
    """
    global _runtime_started, _worker_thread

    if _runtime_started:
        return

    with _runtime_lock:
        if _runtime_started:
            return

        log.info(f"Module geladen: {[m.MODULE_ID for m in _registry.get_modules()]}")
        log_startup_config()

        if not CURRENT_IMAGE_PATH.exists():
            render_image()

        _worker_thread = threading.Thread(
            target=periodic_worker,
            name="plexink-periodic-worker",
            daemon=True,
        )
        _worker_thread.start()

        _runtime_started = True
        log.info("Runtime initialisiert")


if __name__ == "__main__":
    import os as _os
    _port = int(_os.environ.get("PORT", 8787))

    ensure_runtime_started()
    log.info(f"Server startet auf Port {_port}")
    app.run(host="0.0.0.0", port=_port, debug=False)
