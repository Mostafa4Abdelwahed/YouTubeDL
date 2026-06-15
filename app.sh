#!/usr/bin/env bash
# app.sh - Headless one-click launcher for the YouTube Downloader (Linux/macOS).
# Launches the GUI detached so no terminal needs to stay open. The app process
# ends when you close the window (clean shutdown handled in app.py).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PY="$SCRIPT_DIR/venv/bin/python"

if [ ! -x "$VENV_PY" ]; then
    echo "  [ERROR] Virtual environment not found at: $VENV_PY" >&2
    echo "  Run ./deploy.sh first to set up the app." >&2
    exit 1
fi

# Detach from the terminal: no controlling tty, output discarded, survives the
# launching shell. The GUI process exits on window close (no orphaned terminal).
nohup "$VENV_PY" "$SCRIPT_DIR/app.py" "$@" >/dev/null 2>&1 &
disown
