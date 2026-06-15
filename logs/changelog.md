# Changelog

All notable changes to YouTube Playlist Downloader are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [1.2.1] — 2026-06-15

### Added

- **Per-item delete (🗑) button** on each queue row — removes a single item with no
  confirmation. Queued-but-not-started items are skipped by the worker; the row is
  removed instantly.
- **"What the deploy installs (and where)"** section in the README documenting that
  `venv/` (Python deps) and `pot-provider/server/node_modules/` (Node deps) are
  project-local and self-contained.

### Changed

- **All three deploy scripts are now full one-shot auto-installers.** `deploy.bat`
  now installs FFmpeg/Node (winget) and Deno (PowerShell) itself instead of only
  warning — matching `deploy.ps1`. `deploy.sh` now installs `python3-tk`/`python3-venv`
  (apt) or `python3-tkinter` (dnf) so the tkinter GUI launches on Linux, and uses
  `python -m pip` so a failed pip self-upgrade can't abort the run.
- Queue panel: rows now **stretch to the full panel width**; active-download dot +
  percentage use `#8c9472`, and the progress-bar fill uses `#947472`.
- GUI buttons recoloured to a grayscale set; text-selection highlight is now neutral
  grey (`#5a5a5a`) instead of red.
- Window now **auto-sizes to its content and centers** in the screen work area
  (above the taskbar); the left control panel's scrollbar auto-hides when everything
  fits.
- Fetch status text changed to **"Fetching YouTube URL info"** (works for single
  videos and playlists).
- Headless launchers `app.bat` / `app.sh` run the GUI with no console window and
  exit cleanly on window close.

### Verified

- `deploy.ps1` validated end-to-end on Windows: fresh `venv` + all pip deps +
  FFmpeg/Deno/Node detected + PO-token script present → runtime health check `READY`.

---

## [1.2.0] — 2026-06-15

### Changed

- **Removed the Docker dependency for PO Tokens.** The `bgutil-ytdlp-pot-provider`
  plugin now runs in **script mode** against a local Node.js script built into
  `pot-provider/server/` — no Docker container, no background server on `:4416`.
  yt-dlp invokes `build/generate_once.js` on demand for each PO token.
- Deploy scripts now install **Node.js LTS** (≥20.19, required by the provider's
  deps) and **build the provider** (clone bgutil 1.3.1 → `npm install` → `npx tsc`),
  keeping only `build/` + `node_modules/`. The Deno PO-token variant is avoided by
  dropping `src/` (it can't load the provider's native `canvas` dependency).
- `requirements.txt` pins `bgutil-ytdlp-pot-provider==1.3.1` to match the cloned
  server tag.
- `downloader/runtime.py` now checks FFmpeg / Deno / **Node** / PO-token-script and
  passes the `youtubepot-bgutilscript:server_home` extractor arg to yt-dlp.
- **Icons moved to `assets/`.** `icon.png` and a pre-built `icon.ico` now live in
  `assets/` and ship with the project. The deploy scripts no longer convert PNG→ICO,
  and the app no longer generates the `.ico` at runtime — so **Pillow was dropped**
  from `requirements.txt` (it was only used for that conversion). All references
  updated to `assets/`.

### Added

- `app.bat` / `app.sh` headless launchers (run via the venv's windowed interpreter;
  the GUI process exits cleanly on window close — no orphaned background process).

### Notes

- Node ≥20.19 is required: older Node hits `ERR_REQUIRE_ESM` in the provider's
  `jsdom` dependency. The deploy installs the current LTS.
- Any leftover `bgutil-pot` Docker container from v1.1.0 is now unused and can be
  removed: `docker rm -f bgutil-pot`.

---

## [1.1.0] — 2026-06-15

### Added

- **PO Token provider integration** — YouTube now enforces Proof-of-Origin tokens
  for authenticated sessions. Added the `bgutil-ytdlp-pot-provider` plugin + a
  Docker container (`bgutil-pot` on :4416) that mints tokens automatically.
- **Deno-based nsig solver** — YouTube's "n" signature challenge now requires a
  JS runtime. Added `yt-dlp-ejs` + Deno; the app puts Deno on PATH at startup.
- **Automatic FFmpeg setup** — deploy script installs FFmpeg via winget; the app
  locates the winget install and adds it to PATH at runtime (`downloader/runtime.py`).
- **Runtime self-check** — on launch the app verifies FFmpeg, Deno and the PO
  token provider, logs each, and warns clearly if any are missing.
- **Browser-cookie and cookies.txt support** with Netscape-format validation.
- **Per-item + overall progress bars** and a live log panel.
- **Clear Done** button to remove finished rows; duplicate-queue guard.

### Fixed

- **Critical: false "completed" status.** Downloads that actually failed (missing
  FFmpeg, bot-detection, etc.) were reported as Done because `ignoreerrors:True`
  swallowed the error. `download_task` now uses `ignoreerrors:False`, captures the
  real error via a logger, and only marks COMPLETED if the output file truly
  exists on disk — otherwise FAILED with the real message.
- Leftover `.fNNN.m4a` / `.fNNN.mp4` stream fragments now cleaned per-task
  (concurrency-safe — no longer deletes other tasks' in-progress files).
- Format selection no longer over-restricts to `ext=mp4` (caused "Requested
  format is not available" on videos without native MP4 streams).
- ANSI color codes stripped from error dialogs and the log panel.

### Changed

- Removed the WEBM output option (MP4 / MP3 / AAC only).
- Downloads now save flat into `downloads/` (no per-playlist subfolders) — output
  filename is the video title, no `001 -` index prefix.
- History DB moved to `storage/history.db`; resume check verifies the file still
  exists on disk before skipping (records `output_path` per download).
- Deploy scripts now install the full stack (FFmpeg, Deno, Docker provider) and
  call pip via `python -m pip` so pip can self-upgrade on Windows.
- Larger, scrollable left control panel so all buttons stay reachable.

### Known issues / environment notes

- **IP-wide bot-detection.** Many rapid requests can make YouTube challenge *all*
  anonymous requests from your IP (not just specific videos). Observed first-hand
  during testing: an early request succeeded, but after ~dozens of debug requests
  every anonymous request was challenged. It is **time-based and clears on its own**
  (minutes to hours). Mitigations: provide cookies, lower concurrency, or wait.
- **PO Token provider requires Docker Desktop running.** The `bgutil-pot` container
  uses `--restart unless-stopped`, but Docker Desktop itself must be up.
- **SABR-forced videos** may be undownloadable until yt-dlp's SABR support matures.
- **DRM-protected media cannot be downloaded.** Purchased/rented YouTube TV shows
  and movies are encrypted (Widevine); even the purchasing account's cookies yield
  `ERROR: This video is DRM protected`. This is a hard limitation, not a bug.
- **Age-restricted (18+) videos usually fail** with the bot/sign-in error — even
  with cookies from an age-verified 18+ account. YouTube's age-gate verification
  isn't satisfied by account cookies alone.
- Browser-cookie extraction does **not** require closing the browser (validated on
  this build) — the earlier "close the browser" warning was removed.

---

## [1.0.0] — 2026-06-14

### Added

- Initial release of YouTube Playlist Downloader
- Dark-themed tkinter GUI with live download queue
- Single video and full playlist URL support via yt-dlp
- Output format selection: MP4, WEBM (video), MP3, AAC (audio)
- Video quality selection: RAW (best), 1080p, 720p, 480p, 360p
- Audio quality selection: 320 kbps, 256 kbps, 192 kbps, 128 kbps
- Concurrent download support (1–6 parallel workers)
- Resume support via SQLite history database (`downloads/history.db`)
- Exponential backoff retry logic (up to 5 attempts per video)
- `ignoreerrors` enabled — skips deleted, private, or region-locked videos
- Playlist folder structure: `downloads/<playlist_title>/001 - <title>.ext`
- One-shot deployment scripts: `deploy.sh`, `deploy.ps1`, `deploy.bat`
- `requirements.txt` with pinned minimum versions
- `icon.png` application icon wired to taskbar and window on all platforms
- Documentation: `README.md`, `logs/changelog.md`, `debug/troubleshooting.md`

---

<!-- New entries go above this line. Keep entries in reverse-chronological order. -->
