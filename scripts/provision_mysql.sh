#!/usr/bin/env bash
# Create the megacalendar database and its user on an existing MySQL/MariaDB server (idempotent).
#
#   scripts/provision_mysql.sh [DB_NAME] [DB_USER] [DB_PASSWORD]         defaults: megacalendar admin admin
#
# Connects as an administrative user:
#   MYSQL_HOST=localhost MYSQL_TCP_PORT=3306 MYSQL_ADMIN_USER=root MYSQL_PWD=secret scripts/provision_mysql.sh
# (MYSQL_PWD is read by the mysql client; omit it to be prompted.)
set -euo pipefail
DB_NAME="${1:-${DB_NAME:-megacalendar}}"
DB_USER="${2:-${DB_USER:-admin}}"
DB_PASSWORD="${3:-${DB_PASSWORD:-admin}}"
MYSQL_HOST="${MYSQL_HOST:-localhost}"
MYSQL_TCP_PORT="${MYSQL_TCP_PORT:-3306}"
MYSQL_ADMIN_USER="${MYSQL_ADMIN_USER:-root}"
command -v mysql >/dev/null || { echo "mysql client not found" >&2; exit 1; }

args=(--host="$MYSQL_HOST" --port="$MYSQL_TCP_PORT" --protocol=TCP --user="$MYSQL_ADMIN_USER")
[ -n "${MYSQL_PWD:-}" ] || args+=(-p)

# Escape single quotes/backslashes so the values are safe inside SQL string literals.
esc() { printf '%s' "$1" | sed "s/\\\\/\\\\\\\\/g; s/'/\\\\'/g"; }
U=$(esc "$DB_USER"); P=$(esc "$DB_PASSWORD")

mysql "${args[@]}" <<SQL
CREATE DATABASE IF NOT EXISTS \`$DB_NAME\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '$U'@'%' IDENTIFIED BY '$P';
ALTER USER '$U'@'%' IDENTIFIED BY '$P';
GRANT ALL PRIVILEGES ON \`$DB_NAME\`.* TO '$U'@'%';
FLUSH PRIVILEGES;
SQL
echo "MySQL: database '$DB_NAME' and user '$DB_USER' are ready."
echo "Run the app with: DB_TYPE=mysql DB_HOST=$MYSQL_HOST DB_PORT=$MYSQL_TCP_PORT DB_USER=$DB_USER DB_PASSWORD=$DB_PASSWORD scripts/start.sh"
echo "The application user 'master' (password 'master') is created automatically on first start;"
echo "change it with: python scripts/manage_users.py set-password master"
