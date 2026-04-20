#!/bin/sh
# entrypoint.sh — läuft als root, korrigiert Volume-Berechtigungen, wechselt dann zu appuser
set -e

# Gemountete Verzeichnisse auf appuser setzen, damit der Container schreiben kann.
# Pfade entsprechen den Docker-Umgebungsvariablen PLEXINK_OUTPUT_DIR / PLEXINK_LOGS_DIR.
chown -R appuser:appuser /output /logs /config 2>/dev/null || true

# Als appuser weiterarbeiten (gosu wechselt Benutzer ohne Shell-Overhead)
exec gosu appuser "$@"
