#!/usr/bin/env bash
# KubeSentra dev helper for Git Bash on Windows (where make is often absent).
# Usage: scripts/dev.sh <command>
#   env      create .venv and install pinned dependencies
#   up       start the Postgres container
#   down     stop the compose stack
#   migrate  apply pending SQL migrations
#   status   show applied/pending migrations
#   test     run the test suite
#   serve    run the API locally with auto-reload
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -x .venv/Scripts/python.exe ]]; then
  PY=.venv/Scripts/python.exe
else
  PY=.venv/bin/python
fi

cmd="${1:-help}"
case "$cmd" in
  env)
    python -m venv .venv
    "$PY" -m pip install --upgrade pip
    "$PY" -m pip install -e ".[dev]"
    ;;
  up)     docker compose up -d postgres ;;
  down)   docker compose down ;;
  migrate) "$PY" -m database.migrate ;;
  status)  "$PY" -m database.migrate --status ;;
  test)    "$PY" -m pytest -v ;;
  serve)   "$PY" -m uvicorn api.main:app --host 127.0.0.1 --port 8547 --reload ;;
  dashboard) "$PY" -m streamlit run dashboard/app.py --server.port 8551 --server.headless true ;;
  *)
    echo "Usage: scripts/dev.sh <env|up|down|migrate|status|test|serve|dashboard>"
    exit 1
    ;;
esac
