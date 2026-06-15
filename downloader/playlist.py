import re
import yt_dlp
from models.task import VideoTask, OutputFormat, VideoQuality, AudioQuality
from downloader import runtime


def _is_valid_cookiefile(path: str) -> bool:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            first = f.readline().strip()
        return "Netscape" in first or "HTTP Cookie" in first
    except Exception:
        return False


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def build_tasks(
    url: str,
    output_format: OutputFormat,
    video_quality: VideoQuality,
    audio_quality: AudioQuality,
    output_dir: str,
    skip_downloaded: bool = True,
    log_callback=None,
    cookies_from_browser: str = None,
    cookiefile: str = None,
) -> list[VideoTask]:
    """
    Extract playlist/video metadata and return a list of VideoTask objects.
    Raises on error so the caller can display a message to the user.
    """
    class _Logger:
        def debug(self, msg):
            if log_callback and not msg.startswith("[debug]"):
                log_callback(_strip_ansi(msg))
        def warning(self, msg):
            if log_callback:
                log_callback("WARN: " + _strip_ansi(msg))
        def error(self, msg):
            if log_callback:
                log_callback("ERROR: " + _strip_ansi(msg))

    opts = {
        "extract_flat": True,
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": False,
        "logger": _Logger(),
    }
    pot_home = runtime.pot_server_home()
    if pot_home:
        opts["extractor_args"] = {"youtubepot-bgutilscript": {"server_home": [pot_home]}}
    if cookiefile and _is_valid_cookiefile(cookiefile):
        opts["cookiefile"] = cookiefile
    elif cookies_from_browser:
        opts["cookiesfrombrowser"] = (cookies_from_browser,)

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if info is None:
        raise ValueError("yt-dlp returned no information for that URL.")

    # Single video
    if info.get("_type") != "playlist":
        return [_make_task(info, output_format, video_quality, audio_quality, output_dir,
                           playlist_index=None, playlist_title=None,
                           cookies_from_browser=cookies_from_browser,
                           cookiefile=cookiefile)]

    # Playlist — materialise the (possibly lazy) entries iterator
    playlist_title = info.get("title") or "Playlist"
    raw_entries = list(info.get("entries") or [])

    if not raw_entries:
        raise ValueError(f"Playlist '{playlist_title}' has no accessible entries.")

    tasks = []
    for idx, item in enumerate(raw_entries, start=1):
        if item is None:
            continue
        tasks.append(_make_task(item, output_format, video_quality, audio_quality, output_dir,
                                playlist_index=idx, playlist_title=playlist_title,
                                cookies_from_browser=cookies_from_browser,
                                cookiefile=cookiefile))

    return tasks


def _make_task(
    item: dict,
    output_format: OutputFormat,
    video_quality: VideoQuality,
    audio_quality: AudioQuality,
    output_dir: str,
    playlist_index,
    playlist_title,
    cookies_from_browser=None,
    cookiefile=None,
) -> VideoTask:
    vid_id = item.get("id") or item.get("url", "unknown")
    title = item.get("title") or vid_id

    # Build a reliable watch URL
    webpage_url = item.get("webpage_url") or item.get("original_url")
    if not webpage_url:
        raw_url = item.get("url", "")
        if raw_url.startswith("http"):
            webpage_url = raw_url
        else:
            webpage_url = f"https://www.youtube.com/watch?v={vid_id}"

    return VideoTask(
        video_id=vid_id,
        title=title,
        url=webpage_url,
        output_format=output_format,
        video_quality=video_quality,
        audio_quality=audio_quality,
        output_dir=output_dir,
        playlist_index=playlist_index,
        playlist_title=playlist_title,
        cookies_from_browser=cookies_from_browser,
        cookiefile=cookiefile,
    )
