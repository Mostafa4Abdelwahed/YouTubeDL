"""
Runtime environment setup for reliable YouTube downloading.

Modern YouTube requires three things beyond plain yt-dlp:
  1. A PO Token provider  -> bgutil "script mode": a local Node.js script
                             (pot-provider/server/build/generate_once.js)
                             invoked on demand. No background server.
  2. A JS runtime for the nsig challenge -> Deno (via yt-dlp-ejs)
  3. FFmpeg -> merging video+audio and audio conversion

This module puts FFmpeg / Deno / Node on PATH and reports whether each piece is
ready, so the GUI can surface clear guidance.
"""
import os
import glob
import shutil
import subprocess

# Project root = parent of the "downloader" package directory
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DENO_BIN = os.path.join(os.path.expanduser("~"), ".deno", "bin")
NODE_DIR = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "nodejs")
POT_SERVER_HOME = os.path.join(_ROOT, "pot-provider", "server")
POT_SCRIPT = os.path.join(POT_SERVER_HOME, "build", "generate_once.js")

_WINGET_PKGS = os.path.join(os.path.expanduser("~"), "AppData", "Local",
                            "Microsoft", "WinGet", "Packages")


# ── FFmpeg ────────────────────────────────────────────────────────────────────

def ensure_ffmpeg_on_path() -> bool:
    if shutil.which("ffmpeg"):
        return True
    matches = glob.glob(os.path.join(_WINGET_PKGS, "Gyan.FFmpeg*", "**", "bin", "ffmpeg.exe"),
                        recursive=True)
    if matches:
        ffmpeg_dir = os.path.dirname(matches[0])
        if ffmpeg_dir not in os.environ.get("PATH", ""):
            os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
        return True
    return False


def ffmpeg_location() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return os.path.dirname(exe)
    matches = glob.glob(os.path.join(_WINGET_PKGS, "Gyan.FFmpeg*", "**", "bin", "ffmpeg.exe"),
                        recursive=True)
    return os.path.dirname(matches[0]) if matches else ""


# ── Deno (nsig challenge solver) ──────────────────────────────────────────────

def ensure_deno_on_path() -> bool:
    if os.path.isdir(DENO_BIN) and DENO_BIN not in os.environ.get("PATH", ""):
        os.environ["PATH"] = DENO_BIN + os.pathsep + os.environ.get("PATH", "")
    return shutil.which("deno") is not None


# ── Node.js (PO token script runtime) ─────────────────────────────────────────

def ensure_node_on_path() -> bool:
    if not shutil.which("node") and os.path.isdir(NODE_DIR):
        os.environ["PATH"] = NODE_DIR + os.pathsep + os.environ.get("PATH", "")
    return shutil.which("node") is not None


def _node_version_ok() -> bool:
    """bgutil's deps need Node >= 20.19; accept >= 20.19 (and any >= 21)."""
    node = shutil.which("node")
    if not node:
        return False
    try:
        out = subprocess.run([node, "--version"], capture_output=True, text=True,
                             timeout=10).stdout.strip().lstrip("v")
        parts = [int(x) for x in out.split(".")[:3]]
        return tuple(parts) >= (20, 19, 0)
    except Exception:
        return False


# ── PO Token provider (local Node script) ─────────────────────────────────────

def pot_server_home() -> str:
    """Return the bgutil server_home path if the built script exists, else ''."""
    return POT_SERVER_HOME if os.path.isfile(POT_SCRIPT) else ""


def check_pot_provider() -> tuple[bool, str]:
    """Verify the local Node PO-token script is present and Node can run it."""
    if not os.path.isfile(POT_SCRIPT):
        return False, f"PO token script missing ({POT_SCRIPT})"
    if not ensure_node_on_path():
        return False, "Node.js not found (needed for PO tokens)"
    if not _node_version_ok():
        return False, "Node.js too old (need >= 20.19)"
    return True, "PO token provider ready (local Node script)"


# ── Orchestration ─────────────────────────────────────────────────────────────

def setup(log=None) -> dict:
    """
    Prepare the runtime. Returns:
        { 'ffmpeg': bool, 'deno': bool, 'node': bool, 'pot': bool, 'messages': [...] }
    `log` is an optional callable(str) for progress messages.
    """
    def _say(msg):
        if log:
            log(msg)

    status = {"ffmpeg": False, "deno": False, "node": False, "pot": False, "messages": []}

    # FFmpeg
    status["ffmpeg"] = ensure_ffmpeg_on_path()
    status["messages"].append(
        "[OK] FFmpeg found (merge + audio conversion ready)" if status["ffmpeg"]
        else "[!!] FFmpeg NOT found - install with: winget install Gyan.FFmpeg (REQUIRED)")
    _say(status["messages"][-1])

    # Deno (nsig)
    status["deno"] = ensure_deno_on_path()
    status["messages"].append(
        "[OK] Deno found (nsig challenge solver ready)" if status["deno"]
        else "[!!] Deno NOT found - install from https://deno.land")
    _say(status["messages"][-1])

    # Node (PO token script runtime)
    status["node"] = ensure_node_on_path()
    status["messages"].append(
        "[OK] Node.js found (PO token runtime ready)" if status["node"]
        else "[!!] Node.js NOT found - install Node 20.19+ from https://nodejs.org")
    _say(status["messages"][-1])

    # PO token provider (local script)
    ok, msg = check_pot_provider()
    status["pot"] = ok
    status["messages"].append(("[OK] " if ok else "[!!] ") + msg)
    if not ok:
        status["messages"].append(
            "  Re-run the deploy script to build the local PO token provider "
            "(pot-provider/server).")
    _say(status["messages"][-1])

    return status
