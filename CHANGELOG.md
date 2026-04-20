# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog and is adapted for the first public releases of this project.

## [Unreleased]

- Ongoing refinements before the first public release.

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
