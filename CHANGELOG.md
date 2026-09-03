# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog and is adapted for the first public releases of this project.

## [Unreleased]

### Added

- New web interface in four areas: **Anzeige** (live image, the programme with one switch per content, drag-and-drop order, tile heights, previews, night plan), **Inhalte** (one card per source, save per card, errors at the field, connection test), **Gerät** (display settings with theme previews, ESP32 status), **System** (events view, time zone, backup and restore, module reload)
- JSON API for the interface: `/api/display`, `/api/settings/<module>`, `/api/probe/<module>`, `/api/settings/export` and `/api/settings/import`, `/api/logs?events=1`
- Module hooks `describe_status()`, `summarize()`, `probe()` and `ENABLED_KEY`; field types `list`, `mapping` and duration display for seconds fields
- `DISPLAY_THEME=eink`: flat theme using only the six Spectra 6 colours, no blur, gradients or shadows – nothing turns into dithering noise on the panel
- Dashboard mode (`IDLE_LAYOUT=dashboard`, `DASHBOARD_TILES`): several idle modules stacked as tiles in one image; new optional module hook `render_tile()`
- `Müllabfuhr` module: municipal ICS collection calendars with bin colours, `{year}` placeholder in the URL, several addresses
- `Kalender` module: ICS calendars (Google, Nextcloud, iCloud, Outlook) with recurring events, time zones, multi-day events and a colour per source
- On-demand module preview `/api/preview/<module>.png` with theme override and 6-colour display simulation, wired into the settings page
- Optional `PLEXINK_UI_PASSWORD` (HTTP Basic Auth for the web UI; ESP32 endpoints stay open)
- Render smoke tests with recorded API fixtures for every module in every theme; test isolation from the local config

### Changed

- Rendering is serialised (one render at a time), images are written atomically and the hash comes from the written bytes – the ESP32 can no longer download a half-written file or a stale hash
- `/refresh`, `/webhook` and saving settings wake the render worker instead of rendering inside the request; Gunicorn runs with 4 threads and a 120 s timeout
- Plex and Steam code, the Plex overlays and the Tagesschau drawing code moved from `app/` into their modules; `app/text_rendering.py` holds the shared text helpers; `ModuleRenderServices` reduced to size, theme and fonts
- Settings status cards and the startup log are generated from every module's `get_runtime_summary()` (labels as keys)
- DWD and Tagesschau headers show the date instead of "Plex ist aktuell idle"
- Data sources back off for 5 minutes after a failed fetch instead of retrying every tick; Plex being unreachable is logged once, not per tick
- Plex posters and Steam artwork are cached between renders; Steam profile resolution no longer caches failures forever
- `/api/logs` reads newest-first and stops at the limit; log file level is INFO
- Secrets never appear in the settings HTML (empty password fields keep the stored value) and are masked in every log line; settings values are quoted on write and no longer exported to the process environment

### Fixed

- Time zones in Docker: hourly weather labels, "Aktualisiert" stamps and weekday names (`Mi` instead of `Wed`) use the configured zone and German names
- A failed render is retried on the next tick instead of leaving the old image up
- Module rescan no longer wipes packages it did not load itself

## [0.1.0] - 2026-04-20

### Added

- Modular content system with auto-discovery for `plex`, `dwd_weather`, `tagesschau`, and `gallery`
- New `Gallery` idle module with local folders, blur background, overlay options, custom interval, and recent-avoidance
- Global web UI theme toggle and shared base layout across dashboard, settings, and logs
- Module hooks for validation, health status, field options, wake intervals, and background poll intervals
- Docker support via `Dockerfile` and `docker-compose.yml`
- GitHub CI workflow for compile checks, tests, and template smoke tests
- `docs/modules.md` for implementing new modules

### Changed

- Migrated production serving to Gunicorn via `wsgi.py`
- Refactored the old idle-module context model into modular service dataclasses
- Improved dashboard diagnostics with wake reason and effective server polling interval
- Standardized log timestamps for local-time rendering in the UI
- Reworked settings page structure for better grouping and navigation

### Fixed

- Gallery custom interval now affects actual background polling cadence
- Gallery recent-avoidance no longer risks recursion depth errors
- Dashboard and logs now render timestamps with timezone awareness
- DWD timeline behavior aligned between day-start and current-hour modes
- Tagesschau card layout no longer clips the last summary line in tight layouts
