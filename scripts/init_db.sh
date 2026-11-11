#!/usr/bin/env bash
# Creates the project role and database (idempotent), then applies every
# migration in sql/ in filename order. Safe to re-run.
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
  echo "No .env file found. Copy .env.example to .env and fill it in." >&2
  exit 1
fi

set -a
source .env
set +a

echo "Creating role '$PGUSER' and database '$PGDATABASE' if missing..."
PGPASSWORD="$PG_SUPERUSER_PASSWORD" psql -U "$PG_SUPERUSER" -d postgres \
  -v ON_ERROR_STOP=1 -q \
  -v app_user="$PGUSER" -v app_pw="$PGPASSWORD" -v app_db="$PGDATABASE" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'app_user', :'app_pw')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_user') \gexec

SELECT format('CREATE DATABASE %I OWNER %I', :'app_db', :'app_user')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'app_db') \gexec
SQL

for f in sql/*.sql; do
  echo "Applying $f"
  PGOPTIONS="-c client_min_messages=warning" psql -v ON_ERROR_STOP=1 -q -f "$f"
done

echo "Database ready."