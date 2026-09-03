#pragma once
// Zeichnen in den 4-bpp-Framebuffer des Displays (EPD_ROW_BYTES je Zeile,
// zwei Pixel pro Byte, linkes Pixel im hohen Nibble) mit den eingebetteten
// Bitmap-Schriften aus font_data.h. Nur fuer Statusanzeigen der Firmware:
// Offline-Balken, "Nicht eingerichtet".
#include <stdint.h>
#include "font_data.h"

void fbFill(uint8_t* fb, uint8_t color);
void fbFillRect(uint8_t* fb, int x, int y, int w, int h, uint8_t color);
int  fbTextWidth(const BitmapFont& font, const char* utf8);
void fbDrawText(uint8_t* fb, int x, int y, const char* utf8, const BitmapFont& font, uint8_t color);
