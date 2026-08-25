import os
import re
import time
import yt_dlp
from typing import Callable, Optional
from models.task import VideoTask, OutputFormat, DownloadStatus
from downloader import runtime
from downloader.errors import classify_error
from storage import db

MAX_ATTEMPTS = 3


class _PauseRequested(Exception):
    """Raised from a progress hook to abort the current download (pause)."""


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text or "")


def _is_valid_cookiefile(path: str) -> bool:
    """Return True only if the file exists and starts with a Netscape cookie header."""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            first = f.readline().strip()
        return "Netscape" in first or "HTTP Cookie" in first
    except Exception:
        return False


def _build_ydl_opts(task: VideoTask, error_sink: list) -> dict:
    os.makedirs(task.output_dir, exist_ok=True)
    outtmpl = os.path.join(task.output_dir, "%(title)s.%(ext)s")

    class _Logger:
        def debug(self, msg): pass
        def info(self, msg): pass
        def warning(self, msg): pass
        def error(self, msg):
            error_sink.append(_strip_ansi(msg))

    opts: dict = {
        "outtmpl": outtmpl,
        "ignoreerrors": False,        # raise on failure so we can report it
        "retries": 5,
        "fragment_retries": 5,
        "concurrent_fragment_downloads": 4,
        "quiet": True,
        "no_warnings": True,
        "logger": _Logger(),
    }

    ffloc = runtime.ffmpeg_location()
    if ffloc:
        opts["ffmpeg_location"] = ffloc

    # Point the bgutil PO-token plugin at our local Node script.
    pot_home = runtime.pot_server_home()
    if pot_home:
        opts["extractor_args"] = {"youtubepot-bgutilscript": {"server_home": [pot_home]}}

    if task.cookiefile and _is_valid_cookiefile(task.cookiefile):
        opts["cookiefile"] = task.cookiefile
    elif task.cookies_from_browser:
        opts["cookiesfrombrowser"] = (task.cookies_from_browser,)

    if task.is_audio_only:
        codec = "aac" if task.output_format == OutputFormat.AAC else "mp3"
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": codec,
            "preferredquality": task.audio_quality.value,
        }]
    else:
        opts["format"] = task.video_quality.value
        opts["merge_output_format"] = "mp4"

    # Throttle requests to avoid YouTube IP rate-limiting / bot detection.
    if getattr(task, "inter_download_delay", 0) and task.inter_download_delay > 0:
        opts["sleep_interval"] = task.inter_download_delay
        opts["max_sleep_interval"] = task.inter_download_delay

    return opts


def _final_filepath(info: dict) -> str:
    """Extract the authoritative output path from yt-dlp's returned info dict."""
    if not info:
        return ""
    requested = info.get("requested_downloads")
    if requested and isinstance(requested, list):
        fp = requested[0].get("filepath") or requested[0].get("_filename")
        if fp:
            return fp
    return info.get("filepath") or info.get("_filename") or ""


def download_task(
    task: VideoTask,
    progress_hook: Optional[Callable] = None,
    skip_downloaded: bool = True,
) -> bool:
    if skip_downloaded and db.already_downloaded(task.video_id):
        task.status = DownloadStatus.SKIPPED
        task.error_message = "Already downloaded"
        return True

    error_sink: list[str] = []
    opts = _build_ydl_opts(task, error_sink)
    task.status = DownloadStatus.DOWNLOADING
    task.speed_str = ""
    task.eta_str = ""
    if progress_hook:
        progress_hook({"status": "downloading"})

    seen_files: set[str] = set()
    last_report = [0.0]

    def hook(d: dict) -> None:
        # Pause request short-circuits everything else.
        if task.pause_requested:
            raise _PauseRequested()

        fn = d.get("filename", "")
        if fn:
            seen_files.add(os.path.abspath(fn))
            task.current_filename = os.path.basename(fn)

        status = d.get("status")
        if status == "downloading":
            # Prefer the pre-computed percent string
            pct_str = d.get("_percent_str", "").strip().rstrip("%")
            try:
                task.progress = float(pct_str)
            except (ValueError, AttributeError):
                downloaded = d.get("downloaded_bytes") or 0
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                if total > 0:
                    task.progress = min((downloaded / total) * 100, 99.9)
            task.speed_str = d.get("_speed_str", "") or ""
            task.eta_str = d.get("_eta_str", "") or ""

            # Throttle UI reports to ~3/sec; yt-dlp fires far more often and
            # flooding the tkinter event loop makes the whole app laggy.
            now = time.monotonic()
            if now - last_report[0] < 0.33:
                return
            last_report[0] = now

        if progress_hook:
            progress_hook(d)

    opts["progress_hooks"] = [hook]

    for attempt in range(MAX_ATTEMPTS):
        error_sink.clear()
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(task.url, download=True)

            filepath = _final_filepath(info)

            # Success requires BOTH: yt-dlp returned info AND the file is really on disk
            if filepath and os.path.isfile(filepath):
                _delete_intermediates(seen_files, filepath)
                task.status = DownloadStatus.COMPLETED
                task.progress = 100.0
                task.speed_str = ""
                task.eta_str = ""
                task.final_filename = os.path.basename(filepath)
                db.mark_downloaded(task.video_id, task.title, task.url,
                                   task.output_format.value, filepath)
                return "completed"

            # No real output -> treat as failure
            raise RuntimeError(
                "Download produced no output file")

        except _PauseRequested:
            # User paused mid-download — keep partial file, mark as paused.
            task.status = DownloadStatus.PAUSED
            task.pause_requested = False
            task.speed_str = ""
            task.eta_str = ""
            return "paused"

        except Exception as exc:
            msg = _strip_ansi(str(exc)) or (error_sink[-1] if error_sink else "unknown error")
            if attempt == MAX_ATTEMPTS - 1:
                info = classify_error(msg)
                task.status = DownloadStatus.FAILED
                task.error_message = info.title
                task.error_suggestion = info.suggestion
                return "failed"
            time.sleep(2 ** attempt)

    return "failed"

    return "failed"


def _delete_intermediates(seen: set[str], merged: str) -> None:
    """Delete tracked stream fragment files (.fNNN.ext) that are not the final output."""
    merged_abs = os.path.abspath(merged) if merged else ""
    for path in seen:
        if path == merged_abs:
            continue
        name = os.path.basename(path)
        parts = name.rsplit(".", 2)
        if len(parts) == 3 and parts[1].startswith("f") and parts[1][1:].isdigit():
            try:
                if os.path.isfile(path):
                    os.remove(path)
            except OSError:
                pass
