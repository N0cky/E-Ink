#!/bin/sh
set -e

if [ "$(id -u)" = "0" ]; then
    chown -R appuser:appuser /output /logs /config 2>/dev/null || true
    exec gosu appuser "$@"
fi

exec "$@"
