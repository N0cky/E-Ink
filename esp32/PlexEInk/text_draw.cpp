#include <string.h>
#include "text_draw.h"
#include "epd.h"

static inline void setPixel(uint8_t* fb, int x, int y, uint8_t color) {
    if (x < 0 || y < 0 || x >= EPD_WIDTH || y >= EPD_HEIGHT) return;
    uint8_t* p = fb + (size_t)y * EPD_ROW_BYTES + (x >> 1);
    if (x & 1) *p = (*p & 0xF0) | (color & 0x0F);
    else       *p = (*p & 0x0F) | (color << 4);
}

void fbFill(uint8_t* fb, uint8_t color) {
    memset(fb, (color << 4) | (color & 0x0F), (size_t)EPD_HEIGHT * EPD_ROW_BYTES);
}

void fbFillRect(uint8_t* fb, int x, int y, int w, int h, uint8_t color) {
    for (int yy = y; yy < y + h; yy++)
        for (int xx = x; xx < x + w; xx++)
            setPixel(fb, xx, yy, color);
}

// UTF-8 → Codepoint (1–3 Bytes reichen fuer Umlaute, Grad, Punkt, Gedankenstrich, Ellipse)
static uint32_t nextCodepoint(const char*& s) {
    uint8_t c = (uint8_t)*s;
    if (!c) return 0;
    if (c < 0x80) { s += 1; return c; }
    if ((c & 0xE0) == 0xC0 && s[1]) { uint32_t cp = ((c & 0x1F) << 6) | (s[1] & 0x3F); s += 2; return cp; }
    if ((c & 0xF0) == 0xE0 && s[1] && s[2]) {
        uint32_t cp = ((c & 0x0F) << 12) | ((s[1] & 0x3F) << 6) | (s[2] & 0x3F); s += 3; return cp;
    }
    s += 1;
    return '?';
}

static const FontGlyph* findGlyph(const BitmapFont& font, uint32_t cp) {
    for (uint16_t i = 0; i < font.count; i++)
        if (font.glyphs[i].cp == cp) return &font.glyphs[i];
    for (uint16_t i = 0; i < font.count; i++)
        if (font.glyphs[i].cp == '?') return &font.glyphs[i];
    return nullptr;
}

int fbTextWidth(const BitmapFont& font, const char* utf8) {
    int w = 0;
    const char* s = utf8;
    while (*s) {
        const FontGlyph* g = findGlyph(font, nextCodepoint(s));
        if (g) w += g->adv;
    }
    return w;
}

void fbDrawText(uint8_t* fb, int x, int y, const char* utf8, const BitmapFont& font, uint8_t color) {
    const char* s = utf8;
    int cx = x;
    while (*s) {
        const FontGlyph* g = findGlyph(font, nextCodepoint(s));
        if (!g) continue;
        if (g->w && g->h) {
            int rowBytes = (g->w + 7) / 8;
            const uint8_t* bits = font.bits + g->off;
            for (int gy = 0; gy < g->h; gy++) {
                const uint8_t* row = bits + (size_t)gy * rowBytes;
                for (int gx = 0; gx < g->w; gx++) {
                    if (row[gx >> 3] & (0x80 >> (gx & 7)))
                        setPixel(fb, cx + g->xoff + gx, y + g->yoff + gy, color);
                }
            }
        }
        cx += g->adv;
    }
}
