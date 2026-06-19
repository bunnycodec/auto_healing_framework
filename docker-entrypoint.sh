#!/usr/bin/env sh
# Entrypoint: `serve` runs the dashboard/API, anything else is passed to the CLI.
set -e

if [ "$1" = "serve" ] || [ -z "$1" ]; then
  exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
fi

exec auto-healer "$@"
