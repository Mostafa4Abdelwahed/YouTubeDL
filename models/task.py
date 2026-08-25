from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class DownloadStatus(Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    PAUSED = "paused"


class OutputFormat(Enum):
    MP4 = "mp4"
    MP3 = "mp3"
    AAC = "aac"


class VideoQuality(Enum):
    # Download best streams available; FFmpeg remuxes/merges to MP4
    BEST  = "bestvideo+bestaudio/best"
    Q1080 = "bestvideo[height<=1080]+bestaudio/best[height<=1080]"
    Q720  = "bestvideo[height<=720]+bestaudio/best[height<=720]"
    Q480  = "bestvideo[height<=480]+bestaudio/best[height<=480]"
    Q360  = "bestvideo[height<=360]+bestaudio/best[height<=360]"


class AudioQuality(Enum):
    Q320 = "320"
    Q256 = "256"
    Q192 = "192"
    Q128 = "128"


VIDEO_QUALITY_LABELS = {
    "RAW (Best)": VideoQuality.BEST,
    "1080p": VideoQuality.Q1080,
    "720p": VideoQuality.Q720,
    "480p": VideoQuality.Q480,
    "360p": VideoQuality.Q360,
}

AUDIO_QUALITY_LABELS = {
    "320 kbps": AudioQuality.Q320,
    "256 kbps": AudioQuality.Q256,
    "192 kbps": AudioQuality.Q192,
    "128 kbps": AudioQuality.Q128,
}


@dataclass
class VideoTask:
    video_id: str
    title: str
    url: str
    output_format: OutputFormat = OutputFormat.MP4
    video_quality: VideoQuality = VideoQuality.BEST
    audio_quality: AudioQuality = AudioQuality.Q320
    output_dir: str = "downloads"
    status: DownloadStatus = DownloadStatus.QUEUED
    progress: float = 0.0
    error_message: Optional[str] = None
    playlist_index: Optional[int] = None
    playlist_title: Optional[str] = None
    cookies_from_browser: Optional[str] = None
    cookiefile: Optional[str] = None
    cancelled: bool = False
    pause_requested: bool = False
    speed_str: str = ""
    eta_str: str = ""
    current_filename: str = ""
    final_filename: str = ""
    inter_download_delay: int = 0
    error_suggestion: str = ""

    @property
    def is_audio_only(self) -> bool:
        return self.output_format in (OutputFormat.MP3, OutputFormat.AAC)
