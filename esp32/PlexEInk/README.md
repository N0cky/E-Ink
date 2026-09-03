# PlexEInk

ESP32-S3-Firmware fuer ein Waveshare 13.3" Spectra 6 E-Ink-Display (`EPD_13IN3E`).
Das Geraet verbindet sich per WLAN mit dem PlexImageE-Ink-Server, prueft per Hash auf
neue Inhalte, laedt bei Bedarf das Bild, zeigt es an, meldet sich zurueck und geht
anschliessend wieder in den Deep Sleep.

Version: `1.1.0` (siehe `FIRMWARE_VERSION` in `PlexEInk.ino`).

## Features

- ESP32-S3 + PSRAM-Unterstuetzung fuer grosse 1200x1600-Bilder
- Hash-basierter Polling-Ablauf, damit unveraenderte Inhalte nicht neu gerendert werden
- Kompaktes Bildformat `/current.epd` (4 bpp, 960 KB) direkt ins Display; 24-Bit-BMP als Fallback
- **Update ueber den Server (OTA)** mit MD5-Pruefung und automatischem Rollback
- Rueckmeldung mit Gesundheitsdaten (RSSI, Firmware, Boot-Zaehler, PSRAM, Zeiten, letzter Fehler)
- Serielles Log des Zyklus geht mit der Rueckmeldung an den Server (System-Seite → "Geraet")
- Fallback-Sleep bei WLAN-, Server- oder Metadatenfehlern, Retry-Logik fuer alle Requests
- Saubere lokale Konfiguration ueber `config.example.h` und `config.private.h`

## Projektdateien

- `PlexEInk.ino`: Hauptlogik fuer WLAN, HTTP, OTA, Bild-Download, ACK und Deep Sleep
- `epd.cpp` / `epd.h`: Low-Level-Treiber fuer das 13.3" Spectra-6-Display
- `config.example.h`: Sichere Standardwerte und Platzhalter
- `config.private.h`: Lokale, nicht weiterzugebende Overrides (nicht im Repo)
- `config.h`: Zentraler Einstiegspunkt, der private Overrides und Defaults zusammenfuehrt

## Konfiguration

Die Firmware bindet immer `config.h` ein. Diese Datei laedt zuerst `config.private.h`
und danach `config.example.h`, lokale Werte ueberschreiben also die Standardwerte.

```cpp
#define WIFI_SSID       "MeinWLAN"
#define WIFI_PASSWORD   "MeinPasswort"
#define SERVER_BASE_URL "http://192.168.178.47:8787"
#define DEVICE_ID       "esp32-eink-01"
```

Schalter in `config.example.h` (per `config.private.h` ueberschreibbar):

| Schalter | Standard | Bedeutung |
|---|---|---|
| `FIRMWARE_OTA_ENABLED` | `true` | Update einspielen, wenn der Server eine andere Version bereitstellt |
| `DEVICE_LOG_ENABLED` | `true` | Logzeilen des Zyklus mit dem ACK an den Server schicken |
| `PREFER_COMPACT_IMAGE` | `true` | `/current.epd` bevorzugen, BMP nur als Fallback |
| `ACK_ENABLED` | `true` | Rueckmeldung nach jedem Zyklus |

## Ablauf je Wake-Zyklus

1. WLAN verbinden
2. `GET /meta.json` → Hash, `next_wake_sec`, `epd_url`, `firmware_version`/`firmware_md5`/`firmware_url`
   (Fallback fuer alte Server: `GET /hash`)
3. Laufende Firmware als gueltig markieren (Rollback-Schutz nach einem Update)
4. Bietet der Server eine andere Firmware-Version an → `POST /ack` mit `result=ota`, dann
   `/firmware.bin` in die zweite App-Partition laden (MD5 aus dem Header `x-MD5`), Neustart
5. Hash unveraendert → `POST /ack` mit `result=unchanged`, schlafen
6. `GET /current.epd` (4 bpp, direkt ins Display) oder `GET /current.bmp` (24 Bit, konvertieren)
7. Bild anzeigen, `POST /ack` mit `result=updated` (oder `error`), Gesundheitsdaten und Log
8. Deep Sleep fuer `next_wake_sec`

## Update ueber den Server (OTA)

1. Firmware bauen (siehe unten), die `.bin` auf der Geraet-Seite der Weboberflaeche hochladen.
   Der Server liest die Version aus dem Marker `PLEXEINK_FW_VERSION=…` in der Datei.
2. Beim naechsten Aufwachen vergleicht das Geraet die Version aus `/meta.json` mit seiner
   eigenen. Weicht sie ab, laedt es die Datei in die freie App-Partition und startet neu.
3. Die neue Firmware markiert sich erst dann als gueltig, wenn WLAN und Server wieder
   funktionieren. Bleibt das aus, rollt der Bootloader beim naechsten Start auf die alte
   Firmware zurueck.

Voraussetzungen: Partitionsschema mit zwei App-Slots (`16M Flash (3MB APP/9.9MB FATFS)`
hat `app0` und `app1` mit je 3 MB) und einmalig ein Flash per USB mit einer Firmware ab 1.1.0.

## Rueckmeldung (`POST /ack`)

```json
{
  "device_id": "esp32-eink-01",
  "hash": "…",
  "result": "updated | unchanged | error | ota",
  "fw_version": "1.1.0",
  "rssi": -68, "ip": "192.168.178.50",
  "boot_count": 123, "free_psram_kb": 7890,
  "cycle_ms": 6200, "download_ms": 900, "refresh_ms": 4100,
  "image_format": "epd4",
  "wake_reason": "timer",
  "error": "…nur bei result=error…",
  "log": ["== PlexEInk 1.1.0 Boot #123 (timer) ==", "…"]
}
```

## Erwartetes Serververhalten

- `GET /meta.json` liefert mindestens `{"hash": "…", "next_wake_sec": <zahl>}`; optional
  `epd_url`, `firmware_version`, `firmware_md5`, `firmware_url`
- `GET /current.epd` liefert das kompakte Bild (Header `PLX6`, 16 Bytes, danach 600 Bytes je Zeile)
- `GET /current.bmp` liefert ein unkomprimiertes 24-Bit-BMP in `1200x1600`
- `GET /firmware.bin` liefert die Firmware mit Header `x-MD5`
- `POST /ack` akzeptiert das JSON oben

## Build

```powershell
arduino-cli compile --fqbn "esp32:esp32:esp32s3:PSRAM=opi,FlashSize=16M,PartitionScheme=app3M_fat9M_16MB" --export-binaries .
```

Die fertige Datei liegt danach unter `build/esp32.esp32.esp32s3/PlexEInk.ino.bin` und kann
so auf der Geraet-Seite hochgeladen werden. Getestet mit `arduino-cli 1.4.1` und `esp32:esp32 3.3.8`.

## Arduino IDE

Empfohlene Einstellungen:

- Board: `ESP32S3 Dev Module`
- PSRAM: `OPI PSRAM`
- Flash Size: `16MB`
- Partition Scheme: `16M Flash (3MB APP/9.9MB FATFS)`

"Sketch → Kompilierte Binaerdatei exportieren" legt die `.bin` im Sketch-Ordner ab.

## Fehlerverhalten

- WLAN nicht erreichbar: Fallback-Sleep, der Fehler wird im RTC-Speicher gemerkt und mit dem
  naechsten erfolgreichen ACK gemeldet
- `/meta.json` und `/hash` nicht erreichbar: Fallback-Sleep
- `next_wake_sec` fehlt oder ist ungueltig: Wake-Intervall faellt auf `POLL_FALLBACK_SEC` zurueck
- Kompaktes Bild fehlerhaft: Versuch mit BMP; auch das fehlerhaft: kein Display-Update, ACK mit `result=error`
- OTA fehlgeschlagen: Meldung im Log, der normale Zyklus laeuft mit der alten Firmware weiter
- `POST /ack` schlaegt fehl: Warnung im Log, aber kein Abbruch des Zyklus
