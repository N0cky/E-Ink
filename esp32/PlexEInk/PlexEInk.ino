/*
 * PlexEInk – ESP32-S3 Firmware
 * Waveshare 13.3″ Spectra 6 (EPD_13IN3E) via HTTP-Polling
 *
 * Server-Einstellung (Python):
 *   RENDER_WIDTH  = 1200
 *   RENDER_HEIGHT = 1600
 *   DISPLAY_ROTATION = 0
 *   OUTPUT_FORMAT = bmp
 *
 * Ablauf je Wake-Zyklus:
 *   1. WiFi verbinden
 *   2. GET /meta.json → Hash, next_wake_sec, kompaktes Bild, bereitgestellte Firmware
 *      (Fallback: GET /hash)
 *   3. Laufende Firmware als gültig markieren (Rollback-Schutz nach OTA)
 *   4. Firmware-Version weicht ab? → /firmware.bin per OTA einspielen, Neustart
 *   5. Hash unverändert? → ACK "unchanged", schlafen
 *   6. GET /current.epd (4 bpp, direkt ins Display) oder /current.bmp (24 Bit, konvertieren)
 *   7. Bild anzeigen, ACK mit Ergebnis, Gesundheitsdaten und Logzeilen
 *   8. Deep Sleep
 *
 * Board-Einstellungen (Arduino IDE):
 *   Board:            ESP32S3 Dev Module
 *   PSRAM:            OPI PSRAM
 *   Flash Size:       16MB
 *   Partition Scheme: 16M Flash (3MB APP/9.9MB FATFS)   ← zwei App-Slots, OTA-fähig
 */

#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClient.h>
#include <HTTPClient.h>
#include <HTTPUpdate.h>
#include <Preferences.h>
#include <ctype.h>
#include <string.h>
#include <stdarg.h>
#include <esp_sleep.h>
#include <esp_heap_caps.h>
#include <esp_ota_ops.h>
#include "config.h"
#include "epd.h"

// ─── Version ─────────────────────────────────────────────────────────────────
// Der Server liest die Version aus dem Marker in der .bin (Gerät-Seite → Firmware).
// Der Marker wird im Boot-Log referenziert, sonst wirft der Linker ihn weg.
#ifdef OTA_SELFTEST_FAIL
#define FIRMWARE_VERSION "1.1.6-selftest"
#else
#define FIRMWARE_VERSION "1.1.6"
#endif
#define FW_MARKER_PREFIX "PLEXEINK_FW_VERSION="
const char FW_VERSION_MARKER[] __attribute__((used)) = FW_MARKER_PREFIX FIRMWARE_VERSION;
static const char* firmwareVersionFromMarker() { return FW_VERSION_MARKER + sizeof(FW_MARKER_PREFIX) - 1; }

// ─── RTC-Memory (überlebt Deep Sleep) ────────────────────────────────────────
RTC_DATA_ATTR char     storedHash[33] = {0};
RTC_DATA_ATTR uint32_t bootCount      = 0;
RTC_DATA_ATTR char     lastError[96]  = {0};   // Fehler eines Zyklus ohne ACK (z. B. WLAN weg)

// ─── OTA-Gedächtnis im Flash (NVS) ───────────────────────────────────────────
// Rollback-Schutz in der Firmware selbst (der Arduino-Bootloader lässt eine
// neue Firmware nicht im Prüfzustand, siehe Gerätelog "valid" direkt nach OTA):
//   - vor dem Neustart in die neue Firmware: pendingVerify=1, Zielversion merken
//   - die neue Firmware zählt ihre Starts; erreicht sie den Server, ist sie bestätigt
//   - zwei Starts ohne Serverkontakt → Update.rollBack() auf die alte Partition
//   - die alte Firmware sieht rolledBack, meldet es und lädt diese Version nicht erneut
// Bewusst NVS statt RTC-Speicher: RTC-Variablen liegen je Firmware-Build an anderen
// Adressen, die neue Firmware würde die Notiz der alten nicht finden (so passiert
// mit 1.1.4). NVS ist adressunabhängig und überlebt auch Stromausfall.
struct OtaMemory {
    char     targetVersion[32];
    uint8_t  pendingVerify;
    uint8_t  failedBoots;
    uint8_t  rolledBack;
    uint8_t  rollbackReported;
};
static OtaMemory otaMemory;
static const char* OTA_NVS_NAMESPACE = "plexeink";

static void otaMemoryLoad() {
    memset(&otaMemory, 0, sizeof(otaMemory));
    Preferences prefs;
    if (!prefs.begin(OTA_NVS_NAMESPACE, true)) return;      // noch nie geschrieben
    prefs.getString("target", otaMemory.targetVersion, sizeof(otaMemory.targetVersion));
    otaMemory.pendingVerify    = prefs.getUChar("pending", 0);
    otaMemory.failedBoots      = prefs.getUChar("fails", 0);
    otaMemory.rolledBack       = prefs.getUChar("rolled", 0);
    otaMemory.rollbackReported = prefs.getUChar("reported", 0);
    prefs.end();
}

static void otaMemorySave() {
    Preferences prefs;
    if (!prefs.begin(OTA_NVS_NAMESPACE, false)) { Serial.println("[NVS] nicht beschreibbar"); return; }
    prefs.putString("target", otaMemory.targetVersion);
    prefs.putUChar("pending", otaMemory.pendingVerify);
    prefs.putUChar("fails", otaMemory.failedBoots);
    prefs.putUChar("rolled", otaMemory.rolledBack);
    prefs.putUChar("reported", otaMemory.rollbackReported);
    prefs.end();
}

// Falls der Bootloader doch einmal den Prüfzustand nutzt: nicht automatisch bestätigen,
// das macht der Sketch nach erfolgreichem Serverkontakt.
bool verifyRollbackLater() { return true; }

static const uint32_t HTTP_STREAM_IDLE_TIMEOUT_MS = 10000;
static const size_t   EPD_HEADER_SIZE = 16;
static const size_t   DEVICE_LOG_MAX_CHARS = 3000;

// ─── Zyklus-Zustand ──────────────────────────────────────────────────────────
struct Meta {
    String hash;
    uint32_t nextWakeSec = POLL_FALLBACK_SEC;
    String epdUrl;
    String firmwareVersion;
    String firmwareMd5;
    String firmwareUrl;
};

static String   g_log;                 // Logzeilen dieses Zyklus (gehen mit dem ACK zum Server)
static uint32_t g_cycleStart = 0;
static uint32_t g_downloadMs = 0;
static uint32_t g_refreshMs  = 0;
static String   g_imageFormat;
static String   g_error;

// ─── Vorwärtsdeklarationen ───────────────────────────────────────────────────
void     logf(const char* fmt, ...);
bool     connectWiFi();
bool     httpBegin(HTTPClient& http, const String& url);
String   httpGetString(const String& url);
bool     httpGetBinary(const String& url, uint8_t* buf, size_t bufSize, size_t& outLen);
bool     httpPostJson(const String& url, const String& body, int& outCode);
bool     fetchMeta(Meta& meta);
bool     performOta(const Meta& meta);
bool     fetchAndDisplayEpd(const String& url);
bool     fetchAndDisplayBmp();
bool     sendAck(const char* result, const char* hash, const char* fwTarget = nullptr);
void     goSleep(uint32_t seconds);
uint8_t  rgbToSpectra6(uint8_t r, uint8_t g, uint8_t b);
bool     hasUnsetConfig();
bool     parsePositiveUIntField(const String& json, const char* key, uint32_t& outValue);
bool     parseStringField(const String& json, const char* key, String& outValue);
bool     parseBmpHeader(const uint8_t* buf, size_t bufLen,
                        uint32_t& pixelOffset, int32_t& width,
                        int32_t& height, uint16_t& bpp, uint32_t& rowStride);
static void setError(const char* text);
static const char* wakeReasonText();
static String jsonEscape(const String& in);

// ════════════════════════════════════════════════════════════════════════════
void setup() {
    Serial.begin(SERIAL_BAUD);
    delay(500);
    g_cycleStart = millis();
    bootCount++;
    logf("== PlexEInk %s Boot #%lu (%s) ==", firmwareVersionFromMarker(), (unsigned long)bootCount, wakeReasonText());
    logf("PSRAM frei: %u KB", heap_caps_get_free_size(MALLOC_CAP_SPIRAM) / 1024);
    {
        // Welcher App-Slot laeuft, und in welchem OTA-Zustand sind beide Slots?
        // (new/pending/valid/aborted – so sieht man im Geraetelog, ob der Rollback-Schutz greift)
        const esp_partition_t* part = esp_ota_get_running_partition();
        const esp_partition_t* next = esp_ota_get_next_update_partition(NULL);
        auto stateName = [](const esp_partition_t* p) -> const char* {
            esp_ota_img_states_t st;
            if (!p || esp_ota_get_state_partition(p, &st) != ESP_OK) return "?";
            switch (st) {
                case ESP_OTA_IMG_NEW:            return "new";
                case ESP_OTA_IMG_PENDING_VERIFY: return "pending";
                case ESP_OTA_IMG_VALID:          return "valid";
                case ESP_OTA_IMG_INVALID:        return "invalid";
                case ESP_OTA_IMG_ABORTED:        return "aborted";
                default:                         return "undefined";
            }
        };
        logf("Partition: %s (%s), andere: %s (%s)",
             part ? part->label : "?", stateName(part), next ? next->label : "?", stateName(next));
    }
    if (lastError[0]) {
        logf("[WARN] Letzter Zyklus ohne Rueckmeldung: %s", lastError);
    }
    otaMemoryLoad();

    // ── Frisch per OTA geflasht? Starts zählen, notfalls zurückrollen ────────
    if (otaMemory.pendingVerify) {
        otaMemory.failedBoots++;
        if (otaMemory.failedBoots > 2) {
            logf("[OTA] %s hat den Server zweimal nicht erreicht -> Rollback", FIRMWARE_VERSION);
            otaMemory.pendingVerify = 0;
            otaMemory.failedBoots = 0;
            otaMemory.rolledBack = 1;
            otaMemory.rollbackReported = 0;
            otaMemorySave();
            if (Update.canRollBack() && Update.rollBack()) {
                Serial.flush();
                delay(200);
                ESP.restart();
            }
            logf("[OTA] Rollback nicht moeglich - keine bootfaehige alte Firmware");
        } else {
            otaMemorySave();
            logf("[OTA] Erster Lauf von %s, Bestaetigung steht aus (Start %u von 2)",
                 FIRMWARE_VERSION, (unsigned)otaMemory.failedBoots);
        }
    }

#ifdef OTA_SELFTEST_FAIL
    // Selbsttest des Rollbacks: diese Firmware erreicht den Server absichtlich nie.
    // Sie schläft kurz, wacht auf, und nach zwei Starts muss der Rollback greifen.
    // Notbremse unabhängig vom NVS-Gedächtnis: nach sechs Starts in jedem Fall zurück.
    {
        static RTC_DATA_ATTR uint32_t selftestBoots = 0;
        selftestBoots++;
        logf("[SELFTEST] Absichtlich kaputte Firmware (Start %lu) - kein WLAN, Sleep 20 s, Rollback erwartet",
             (unsigned long)selftestBoots);
        if (selftestBoots > 6 && Update.canRollBack() && Update.rollBack()) {
            logf("[SELFTEST] Notbremse: Rollback ohne NVS");
            Serial.flush(); delay(200); ESP.restart();
        }
        Serial.flush();
        esp_sleep_enable_timer_wakeup(20ULL * 1000000ULL);
        esp_deep_sleep_start();
    }
#endif

    if (hasUnsetConfig()) {
        logf("[ERR] Konfiguration unvollstaendig. Bitte config.private.h oder config.example.h anpassen.");
        setError("Konfiguration unvollstaendig");
        goSleep(POLL_FALLBACK_SEC);
    }

    if (!connectWiFi()) {
        logf("[WARN] WiFi failed -> Fallback-Sleep");
        setError("WLAN nicht erreichbar");
        goSleep(POLL_FALLBACK_SEC);
    }

    // ── Meta (Hash, Wake, Bildformat, Firmware) ──────────────────────────────
    Meta meta;
    if (!fetchMeta(meta)) {
        // Alter Server ohne meta.json? Notfalls nur den Hash holen.
        meta.hash = httpGetString(String(SERVER_BASE_URL) + "/hash");
        meta.hash.trim();
        if (meta.hash.isEmpty()) {
            logf("[WARN] Server nicht erreichbar (/meta.json und /hash)");
            setError("Server nicht erreichbar");
            goSleep(POLL_FALLBACK_SEC);
        }
    }
    logf("[Hash] server=%s lokal=%s", meta.hash.c_str(), storedHash[0] ? storedHash : "(leer)");

    // ── Rollback-Schutz: WLAN und Server funktionieren, diese Firmware ist gut ──
    const esp_partition_t* running = esp_ota_get_running_partition();
    esp_ota_img_states_t otaState;
    if (running && esp_ota_get_state_partition(running, &otaState) == ESP_OK
        && otaState == ESP_OTA_IMG_PENDING_VERIFY) {
        esp_ota_mark_app_valid_cancel_rollback();
    }
    if (otaMemory.pendingVerify) {
        otaMemory.pendingVerify = 0;
        otaMemory.failedBoots = 0;
        otaMemory.targetVersion[0] = 0;
        otaMemorySave();
        logf("[OTA] Neue Firmware %s bestaetigt (Partition %s)", FIRMWARE_VERSION, running ? running->label : "?");
    }

    // ── Wurde die letzte Firmware zurückgerollt? ─────────────────────────────
    // Dann sagt die gemerkte Zielversion, welche Version wir nicht noch einmal laden.
    String rejectedVersion;
    const esp_partition_t* other = esp_ota_get_next_update_partition(NULL);
    esp_ota_img_states_t otherState;
    bool otherAborted = other && esp_ota_get_state_partition(other, &otherState) == ESP_OK
        && (otherState == ESP_OTA_IMG_ABORTED || otherState == ESP_OTA_IMG_INVALID);
    if (otaMemory.targetVersion[0] && (otaMemory.rolledBack || otherAborted)) {
        rejectedVersion = otaMemory.targetVersion;
        if (!otaMemory.rollbackReported) {
            g_error = String("Firmware ") + rejectedVersion + " zurueckgerollt: Start ohne Serverkontakt";
            logf("[OTA] %s (laeuft wieder %s auf %s)", g_error.c_str(), FIRMWARE_VERSION, running ? running->label : "?");
            otaMemory.rollbackReported = 1;
            otaMemorySave();
        }
    }

    // ── Firmware-Update? ─────────────────────────────────────────────────────
    if (FIRMWARE_OTA_ENABLED && !meta.firmwareVersion.isEmpty()
        && meta.firmwareVersion != FIRMWARE_VERSION && !meta.firmwareUrl.isEmpty()) {
        if (meta.firmwareVersion == rejectedVersion) {
            logf("[OTA] %s wurde schon einmal zurueckgerollt - kein neuer Versuch, bis eine andere Version bereitsteht",
                 rejectedVersion.c_str());
        } else {
            logf("[OTA] Server bietet %s an, laufend ist %s -> Update", meta.firmwareVersion.c_str(), FIRMWARE_VERSION);
            meta.firmwareVersion.toCharArray(otaMemory.targetVersion, sizeof(otaMemory.targetVersion));
            otaMemory.rollbackReported = 0;
            otaMemory.rolledBack = 0;
            otaMemorySave();
            performOta(meta);   // startet bei Erfolg neu; sonst laeuft der Zyklus normal weiter
        }
    }

    // ── Hash unverändert → nur melden und schlafen ───────────────────────────
    if (meta.hash == String(storedHash)) {
        logf("[Hash] Unveraendert -> Sleep %lu s", (unsigned long)meta.nextWakeSec);
        if (ACK_ENABLED) sendAck(g_error.isEmpty() ? "unchanged" : "error", storedHash);
        WiFi.disconnect(true);
        WiFi.mode(WIFI_OFF);
        goSleep(meta.nextWakeSec);
    }

    // ── Neues Bild laden und anzeigen ────────────────────────────────────────
    logf("[Hash] Geaendert -> Bild laden...");
    bool shown = false;
    if (PREFER_COMPACT_IMAGE && !meta.epdUrl.isEmpty()) {
        shown = fetchAndDisplayEpd(meta.epdUrl);
        if (!shown) logf("[WARN] Kompaktes Bild fehlgeschlagen, versuche BMP");
    }
    if (!shown) {
        shown = fetchAndDisplayBmp();
    }

    if (shown) {
        meta.hash.toCharArray(storedHash, sizeof(storedHash));
        logf("[OK] Bild aktualisiert (%s, Download %lu ms, Anzeige %lu ms)",
             g_imageFormat.c_str(), (unsigned long)g_downloadMs, (unsigned long)g_refreshMs);
        // Ein gemerkter Rollback wird als Fehler gemeldet, damit er auf der Geraet-Seite steht
        if (ACK_ENABLED && !sendAck(g_error.isEmpty() ? "updated" : "error", storedHash)) {
            logf("[WARN] ACK nicht bestaetigt");
        }
    } else {
        logf("[ERR] Bild konnte nicht angezeigt werden");
        if (g_error.isEmpty()) g_error = "Bild konnte nicht geladen werden";
        if (ACK_ENABLED) sendAck("error", storedHash);
    }

    WiFi.disconnect(true);
    WiFi.mode(WIFI_OFF);
    goSleep(meta.nextWakeSec);
}

void loop() {}


// ════════════════════════════════════════════════════════════════════════════
//  Log
// ════════════════════════════════════════════════════════════════════════════
void logf(const char* fmt, ...) {
    char buf[256];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    Serial.println(buf);
    if (DEVICE_LOG_ENABLED && g_log.length() + strlen(buf) + 1 < DEVICE_LOG_MAX_CHARS) {
        g_log += buf;
        g_log += '\n';
    }
}

static void setError(const char* text) {
    strncpy(lastError, text, sizeof(lastError) - 1);
    lastError[sizeof(lastError) - 1] = 0;
    g_error = text;
}

static const char* wakeReasonText() {
    switch (esp_sleep_get_wakeup_cause()) {
        case ESP_SLEEP_WAKEUP_TIMER: return "timer";
        case ESP_SLEEP_WAKEUP_EXT0:
        case ESP_SLEEP_WAKEUP_EXT1:  return "button";
        default:                     return "poweron";
    }
}

static String jsonEscape(const String& in) {
    String out;
    out.reserve(in.length() + 8);
    for (size_t i = 0; i < in.length(); i++) {
        char c = in[i];
        switch (c) {
            case '"':  out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\n': out += "\\n";  break;
            case '\r': break;
            case '\t': out += "  ";   break;
            default:
                if ((unsigned char)c < 0x20) break;
                out += c;
        }
    }
    return out;
}


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
    Serial.println();
    logf("[WiFi] OK IP=%s RSSI=%d dBm (%lu ms)",
         WiFi.localIP().toString().c_str(), WiFi.RSSI(), (unsigned long)(millis() - t));
    return true;
}


// ════════════════════════════════════════════════════════════════════════════
//  HTTP
// ════════════════════════════════════════════════════════════════════════════
bool httpBegin(HTTPClient& http, const String& url) {
    http.setTimeout(HTTP_TIMEOUT_MS);
    if (!http.begin(url)) {
        logf("[HTTP] begin fehlgeschlagen fuer %s", url.c_str());
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

        logf("[HTTP] GET %s Versuch %lu/%d -> %d", url.c_str(), (unsigned long)attempt, HTTP_RETRY_COUNT, code);
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
            logf("[HTTP] GET %s Versuch %lu/%d -> %d", url.c_str(), (unsigned long)attempt, HTTP_RETRY_COUNT, code);
            http.end();
            if (attempt < HTTP_RETRY_COUNT) delay(HTTP_RETRY_DELAY_MS);
            continue;
        }

        int contentLen = http.getSize();
        Serial.printf("[HTTP] Download %s  Content-Length=%d\n", url.c_str(), contentLen);
        if (contentLen > 0 && (size_t)contentLen > bufSize) {
            logf("[HTTP] Datei zu gross fuer Puffer (%d > %u)", contentLen, (unsigned)bufSize);
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
                    logf("[HTTP] Stream-Timeout ohne weitere Daten");
                    failed = true;
                    break;
                }
                delay(1);
                continue;
            }
            size_t toRead = min(avail, sizeof(chunk));
            toRead        = min(toRead, bufSize - outLen);
            if (!toRead)  {
                logf("[HTTP] Buffer voll!");
                failed = true;
                break;
            }
            size_t rd = stream->readBytes(chunk, toRead);
            if (!rd) {
                logf("[HTTP] Stream lieferte 0 Bytes");
                failed = true;
                break;
            }
            memcpy(buf + outLen, chunk, rd);
            outLen += rd;
            lastProgressAt = millis();
            if (contentLen > 0 && (int)outLen >= contentLen) break;
        }

        http.end();
        logf("[HTTP] %u Bytes geladen", (unsigned)outLen);

        if (!failed && contentLen > 0 && (int)outLen != contentLen) {
            logf("[HTTP] Unvollstaendiger Download (%u/%d Bytes)", (unsigned)outLen, contentLen);
            failed = true;
        }

        if (!failed && outLen > 0) return true;

        logf("[HTTP] Download fehlgeschlagen, Versuch %lu/%d", (unsigned long)attempt, HTTP_RETRY_COUNT);
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

        Serial.printf("[HTTP] POST %s Versuch %lu/%d -> %d\n",
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

// "key": "wert" – ohne Escapes, reicht fuer Hash, Pfade und Versionsnummern
bool parseStringField(const String& json, const char* key, String& outValue) {
    String quotedKey = String("\"") + key + "\"";
    int keyPos = json.indexOf(quotedKey);
    if (keyPos < 0) return false;
    int colonPos = json.indexOf(':', keyPos + quotedKey.length());
    if (colonPos < 0) return false;
    int openQuote = json.indexOf('"', colonPos + 1);
    if (openQuote < 0) return false;
    // Zwischen Doppelpunkt und Anfuehrungszeichen darf nur Leerraum stehen
    for (int i = colonPos + 1; i < openQuote; i++) {
        if (!isspace((unsigned char)json[i])) return false;
    }
    int closeQuote = json.indexOf('"', openQuote + 1);
    if (closeQuote < 0) return false;
    outValue = json.substring(openQuote + 1, closeQuote);
    return true;
}

bool fetchMeta(Meta& meta) {
    String body = httpGetString(String(SERVER_BASE_URL) + "/meta.json");
    if (body.isEmpty()) return false;

    if (!parseStringField(body, "hash", meta.hash) || meta.hash.isEmpty()) {
        logf("[Meta] hash fehlt");
        return false;
    }
    if (!parsePositiveUIntField(body, "next_wake_sec", meta.nextWakeSec)) {
        logf("[Meta] next_wake_sec fehlt oder ist ungueltig");
        meta.nextWakeSec = POLL_FALLBACK_SEC;
    }
    parseStringField(body, "epd_url", meta.epdUrl);
    parseStringField(body, "firmware_version", meta.firmwareVersion);
    parseStringField(body, "firmware_md5", meta.firmwareMd5);
    parseStringField(body, "firmware_url", meta.firmwareUrl);
    logf("[Meta] next_wake_sec=%lu epd=%s firmware=%s",
         (unsigned long)meta.nextWakeSec,
         meta.epdUrl.isEmpty() ? "nein" : "ja",
         meta.firmwareVersion.isEmpty() ? "-" : meta.firmwareVersion.c_str());
    return true;
}


// ════════════════════════════════════════════════════════════════════════════
//  OTA
// ════════════════════════════════════════════════════════════════════════════
bool performOta(const Meta& meta) {
    String url = meta.firmwareUrl;
    if (url.startsWith("/")) url = String(SERVER_BASE_URL) + url;

    // Erst melden, dann flashen: so weiss der Server, warum das Geraet gleich neu startet
    if (ACK_ENABLED) sendAck("ota", storedHash, meta.firmwareVersion.c_str());

    WiFiClient client;
    httpUpdate.rebootOnUpdate(false);
    httpUpdate.setLedPin(-1);
    uint32_t t = millis();
    t_httpUpdate_return ret = httpUpdate.update(client, url, FIRMWARE_VERSION);

    switch (ret) {
        case HTTP_UPDATE_OK:
            logf("[OTA] Firmware %s geschrieben (%lu ms), Neustart", meta.firmwareVersion.c_str(),
                 (unsigned long)(millis() - t));
            // Ab jetzt muss sich die neue Firmware beweisen (siehe OtaMemory)
            otaMemory.pendingVerify = 1;
            otaMemory.failedBoots = 0;
            otaMemorySave();
            Serial.flush();
            delay(200);
            ESP.restart();
            return true;   // nicht erreicht
        case HTTP_UPDATE_NO_UPDATES:
            logf("[OTA] Server meldet: kein Update");
            return false;
        default:
            logf("[OTA] Fehlgeschlagen: %d %s", httpUpdate.getLastError(), httpUpdate.getLastErrorString().c_str());
            g_error = String("OTA fehlgeschlagen: ") + httpUpdate.getLastErrorString();
            return false;
    }
}


// ════════════════════════════════════════════════════════════════════════════
//  Kompaktes Bild (PLX6, 4 bpp) → direkt ins Display
// ════════════════════════════════════════════════════════════════════════════
bool fetchAndDisplayEpd(const String& path) {
    String url = path.startsWith("/") ? String(SERVER_BASE_URL) + path : path;
    const size_t EPD_BUF_SIZE = (size_t)EPD_HEIGHT * EPD_ROW_BYTES;     // 960 000
    const size_t BUF_SIZE = EPD_HEADER_SIZE + EPD_BUF_SIZE + 64;
    uint8_t* buf = (uint8_t*)heap_caps_malloc(BUF_SIZE, MALLOC_CAP_SPIRAM);
    if (!buf) {
        logf("[ERR] PSRAM-Alloc fehlgeschlagen (%u KB)", (unsigned)(BUF_SIZE / 1024));
        g_error = "PSRAM zu klein";
        return false;
    }

    uint32_t t = millis();
    size_t len = 0;
    if (!httpGetBinary(url, buf, BUF_SIZE, len)) {
        heap_caps_free(buf);
        g_error = "Download des kompakten Bildes fehlgeschlagen";
        return false;
    }
    g_downloadMs = millis() - t;

    // Header pruefen: Magic, Version, bpp, Groesse
    auto le16 = [&](int o) -> uint16_t { return (uint16_t)buf[o] | ((uint16_t)buf[o + 1] << 8); };
    auto le32 = [&](int o) -> uint32_t {
        return (uint32_t)buf[o] | ((uint32_t)buf[o+1] << 8) | ((uint32_t)buf[o+2] << 16) | ((uint32_t)buf[o+3] << 24);
    };
    bool ok = len >= EPD_HEADER_SIZE && memcmp(buf, "PLX6", 4) == 0 && buf[4] == 1 && buf[5] == 4;
    uint16_t w = ok ? le16(6) : 0, h = ok ? le16(8) : 0;
    uint32_t payload = ok ? le32(10) : 0;
    if (!ok || w != EPD_WIDTH || h != EPD_HEIGHT || payload != EPD_BUF_SIZE || len < EPD_HEADER_SIZE + payload) {
        logf("[ERR] Kompaktes Bild ungueltig (magic=%s %ux%u payload=%lu len=%u)",
             ok ? "ok" : "falsch", w, h, (unsigned long)payload, (unsigned)len);
        heap_caps_free(buf);
        g_error = "Kompaktes Bild ungueltig";
        return false;
    }

    t = millis();
    EPD_Init();
    logf("[EPD] Sende kompaktes Bild an Display...");
    EPD_Display(buf + EPD_HEADER_SIZE);
    g_refreshMs = millis() - t;
    heap_caps_free(buf);
    g_imageFormat = "epd4";
    logf("[EPD] Fertig!");
    return true;
}


// ════════════════════════════════════════════════════════════════════════════
//  BMP → Spectra 6 → Display (Fallback / alte Server)
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
        logf("[BMP] Unerwartete Bildgroesse, erwartet %dx%d", EPD_WIDTH, EPD_HEIGHT);
        return false;
    }
    if ((width & 1) != 0) {
        logf("[BMP] Bildbreite muss gerade sein");
        return false;
    }

    uint64_t rowStride64 = ((uint64_t)width * 3ULL + 3ULL) & ~3ULL;
    uint64_t pixelDataEnd = (uint64_t)pixelOffset + rowStride64 * (uint64_t)abs(height);
    if (rowStride64 > UINT32_MAX || pixelDataEnd > bufLen) {
        logf("[BMP] Pixeldaten ausserhalb des Puffers");
        return false;
    }

    rowStride = (uint32_t)rowStride64;
    return true;
}

bool fetchAndDisplayBmp() {
    // ── 1. BMP in PSRAM laden ─────────────────────────────────────────────
    // 1200 × 1600 × 3 Bytes + Header ≈ 5.76 MB
    const size_t BMP_BUF_SIZE = (size_t)EPD_WIDTH * EPD_HEIGHT * 3 + 256;
    uint8_t* bmpBuf = (uint8_t*)heap_caps_malloc(BMP_BUF_SIZE, MALLOC_CAP_SPIRAM);
    if (!bmpBuf) {
        logf("[ERR] PSRAM-Alloc fehlgeschlagen (%u KB)", (unsigned)(BMP_BUF_SIZE / 1024));
        g_error = "PSRAM zu klein";
        return false;
    }

    uint32_t t = millis();
    size_t bmpLen = 0;
    if (!httpGetBinary(String(SERVER_BASE_URL) + "/current.bmp",
                       bmpBuf, BMP_BUF_SIZE, bmpLen)) {
        heap_caps_free(bmpBuf);
        g_error = "BMP-Download fehlgeschlagen";
        return false;
    }
    g_downloadMs = millis() - t;

    uint32_t pixelOffset;
    int32_t  imgW, imgH;
    uint16_t bpp;
    uint32_t rowStride;
    if (!parseBmpHeader(bmpBuf, bmpLen, pixelOffset, imgW, imgH, bpp, rowStride)) {
        logf("[ERR] Ungueltiges BMP");
        heap_caps_free(bmpBuf);
        g_error = "BMP ungueltig";
        return false;
    }

    int32_t  absH      = abs(imgH);
    bool     bottomUp  = (imgH > 0);             // Standard-BMP: Zeilen bottom-up

    // ── 2. Display initialisieren ─────────────────────────────────────────
    t = millis();
    EPD_Init();

    // ── 3. Kombinierten 4bpp-Puffer in PSRAM allokieren ──────────────────
    // EPD-Zeile = EPD_ROW_BYTES (600) Bytes: Bytes 0..299 Master, 300..599 Slave.
    // 4 bpp, 2 Pixel pro Byte: (linkes_Pixel << 4) | rechtes_Pixel
    const size_t EPD_BUF_SIZE = (size_t)EPD_HEIGHT * EPD_ROW_BYTES;
    uint8_t* epdBuf = (uint8_t*)heap_caps_malloc(EPD_BUF_SIZE, MALLOC_CAP_SPIRAM);
    if (!epdBuf) {
        logf("[ERR] PSRAM fuer EPD-Puffer nicht ausreichend");
        heap_caps_free(bmpBuf);
        g_error = "PSRAM zu klein";
        return false;
    }

    Serial.println("[EPD] Konvertiere BMP -> 4bpp Spectra-6...");
    for (int32_t row = 0; row < absH; row++) {
        int32_t bmpRow         = bottomUp ? (absH - 1 - row) : row;
        const uint8_t* src     = bmpBuf + pixelOffset + (size_t)bmpRow * rowStride;
        uint8_t*       dst     = epdBuf + (size_t)row * EPD_ROW_BYTES;

        for (int32_t col = 0; col < imgW; col += 2) {
            size_t px0 = (size_t)col * 3U;
            size_t px1 = (size_t)(col + 1) * 3U;
            uint8_t b0 = src[px0 + 0], g0 = src[px0 + 1], r0 = src[px0 + 2];
            uint8_t b1 = src[px1 + 0], g1 = src[px1 + 1], r1 = src[px1 + 2];
            dst[col/2] = (rgbToSpectra6(r0,g0,b0) << 4) | rgbToSpectra6(r1,g1,b1);
        }
    }
    heap_caps_free(bmpBuf);

    logf("[EPD] Sende BMP-Bild an Display...");
    EPD_Display(epdBuf);
    g_refreshMs = millis() - t;

    heap_caps_free(epdBuf);
    g_imageFormat = "bmp";
    logf("[EPD] Fertig!");
    return true;
}


// ════════════════════════════════════════════════════════════════════════════
//  ACK – Ergebnis, Gesundheitsdaten und Log
// ════════════════════════════════════════════════════════════════════════════
bool sendAck(const char* result, const char* hash, const char* fwTarget) {
    String body;
    body.reserve(g_log.length() + 512);
    body += "{\"device_id\":\""; body += jsonEscape(DEVICE_ID);
    body += "\",\"hash\":\"";    body += jsonEscape(hash);
    body += "\",\"result\":\"";  body += result;
    body += "\",\"fw_version\":\"" FIRMWARE_VERSION "\"";
    if (fwTarget && fwTarget[0]) { body += ",\"fw_target\":\""; body += jsonEscape(fwTarget); body += "\""; }
    body += ",\"rssi\":";          body += String(WiFi.RSSI());
    body += ",\"ip\":\"";          body += WiFi.localIP().toString(); body += "\"";
    body += ",\"boot_count\":";    body += String((unsigned long)bootCount);
    body += ",\"free_psram_kb\":"; body += String((unsigned long)(heap_caps_get_free_size(MALLOC_CAP_SPIRAM) / 1024));
    body += ",\"cycle_ms\":";      body += String((unsigned long)(millis() - g_cycleStart));
    if (g_downloadMs) { body += ",\"download_ms\":"; body += String((unsigned long)g_downloadMs); }
    if (g_refreshMs)  { body += ",\"refresh_ms\":";  body += String((unsigned long)g_refreshMs); }
    if (!g_imageFormat.isEmpty()) { body += ",\"image_format\":\""; body += g_imageFormat; body += "\""; }
    body += ",\"wake_reason\":\""; body += wakeReasonText(); body += "\"";
    if (!g_error.isEmpty()) { body += ",\"error\":\""; body += jsonEscape(g_error); body += "\""; }

    if (DEVICE_LOG_ENABLED && g_log.length()) {
        body += ",\"log\":[";
        int start = 0;
        bool first = true;
        while (start < (int)g_log.length()) {
            int nl = g_log.indexOf('\n', start);
            if (nl < 0) nl = g_log.length();
            if (nl > start) {
                if (!first) body += ',';
                body += '"'; body += jsonEscape(g_log.substring(start, nl)); body += '"';
                first = false;
            }
            start = nl + 1;
        }
        body += ']';
    }
    body += '}';

    int code = -1;
    bool ok = httpPostJson(String(SERVER_BASE_URL) + "/ack", body, code);
    Serial.printf("[ACK] POST /ack (%s, %u Bytes) -> HTTP %d\n", result, (unsigned)body.length(), code);
    if (ok) {
        lastError[0] = 0;      // Server hat den Fehler des letzten Zyklus jetzt gesehen
        g_log = "";
    }
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
