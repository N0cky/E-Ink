"""
Erzeugt esp32/Inkwall/font_data.h: zwei Bitmap-Schriften (gross fuer den
Offline-Balken, klein fuer Details) aus einer TrueType-Schrift, damit die
Firmware ohne Server Text zeichnen kann.

Aufruf (aus dem Projektordner, mit dem venv):
    python esp32/tools/make_font.py

Format im Header:
    struct FontGlyph { uint16_t cp; uint8_t w, h; int8_t xoff, yoff; uint8_t adv; uint32_t off; };
    Bits zeilenweise, MSB zuerst, jede Zeile auf ganze Bytes aufgefuellt.
    yoff = Abstand von der Oberkante der Zeile bis zur Oberkante der Glyphe.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "esp32" / "Inkwall" / "font_data.h"

CHARSET = "".join(chr(c) for c in range(32, 127)) + "ÄÖÜäöüß°·–…"
SIZES = {"L": 44, "S": 26}


def find_font() -> str:
    candidates = [
        "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/segoeuib.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    sys.exit("Keine fette TrueType-Schrift gefunden")


def build(name: str, size: int, font_path: str) -> str:
    font = ImageFont.truetype(font_path, size)
    ascent, descent = font.getmetrics()
    line_h = ascent + descent
    bits = bytearray()
    glyphs = []
    for ch in CHARSET:
        left, top, right, bottom = font.getbbox(ch)
        w, h = max(0, right - left), max(0, bottom - top)
        adv = int(round(font.getlength(ch)))
        off = len(bits)
        if w and h:
            img = Image.new("L", (w, h), 0)
            ImageDraw.Draw(img).text((-left, -top), ch, font=font, fill=255)
            row_bytes = (w + 7) // 8
            px = img.load()
            for y in range(h):
                row = bytearray(row_bytes)
                for x in range(w):
                    if px[x, y] > 128:
                        row[x >> 3] |= 0x80 >> (x & 7)
                bits += row
        glyphs.append((ord(ch), w, h, left, top, adv, off))

    lines = [f"static const uint8_t FONT_{name}_BITS[] = {{"]
    for i in range(0, len(bits), 24):
        lines.append("    " + ", ".join(f"0x{b:02X}" for b in bits[i:i + 24]) + ",")
    lines.append("};")
    lines.append(f"static const FontGlyph FONT_{name}_GLYPHS[] = {{")
    for cp, w, h, xo, yo, adv, off in glyphs:
        lines.append(f"    {{{cp}, {w}, {h}, {xo}, {yo}, {adv}, {off}}},")
    lines.append("};")
    lines.append(f"static const BitmapFont FONT_{name} = {{{line_h}, {ascent}, {len(glyphs)}, FONT_{name}_GLYPHS, FONT_{name}_BITS}};")
    print(f"{name}: {size}px, {len(glyphs)} Glyphen, {len(bits)} Bytes Bitmaps, Zeilenhoehe {line_h}")
    return "\n".join(lines)


def main() -> None:
    font_path = find_font()
    parts = [
        "// Automatisch erzeugt von esp32/tools/make_font.py – nicht von Hand aendern.",
        f"// Quelle: {os.path.basename(font_path)}",
        "#pragma once",
        "#include <stdint.h>",
        "",
        "struct FontGlyph { uint16_t cp; uint8_t w, h; int8_t xoff, yoff; uint8_t adv; uint32_t off; };",
        "struct BitmapFont { uint8_t height; uint8_t ascent; uint16_t count; const FontGlyph* glyphs; const uint8_t* bits; };",
        "",
    ]
    for name, size in SIZES.items():
        parts.append(build(name, size, font_path))
        parts.append("")
    OUT.write_text("\n".join(parts), encoding="utf-8", newline="\n")
    print(f"geschrieben: {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
