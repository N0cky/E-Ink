/*
 * PlexEInk – ESP32-S3 Firmware
 * Waveshare 13.3″ Spectra 6 (EPD_13IN3E) via HTTP-Polling
 *
 * Server-Einstellung (Python):
 *   RENDER_WIDTH  = 1200
 *   RENDER_HEIGHT = 1600
 *   DISPLAY_ROTATION = 0
 *   OUTPUT_FORMAT = bmp
 *   DISPLAY_THEME = light
 *
 * Ablauf je Wake-Zyklus:
 *   1. WiFi verbinden
 *   2. GET /hash  → unverändert? → direkt schlafen
 *   3. GET /meta.json → next_wake_sec
 *   4. GET /current.bmp → in PSRAM laden (~5.76 MB)
 *   5. BMP → 4bpp Spectra-6 → Display (2 Passes: Master + Slave)
 *   6. POST /ack
 *   7. Deep Sleep
 *
 * Board-Einstellungen (Arduino IDE):
 *   Board:            ESP32S3 Dev Module
 *   PSRAM:            OPI PSRAM
 *   Flash Size:       16MB
 *   Partition Scheme: 16M Flash (3MB APP/9.9MB FATFS)
 */

#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ctype.h>
#include <string.h>
#include <esp_sleep.h>
#include <esp_heap_caps.h>
#include "config.h"
#include "epd.h"

// ─── RTC-Memory (überlebt Deep Sleep) ────────────────────────────────────────
RTC_DATA_ATTR char     storedHash[33] = {0};
RTC_DATA_ATTR uint32_t bootCount      = 0;

static const uint32_t HTTP_STREAM_IDLE_TIMEOUT_MS = 10000;

// ─── Vorwärtsdeklarationen ───────────────────────────────────────────────────
bool     connectWiFi();
bool     httpBegin(HTTPClient& http, const String& url);
String   httpGetString(const String& url);
bool     httpGetBinary(const String& url, uint8_t* buf, size_t bufSize, size_t& outLen);
bool     httpPostJson(const String& url, const String& body, int& outCode);
uint32_t fetchNextWakeSec();
bool     fetchAndDisplay();
bool     sendAck(const char* hash);
void     goSleep(uint32_t seconds);
uint8_t  rgbToSpectra6(uint8_t r, uint8_t g, uint8_t b);
bool     hasUnsetConfig();
bool     parsePositiveUIntField(const String& json, const char* key, uint32_t& outValue);
bool     parseBmpHeader(const uint8_t* buf, size_t bufLen,
                        uint32_t& pixelOffset, int32_t& width,
                        int32_t& height, uint16_t& bpp, uint32_t& rowStride);

// ════════════════════════════════════════════════════════════════════════════
void setup() {
    Serial.begin(SERIAL_BAUD);
    delay(500);
    bootCount++;
    Serial.printf("\n\n══ PlexEInk Boot #%lu ══\n", (unsigned long)bootCount);
    Serial.printf("    PSRAM frei: %u KB\n",
                  heap_caps_get_free_size(MALLOC_CAP_SPIRAM) / 1024);

    if (hasUnsetConfig()) {
        Serial.println("[ERR] Konfiguration unvollstaendig. Bitte config.private.h oder config.example.h anpassen.");
        goSleep(POLL_FALLBACK_SEC);
    }

    if (!connectWiFi()) {
        Serial.println("[WARN] WiFi failed → Fallback-Sleep");
        goSleep(POLL_FALLBACK_SEC);
    }

    // ── Hash-Check ───────────────────────────────────────────────────────────
    String serverHash = httpGetString(String(SERVER_BASE_URL) + "/hash");
    serverHash.trim();
    Serial.printf("[Hash] server=%-32s  lokal=%s\n",
                  serverHash.isEmpty() ? "(fehler)" : serverHash.c_str(),
                  storedHash[0] ? storedHash : "(leer)");

    if (serverHash.isEmpty()) {
        Serial.println("[WARN] /hash nicht erreichbar");
        goSleep(POLL_FALLBACK_SEC);
    }

    uint32_t nextWakeSec = fetchNextWakeSec();

    if (serverHash == String(storedHash)) {
        Serial.printf("[Hash] Unveraendert → Sleep %lu s\n", (unsigned long)nextWakeSec);
        WiFi.disconnect(true);
        WiFi.mode(WIFI_OFF);
        goSleep(nextWakeSec);
    }

    // ── Neues Bild laden und anzeigen ────────────────────────────────────────
    Serial.println("[Hash] Geaendert → Bild laden...");
    if (fetchAndDisplay()) {
        serverHash.toCharArray(storedHash, sizeof(storedHash));
        if (ACK_ENABLED && !sendAck(storedHash)) {
            Serial.println("[WARN] ACK nicht bestaetigt");
        }
        Serial.printf("[OK] Bild aktualisiert → Sleep %lu s\n", (unsigned long)nextWakeSec);
    } else {
        Serial.println("[ERR] fetchAndDisplay fehlgeschlagen");
    }

    WiFi.disconnect(true);
    WiFi.mode(WIFI_OFF);
    goSleep(nextWakeSec);
}

void loop() {}


// ════════════════════════════════════════════════════════════════════════════
//  WiFi
// ════════════════════════════════════════════════════════════════════════════
bool hasUnsetConfig() {
    return strcmp(WIFI_SSID, "WIFI_SSID_HERE") == 0
        || strcmp(WIFI_PASSWORD, "WIFI_PASSWORD_HERE") == 0
        || strlen(WIFI_SSID) == 0
        || strlen(SERVER_BASE_URL) == 0
        || strlen(DEVICE_ID) == 0;
}

bool connectWiFi() {
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    Serial.printf("[WiFi] Verbinde mit %s", WIFI_SSID);
    uint32_t t = millis();
    while (WiFi.status() != WL_CONNECTED) {
        if (millis() - t > WIFI_TIMEOUT_MS) { Serial.println(" TIMEOUT"); return false; }
        delay(300);
        Serial.print(".");
    }
    Serial.printf(" OK  IP=%s  RSSI=%d dBm\n",
                  WiFi.localIP().toString().c_str(), WiFi.RSSI());
    return true;
}


// ════════════════════════════════════════════════════════════════════════════
//  HTTP
// ════════════════════════════════════════════════════════════════════════════
bool httpBegin(HTTPClient& http, const String& url) {
    http.setTimeout(HTTP_TIMEOUT_MS);
    if (!http.begin(url)) {
        Serial.printf("[HTTP] begin fehlgeschlagen fuer %s\n", url.c_str());
        return false;
    }
    return true;
}

String httpGetString(const String& url) {
    for (uint32_t attempt = 1; attempt <= HTTP_RETRY_COUNT; attempt++) {
        HTTPClient http;
        if (!httpBegin(http, url)) {
            if (attempt < HTTP_RETRY_COUNT) delay(HTTP_RETRY_DELAY_MS);
            continue;
        }

        int    code = http.GET();
        String body;
        if (code == 200) {
            body = http.getString();
            http.end();
            return body;
        }

        Serial.printf("[HTTP] GET %s Versuch %lu/%d → %d\n",
                      url.c_str(), (unsigned long)attempt, HTTP_RETRY_COUNT, code);
        http.end();
        if (attempt < HTTP_RETRY_COUNT) delay(HTTP_RETRY_DELAY_MS);
    }

    return String();
}

bool httpGetBinary(const String& url, uint8_t* buf, size_t bufSize, size_t& outLen) {
    for (uint32_t attempt = 1; attempt <= HTTP_RETRY_COUNT; attempt++) {
        HTTPClient http;
        if (!httpBegin(http, url)) {
            if (attempt < HTTP_RETRY_COUNT) delay(HTTP_RETRY_DELAY_MS);
            continue;
        }

        int code = http.GET();
        if (code != 200) {
            Serial.printf("[HTTP] GET %s Versuch %lu/%d → %d\n",
                          url.c_str(), (unsigned long)attempt, HTTP_RETRY_COUNT, code);
            http.end();
            if (attempt < HTTP_RETRY_COUNT) delay(HTTP_RETRY_DELAY_MS);
            continue;
        }

        int contentLen = http.getSize();
        Serial.printf("[HTTP] Download %s  Content-Length=%d\n", url.c_str(), contentLen);
        if (contentLen > 0 && (size_t)contentLen > bufSize) {
            Serial.printf("[HTTP] Datei zu gross fuer Puffer (%d > %u)\n",
                          contentLen, (unsigned)bufSize);
            http.end();
            return false;
        }

        WiFiClient* stream = http.getStreamPtr();
        outLen = 0;
        uint8_t chunk[4096];
        uint32_t lastProgressAt = millis();
        bool failed = false;

        while (http.connected() || stream->available()) {
            size_t avail  = stream->available();
            if (!avail) {
                if (millis() - lastProgressAt > HTTP_STREAM_IDLE_TIMEOUT_MS) {
                    Serial.println("[HTTP] Stream-Timeout ohne weitere Daten");
                    failed = true;
                    break;
                }
                delay(1);
                continue;
            }
            size_t toRead = min(avail, sizeof(chunk));
            toRead        = min(toRead, bufSize - outLen);
            if (!toRead)  {
                Serial.println("[HTTP] Buffer voll!");
                failed = true;
                break;
            }
            size_t rd = stream->readBytes(chunk, toRead);
            if (!rd) {
                Serial.println("[HTTP] Stream lieferte 0 Bytes");
                failed = true;
                break;
            }
            memcpy(buf + outLen, chunk, rd);
            outLen += rd;
            lastProgressAt = millis();
            if (contentLen > 0 && (int)outLen >= contentLen) break;
        }

        http.end();
        Serial.printf("[HTTP] %u Bytes geladen\n", (unsigned)outLen);

        if (!failed && contentLen > 0 && (int)outLen != contentLen) {
            Serial.printf("[HTTP] Unvollstaendiger Download (%u/%d Bytes)\n",
                          (unsigned)outLen, contentLen);
            failed = true;
        }

        if (!failed && outLen > 0) return true;

        Serial.printf("[HTTP] Download fehlgeschlagen, Versuch %lu/%d\n",
                      (unsigned long)attempt, HTTP_RETRY_COUNT);
        if (attempt < HTTP_RETRY_COUNT) delay(HTTP_RETRY_DELAY_MS);
    }

    outLen = 0;
    return false;
}

bool httpPostJson(const String& url, const String& body, int& outCode) {
    for (uint32_t attempt = 1; attempt <= HTTP_RETRY_COUNT; attempt++) {
        HTTPClient http;
        if (!httpBegin(http, url)) {
            if (attempt < HTTP_RETRY_COUNT) delay(HTTP_RETRY_DELAY_MS);
            continue;
        }

        http.addHeader("Content-Type", "application/json");
        outCode = http.POST(body);
        http.end();

        if (outCode >= 200 && outCode < 300) return true;

        Serial.printf("[HTTP] POST %s Versuch %lu/%d → %d\n",
                      url.c_str(), (unsigned long)attempt, HTTP_RETRY_COUNT, outCode);
        if (attempt < HTTP_RETRY_COUNT) delay(HTTP_RETRY_DELAY_MS);
    }

    return false;
}


// ════════════════════════════════════════════════════════════════════════════
//  Meta
// ════════════════════════════════════════════════════════════════════════════
bool parsePositiveUIntField(const String& json, const char* key, uint32_t& outValue) {
    String quotedKey = String("\"") + key + "\"";
    int keyPos = json.indexOf(quotedKey);
    if (keyPos < 0) return false;

    int colonPos = json.indexOf(':', keyPos + quotedKey.length());
    if (colonPos < 0) return false;

    int valuePos = colonPos + 1;
    while (valuePos < json.length() && isspace((unsigned char)json[valuePos])) valuePos++;

    if (valuePos >= json.length() || !isDigit(json[valuePos])) return false;

    uint32_t value = 0;
    while (valuePos < json.length() && isDigit(json[valuePos])) {
        uint8_t digit = (uint8_t)(json[valuePos] - '0');
        if (value > (UINT32_MAX - digit) / 10U) return false;
        value = value * 10U + digit;
        valuePos++;
    }

    if (value == 0) return false;
    outValue = value;
    return true;
}

uint32_t fetchNextWakeSec() {
    String body = httpGetString(String(SERVER_BASE_URL) + "/meta.json");
    if (body.isEmpty()) return POLL_FALLBACK_SEC;

    uint32_t nextWakeSec = 0;
    if (!parsePositiveUIntField(body, "next_wake_sec", nextWakeSec)) {
        Serial.println("[Meta] next_wake_sec fehlt oder ist ungueltig");
        return POLL_FALLBACK_SEC;
    }

    Serial.printf("[Meta] next_wake_sec=%lu\n", (unsigned long)nextWakeSec);
    return nextWakeSec;
}


// ════════════════════════════════════════════════════════════════════════════
//  BMP → Spectra 6 → Display
// ════════════════════════════════════════════════════════════════════════════

// Device-RGB → 4-Bit-Farbcode des Spectra-6-Displays
uint8_t rgbToSpectra6(uint8_t r, uint8_t g, uint8_t b) {
    if (r ==   0 && g ==   0 && b ==   0) return EPD_COLOR_BLACK;
    if (r == 255 && g == 255 && b == 255) return EPD_COLOR_WHITE;
    if (r == 255 && g == 255 && b ==   0) return EPD_COLOR_YELLOW;
    if (r == 255 && g ==   0 && b ==   0) return EPD_COLOR_RED;
    if (r ==   0 && g ==   0 && b == 255) return EPD_COLOR_BLUE;
    if (r ==   0 && g == 255 && b ==   0) return EPD_COLOR_GREEN;
    return EPD_COLOR_WHITE;
}

bool parseBmpHeader(const uint8_t* buf, size_t bufLen,
                    uint32_t& pixelOffset, int32_t& width,
                    int32_t& height, uint16_t& bpp, uint32_t& rowStride) {
    if (bufLen < 54 || buf[0] != 'B' || buf[1] != 'M') return false;
    auto le32 = [&](int o) -> uint32_t {
        return (uint32_t)buf[o] | ((uint32_t)buf[o+1]<<8)
             | ((uint32_t)buf[o+2]<<16) | ((uint32_t)buf[o+3]<<24);
    };
    auto le16 = [&](int o) -> uint16_t {
        return (uint16_t)buf[o] | ((uint16_t)buf[o+1] << 8);
    };

    uint32_t dibHeaderSize = le32(14);
    uint16_t planes        = le16(26);
    pixelOffset = le32(10);
    width       = (int32_t)le32(18);
    height      = (int32_t)le32(22);   // positiv = bottom-up (Standard)
    bpp         = le16(28);
    uint32_t compression = le32(30);
    Serial.printf("[BMP] %dx%d  bpp=%d  offset=%u\n", width, abs(height), bpp, pixelOffset);

    if (dibHeaderSize < 40 || planes != 1 || bpp != 24 || compression != 0) return false;
    if (width <= 0 || height == 0) return false;
    if (width != EPD_WIDTH || abs(height) != EPD_HEIGHT) {
        Serial.printf("[BMP] Unerwartete Bildgroesse, erwartet %dx%d\n", EPD_WIDTH, EPD_HEIGHT);
        return false;
    }
    if ((width & 1) != 0) {
        Serial.println("[BMP] Bildbreite muss gerade sein");
        return false;
    }

    uint64_t rowStride64 = ((uint64_t)width * 3ULL + 3ULL) & ~3ULL;
    uint64_t pixelDataEnd = (uint64_t)pixelOffset + rowStride64 * (uint64_t)abs(height);
    if (rowStride64 > UINT32_MAX || pixelDataEnd > bufLen) {
        Serial.println("[BMP] Pixeldaten ausserhalb des Puffers");
        return false;
    }

    rowStride = (uint32_t)rowStride64;
    return true;
}

bool fetchAndDisplay() {
    // ── 1. BMP in PSRAM laden ─────────────────────────────────────────────
    // 1200 × 1600 × 3 Bytes + Header ≈ 5.76 MB
    const size_t BMP_BUF_SIZE = (size_t)EPD_WIDTH * EPD_HEIGHT * 3 + 256;
    uint8_t* bmpBuf = (uint8_t*)heap_caps_malloc(BMP_BUF_SIZE, MALLOC_CAP_SPIRAM);
    if (!bmpBuf) {
        Serial.printf("[ERR] PSRAM-Alloc fehlgeschlagen (%u KB)\n",
                      (unsigned)(BMP_BUF_SIZE / 1024));
        return false;
    }

    size_t bmpLen = 0;
    if (!httpGetBinary(String(SERVER_BASE_URL) + "/current.bmp",
                       bmpBuf, BMP_BUF_SIZE, bmpLen)) {
        heap_caps_free(bmpBuf);
        return false;
    }

    uint32_t pixelOffset;
    int32_t  imgW, imgH;
    uint16_t bpp;
    uint32_t rowStride;
    if (!parseBmpHeader(bmpBuf, bmpLen, pixelOffset, imgW, imgH, bpp, rowStride)) {
        Serial.println("[ERR] Ungültiges BMP");
        heap_caps_free(bmpBuf);
        return false;
    }

    int32_t  absH      = abs(imgH);
    bool     bottomUp  = (imgH > 0);             // Standard-BMP: Zeilen bottom-up

    // ── 2. Display initialisieren ─────────────────────────────────────────
    EPD_Init();

    // ── 3. Kombinierten 4bpp-Puffer in PSRAM allokieren ──────────────────
    //
    // EPD-Zeile = EPD_ROW_BYTES (600) Bytes:
    //   Bytes 0..299   → Master CS (linke 600 Pixel)
    //   Bytes 300..599 → Slave  CS (rechte 600 Pixel)
    // Format: 4 bpp, 2 Pixel pro Byte: (linkes_Pixel << 4) | rechtes_Pixel
    //
    // Kombinierten 4bpp-Puffer in PSRAM allokieren:
    // EPD_HEIGHT × EPD_ROW_BYTES = 1600 × 600 = 960 000 Bytes
    const size_t EPD_BUF_SIZE = (size_t)EPD_HEIGHT * EPD_ROW_BYTES;
    uint8_t* epdBuf = (uint8_t*)heap_caps_malloc(EPD_BUF_SIZE, MALLOC_CAP_SPIRAM);
    if (!epdBuf) {
        // Fallback: kein zweiter Puffer möglich – Fehler melden
        Serial.println("[ERR] PSRAM fuer EPD-Puffer nicht ausreichend");
        heap_caps_free(bmpBuf);
        return false;
    }

    Serial.println("[EPD] Konvertiere BMP → 4bpp Spectra-6...");
    for (int32_t row = 0; row < absH; row++) {
        // BMP: Zeile 0 = untere Bildzeile → Display: Zeile 0 = obere Bildzeile
        int32_t bmpRow         = bottomUp ? (absH - 1 - row) : row;
        const uint8_t* src     = bmpBuf + pixelOffset + (size_t)bmpRow * rowStride;
        uint8_t*       dst     = epdBuf + (size_t)row * EPD_ROW_BYTES;

        for (int32_t col = 0; col < imgW; col += 2) {
            // BMP speichert Pixel in BGR-Reihenfolge
            size_t px0 = (size_t)col * 3U;
            size_t px1 = (size_t)(col + 1) * 3U;
            uint8_t b0 = src[px0 + 0], g0 = src[px0 + 1], r0 = src[px0 + 2];
            uint8_t b1 = src[px1 + 0], g1 = src[px1 + 1], r1 = src[px1 + 2];
            dst[col/2] = (rgbToSpectra6(r0,g0,b0) << 4) | rgbToSpectra6(r1,g1,b1);
        }
    }
    heap_caps_free(bmpBuf);

    Serial.println("[EPD] Sende an Display...");
    EPD_Display(epdBuf);

    heap_caps_free(epdBuf);
    Serial.println("[EPD] Fertig!");
    return true;
}


// ════════════════════════════════════════════════════════════════════════════
//  ACK
// ════════════════════════════════════════════════════════════════════════════
bool sendAck(const char* hash) {
    String body = String("{\"device_id\":\"") + DEVICE_ID
                + "\",\"hash\":\"" + hash + "\"}";
    int code = -1;
    bool ok = httpPostJson(String(SERVER_BASE_URL) + "/ack", body, code);
    Serial.printf("[ACK] POST /ack → HTTP %d\n", code);
    return ok;
}


// ════════════════════════════════════════════════════════════════════════════
//  Deep Sleep
// ════════════════════════════════════════════════════════════════════════════
void goSleep(uint32_t seconds) {
    Serial.printf("[Sleep] Deep Sleep fuer %lu s\n", (unsigned long)seconds);
    Serial.flush();
    EPD_Sleep();
    esp_sleep_enable_timer_wakeup((uint64_t)seconds * 1000000ULL);
    esp_deep_sleep_start();
}
