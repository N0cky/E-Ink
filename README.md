# PlexImageE-Ink

<p align="center">
  <img src="static/logo.png" alt="PlexImageE-Ink logo" width="220">
</p>

PlexImageE-Ink is a self-hosted image server for E-Ink displays.

It renders active live content like Plex playback or the current Steam game, plus configurable idle content like weather, news, and gallery images into a display-ready image that can be fetched by an ESP32 or another lightweight client. The client only needs to wake up briefly, check whether the image changed, download it if needed, and go back to sleep.

Supported output modes:

- `PNG` for regular displays or preview workflows
- `BMP` with dithering for Waveshare Spectra 6 E-Ink displays

---

## Why This Project

- Designed for low-power E-Ink clients that should sleep most of the time
- Optimized for a "now playing" use case with Plex and Steam as primary live sources
- Falls back to modular idle content when nothing is playing
- Fully self-hosted and configurable through a browser UI
- Built to be extensible through standalone modules instead of hard-coded features

---

## Features

- **Plex integration** – automatically shows active movies, TV episodes, and music with cover art, metadata, and progress bars
- **Steam integration** – shows the currently played Steam game for a configured profile with cover art, avatar, and status
- **DWD weather** – current conditions, hourly timeline, multi-day forecast, UV index, and pollen data from the German Weather Service
- **Tagesschau news** – current news cards with thumbnail and teaser text
- **Müllabfuhr** – next garbage collection days from your municipality's ICS calendar, bin colours included, with a `{year}` placeholder so the URL never needs a yearly update
- **Kalender** – today and the next days from one or more ICS calendars (Google, Nextcloud, iCloud, Outlook), with recurring events, a colour per calendar and multi-day events
- **Dashboard mode** – instead of rotating full-screen modules, stack several of them as tiles in one image (`IDLE_LAYOUT=dashboard`): weather on top, calendar in the middle, garbage or news below. Fewer display refreshes, more information per glance
- **Gallery** – local image folders as an idle module with random selection, blur background, and optional overlay
- **Modular architecture** – add new content sources as standalone modules without touching the core framework
- **Dark and light themes** – optimized for OLED-like displays and Waveshare Spectra 6 E-Ink panels
- **Web UI** – four pages that follow the user's questions: *Anzeige* (what the display shows, with the programme, switches, order and previews), *Inhalte* (one card per source with its own save button and a connection test), *Gerät* (display and ESP32 status), *System* (events, time zone, backup and restore)
- **Docker-ready** – container startup via `Dockerfile` and `docker-compose.yml`
- **WSGI-ready** – production container startup through Gunicorn with a clean runtime bootstrap

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
- [Unraid Deployment](#unraid-deployment)
- [Configuration](#configuration)
- [API Endpoints](#api-endpoints)
- [Project Structure](#project-structure)
- [Module System](#module-system)
- [Create a New Module](#create-a-new-module)
- [ESP32 Client](#esp32-client)
- [GitHub](#github)
- [License](#license)

### Local Development

```bash
# Clone the repository
git clone https://github.com/N0cky/E-Ink.git
cd E-Ink

# Create and activate a virtual environment
python -m venv .venv
.venv/Scripts/activate        # Windows
# source .venv/bin/activate   # Linux / macOS

# Install dependencies
pip install -r app/requirements.txt

# Create the config file
mkdir config
copy config\settings.env.example config\settings.env      # Windows PowerShell / CMD
# mkdir -p config && cp config/settings.env.example config/settings.env   # Linux / macOS

# Start the server
python app/server.py
```

The web UI is then available at `http://localhost:8787`.

### Docker

```bash
mkdir config
copy config\settings.env.example config\settings.env      # Windows
# mkdir -p config && cp config/settings.env.example config/settings.env   # Linux / macOS

docker compose up --build -d
```

The containerized app is also available at `http://localhost:8787`.

---

## Requirements

- Python 3.11 or newer
- pip / venv
- Optional: an ESP32 using the included firmware sketch in `esp32/`

---

## Runtime Model

The server keeps the latest rendered image on disk and exposes it over HTTP.

Typical flow:

1. A priority module like Plex or Steam provides live content if active.
2. Otherwise the configured idle modules rotate automatically.
3. The client checks `/meta.json` for hash, format, and the suggested sleep interval.
4. The client downloads the image only when it actually changed.

This keeps the display logic simple while letting the server handle data fetching, rendering, and wake timing.

---

## Docker Deployment

### With Docker Compose

```bash
# Create the config file
mkdir config
copy config\settings.env.example config\settings.env      # Windows
# mkdir -p config && cp config/settings.env.example config/settings.env   # Linux / macOS

# Build and start the container
docker compose up --build -d
```

The web UI is then available at `http://localhost:8787`.

Persistent directories:

- `./config` – runtime configuration file
- `./data/output` – rendered images
- `./logs` – JSON logs

### Direct Docker Usage

```bash
docker build -t pleximagee-ink .
docker run --rm -p 8787:8787 \
  -e PLEXINK_CONFIG_FILE=/config/settings.env \
  -v ./config:/config \
  -v ./data/output:/output \
  -v ./logs:/logs \
  pleximagee-ink
```

### Production Notes

The container starts through Gunicorn:

```bash
gunicorn --workers 1 --threads 4 --timeout 120 --bind 0.0.0.0:8787 wsgi:app
```

The container intentionally uses **one worker**. The project runs its own background worker for rendering and module rotation, so multiple Gunicorn workers would otherwise start multiple parallel render loops. The four threads keep the ESP32 endpoints responsive while someone is using the web UI.

For local development, `python app/server.py` remains the simplest path. In Docker or production-like environments, the project should run through Gunicorn as a WSGI server.

### Security Notes

- The web UI has **no authentication by default**. It is meant for a trusted home network.
- Set `PLEXINK_UI_PASSWORD` as a container environment variable to protect all pages and `/api/*` routes with HTTP Basic Auth (any username, that password). The endpoints the ESP32 needs (`/hash`, `/meta.json`, `/current.png`, `/current.bmp`, `/ack`, `/health`) stay open so the device does not need credentials.
- Secrets such as the Plex token or the Steam API key are never written into the settings page HTML. The field shows as empty; leaving it empty on save keeps the stored value.
- Query parameters that carry secrets (`X-Plex-Token`, `key`, `token`, …) are masked in every log line.
- Values in `config/settings.env` are written quoted when needed and read without variable interpolation. Settings are never exported to the process environment.

---

## Unraid Deployment

The recommended way to use this project on Unraid is a published container image from GitHub Container Registry.

Planned image format:

- `ghcr.io/n0cky/e-ink:latest`
- `ghcr.io/n0cky/e-ink:0.1.0`

This repository is now prepared for that flow:

- Git tags like `v0.1.0` trigger an automatic Docker publish workflow
- Images are published to `ghcr.io`
- Multi-arch builds are prepared for `linux/amd64` and `linux/arm64`

### Unraid Container Settings

Typical Unraid mapping:

- Repository:
  - `ghcr.io/n0cky/e-ink:latest`
- Port:
  - `8787` container -> `8787` host
- Environment:
  - `PLEXINK_CONFIG_FILE=/config/settings.env` (already the image default)
  - `PLEXINK_UI_PASSWORD=...` (optional, protects the web UI with Basic Auth)
- AppData / volumes:
  - `/mnt/user/appdata/pleximagee-ink/config` -> `/config`
  - `/mnt/user/appdata/pleximagee-ink/output` -> `/output`
  - `/mnt/user/appdata/pleximagee-ink/logs` -> `/logs`

Keep the main runtime configuration in `/config/settings.env`.

### First Release to GHCR

Once the GitHub repository exists and your first push succeeded:

```bash
git tag v0.1.0
git push origin main --tags
```

After that, GitHub Actions will build and publish the image automatically.

If you want Unraid to pull the image without GitHub authentication, make sure the published GHCR package is set to `public`.

---

## Configuration

All settings can be managed through the web UI (`/` for the programme, `/inhalte` for sources, `/geraet` for the display, `/system` for time zone and maintenance), or directly in an env-style config file. The UI writes the same keys, so both ways stay in sync.

Config file lookup:

1. `PLEXINK_CONFIG_FILE`
2. `./config/settings.env`

Recommended setup for all environments:

- `./config/settings.env`

| Variable | Description | Default |
|---|---|---|
| `PORT` | HTTP port for the server | `8787` |
| `RENDER_WIDTH` | Render width in pixels | `1600` |
| `RENDER_HEIGHT` | Render height in pixels | `1200` |
| `DISPLAY_ROTATION` | Rotation: `0`, `90`, `180`, `270` | `0` |
| `DISPLAY_THEME` | `dark`, `light` or `eink` (flat Spectra 6 colours, no blur or gradients, recommended for the E-Ink display) | `dark` |
| `OUTPUT_FORMAT` | `png` or `bmp` (Spectra 6) | `png` |
| `REFRESH_INTERVAL` | Poll interval in seconds | `60` |
| `TIMEZONE` | IANA timezone, for example `Europe/Berlin` | `Europe/Berlin` |
| `IDLE_MODULES` | Active idle modules, comma-separated | `` |
| `IDLE_LAYOUT` | `rotation` (one module per image, in turns) or `dashboard` (several modules stacked as tiles in one image) | `rotation` |
| `DASHBOARD_TILES` | Tile order and heights for the dashboard, e.g. `dwd_weather:45, calendar:30, garbage:25`. Modules without a percentage share the rest. Empty: all active idle modules with equal height | `` |
| `IDLE_MODULE_ROTATION_SECONDS` | Rotation interval between idle modules | `120` |
| `NIGHT_MODE_ENABLED` | Enable reduced refreshes during a local night window | `false` |
| `NIGHT_MODE_START` | Local start time for night mode (`HH:MM`) | `23:00` |
| `NIGHT_MODE_END` | Local end time for night mode (`HH:MM`) | `07:00` |
| `NIGHT_MODE_INTERVAL_MINUTES` | Idle refresh interval during night mode | `15` |
| `NIGHT_MODE_IDLE_BEHAVIOR` | `rotate` or `fixed` idle behavior at night | `rotate` |
| `NIGHT_MODE_FIXED_MODULE` | Idle module to pin during night mode when behavior is `fixed` | `` |
| `PLEX_BASE_URL` | Plex server URL | `` |
| `PLEX_TOKEN` | Plex API token | `` |
| `STEAM_PROFILE` | SteamID64, vanity name, or Steam profile URL | `` |
| `STEAM_API_KEY` | Steam Web API key | `` |
| `STEAM_MODULE_ENABLED` | Enable Steam live game detection | `false` |

Module-specific variables such as DWD station, pollen region, or gallery paths are defined by the modules themselves and are also managed through the web UI.

When settings are changed through the web UI, the application writes them back to the active config file path.

---

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/current.png` | GET | Current image as PNG |
| `/current.bmp` | GET | Current image as BMP (only when `OUTPUT_FORMAT=bmp`) |
| `/meta.json` | GET | Hash, format, status, and suggested sleep interval |
| `/health` | GET | Health check for Docker and monitoring |
| `/hash` | GET | MD5 hash of the current image (plain text) |
| `/ack` | POST | Acknowledgement from the display client |
| `/refresh` | POST | Force an immediate re-render |
| `/webhook` | POST | Plex webhook receiver |
| `/api/status` | GET | Runtime status including loaded modules |
| `/api/modules` | GET | List of all discovered modules |
| `/api/rescan-modules` | POST | Reload modules without restarting the server |
| `/api/preview/<module_id>.png` | GET | Render one module on demand without touching the display. `?theme=dark\|light\|eink` overrides the theme, `?device=1` returns the 6-colour Spectra preview, `dashboard` renders all tiles. 404 with a JSON message when the module has no content |
| `/api/display` | GET, PUT | What the display shows, the programme (content modules with on/off, order, tile heights, status), live sources, night plan, device status. PUT accepts the same shape and writes the settings |
| `/api/settings/<module_id>` | GET, PUT | Fields of one module card (`framework` for device and system fields) with current values; PUT validates and returns errors per field. Passwords are never returned, an empty password keeps the stored one |
| `/api/probe/<module_id>` | POST | Fetch the module's source once and report the result in one sentence |
| `/api/logs?events=1` | GET | Only events (content switched, device reported, settings saved, source unreachable) instead of every render line |

---

## Project Structure

```
PlexImageE-Ink/
│
├── app/                        # Framework core (no module-specific code)
│   ├── server.py               # Flask server, render loop, and API routes
│   ├── config.py               # Configuration, RuntimeConfig, and env-file I/O
│   ├── logger.py               # JSONL + console logging with secret masking
│   ├── module_base.py          # PlexInkModule base class for all modules
│   ├── module_registry.py      # Module auto-discovery and hot reload
│   ├── module_services.py      # ModuleRenderServices (size, theme, fonts)
│   ├── http_client.py          # Shared HTTP client, image download + cache
│   ├── image_rendering.py      # Shared image helpers (crop, blur, canvas, Spectra 6)
│   └── text_rendering.py       # Shared text helpers (wrap, fit, draw lines)
│
├── modules/                    # Fully self-contained modules
│   ├── plex/
│   │   ├── __init__.py         # Plex module (priority 0)
│   │   ├── plex.py             # Plex API client, session parsing, artwork
│   │   └── renderer.py         # Now-playing overlays (video/music, dark/light)
│   ├── steam/
│   │   ├── __init__.py         # Steam module (priority 1)
│   │   ├── steam.py            # Steam API client (profile resolution, artwork)
│   │   └── renderer.py         # Steam-specific image rendering
│   ├── dwd_weather/
│   │   ├── __init__.py         # Module entry point
│   │   ├── dwd.py              # DWD weather data source
│   │   ├── dwd_pollen.py       # Pollen data source
│   │   ├── dwd_uv.py           # UV index data source
│   │   └── renderer.py         # Image rendering
│   ├── calendar_ics/
│   │   ├── __init__.py         # Kalender module (priority 106)
│   │   ├── data_source.py      # ICS parser with RRULE/EXDATE, timezones, multi-source cache
│   │   └── renderer.py         # Today + upcoming days, colour bar per calendar
│   ├── garbage/
│   │   ├── __init__.py         # Müllabfuhr module (priority 105)
│   │   ├── data_source.py      # ICS parser, {year} handling, bin colour mapping
│   │   └── renderer.py         # Next pickup hero + upcoming list
│   ├── gallery/
│   │   ├── __init__.py         # Module entry point
│   │   ├── data_source.py      # File discovery and image selection
│   │   └── renderer.py         # Image rendering
│   └── tagesschau/
│       ├── __init__.py         # Module entry point
│       ├── data_source.py      # Data source and image cache
│       └── renderer.py         # Image rendering
│
├── .github/workflows/          # GitHub Actions workflows
├── .gitattributes              # Line ending and binary file hints
├── CHANGELOG.md                # Release history
├── CONTRIBUTING.md             # Contribution guidelines
├── Dockerfile                  # Container build definition
├── docker-compose.yml          # Local container startup
├── wsgi.py                     # Gunicorn/WSGI entry point
├── templates/                  # Jinja2 HTML templates
├── font/                       # Font Awesome files for weather icons
├── esp32/                      # Arduino sketch for the E-Ink client
├── config/
│   ├── settings.env.example    # Example runtime configuration
│   └── settings.env            # Local runtime configuration (do not commit)
├── data/output/                # Rendered images and state file
├── logs/                       # JSON log files
└── ...
```

---

## Module System

The framework is intentionally lightweight. All display logic lives in modules under `modules/`. On startup, the server scans this directory automatically and registers every valid module it finds. Modules can also be reloaded at runtime through the web UI without restarting the server.

### Priorities

| `MODULE_PRIORITY` | Type | Behavior |
|---|---|---|
| `< 10` | **Priority module** | Overrides all idle modules as soon as it provides content, for example Plex or Steam during live activity |
| `>= 10` | **Idle module** | Rotates when no priority module is active |

---

## Create a New Module

A module consists of a folder under `modules/` with a `__init__.py`. Additional files for data fetching, parsing, caching, or rendering can be organized freely inside the same folder.

### Step 1 – Create a Folder

```
modules/
└── my_module/
    └── __init__.py
```

### Step 2 – Write `__init__.py`

```python
from __future__ import annotations
from typing import Any
from PIL import Image, ImageDraw
from app.module_base import PlexInkModule
from app.logger import get_logger

log = get_logger(__name__)


# Settings fields (automatically appear in the web UI)

SETTINGS_FIELDS: list[dict] = [
    {
        "name":        "MEIN_MODUL_API_KEY",
        "label":       "API Key",
        "type":        "text",           # text | number | password | select |
                                         # checkbox_group | priority_list | list | mapping
                                         # (see docs/modules.md for list/mapping item_fields)
        "wide":        True,             # True = volle Breite im Formular
        "placeholder": "abc123",
        "help":        "API key for the external service.",
    },
    {
        "name":        "MEIN_MODUL_REFRESH",
        "label":       "Refresh (s)",
        "type":        "number",
        "wide":        False,
        "placeholder": "300",
        "min":         60,
        "max":         86400,
        "help":        "How often data should be refreshed.",
    },
]

# Optional field groups for the settings page
SETTINGS_GROUPS: list[dict] = [
    {
        "title":  "Connection",
        "desc":   "Access details for the external service.",
        "fields": ["MEIN_MODUL_API_KEY", "MEIN_MODUL_REFRESH"],
    },
]


# Module implementation

class MyModule(PlexInkModule):
    MODULE_ID          = "my_module"             # unique ID, lowercase + underscores
    MODULE_NAME        = "My Module"            # display name in the web UI
    MODULE_DESCRIPTION = "Short description."
    MODULE_PRIORITY    = 120                    # >= 10 means idle module

    SETTINGS_FIELDS = SETTINGS_FIELDS
    SETTINGS_GROUPS = SETTINGS_GROUPS

    def is_enabled(self, env: dict[str, str]) -> bool:
        """Return False to skip the module entirely."""
        return "my_module" in env.get("IDLE_MODULES", "")

    def fetch_content(self, env: dict[str, str]) -> Any | None:
        """
        Fetch data from an API, file, cache, or other source.
        Return None when the module currently has no content.
        """
        api_key = env.get("MEIN_MODUL_API_KEY", "").strip()
        if not api_key:
            return None

        # Your own data-fetching logic goes here:
        # from .data_source import fetch_meine_daten
        # return fetch_meine_daten(api_key)
        return {"message": "Hello World", "api_key": api_key}

    def render(self, env: dict[str, str], content: Any) -> Image.Image:
        """Render the module content into a PIL image."""
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
        Return True to force re-rendering even when the state key
        is unchanged. Useful for time-based cache invalidation.
        """
        return False

    def get_state_key(self, content: Any) -> str:
        """
        Unique fingerprint of the current content. When it changes,
        the framework re-renders. Default behavior is effectively
        "render whenever the active module changes".
        """
        if isinstance(content, dict):
            return content.get("message", self.MODULE_ID)
        return self.MODULE_ID

    def get_next_wake_seconds(self, env: dict[str, str], state: str) -> int | None:
        """
        Optional: module-specific wake recommendation for /meta.json.
        Return None to fall back to the framework default.
        """
        return None

    def get_background_poll_seconds(self, env: dict[str, str]) -> int | None:
        """
        Optional: custom poll interval for the background worker.
        Return None to use the framework default.
        """
        return None


module = MyModule()   # must be exported as "module"
```

### Step 3 – Enable the Module

1. **Restart the server** or click **"Rescan modules"** in the web UI.
2. Enable the module under **Settings -> Core Settings -> Idle Modules**.
3. Module-specific settings will appear automatically in their own section.

---

### Additional Files Inside the Module Folder

For larger modules, it makes sense to split fetching and rendering into separate files:

```
modules/
└── my_module/
    ├── __init__.py       # PlexInkModule class + module = MyModule()
    ├── data_source.py    # API calls, parsing, caching
    └── renderer.py       # PIL rendering helpers
```

Relative imports can be used inside the package:

```python
# In __init__.py:
from .data_source import fetch_meine_daten
from .renderer import render_meine_ansicht
```

---

### Framework Utilities

These helpers from the framework are available inside modules:

| Import | Description |
|---|---|
| `from app.config import get_cfg` | Read the current `RuntimeConfig` snapshot |
| `from app.config import load_font` | Load a cached TrueType font |
| `from app.http_client import HTTP_SESSION` | Shared `requests.Session` with retry behavior |
| `from app.http_client import download_image` | Load a URL into a PIL image |
| `from app.logger import get_logger` | Structured JSON logger |
| `from app.image_rendering import ...` | Shared rendering utilities |

---

## ESP32 Client

The sketch in `esp32/PlexEInk/` connects to the server over Wi-Fi, periodically checks `/meta.json`, and downloads the image only when the hash changed. The suggested sleep interval also comes directly from the server through `next_wake_sec`.

`next_wake_sec` is intentionally modular:

- Plex and Steam use their own wake logic while active
- Idle modules use `IDLE_MODULE_ROTATION_SECONDS` by default
- Night mode can temporarily slow idle refreshes and optionally pin a single idle module within a local time window
- Individual modules can provide their own wake recommendation for `/meta.json` through a hook

This is especially relevant for `Gallery` when a custom image change interval is enabled.

---

## GitHub

The repository is now prepared for a clean GitHub setup with:

- `.gitignore` for local runtime data and development artifacts
- `.gitattributes` for consistent line endings and binary files
- `config/settings.env.example` as a starting configuration
- `LICENSE` (Non-Commercial)
- `CHANGELOG.md` for release history
- `CONTRIBUTING.md` for development and pull request guidance
- GitHub Actions CI in `.github/workflows/ci.yml`
- Docker publish workflow in `.github/workflows/docker-publish.yml`

The CI currently checks:

- Python bytecode compilation
- Unit tests
- Template smoke test

---

## License

This project is free for personal use only.

If you want to use this project commercially (e.g. selling devices or services),
please contact me for a commercial license.
