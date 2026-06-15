#!/usr/bin/env bash
# deploy.sh — One-shot deployment for YouTube Playlist Downloader
# Compatible with Linux and macOS

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/venv"
REQUIREMENTS="$SCRIPT_DIR/requirements.txt"
PYTHON_MIN_MAJOR=3
PYTHON_MIN_MINOR=10

# ── Colour helpers ──────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${CYAN}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║    YouTube Playlist Downloader — Deploy      ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════╝${NC}"
echo ""

# ── 1. Locate Python 3.10+ ─────────────────────────────────────────────────
info "Locating Python interpreter …"
PYTHON=""
for candidate in python3 python python3.12 python3.11 python3.10; do
    if command -v "$candidate" &>/dev/null; then
        version=$("$candidate" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        major=$(echo "$version" | cut -d. -f1)
        minor=$(echo "$version" | cut -d. -f2)
        if [ "$major" -ge "$PYTHON_MIN_MAJOR" ] && [ "$minor" -ge "$PYTHON_MIN_MINOR" ]; then
            PYTHON="$candidate"
            success "Found $candidate ($version)"
            break
        fi
    fi
done

[ -z "$PYTHON" ] && error "Python ${PYTHON_MIN_MAJOR}.${PYTHON_MIN_MINOR}+ not found. Install it and re-run."

# ── 1b. Ensure tkinter (GUI) + venv support ────────────────────────────────
# Many Linux distros ship python3 WITHOUT tkinter; the app is a tkinter GUI.
info "Checking tkinter (GUI toolkit) …"
if "$PYTHON" -c "import tkinter" &>/dev/null; then
    success "tkinter available."
else
    warn "tkinter not found for $PYTHON."
    if command -v apt-get &>/dev/null; then
        info "Installing python3-tk + python3-venv …"
        sudo apt-get update -q && sudo apt-get install -y python3-tk python3-venv \
            && success "tkinter installed." \
            || warn "Failed to install python3-tk — install it manually and re-run."
    elif command -v dnf &>/dev/null; then
        sudo dnf install -y python3-tkinter && success "tkinter installed." || warn "Install python3-tkinter manually."
    elif command -v brew &>/dev/null; then
        warn "Install a Tk-enabled Python: 'brew install python-tk' (or use the python.org build)."
    else
        warn "Install your distro's python3-tk package, then re-run."
    fi
fi

# ── 2. Check / install FFmpeg ──────────────────────────────────────────────
info "Checking FFmpeg …"
if command -v ffmpeg &>/dev/null; then
    success "FFmpeg found: $(ffmpeg -version 2>&1 | head -1)"
else
    warn "FFmpeg not found. Attempting install …"
    if command -v apt-get &>/dev/null; then
        sudo apt-get update -q && sudo apt-get install -y ffmpeg
    elif command -v brew &>/dev/null; then
        brew install ffmpeg
    else
        warn "Could not auto-install FFmpeg. Download from https://ffmpeg.org and add to PATH."
    fi
fi

# ── 2b. Install Deno (solves YouTube's 'n' signature challenge) ────────────
info "Checking Deno (nsig challenge solver) …"
if command -v deno &>/dev/null || [ -x "$HOME/.deno/bin/deno" ]; then
    success "Deno is available."
else
    info "Installing Deno …"
    curl -fsSL https://deno.land/install.sh | sh -s -- -y 2>/dev/null \
        && success "Deno installed." \
        || warn "Deno install failed. Install manually: https://deno.land"
fi

# ── 2c. Install Node.js (runs the local PO Token script) ──────────────────
info "Checking Node.js (>= 20.19, for PO tokens) …"
NODE_OK=0
if command -v node &>/dev/null; then
    NODE_MAJOR=$(node -p "process.versions.node.split('.')[0]" 2>/dev/null || echo 0)
    NODE_MINOR=$(node -p "process.versions.node.split('.')[1]" 2>/dev/null || echo 0)
    if [ "$NODE_MAJOR" -gt 20 ] || { [ "$NODE_MAJOR" -eq 20 ] && [ "$NODE_MINOR" -ge 19 ]; }; then NODE_OK=1; fi
fi
if [ "$NODE_OK" = "1" ]; then
    success "Node.js is available ($(node --version))."
else
    info "Installing Node.js LTS …"
    if command -v apt-get &>/dev/null; then
        curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash - >/dev/null 2>&1 && sudo apt-get install -y nodejs
    elif command -v brew &>/dev/null; then
        brew install node
    else
        warn "Could not auto-install Node.js. Install 20.19+ from https://nodejs.org"
    fi
fi

# ── 2d. Build the local PO Token provider (bgutil 'script mode') ──────────
info "Setting up local PO Token provider …"
POT_DIR="$SCRIPT_DIR/pot-provider/server"
POT_SCRIPT="$POT_DIR/build/generate_once.js"
POT_VERSION="1.3.1"   # keep in sync with bgutil-ytdlp-pot-provider in requirements.txt
if [ -f "$POT_SCRIPT" ]; then
    success "PO Token provider already built."
elif command -v node &>/dev/null && command -v git &>/dev/null; then
    TMP="$(mktemp -d)"
    info "  Cloning bgutil provider v$POT_VERSION …"
    git clone --depth 1 --branch "$POT_VERSION" https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git "$TMP" 2>/dev/null
    (
        cd "$TMP/server"
        info "  Installing npm dependencies …"
        npm install --no-audit --no-fund --silent
        info "  Building (tsc) …"
        npx --yes tsc
    )
    # Keep build/ + node_modules/ + package files; drop src/ so the Node provider
    # is selected over the Deno one (which needs src/*.ts).
    rm -rf "$POT_DIR"; mkdir -p "$POT_DIR"
    for item in build node_modules package.json package-lock.json; do
        [ -e "$TMP/server/$item" ] && mv "$TMP/server/$item" "$POT_DIR/"
    done
    rm -rf "$TMP"
    [ -f "$POT_SCRIPT" ] && success "PO Token provider built (pot-provider/server)." \
        || warn "PO Token provider build failed - check Node/npm and re-run."
else
    warn "Node.js and/or git unavailable - skipping PO provider build."
    warn "Bot-gated/age-restricted videos may fail. Re-run deploy after installing them."
fi

# ── 3. Create virtual environment ─────────────────────────────────────────
info "Creating virtual environment at $VENV_DIR …"
if [ -d "$VENV_DIR" ]; then
    warn "Existing venv found — removing and recreating."
    rm -rf "$VENV_DIR"
fi
"$PYTHON" -m venv "$VENV_DIR"
success "Virtual environment created."

# ── 4. Upgrade pip + install dependencies ──────────────────────────────────
info "Installing dependencies from requirements.txt …"
# pip self-upgrade is optional; don't let it abort the deploy (set -e).
"$VENV_DIR/bin/python" -m pip install --upgrade pip --quiet || warn "pip self-upgrade skipped."
"$VENV_DIR/bin/python" -m pip install -r "$REQUIREMENTS" --quiet
success "Dependencies installed."

# ── 5. Create directory structure ─────────────────────────────────────────
info "Creating project directories …"
mkdir -p "$SCRIPT_DIR/downloads" "$SCRIPT_DIR/logs" "$SCRIPT_DIR/debug"
success "Directories ready."

# ── Done ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║         Deployment complete!                 ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════╝${NC}"
echo ""
echo "  Run the app:    source venv/bin/activate && python app.py"
echo "  Or directly:    venv/bin/python app.py"
echo ""
