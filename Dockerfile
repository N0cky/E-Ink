FROM python:3.13-slim

LABEL org.opencontainers.image.title="PlexImageE-Ink" \
      org.opencontainers.image.description="Self-hosted image server for E-Ink now playing and idle dashboards." \
      org.opencontainers.image.licenses="E-Ink Now Playing Display License (Non-Commercial)"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# gosu: sicherer Benutzerwechsel im Entrypoint (root → appuser nach Volume-chown)
RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/*

RUN adduser --disabled-password --gecos "" appuser

COPY app/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

COPY . /app

# Verzeichnisse im Image anlegen; Entrypoint überschreibt Berechtigungen der Mounts zur Laufzeit
RUN mkdir -p /app/data/output /app/logs /config \
    && chown -R appuser:appuser /app /config \
    && chmod +x /app/entrypoint.sh

EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/health', timeout=3)"

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "--workers", "1", "--bind", "0.0.0.0:8787", "wsgi:app"]
