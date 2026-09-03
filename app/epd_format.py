"""
Kompaktes Bildformat für den ESP32: 4 Bit pro Pixel in der Reihenfolge, die
das Spectra-6-Display erwartet. 1200 × 1600 sind so 960 000 Bytes statt
5,76 MB als 24-Bit-BMP – sechsmal weniger Download, und die Konvertierung
im Gerät entfällt: der ESP32 schiebt die Nutzdaten direkt ins Display.

Aufbau (Little Endian):
    0   4  Magic "PLX6"
    4   1  Formatversion (1)
    5   1  Bits pro Pixel (4)
    6   2  Breite in Pixeln (gerade)
    8   2  Höhe in Pixeln
    10  4  Länge der Nutzdaten in Bytes (= Breite/2 × Höhe)
    14  2  reserviert (0)
    16  …  Zeilen von oben nach unten, je Byte zwei Pixel: linkes Pixel im
           hohen Nibble. Farbcodes wie im Display: 0 Schwarz, 1 Weiß, 2 Gelb,
           3 Rot, 5 Blau, 6 Grün.
"""

from __future__ import annotations

import struct

from PIL import Image

MAGIC = b"PLX6"
FORMAT_VERSION = 1
BITS_PER_PIXEL = 4
HEADER_SIZE = 16

# Palettenindex (Reihenfolge aus image_rendering: Schwarz, Weiß, Gelb, Rot, Blau, Grün)
# → Farbcode des Displays. Alle weiteren Indizes fallen auf Schwarz.
_INDEX_TO_CODE = bytes([0x0, 0x1, 0x2, 0x3, 0x5, 0x6]) + bytes(250)
_CODE_TO_INDEX = {0x0: 0, 0x1: 1, 0x2: 2, 0x3: 3, 0x5: 4, 0x6: 5}


def encode_epd4(quantized: Image.Image) -> bytes:
    """Paletten-Bild (Modus P, Indizes 0–5) → Datei-Bytes."""
    if quantized.mode != "P":
        raise ValueError("encode_epd4 erwartet ein Paletten-Bild (Modus P)")
    width, height = quantized.size
    if width % 2:
        raise ValueError("Bildbreite muss gerade sein")
    codes = quantized.tobytes().translate(_INDEX_TO_CODE)
    hi, lo = codes[0::2], codes[1::2]
    # Zwei Nibbles je Byte ohne Python-Schleife: die Byte-Folgen als große
    # Ganzzahlen addieren. Keine Überträge, weil jeder Code ≤ 6 ist.
    packed = (int.from_bytes(hi, "big") * 16 + int.from_bytes(lo, "big")).to_bytes(len(hi), "big")
    header = MAGIC + struct.pack("<BBHHIH", FORMAT_VERSION, BITS_PER_PIXEL, width, height, len(packed), 0)
    assert len(header) == HEADER_SIZE
    return header + packed


def decode_epd4(data: bytes) -> tuple[int, int, list[int]]:
    """Datei-Bytes → (Breite, Höhe, Farbcodes je Pixel). Für Tests und Werkzeuge."""
    if len(data) < HEADER_SIZE or data[:4] != MAGIC:
        raise ValueError("Kein PLX6-Bild")
    version, bpp, width, height, length, _ = struct.unpack("<BBHHIH", data[4:HEADER_SIZE])
    if version != FORMAT_VERSION or bpp != BITS_PER_PIXEL:
        raise ValueError(f"Unbekannte Formatversion {version}/{bpp} bpp")
    payload = data[HEADER_SIZE:HEADER_SIZE + length]
    if len(payload) != length or length != width // 2 * height:
        raise ValueError("Nutzdaten unvollständig")
    codes: list[int] = []
    for byte in payload:
        codes.append(byte >> 4)
        codes.append(byte & 0x0F)
    return width, height, codes


def code_to_index(code: int) -> int:
    return _CODE_TO_INDEX.get(code, 0)
