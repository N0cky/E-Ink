"""
Dashboard-Modus (IDLE_LAYOUT=dashboard): mehrere Idle-Module teilen sich ein
Bild. Jedes Modul liefert über render_tile() eine Kachel, das Framework setzt
sie untereinander zusammen – mit einer Kopfzeile (Datum, Stand) und Trennlinien.

Vorteil gegenüber der Rotation: weniger Display-Refreshes, alles auf einen Blick.
"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageDraw

from app.config import RuntimeConfig, format_date_long, load_font, now_local
from app.image_rendering import SPECTRA6_COLORS
from app.logger import get_logger
from app.module_base import PlexInkModule

log = get_logger(__name__)

_PALETTES = {
    "dark":  {"bg": (26, 28, 34), "header": (225, 228, 235), "muted": (150, 156, 168), "line": (255, 255, 255, 40)},
    "light": {"bg": (244, 241, 236), "header": (40, 34, 28), "muted": (120, 112, 102), "line": (0, 0, 0, 40)},
    "eink":  {"bg": SPECTRA6_COLORS["white"], "header": SPECTRA6_COLORS["black"],
              "muted": SPECTRA6_COLORS["blue"], "line": (*SPECTRA6_COLORS["black"], 255)},
}


@dataclass
class TileResult:
    module_id: str
    state_key: str
    image: Image.Image | None      # None → Modul hat keine Kachel geliefert


def resolve_tile_layout(tiles: tuple[tuple[str, int], ...], available_ids: list[str]) -> list[tuple[str, int]]:
    """
    Wandelt (modul, prozent)-Angaben in eine Liste mit Prozenten um, die sich zu 100 addieren.
    Fehlt eine Angabe (0), teilen sich diese Module den Rest gleichmäßig. Unbekannte Module
    werden übersprungen. Ohne Konfiguration: alle verfügbaren Module gleich hoch.
    """
    chosen = [(mid, pct) for mid, pct in tiles if mid in available_ids]
    if not chosen:
        chosen = [(mid, 0) for mid in available_ids]
    if not chosen:
        return []
    fixed_total = sum(pct for _, pct in chosen if pct > 0)
    unsized = [mid for mid, pct in chosen if pct <= 0]
    if fixed_total > 100 or (fixed_total == 100 and unsized):
        # Überzeichnet: proportional stauchen, Rest für die unbenannten lassen
        factor = (100 - (10 * len(unsized))) / fixed_total if unsized else 100 / fixed_total
        chosen = [(mid, int(pct * factor) if pct > 0 else 0) for mid, pct in chosen]
        fixed_total = sum(pct for _, pct in chosen if pct > 0)
    remainder = max(0, 100 - fixed_total)
    share = remainder // len(unsized) if unsized else 0
    result = [(mid, pct if pct > 0 else share) for mid, pct in chosen]
    if not unsized and fixed_total < 100:
        # Nur feste Angaben unter 100: Rest der letzten Kachel geben
        mid, pct = result[-1]
        result[-1] = (mid, pct + remainder)
    return [(mid, pct) for mid, pct in result if pct > 0]


def compose_dashboard(env: dict[str, str], cfg: RuntimeConfig, modules: list[PlexInkModule],
                      width: int | None = None, height: int | None = None) -> tuple[Image.Image, str] | None:
    """
    Rendert das Dashboard. modules: aktive Idle-Module in Reihenfolge der
    Kachel-Konfiguration. Rückgabe (Bild, State-Key) oder None, wenn keine
    einzige Kachel Inhalt hat.
    """
    width = width or cfg.render_width
    height = height or cfg.render_height
    theme = cfg.display_theme
    pal = _PALETTES.get(theme, _PALETTES["dark"])
    flat = theme == "eink"
    scale = max(0.5, min(width / 1200.0, 1.4))

    layout = resolve_tile_layout(cfg.dashboard_tiles, [m.MODULE_ID for m in modules])
    by_id = {m.MODULE_ID: m for m in modules}
    if not layout:
        return None

    header_h = int(64 * scale)
    gap = int(8 * scale)
    margin = int(24 * scale)
    usable_h = height - header_h - gap * (len(layout) - 1)

    tiles: list[TileResult] = []
    for module_id, pct in layout:
        mod = by_id[module_id]
        tile_h = max(1, int(usable_h * pct / 100))
        try:
            content = mod.fetch_content(env)
        except Exception as exc:
            log.error(f"dashboard fetch [{module_id}]: {exc}", exc_info=True)
            content = None
        if content is None:
            tiles.append(TileResult(module_id, f"{module_id}=none", _empty_tile(mod, width, tile_h, pal, flat, scale)))
            continue
        try:
            image = mod.render_tile(env, content, width, tile_h)
        except Exception as exc:
            log.error(f"dashboard tile [{module_id}]: {exc}", exc_info=True)
            image = None
        if image is None:
            log.warning(f"Dashboard: Modul '{module_id}' liefert keine Kachel – übersprungen")
            continue
        if image.size != (width, tile_h):
            image = image.resize((width, tile_h))
        tiles.append(TileResult(module_id, f"{module_id}={mod.get_state_key(content)}", image.convert("RGB")))

    if not tiles or all(t.state_key.endswith("=none") for t in tiles):
        return None

    canvas = Image.new("RGB", (width, height), pal["bg"])
    draw = ImageDraw.Draw(canvas, "RGBA")

    # Kopfzeile: Datum links, Stand rechts
    now = now_local()
    font_date = load_font(int(30 * scale), True)
    font_stand = load_font(int(22 * scale), False)
    draw.text((margin, int(16 * scale)), format_date_long(now), font=font_date, fill=pal["header"])
    stand = f"Stand {now.strftime('%H:%M')}"
    sw = draw.textlength(stand, font=font_stand)
    draw.text((width - margin - sw, int(22 * scale)), stand, font=font_stand, fill=pal["muted"])

    y = header_h
    for index, tile in enumerate(tiles):
        if tile.image is None:
            continue
        if index > 0:
            line_y = y - gap // 2
            draw.line([(margin, line_y), (width - margin, line_y)], fill=pal["line"], width=3 if flat else 1)
        canvas.paste(tile.image, (0, y))
        y += tile.image.height + gap

    state_key = f"dashboard:{now.date().isoformat()}:" + "|".join(t.state_key for t in tiles)
    return canvas, state_key


def _empty_tile(mod: PlexInkModule, width: int, height: int, pal: dict, flat: bool, scale: float) -> Image.Image:
    img = Image.new("RGB", (width, height), pal["bg"])
    draw = ImageDraw.Draw(img)
    draw.text((int(24 * scale), int(16 * scale)), mod.MODULE_NAME, font=load_font(int(26 * scale), True), fill=pal["header"])
    draw.text((int(24 * scale), int(56 * scale)), "Keine Daten", font=load_font(int(24 * scale), False), fill=pal["muted"])
    return img
