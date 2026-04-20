# PlexEInk

ESP32-S3-Firmware fuer ein Waveshare 13.3" Spectra 6 E-Ink-Display (`EPD_13IN3E`).
Das Geraet verbindet sich per WLAN mit einem HTTP-Server, prueft per Hash auf neue Inhalte,
laedt bei Bedarf ein 24-Bit-BMP, konvertiert es in das 4-bpp-Format des Displays und geht
anschliessend wieder in den Deep Sleep.

## Features

- ESP32-S3 + PSRAM-Unterstuetzung fuer grosse 1200x1600-BMPs
- Hash-basierter Polling-Ablauf, damit unveraenderte Inhalte nicht neu gerendert werden
- Fallback-Sleep bei WLAN-, Server- oder Metadatenfehlern
- Robusterer HTTP-Stack mit Retry-Logik fuer `GET` und `POST /ack`
- Saubere lokale Konfiguration ueber `config.example.h` und `config.private.h`

## Projektdateien

- [PlexEInk.ino](C:\Users\tobia\Documents\PlexImageE-Ink\esp32\PlexEInk\PlexEInk.ino): Hauptlogik fuer WLAN, HTTP, BMP-Download und Deep Sleep
- [epd.cpp](C:\Users\tobia\Documents\PlexImageE-Ink\esp32\PlexEInk\epd.cpp): Low-Level-Treiber fuer das 13.3" Spectra-6-Display
- [epd.h](C:\Users\tobia\Documents\PlexImageE-Ink\esp32\PlexEInk\epd.h): Oeffentliche Display-API und Farbdefinitionen
- [config.example.h](C:\Users\tobia\Documents\PlexImageE-Ink\esp32\PlexEInk\config.example.h): Sichere Standardwerte und Platzhalter
- [config.private.h](C:\Users\tobia\Documents\PlexImageE-Ink\esp32\PlexEInk\config.private.h): Lokale, nicht weiterzugebende Overrides
- [config.h](C:\Users\tobia\Documents\PlexImageE-Ink\esp32\PlexEInk\config.h): Zentraler Einstiegspunkt, der private Overrides und Defaults zusammenfuehrt

## Konfiguration

Die Firmware bindet immer `config.h` ein.
Diese Datei laedt zuerst `config.private.h` und danach `config.example.h`.
Dadurch ueberschreiben lokale Werte die sicheren Standardwerte.

Typischer Ablauf:

1. `config.example.h` unveraendert als Vorlage im Projekt lassen.
2. In `config.private.h` die lokalen Werte setzen, zum Beispiel:

```cpp
#define WIFI_SSID       "MeinWLAN"
#define WIFI_PASSWORD   "MeinPasswort"
#define SERVER_BASE_URL "http://192.168.178.47:8787"
#define DEVICE_ID       "esp32-eink-01"
```

Wenn `WIFI_SSID` oder `WIFI_PASSWORD` auf den Platzhalterwerten bleiben, startet die Firmware
nicht normal durch und faellt stattdessen kontrolliert in den Fallback-Sleep.

## Erwartetes Serververhalten

Die Firmware erwartet folgende Endpunkte:

- `GET /hash` liefert einen stabilen Inhalts-Hash als Text
- `GET /meta.json` liefert mindestens `{"next_wake_sec": <zahl>}`
- `GET /current.bmp` liefert ein unkomprimiertes 24-Bit-BMP in `1200x1600`
- `POST /ack` akzeptiert JSON wie `{"device_id":"...","hash":"..."}`

Wichtige BMP-Annahmen:

- 24 Bit pro Pixel
- keine Kompression
- Bildgroesse exakt `1200x1600`
- gerade Bildbreite

## Build

Verifizierter CLI-Build:

```powershell
arduino-cli compile --fqbn esp32:esp32:esp32s3 .
```

Im aktuellen Stand wurde der Build erfolgreich mit `arduino-cli 1.4.1` und `esp32:esp32 3.3.8` getestet.

## Arduino IDE

Empfohlene Einstellungen:

- Board: `ESP32S3 Dev Module`
- PSRAM: `OPI PSRAM`
- Flash Size: `16MB`
- Partition Scheme: `16M Flash (3MB APP/9.9MB FATFS)`

## Fehlerverhalten

Bei Stoerungen verhaelt sich die Firmware bewusst konservativ:

- WLAN nicht erreichbar: Fallback-Sleep
- `/hash` nicht erreichbar: Fallback-Sleep
- `meta.json` fehlt oder ist ungueltig: Wake-Intervall faellt auf `POLL_FALLBACK_SEC` zurueck
- BMP-Download fehlerhaft oder unvollstaendig: kein Display-Update, danach Sleep
- `POST /ack` schlaegt fehl: Warnung im Log, aber kein Abbruch des Zyklus

Fuer HTTP-Requests gibt es konfigurierbare Wiederholungen:

- `HTTP_RETRY_COUNT`
- `HTTP_RETRY_DELAY_MS`

Beide Werte koennen in `config.private.h` ueberschrieben werden.
