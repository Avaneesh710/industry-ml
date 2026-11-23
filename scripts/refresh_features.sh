#!/usr/bin/env bash
# Rebuilds the stored feature panel from the current raw tables, then prints
# a one-line summary of what it holds.
set -euo pipefail

cd "$(dirname "$0")/.."

set -a
source .env
set +a
export PGCONNECT_TIMEOUT=10

# The migration in init_db.sh rebuilds the panel at the start of the pipeline, before ingestion.
# If ingestion then loads a new month, the panel is out of date. REFRESH MATERIALIZED VIEW re-runs the stored query against the current raw tables.

psql -w -v ON_ERROR_STOP=1 -q -c "REFRESH MATERIALIZED VIEW features.panel" # psql -c "…" runs one SQL command from the command line, with no file needed.
psql -w -v ON_ERROR_STOP=1 -q -t -A -c \
  "SELECT count(*) || ' rows, ' || min(month) || ' to ' || max(month) FROM features.panel"

# In the summary query, -t prints only the result rows (no column headers) and -A drops the table borders.
# || joins text in SQL, so the output is one tidy line: 33593 rows, 1969-07-01 to 2026-09-01.

# The first six lines repeat init_db.sh's set-up. Two copies are manageable; with a third script it would be worth moving them into one shared file that each script loads with source.

