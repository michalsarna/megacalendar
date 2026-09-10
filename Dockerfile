FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHON=python \
    MEGACALENDAR_DATA_DIR=/data \
    MEGACALENDAR_FONT_DIR=/app/assets/fonts

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY megacalendar ./megacalendar
COPY assets ./assets
COPY scripts ./scripts

# Editable install keeps the code (and the bundled fonts) under /app.
RUN pip install --no-cache-dir -e ".[postgres,mysql]" && chmod +x scripts/*.sh

# SQLite database (when DB_TYPE=sqlite) and uploaded artwork (always) live here.
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/meta')" || exit 1

ENTRYPOINT ["scripts/start.sh"]
