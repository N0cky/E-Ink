# PlexImageE-Ink

PlexImageE-Ink is a self-hosted image server for E-Ink displays.

It renders active Plex playback and configurable idle content like weather, news, and gallery images into a display-ready image that can be fetched by an ESP32 or another lightweight client. The client only needs to wake up briefly, check whether the image changed, download it if needed, and go back to sleep.

Supported output modes:

- `PNG` for regular displays or preview workflows
- `BMP` with dithering for Waveshare Spectra 6 E-Ink displays

---

## Why This Project

- Designed for low-power E-Ink clients that should sleep most of the time
- Optimized for a "now playing" use case with Plex as the primary live source
- Falls back to modular idle content when nothing is playing
- Fully self-hosted and configurable through a browser UI
- Built to be extensible through standalone modules instead of hard-coded features

---

## Features

- **Plex-Integration** – zeigt automatisch laufende Filme, Serien und Musik mit Cover-Art, Metadaten und Fortschrittsbalken
- **DWD-Wetter** – aktuelles Wetter, Stundenverlauf, Mehrtagesprognose, UV-Index und Pollenflug (Deutscher Wetterdienst, kostenfrei)
- **Tagesschau-Nachrichten** – aktuelle Nachrichten mit Thumbnail und Teasertext
- **Gallery** – lokale Bildordner als Idle-Modul mit Zufallsauswahl, Blur-Hintergrund und optionalem Overlay
- **Modulares System** – neue Inhalte als eigenständige Module hinzufügen, ohne den Kern anzufassen
- **Dark- und Light-Theme** – optimiert für OLED-ähnliche Displays und das Waveshare Spectra-6-Farbdisplay
- **Weboberfläche** – alle Einstellungen über den Browser, Live-Vorschau, Log-Viewer
- **Docker-Ready** – Container-Start via `Dockerfile` und `docker-compose.yml`
- **WSGI-Ready** – produktiver Start im Container über Gunicorn mit sauberem Runtime-Bootstrap
- **GitHub-Ready** – Non-Commercial-Lizenz, CI-Workflow und saubere Repo-Dateien

---

## Quick Start

- Want to test locally? Use `python app/server.py`
- Want a production-like setup? Use Docker and Gunicorn
- Want to add content sources later? Use the modular `modules/` system

### Contents

- [Features](#features)
- [Quick Start](#quick-start)
- [Requirements](#requirements)
- [Runtime Model](#runtime-model)
- [Docker Deployment](#docker-deployment)
- [Configuration](#configuration)
- [API Endpoints](#api-endpoints)
- [Project Structure](#project-structure)
- [Module System](#modul-system)
- [Create a New Module](#neues-modul-erstellen)
- [ESP32 Client](#esp32-client)
- [GitHub](#github)
- [License](#license)

### Local Development

```bash
# Repository klonen
git clone https://github.com/dein-user/PlexImageE-Ink.git
cd PlexImageE-Ink

# Virtuelle Umgebung anlegen und aktivieren
python -m venv .venv
.venv/Scripts/activate        # Windows
# source .venv/bin/activate   # Linux / macOS

# Abhängigkeiten installieren
pip install -r app/requirements.txt

# Konfiguration anlegen
copy .env.example .env              # Windows PowerShell / CMD
# cp .env.example .env             # Linux / macOS

# Server starten
python app/server.py
```

The web UI is then available at `http://localhost:8787`.

### Docker

```bash
copy .env.example .env              # Windows
# cp .env.example .env             # Linux / macOS

docker compose up --build -d
```

The containerized app is also available at `http://localhost:8787`.

---

## Requirements

- Python 3.11 oder neuer
- pip / venv
- Optional: ESP32 mit dem mitgelieferten Firmware-Sketch (`esp32/`)

---

## Runtime Model

The server keeps the latest rendered image on disk and exposes it over HTTP.

Typical flow:

1. A priority module like Plex provides live content if active.
2. Otherwise the configured idle modules rotate automatically.
3. The client checks `/meta.json` for hash, format, and the suggested sleep interval.
4. The client downloads the image only when it actually changed.

This keeps the display logic simple while letting the server handle data fetching, rendering, and wake timing.

---

## Docker Deployment

### Mit Docker Compose

```bash
# Konfiguration anlegen
copy .env.example .env              # Windows
# cp .env.example .env             # Linux / macOS

# Container bauen und starten
docker compose up --build -d
```

Danach ist die Weboberfläche unter `http://localhost:8787` erreichbar.

Persistente Verzeichnisse:

- `./data/output` – gerenderte Bilder
- `./logs` – JSON-Logs

### Direkt mit Docker

```bash
docker build -t pleximagee-ink .
docker run --rm -p 8787:8787 --env-file .env -v ./data/output:/app/data/output -v ./logs:/app/logs pleximagee-ink
```

### Produktionshinweis

Der Container startet über Gunicorn:

```bash
gunicorn --workers 1 --bind 0.0.0.0:8787 wsgi:app
```

Es wird bewusst **ein Worker** verwendet. Das Projekt betreibt einen eigenen Background-Worker für Rendering und Modul-Rotation; mehrere Gunicorn-Worker würden sonst mehrere parallele Render-Loops starten.

Für lokale Entwicklung bleibt `python app/server.py` der einfachste Weg. Im Docker-/Produktivbetrieb startet das Projekt über Gunicorn als WSGI-Server.

---

## Configuration

Alle Einstellungen können über die Weboberfläche unter `/settings` vorgenommen werden. Alternativ direkt in der `.env`-Datei im Projektstamm.

| Variable | Beschreibung | Standard |
|---|---|---|
| `PORT` | HTTP-Port des Servers | `8787` |
| `RENDER_WIDTH` | Bildbreite in Pixeln | `1600` |
| `RENDER_HEIGHT` | Bildhöhe in Pixeln | `1200` |
| `DISPLAY_ROTATION` | Rotation: `0`, `90`, `180`, `270` | `0` |
| `DISPLAY_THEME` | `dark` oder `light` | `dark` |
| `OUTPUT_FORMAT` | `png` oder `bmp` (Spectra 6) | `png` |
| `REFRESH_INTERVAL` | Prüfintervall in Sekunden | `60` |
| `TIMEZONE` | IANA-Zeitzone, z. B. `Europe/Berlin` | `Europe/Berlin` |
| `IDLE_MODULES` | Aktive Idle-Module, kommagetrennt | `` |
| `IDLE_MODULE_ROTATION_SECONDS` | Wechselintervall zwischen Idle-Modulen | `120` |
| `PLEX_BASE_URL` | URL des Plex-Servers | `` |
| `PLEX_TOKEN` | Plex-API-Token | `` |

Modul-spezifische Variablen (DWD-Station, Pollen-Region, Gallery-Pfade, …) werden von den jeweiligen Modulen definiert und ebenfalls über die Weboberfläche verwaltet.

---

## API Endpoints

| Endpunkt | Methode | Beschreibung |
|---|---|---|
| `/current.png` | GET | Aktuelles Bild als PNG |
| `/current.bmp` | GET | Aktuelles Bild als BMP (nur wenn `OUTPUT_FORMAT=bmp`) |
| `/meta.json` | GET | Hash, Format, Status, empfohlene Schlafzeit |
| `/health` | GET | Health-Check für Docker / Monitoring |
| `/hash` | GET | MD5-Hash des aktuellen Bildes (plain text) |
| `/ack` | POST | Empfangsbestätigung vom Display-Client |
| `/refresh` | POST | Sofortiger Neu-Render |
| `/webhook` | POST | Plex-Webhook-Empfänger |
| `/api/status` | GET | Laufzeit-Status inkl. geladener Module |
| `/api/modules` | GET | Liste aller entdeckten Module |
| `/api/rescan-modules` | POST | Module neu einlesen (ohne Neustart) |

---

## Project Structure

```
PlexImageE-Ink/
│
├── app/                        # Framework-Kern
│   ├── server.py               # Flask-Server, Rendering-Loop, API-Routes
│   ├── config.py               # Konfiguration, RuntimeConfig, .env-IO
│   ├── module_base.py          # PlexInkModule – Basisklasse für alle Module
│   ├── module_registry.py      # Auto-Discovery und Hot-Reload der Module
│   ├── module_services.py      # Service-Dataclasses für modulare Renderer
│   ├── http_client.py          # Gemeinsamer HTTP-Client (requests.Session)
│   ├── plex.py                 # Plex-API-Client (Session-Parsing, Artwork)
│   ├── image_rendering.py      # Shared Rendering-Utilities
│   └── data_sources/           # Backward-Compat-Stubs (zeigen auf modules/)
│
├── modules/                    # Module – vollständig eigenständig
│   ├── plex/
│   │   └── __init__.py         # Plex-Modul (Priorität 0)
│   ├── dwd_weather/
│   │   ├── __init__.py         # Modul-Einstiegspunkt
│   │   ├── dwd.py              # Datenabruf DWD Wetter
│   │   ├── dwd_pollen.py       # Datenabruf Pollenflug
│   │   ├── dwd_uv.py           # Datenabruf UV-Index
│   │   └── renderer.py         # Bildrendering
│   ├── gallery/
│   │   ├── __init__.py         # Modul-Einstiegspunkt
│   │   ├── data_source.py      # Dateisuche + Bildauswahl
│   │   └── renderer.py         # Bildrendering
│   └── tagesschau/
│       ├── __init__.py         # Modul-Einstiegspunkt
│       ├── data_source.py      # Datenabruf + Bild-Cache
│       └── renderer.py         # Bildrendering
│
├── .github/workflows/          # GitHub Actions CI
├── .gitattributes              # Einheitliche Zeilenenden/Binary-Markierungen
├── CHANGELOG.md                # Release-Historie
├── CONTRIBUTING.md             # Hinweise für Beiträge
├── Dockerfile                  # Container-Build
├── docker-compose.yml          # Lokaler Container-Start
├── wsgi.py                     # Gunicorn/WSGI-Einstiegspunkt
├── templates/                  # Jinja2-HTML-Templates
├── font/                       # Font Awesome (für Wetter-Icons)
├── esp32/                      # Arduino-Sketch für den E-Ink-Client
├── data/output/                # Gerenderte Bilder + State-Datei
├── logs/                       # JSON-Logdateien
└── .env                        # Konfiguration (nicht einchecken)
```

---

## Modul-System

Das Framework ist ein reines Gerüst. Die gesamte Anzeigelogik steckt in Modulen unter `modules/`. Beim Start scannt der Server automatisch diesen Ordner und registriert alle gefundenen Module. Über die Weboberfläche können Module auch zur Laufzeit neu eingelesen werden, ohne den Server neu zu starten.

### Prioritäten

| `MODULE_PRIORITY` | Typ | Verhalten |
|---|---|---|
| `< 10` | **Prioritätsmodul** | Überschreibt alle Idle-Module sobald es Inhalt liefert (z. B. Plex während der Wiedergabe) |
| `>= 10` | **Idle-Modul** | Wird rotiert wenn kein Prioritätsmodul aktiv ist |

---

## Neues Modul erstellen

Ein Modul besteht aus einem Ordner unter `modules/` mit einer `__init__.py`. Mehr Dateien (Datenabruf, Rendering, …) können frei im selben Ordner organisiert werden.

### Schritt 1 – Ordner anlegen

```
modules/
└── mein_modul/
    └── __init__.py
```

### Schritt 2 – `__init__.py` schreiben

```python
from __future__ import annotations
from typing import Any
from PIL import Image, ImageDraw
from app.module_base import PlexInkModule
from app.logger import get_logger

log = get_logger(__name__)


# ── Settings-Felder (erscheinen automatisch in der Weboberfläche) ──────────

SETTINGS_FIELDS: list[dict] = [
    {
        "name":        "MEIN_MODUL_API_KEY",
        "label":       "API-Schlüssel",
        "type":        "text",           # text | number | password | select |
                                         # checkbox_group | priority_list
        "wide":        True,             # True = volle Breite im Formular
        "placeholder": "abc123",
        "help":        "API-Key für den externen Dienst.",
    },
    {
        "name":        "MEIN_MODUL_REFRESH",
        "label":       "Aktualisierung (s)",
        "type":        "number",
        "wide":        False,
        "placeholder": "300",
        "min":         60,
        "max":         86400,
        "help":        "Wie oft Daten neu abgerufen werden.",
    },
]

# Optionale Untergruppen – gruppiert die Felder in der Weboberfläche
SETTINGS_GROUPS: list[dict] = [
    {
        "title":  "Verbindung",
        "desc":   "Zugangsdaten für den externen Dienst.",
        "fields": ["MEIN_MODUL_API_KEY", "MEIN_MODUL_REFRESH"],
    },
]


# ── Modul-Implementierung ──────────────────────────────────────────────────

class MeinModul(PlexInkModule):
    MODULE_ID          = "mein_modul"           # eindeutige ID, Kleinbuchstaben + _
    MODULE_NAME        = "Mein Modul"           # Anzeigename in der Weboberfläche
    MODULE_DESCRIPTION = "Kurze Beschreibung."
    MODULE_PRIORITY    = 120                    # >= 10 → Idle-Modul

    SETTINGS_FIELDS = SETTINGS_FIELDS
    SETTINGS_GROUPS = SETTINGS_GROUPS

    def is_enabled(self, env: dict[str, str]) -> bool:
        """Gibt False zurück → Modul wird komplett übersprungen."""
        return "mein_modul" in env.get("IDLE_MODULES", "")

    def fetch_content(self, env: dict[str, str]) -> Any | None:
        """
        Daten holen (API-Call, Datei lesen, …).
        Gibt None zurück → kein Inhalt, nächstes Modul wird versucht.
        """
        api_key = env.get("MEIN_MODUL_API_KEY", "").strip()
        if not api_key:
            return None

        # Eigene Datenabruf-Logik hier:
        # from .data_source import fetch_meine_daten
        # return fetch_meine_daten(api_key)
        return {"message": "Hallo Welt", "api_key": api_key}

    def render(self, env: dict[str, str], content: Any) -> Image.Image:
        """Inhalt als PIL-Bild rendern."""
        from app.config import get_cfg, load_font
        cfg = get_cfg()
        w, h = cfg.render_width, cfg.render_height

        img  = Image.new("RGB", (w, h), (20, 20, 30))
        draw = ImageDraw.Draw(img)

        font = load_font(48, is_bold=True)
        draw.text(
            (w // 2, h // 2),
            content.get("message", ""),
            font=font,
            fill=(255, 255, 255),
            anchor="mm",
        )
        return img

    def should_refresh(self, env: dict[str, str]) -> bool:
        """
        True → neu rendern, auch wenn get_state_key() gleich geblieben ist.
        Nützlich für zeitgesteuerte Cache-Invalidierung.
        """
        return False

    def get_state_key(self, content: Any) -> str:
        """
        Eindeutiger Fingerabdruck des Inhalts. Ändert er sich, wird neu gerendert.
        Standard: MODULE_ID (immer neu rendern wenn Modul wechselt).
        """
        if isinstance(content, dict):
            return content.get("message", self.MODULE_ID)
        return self.MODULE_ID

    def get_next_wake_seconds(self, env: dict[str, str], state: str) -> int | None:
        """
        Optional: modul-spezifische Wake-Empfehlung für /meta.json.
        None -> Framework-Standardlogik verwenden.
        """
        return None

    def get_background_poll_seconds(self, env: dict[str, str]) -> int | None:
        """
        Optional: eigenes Poll-Intervall für den Background-Worker.
        None -> Framework-Standardlogik verwenden.
        """
        return None


module = MeinModul()   # ← Pflicht: muss 'module' heißen
```

### Schritt 3 – Aktivieren

1. **Server neustarten** – oder in der Weboberfläche auf **„Module neu scannen"** klicken.
2. Unter **Einstellungen → Kern-Einstellungen → Idle-Module** das neue Modul aktivieren.
3. Modul-eigene Einstellungen erscheinen automatisch im neuen Abschnitt.

---

### Eigene Dateien im Modul-Ordner

Für größere Module empfiehlt es sich, Datenabruf und Rendering in separate Dateien aufzuteilen:

```
modules/
└── mein_modul/
    ├── __init__.py       # PlexInkModule-Klasse + module = MeinModul()
    ├── data_source.py    # API-Calls, Parsing, Caching
    └── renderer.py       # PIL-Rendering-Funktionen
```

Innerhalb des Pakets können relative Imports verwendet werden:

```python
# In __init__.py:
from .data_source import fetch_meine_daten
from .renderer import render_meine_ansicht
```

---

### Framework-Utilities

Folgende Helfer aus dem Framework können in Modulen verwendet werden:

| Import | Beschreibung |
|---|---|
| `from app.config import get_cfg` | Aktuellen `RuntimeConfig`-Snapshot lesen |
| `from app.config import load_font` | TrueType-Font laden (gecacht) |
| `from app.http_client import HTTP_SESSION` | Gemeinsame `requests.Session` mit Retry |
| `from app.http_client import download_image` | URL als PIL-Image laden |
| `from app.logger import get_logger` | Strukturierter Logger (JSON) |
| `from app.image_rendering import …` | Shared Rendering-Utilities |

---

## ESP32-Client

Der Sketch unter `esp32/PlexEInk/` verbindet sich per WLAN mit dem Server, prüft periodisch den `/meta.json`-Endpunkt und lädt das Bild nur dann herunter, wenn sich der Hash geändert hat. Die empfohlene Schlafzeit kommt direkt vom Server (`next_wake_sec`).

`next_wake_sec` ist bewusst modular aufgebaut:

- Plex verwendet eine eigene Wake-Logik abhängig vom Wiedergabestatus
- Idle-Module verwenden standardmäßig `IDLE_MODULE_ROTATION_SECONDS`
- einzelne Module können über einen Hook eine eigene Wake-Empfehlung für `/meta.json` liefern

Das ist zum Beispiel für `Gallery` relevant, wenn dort ein eigenes Bildwechsel-Intervall aktiviert ist.

---

## GitHub

Für einen sauberen Start auf GitHub sind jetzt enthalten:

- `.gitignore` für lokale Laufzeitdaten und Entwicklungsartefakte
- `.gitattributes` für konsistente Zeilenenden und Binary-Dateien
- `.env.example` als Einstiegskonfiguration
- `LICENSE` (Non-Commercial)
- `CHANGELOG.md` für Release-Historie
- `CONTRIBUTING.md` für Entwicklungs- und PR-Hinweise
- GitHub Actions CI unter `.github/workflows/ci.yml`

Die CI prüft:

- Python-Bytecode-Compile
- Unit-Tests
- Template-Smoke-Test

---

## License

This project is free for personal use only.

If you want to use this project commercially (e.g. selling devices or services),
please contact me for a commercial license.
