#!/usr/bin/env bash
# Start megacalendar with a local SQLite database (default) or an external PostgreSQL/MySQL server.
#
#   DB_TYPE=sqlite   (default) data in $MEGACALENDAR_DATA_DIR (./data locally, /data in Docker)
#   DB_TYPE=postgres requires DB_HOST, DB_USER, DB_PASSWORD; optional DB_PORT (5432), DB_NAME (megacalendar)
#   DB_TYPE=mysql    requires DB_HOST, DB_USER, DB_PASSWORD; optional DB_PORT (3306), DB_NAME (megacalendar)
#   DATABASE_URL     alternatively a full SQLAlchemy URL, used verbatim
#
# Uploaded artwork is always stored on disk under $MEGACALENDAR_DATA_DIR, also with an external database.
# Extra arguments are passed to uvicorn (e.g. --reload).
set -euo pipefail
cd "$(dirname "$0")/.."

DB_TYPE="${DB_TYPE:-sqlite}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"
export MEGACALENDAR_DATA_DIR="${MEGACALENDAR_DATA_DIR:-$PWD/data}"

if [ -z "${PYTHON:-}" ]; then
  if [ -x .venv/bin/python ]; then PYTHON=.venv/bin/python; else PYTHON=python3; fi
fi

case "$DB_TYPE" in
  sqlite)
    mkdir -p "$MEGACALENDAR_DATA_DIR"
    echo "megacalendar: SQLite database in $MEGACALENDAR_DATA_DIR/megacalendar.db"
    ;;
  postgres|mysql)
    if [ -z "${DATABASE_URL:-}" ]; then
      for var in DB_HOST DB_USER DB_PASSWORD; do
        if [ -z "${!var:-}" ]; then
          echo "megacalendar: DB_TYPE=$DB_TYPE requires $var (and optionally DB_PORT, DB_NAME)" >&2
          exit 2
        fi
      done
      if [ "$DB_TYPE" = postgres ]; then DB_PORT="${DB_PORT:-5432}"; else DB_PORT="${DB_PORT:-3306}"; fi
      export DB_PORT
      echo "megacalendar: waiting for $DB_TYPE at $DB_HOST:$DB_PORT ..."
      "$PYTHON" - "$DB_HOST" "$DB_PORT" "${DB_WAIT_SECONDS:-60}" <<'PY'
import socket, sys, time
host, port, timeout = sys.argv[1], int(sys.argv[2]), float(sys.argv[3])
deadline = time.time() + timeout
while True:
    try:
        with socket.create_connection((host, port), timeout=3):
            break
    except OSError:
        if time.time() > deadline:
            sys.exit(f"database at {host}:{port} not reachable after {timeout:.0f}s")
        time.sleep(1)
PY
    fi
    echo "megacalendar: using $DB_TYPE database, uploads in $MEGACALENDAR_DATA_DIR/uploads"
    ;;
  *)
    echo "megacalendar: DB_TYPE must be sqlite, postgres or mysql (got '$DB_TYPE')" >&2
    exit 2
    ;;
esac

exec "$PYTHON" -m uvicorn megacalendar.main:app --host "$HOST" --port "$PORT" "$@"
