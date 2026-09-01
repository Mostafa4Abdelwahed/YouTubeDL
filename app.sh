#!/usr/bin/env bash
# app.sh - One-click headless launcher for YouTube Downloader (Linux/macOS).
# Auto-setup on first run: if venv or PO provider is missing, it runs
# deploy.sh automatically so the user never types a command.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PY="$SCRIPT_DIR/venv/bin/python"
POT_SCRIPT="$SCRIPT_DIR/pot-provider/server/build/generate_once.js"

NEED_SETUP=0
[ ! -x "$VENV_PY" ] && NEED_SETUP=1
[ ! -f "$POT_SCRIPT" ] && NEED_SETUP=1

if [ "$NEED_SETUP" = "1" ]; then
    echo "  [INFO] First run detected - setting up environment..."
    echo "  [INFO] This may take 2-5 minutes (installing deps + building PO provider)."
    if [ -x "$SCRIPT_DIR/deploy.sh" ]; then
        chmod +x "$SCRIPT_DIR/deploy.sh"
        bash "$SCRIPT_DIR/deploy.sh"
    else
        echo "  [ERROR] deploy.sh not found at $SCRIPT_DIR/deploy.sh" >&2
        exit 1
    fi
    if [ ! -x "$VENV_PY" ]; then
        echo "  [ERROR] Setup failed - venv still missing at: $VENV_PY" >&2
        exit 1
    fi
fi

# Detach from the terminal: no controlling tty, output discarded, survives the
# launching shell. The GUI process exits on window close (no orphaned terminal).
nohup "$VENV_PY" "$SCRIPT_DIR/app.py" "$@" >/dev/null 2>&1 &
disown
echo "  [OK] App launched."
