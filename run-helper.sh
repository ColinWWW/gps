#!/bin/sh
# macOS / Linux: run the helper. Extra flags pass through, e.g. ./run-helper.sh --language bg
set -e
cd "$(dirname "$0")/helper"
if command -v uv >/dev/null 2>&1; then
  exec uv run --quiet python gamepadspeak_helper.py "$@"
fi
if [ ! -x .venv/bin/python ]; then
  PY=""
  for c in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
  done
  [ -n "$PY" ] || { echo "Python 3.10-3.13 not found" >&2; exit 1; }
  "$PY" -m venv .venv
  .venv/bin/pip install --quiet --upgrade pip
  .venv/bin/pip install --quiet .
fi
exec .venv/bin/python gamepadspeak_helper.py "$@"
