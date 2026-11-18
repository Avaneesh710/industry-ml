#!/usr/bin/env bash
# Creates the project role and database (idempotent), then applies every
# migration in sql/ in filename order. Safe to re-run.
set -euo pipefail         # -e means stop on any error, -u means treat undefined variables as undefined error, fails a pipeline if any part of it fails
cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
  echo "No .env file found. Copy .env.example to .env and fill it in." >&2
  exit 1
fi

set -a
source .env  # exports every variable in .env so psql can see them
set +a
# Fail instead of waiting for a password prompt, and give up fast if the server is down.
export PGCONNECT_TIMEOUT=10

echo "Creating role '$PGUSER' and database '$PGDATABASE' if missing..."
# format() builds each SQL statement as text and \gexec runs it.
# %I quotes a name (identifier) and %L quotes a value (literal) safely,
# which prevents SQL injection.
PGPASSWORD="$PG_SUPERUSER_PASSWORD" psql -w -U "$PG_SUPERUSER" -d postgres \
  -v ON_ERROR_STOP=1 -q \
  -v app_user="$PGUSER" -v app_pw="$PGPASSWORD" -v app_db="$PGDATABASE" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'app_user', :'app_pw')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_user') \gexec

SELECT format('CREATE DATABASE %I OWNER %I', :'app_db', :'app_user')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'app_db') \gexec
SQL

for f in sql/*.sql; do
  echo "Applying $f"
  PGOPTIONS="-c client_min_messages=warning" psql -w -v ON_ERROR_STOP=1 -q -f "$f"
done

echo "Database ready."