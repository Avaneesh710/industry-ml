#!/usr/bin/env bash
# Runs the full pipeline: database setup, raw ingestion, then all tests.
# Extra arguments are passed to the ingest step, e.g. --refresh.
# Output is shown on screen and saved to logs/.
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ -z "${VIRTUAL_ENV:-}" ]]; then
  if [[ -f .venv/Scripts/activate ]]; then
    source .venv/Scripts/activate
  else
    source .venv/bin/activate
  fi
fi
# set -euo pipefail, from Step 1: stop at the first error, treat undefined variables as errors, and let a failure anywhere in a pipeline count.
# cd "$(dirname "$0")/..": $0 is the script's own path, so this moves to the project root wherever you run the script from.
# ${VIRTUAL_ENV:-} means "the value of VIRTUAL_ENV, or an empty string if it isn't set". Without :-, the -u option would stop the script whenever the venv isn't active.
# The two activate paths exist because Windows venvs put it in Scripts/ and Linux ones in bin/.

mkdir -p logs
log_file="logs/pipeline_$(date +%Y%m%d_%H%M%S).log"

run_step() {
  local name=$1
  shift
  echo "=== ${name} ==="
  local start=$SECONDS
  "$@"
  echo "--- ${name} finished in $((SECONDS - start))s"
}

{
  run_step "init database" bash scripts/init_db.sh
  run_step "ingest raw data" python -m industry_ml.ingest "$@"
  run_step "refresh features" bash scripts/refresh_features.sh
  run_step "tests" python -m pytest -q
} 2>&1 | tee "$log_file"

echo "Log saved to ${log_file}"

# $(date +%Y%m%d_%H%M%S) inserts the current date and time, so each run gets its own log file, for example pipeline_20261113_142501.log.
# run_step is a Bash function. local keeps its variables private, and shift drops the first argument (the step's name), so "$@" is then the command to run. 
# $SECONDS is a built-in counter of seconds since the shell started, and $(( … )) does arithmetic.
# "$@" on the ingest line passes on whatever arguments you gave the script, so bash scripts/run_pipeline.sh --refresh reaches Python.
# { … } 2>&1 | tee "$log_file": the braces group the three steps. 2>&1 merges errors into normal output, and tee copies everything both to the screen and to the log file.

# A pipeline's exit status is normally that of its last command. tee almost always succeeds, so it would hide a failed Python step:

# Command	                     Without pipefail	       With pipefail
# false | tee out.log; echo $?	 prints 0 (success)	     prints 1 (failure)