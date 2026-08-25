import re
from dataclasses import dataclass


@dataclass
class ErrorInfo:
    title: str
    suggestion: str = ""


# Ordered, most-specific first. Each rule: (regex, friendly title, suggestion).
_RULES = [
    ("drm|widevine|this video is drm protected|encrypted with",
     "DRM-protected",
     "YouTube encrypts this with Widevine DRM — yt-dlp cannot download it, even with cookies."),

    ("members.?only|member only|join this channel to|this is a members[- ]only",
     "Members-only",
     "Sign in with a cookies.txt exported from a channel member, or it simply isn't downloadable."),

    ("private video|this video is private|owner has made|removed by the user|deleted video|"
     "not available in your country|video is not available|this video is not available",
     "Unavailable / private / geo-blocked",
     "The video is private, deleted, or blocked in your region."),

    ("could not copy .*cookie database|cookie database|failed to extract cookies|"
     "cookiesfrombrowser|unable to find cookie|no cookie",
     "Browser cookie database is locked",
     "The app now tries to force-unlock the cookie DB automatically (it closes the "
     "process locking it). If it still fails, fully close the browser (all background "
     "processes) and retry, or export a cookies.txt with 'Get cookies.txt LOCALLY'."),

    ("dpapi|failed to decrypt|decrypt with",
     "Chrome 127+ App-Bound Encryption blocks cookie decryption",
     "Modern Chrome/Edge encrypt cookies so external apps can NEVER decrypt them "
     "(yt-dlp issue #10927). This is not fixable in-app. Use one of: (1) install Firefox, "
     "log into YouTube there, and choose 'firefox' as cookie source - it has no such "
     "encryption; or (2) export a cookies.txt with the 'Get cookies.txt LOCALLY' Chrome "
     "extension and select that file instead; or (3) if you are on an older Chrome and run "
     "the app under a DIFFERENT Windows user than the browser, launch the app as that same user."),

    ("age.?restricted|confirm you.?re not a bot|sign in to confirm|"
     "inappropriate for some users|verify you.?re a human|unusual traffic|"
     "this helps protect our community|too many requests|http error 429|"
     "rate.?limited|not a robot|http error 403",
     "Bot check / age gate / IP rate-limit",
     "Use cookies from a logged-in, age-verified account, lower concurrency, add a delay, "
     "or wait a few hours for the rate-limit to clear."),

    ("requested format is not available|no (video )?formats|nsig|"
     "unable to extract|extractor returned no formats|zero formats|"
     "sign in to confirm you",  # duplicate token above catches most
     "No playable format (nsig / PO token)",
     "Make sure FFmpeg, Deno and the local PO-token provider are installed and detected at startup."),

    ("ffmpeg|postprocess",
     "FFmpeg missing",
     "Install FFmpeg (e.g. `winget install Gyan.FFmpeg`) and retry."),

    ("connection reset|timed? ?out|timeout|name or service not known|"
     "failed to resolve|network is unreachable|connection aborted|tunnel connection",
     "Network error",
     "Check your internet connection and retry."),

    ("permission denied|no space left|disk|denied",
     "File / disk error",
     "Check the output folder permissions and that there is free disk space."),
]


def classify_error(raw: str) -> ErrorInfo:
    """Turn a raw yt-dlp / download error string into a friendly message."""
    text = (raw or "").lower()
    text = re.sub(r"^error:\s*", "", text)
    for pat, title, suggestion in _RULES:
        if re.search(pat, text):
            return ErrorInfo(title, suggestion)
    return ErrorInfo("Download failed", (raw or "unknown error").strip()[:200])
