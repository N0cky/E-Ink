#!/bin/sh
# entrypoint.sh — läuft als root, korrigiert Volume-Berechtigungen, wechselt dann zu appuser
set -e

# Gemountete Verzeichnisse auf appuser setzen, damit der Container schreiben kann.
# chown schlägt still fehl wenn ein Verzeichnis nicht existiert (|| true).
chown -R appuser:appuser /app/data/output /app/logs /config 2>/dev/null || true

# Als appuser weiterarbeiten (gosu wechselt Benutzer ohne Shell-Overhead)
exec gosu appuser "$@"
