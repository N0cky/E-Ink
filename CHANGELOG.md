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
- `Müllabfuhr`: reminder banner "Morgen rausstellen" from an evening hour (`GARBAGE_REMINDER_HOUR`), the module is then interleaved into the rotation and moved to the top of the dashboard; collection counts as done from `GARBAGE_DONE_HOUR`; shifted dates show "verschoben, sonst Montag"; week strip with icons per bin type (`GARBAGE_UPCOMING_STYLE`), one column per address (`GARBAGE_LAYOUT=columns`), icons for sack, paper, bulky waste and Christmas tree; last successful calendar is kept on disk and shown with "Stand vom …" when the source is down; missing year calendars (404) are reported instead of an empty tile; "Verbindung prüfen" lists the next dates and how every summary is classified
- Module hook `is_urgent()`; `probe()` may return `details` lines shown under the result
- `SHOW_RENDER_TIME` (Gerät page): optional "Stand HH:MM" pill top right on every page, so a stale image is recognisable when the server or the WLAN is down
- Firmware 1.2.0: offline banner – after three cycles without server contact the device redraws the last image from its flash file system with a black bar "Keine Verbindung zum Server seit HH:MM" (or "Kein WLAN …"); embedded bitmap font (`esp32/tools/make_font.py`); clock set from the server (`epoch`, `tz_offset_sec` in `/meta.json`); panel cleaning cycle scheduled by the server (`PANEL_CLEAN_INTERVAL_DAYS`, `PANEL_CLEAN_HOUR`); "nicht eingerichtet" page when Wi-Fi or server are not configured; "Auf dem Display ausprobieren" button on the Gerät page shows the offline banner once for real
- Firmware 1.1.x and device services: over-the-air updates hosted by the server (upload on the *Gerät* page, `/firmware.json`, `/firmware.bin` with `x-MD5`, version read from the binary). Rollback lives in the firmware itself with its memory in NVS: two starts without server contact roll back to the previous partition, the rolled-back version is reported and not retried; verified on the device with a deliberately broken self-test build, compact 4-bpp image `/current.epd` (960 KB instead of 5.8 MB, written straight to the panel), health data in every acknowledgement (RSSI, firmware, boot count, PSRAM, timings, last error) shown on the *Gerät* page, and the device's serial log shipped with the acknowledgement and shown under *System → Gerät*
- E-Ink theme tuned on the real panel: the black bin is hollow so it stays distinguishable from the (very dark) green one, the moon phase disc is yellow/black instead of white on white, photos in Tagesschau and Gallery get contrast and colour boosted before dithering
- `Kalender` module: ICS calendars (Google, Nextcloud, iCloud, Outlook) with recurring events, time zones, multi-day events and a colour per source
- `Kalender`: the last good calendar of every source is kept on disk and shown with "Stand vom …" when the source is down; errors are tracked per source (the programme row says which calendar is unreachable, the status turns red only when nothing was ever loaded); "Verbindung prüfen" lists events per source and the next six appointments; the programme summary shows the next appointment
- Schedule (`SCHEDULE_WINDOWS`, card *Zeitplan* on the Anzeige page): time windows per weekday with their own contents (incl. tile order and heights), layout and interval; the first matching window wins, empty fields inherit from the programme, windows may run past midnight. The device is woken exactly at window borders. The old night mode keeps working while no schedule is saved and is shown as a window "Nachts" that the first save converts
- New logo: a flat panel with four dashboard tiles in the Spectra 6 colours (`logo.svg`, `static/logo.svg`, wordmark `static/wordmark.svg`, PNGs in 512, 180 and 32 px). Replaces the glossy placeholder; used as favicon, in the page header, the README and as default avatar of the notifications
- Rich notifications (`app/notifications.py`): Discord webhooks receive embeds with bot name, avatar (project logo or `NOTIFY_AVATAR_URL`), colour per event, fields, footer, timestamp, link to the Gerät page (`NOTIFY_BASE_URL`) and the current display image as attachment; ntfy gets icon, click link and the image as attachment; Slack gets blocks. Events selectable in `NOTIFY_EVENTS`: outage and recovery, firmware update and rollback, three device errors in a row, a content showing cached data for more than 6 h (and its recovery), a morning picture (`NOTIFY_DAILY_HOUR`) and a Monday report with the week's statistics. Markers live in `device_state.json` so restarts repeat nothing; the test button sends the full format
- Watching the device: every acknowledgement is kept in `data/output/ack_history.jsonl`; the *Gerät* page shows a card "Verlauf des Geräts" with statistics (messages, longest gap, gaps over threshold, average cycle, weakest signal, errors), a chart (RSSI line, cycle bars, error marks, 24 h or 7 days) and the last ten acknowledgements (`/api/device/history`). Notification via `NOTIFY_URL` (ntfy topic, Discord or Slack webhook, plain text POST otherwise) once the device has been silent for `NOTIFY_OFFLINE_MINUTES` and again when it is back, with a test button on the Gerät page; the last acknowledgement survives a server restart. `/metrics` in Prometheus text format: renders and errors per content, acknowledgements per result, image age, device gauges, content states, active schedule window
- Panel polish: the temperature curve of the E-Ink weather page is hatched instead of a solid blue block; the weather page scales below 1200 px (600×800, 800×480 no longer overlap); photo preparation for the panel no longer brightens and adds less contrast, so faces keep their detail while clothes and objects stay clean
- `PLEXINK_GALLERY_ROOTS` (container environment): optional allowlist of root folders for the Gallery module – folders outside are rejected on save, skipped when scanning (symlinks leading out included) and reported in the content status
- Render history: the last 24 images the display received are kept as small PNGs (`data/output/history/`) with time and content; the *Anzeige* page shows them as a strip under the live image, clicking one shows it large. `/api/history` lists them, `DELETE /api/history` clears them
- Weather: the pollen strip picks its layout from the available height – the two-column grid when there is room, otherwise compact chips (peak value plus three day dots per allergen), so a season full of "0-1" values no longer squeezes the hourly chart; on the E-Ink theme a "0" is a hollow circle with black text instead of white on white; the dashboard tile shows pollen chips when there is space below the forecast
- On-demand module preview `/api/preview/<module>.png` with theme override and 6-colour display simulation, wired into the settings page
- Optional `PLEXINK_UI_PASSWORD` (HTTP Basic Auth for the web UI; ESP32 endpoints stay open)
- Render smoke tests with recorded API fixtures for every module in every theme; test isolation from the local config

### Changed

- Renamed to **Inkwall** (the previous name carried two trademarks). Environment variables use the prefix `INKWALL_`, the old `PLEXINK_` prefix keeps working; the firmware version marker is `INKWALL_FW_VERSION=` and the server still reads `PLEXEINK_FW_VERSION=` from older builds; the module base class is `InkwallModule` with `PlexInkModule` kept as an alias; the firmware sketch lives in `esp32/Inkwall`; Prometheus metrics are prefixed `inkwall_`
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

- Renamed to **Inkwall** (the previous name carried two trademarks). Environment variables use the prefix `INKWALL_`, the old `PLEXINK_` prefix keeps working; the firmware version marker is `INKWALL_FW_VERSION=` and the server still reads `PLEXEINK_FW_VERSION=` from older builds; the module base class is `InkwallModule` with `PlexInkModule` kept as an alias; the firmware sketch lives in `esp32/Inkwall`; Prometheus metrics are prefixed `inkwall_`
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
