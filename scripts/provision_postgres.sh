#!/usr/bin/env bash
# Create the megacalendar database and its user on an existing PostgreSQL server (idempotent).
#
#   scripts/provision_postgres.sh [DB_NAME] [DB_USER] [DB_PASSWORD]      defaults: megacalendar admin admin
#
# Connects as a superuser using the standard libpq variables, e.g.
#   PGHOST=localhost PGPORT=5432 PGUSER=postgres PGPASSWORD=secret scripts/provision_postgres.sh
set -euo pipefail
DB_NAME="${1:-${DB_NAME:-megacalendar}}"
DB_USER="${2:-${DB_USER:-admin}}"
DB_PASSWORD="${3:-${DB_PASSWORD:-admin}}"
command -v psql >/dev/null || { echo "psql not found; install the PostgreSQL client" >&2; exit 1; }

psql -v ON_ERROR_STOP=1 -X -d postgres -v db="$DB_NAME" -v user="$DB_USER" -v pass="$DB_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'user', :'pass')
  WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'user') \gexec
SELECT format('ALTER ROLE %I WITH LOGIN PASSWORD %L', :'user', :'pass') \gexec
SELECT format('CREATE DATABASE %I OWNER %I ENCODING ''UTF8''', :'db', :'user')
  WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'db') \gexec
SELECT format('GRANT ALL PRIVILEGES ON DATABASE %I TO %I', :'db', :'user') \gexec
SQL
psql -v ON_ERROR_STOP=1 -X -d "$DB_NAME" -v user="$DB_USER" <<'SQL'
SELECT format('GRANT ALL ON SCHEMA public TO %I', :'user') \gexec
SQL
echo "PostgreSQL: database '$DB_NAME' owned by '$DB_USER' is ready."
echo "Run the app with: DB_TYPE=postgres DB_HOST=${PGHOST:-localhost} DB_PORT=${PGPORT:-5432} DB_USER=$DB_USER DB_PASSWORD=$DB_PASSWORD scripts/start.sh"
