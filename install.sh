#!/bin/sh
# macOS / Linux: prepare helper env. The helper itself syncs the addon on start.
set -e
cd "$(dirname "$0")"
if command -v uv >/dev/null 2>&1; then
  (cd helper && uv sync --quiet)
  echo "Helper environment ready (uv)."
else
  echo "uv not found; ./run-helper.sh will create a venv with pip on first run."
fi
echo "Next: ./run-helper.sh  (auto-installs/updates the addon into WoW, then starts)"
echo "Set WOW_DIR if needed, or create GamepadSpeak.ini with wow_dir=..."
