# Troubleshooting Guide

---

## YouTube Anti-Bot Stack (read this first)

Since 2024–2025 YouTube enforces three protections that plain yt-dlp cannot
satisfy alone. This app sets all three up, but if downloads fail, verify each:

### The three requirements

| Component | Purpose | How to check |
|-----------|---------|--------------|
| **FFmpeg** | Merge video+audio, convert MP3/AAC | `ffmpeg -version` |
| **Deno** | Solve the "n" signature challenge (nsig) | `deno --version` |
| **Node.js ≥20.19** | Runs the local PO token script | `node --version` |
| **PO Token script** | Mint Proof-of-Origin tokens (local Node script) | `pot-provider/server/build/generate_once.js` exists |

The app logs the status of all four on startup. If any show `[!!]`, that's your problem.
The PO token provider is a **local Node.js script** built into `pot-provider/server`.

### "Requested format is not available"

Means YouTube returned **zero real media formats** (only storyboards). Causes:
- **PO token provider missing** — `pot-provider/server` wasn't built. Re-run the
  deploy script (it clones + builds the bgutil server with npm).
- **Node.js missing or too old** (need ≥20.19) — install it and re-run deploy.
- **Deno missing** — the nsig challenge can't be solved, so format URLs are invalid.
  Install from https://deno.land and restart the app.

### "Sign in to confirm you're not a bot"

YouTube has flagged your IP. The flag **escalates** the more you hit it:

1. **Per-video** — only specific (heavily-requested) video IDs are challenged.
2. **IP-wide** — *every* anonymous request from your IP is challenged, even videos
   you've never touched.

We observed this escalation first-hand: early in a session a video downloaded
anonymously, but after dozens of rapid debug requests, **all** anonymous requests
(including brand-new videos) started failing. The trigger is **request volume**,
not the videos themselves.

**What to do, in order of preference:**

1. **Wait.** The flag is IP/time-based and clears on its own — typically a few
   hours, reliably by the next morning. This is the simplest fix and needs nothing.
2. **Provide cookies** to authenticate past the challenge:
   - Export a **Netscape** `cookies.txt` using the
     "Get cookies.txt LOCALLY" Chrome extension (or "cookies.txt" for Firefox)
     while logged into youtube.com, then select it in the app's *Cookies.txt* field.
   - Or pick your browser in the *Browser Cookies* dropdown (Chrome, Firefox, etc.).
3. **Slow down.** Reduce *Concurrent Downloads* to 1–2 and avoid re-running the
   same playlist repeatedly. Each failed attempt refreshes the flag timer.

> ⚠ **Stop retrying a flagged playlist.** Every attempt resets the cooldown clock
> and can escalate per-video → IP-wide. If you're flagged, wait or authenticate —
> don't keep clicking Start.

#### Cookies don't work — likely an *incomplete* export

A `cookies.txt` can be valid Netscape format yet still fail the bot gate if it's
**missing the core sign-in cookies**. A real logged-in export contains `SID`,
`SAPISID`, `HSID`, `SSID`, `APISID`, `__Secure-1PSID`, `__Secure-3PSID`, and
`LOGIN_INFO`. If yours only has the `__Secure-3P*` / consent cookies, YouTube does
**not** treat the session as signed in and the bot gate stays up (observed in testing).

Check your file:
```bash
grep -oE "SID|SAPISID|LOGIN_INFO" cookies.txt | sort -u    # should list all three
```

Most reliable way to get a complete, stable export:
1. Open a **private/incognito** window and sign into YouTube there.
2. Confirm you're logged in (open `youtube.com` in a new tab).
3. Export with **Get cookies.txt LOCALLY** → save the file.
4. **Close the incognito window immediately** — otherwise YouTube rotates the
   session tokens and invalidates the export.

> Note: account cookies WITHOUT a working PO token provider return **0 formats**
> (silent failure). You need *both* valid cookies and the provider to download
> bot-gated videos.

### PO Token provider (local Node script) management

yt-dlp runs a **local Node.js script on demand** — no background server. The
provider lives in `pot-provider/server/`.

```bash
# Verify Node and the script are present:
node --version                                   # need >= 20.19
ls pot-provider/server/build/generate_once.js    # the script yt-dlp invokes

# Test the script directly (prints a JSON poToken):
node pot-provider/server/build/generate_once.js
```

If the script is missing, re-run the deploy script — it clones the bgutil server
(tag 1.3.1, matching the pip plugin), runs `npm install` + `npx tsc`, and keeps
only `build/` + `node_modules/` (dropping `src/` so yt-dlp uses the **Node**
provider, not the Deno one — the Deno variant can't load the native `canvas` dep).

### Downloads show "Done" but no file appears

Fixed in v1.1.0. If you still see this, your `download.py` predates the fix —
the app now verifies the output file exists on disk before marking COMPLETED.
The usual root cause was **FFmpeg missing**: the merge step failed but the error
was swallowed. Install FFmpeg (`winget install Gyan.FFmpeg`) and restart.

---

## Deployment Issues

### Re-running the deploy fails with "Access to the path ... is denied" (Windows)

The deploy recreates `venv/`, which fails if a file is **locked by a running app
instance**. Close the app window (and confirm no `python.exe`/`pythonw.exe` for this
project remains in Task Manager), then re-run the deploy.

### `python` not found after running deploy script

- **Windows**: Ensure Python is installed with **"Add to PATH"** checked. Restart your terminal.
- **macOS/Linux**: Try `python3 --version`. The deploy script searches `python3`, `python`, and `py`.
- If multiple Python versions are installed, ensure the active one is 3.10+:
  ```bash
  python --version   # should print 3.10 or higher
  ```

### App won't start on Linux — `ModuleNotFoundError: No module named 'tkinter'`

Many Linux distros ship `python3` **without** tkinter. `deploy.sh` now installs it
automatically (`python3-tk` on apt, `python3-tkinter` on dnf), but if you hit this:
```bash
sudo apt install python3-tk python3-venv      # Debian/Ubuntu
sudo dnf install python3-tkinter              # Fedora
```
On macOS, use a Tk-enabled Python (`brew install python-tk` or the python.org build).

### `venv` creation fails

- Ensure the `venv` module is available: `python -m ensurepip --upgrade`
- On Ubuntu/Debian you may need: `sudo apt install python3-venv`

### pip install fails

- Network error — check internet connectivity.
- If behind a proxy: `pip install --proxy http://user:pass@host:port -r requirements.txt`
- If SSL errors occur: `pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt`

---

## FFmpeg Issues

### "FFmpeg not found" / Merge or conversion fails

yt-dlp requires FFmpeg to:
- Merge separate video + audio streams into a single MP4
- Extract and convert audio to MP3 or AAC

Without FFmpeg, downloads produce **no output file at all** (this was the original
cause of the "shows Done but no file" bug — see above). The app auto-locates a
winget-installed FFmpeg at runtime, so you usually just need to install it once.

**Windows fix (recommended):** `winget install Gyan.FFmpeg`
- The app's `downloader/runtime.py` finds it under
  `%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg*\...\bin` automatically.
- Alternatively, download a static build from [ffmpeg.org](https://ffmpeg.org/download.html),
  extract, and add the `bin\` folder to your PATH.

**macOS fix:** `brew install ffmpeg`

**Linux fix:** `sudo apt install ffmpeg` (Debian/Ubuntu) or `sudo dnf install ffmpeg` (Fedora)

Verify with `ffmpeg -version`, then restart the app — the startup log should show
`[OK] FFmpeg found`.

---

## Download Errors

### "This video is DRM protected"

**This is a hard limitation, not a bug — the download cannot succeed.** Purchased or
rented YouTube content (TV shows, movies) is encrypted with Widevine DRM. yt-dlp
can see the video but cannot decrypt the stream, so it fails with
`ERROR: [youtube] <id>: This video is DRM protected`.

- This happens **even with the cookies of the account that bought the media** —
  ownership does not remove the encryption.
- The PO token + Deno stack is working correctly in this case (you'll see
  `Generating a gvs PO Token` and `Solving JS challenges using deno` in the log
  right before the DRM error) — the block is the encryption, nothing in this app.
- There is no workaround within yt-dlp. Only non-DRM public videos can be downloaded.

### Age-restricted (18+) videos still fail with "Sign in to confirm you're not a bot"

Age-restricted content is the hardest case. In testing, **even cookies extracted
from an age-verified 18+ YouTube account did not get past the bot/sign-in error**
for 18+ videos. YouTube applies extra verification to age-gated media that account
cookies alone do not satisfy, so these videos commonly fail with:

```
ERROR: [youtube] <id>: Sign in to confirm you're not a bot. Use --cookies-from-browser or --cookies ...
```

Things that sometimes help (no guarantee for 18+ content):
- Make sure the cookies are **fresh** (re-export right before downloading) and from
  the age-verified account.
- Try the *Browser Cookies* dropdown instead of `cookies.txt` (live session).
- Ensure the PO token script is present (`node pot-provider/server/build/generate_once.js`).

If it still fails after the above, the video is effectively un-downloadable with
the current public yt-dlp + token tooling. This is a YouTube-side restriction, not
a bug in this app.

### "Video unavailable" / a video fails in a playlist

- The video may be private, deleted, age-restricted, or region-locked.
- As of v1.1.0 the app uses `ignoreerrors: False` per video so the **real error is
  reported** (not silently hidden). One bad video is marked **Failed** with its
  reason; the rest of the playlist continues.
- Status column meanings: **Already DL'd / Skipped** = in history with the file
  still on disk; **Failed** = hit a real error (hover/see the log for the message);
  **Done** = output file verified on disk.

### Downloads are slow

- Increase **Concurrent Downloads** slider (up to 6).
- yt-dlp uses `concurrent_fragment_downloads: 4` by default for DASH/HLS streams.
- Speed is ultimately limited by YouTube's CDN rate limits and your connection.

### "HTTP Error 429: Too Many Requests"

YouTube is throttling your IP. Solutions:
- Reduce concurrent workers to 1–2.
- Wait 5–10 minutes before retrying.
- The app's exponential backoff will retry up to 5 times automatically.

### Playlist only downloads first 100 videos

Some very large playlists (1000+ items) may require yt-dlp to paginate. This is handled by `extract_flat: True` during metadata fetch. If pagination still fails:
- Update yt-dlp: `pip install -U yt-dlp`
- Try splitting the playlist into smaller ranges using YouTube URL parameters.

---

## GUI Issues

### Window appears but is blank / not styled correctly

- Ensure you are running Python 3.10+ with tkinter built in.
- On Linux, install: `sudo apt install python3-tk`
- macOS Homebrew Python may lack tkinter — install the official python.org build instead.

### "Add to Queue" does nothing / spins forever

- The URL field may be empty or malformed.
- yt-dlp network call may be blocked by a firewall or proxy.
- Open a terminal, activate the venv, and run `python -c "import yt_dlp; yt_dlp.YoutubeDL({'quiet':True}).extract_info('https://www.youtube.com/watch?v=dQw4w9WgXcQ', download=False)"` to test connectivity independently.

### Progress stays at 0% for a long time

- Large video files take time to start — yt-dlp resolves the best format first.
- DASH streams download video and audio separately then merge; progress reflects the current stream.

---

## History / Resume Issues

### Videos skip when you expected a re-download

- History lives in `storage/history.db` and persists across sessions. The app only
  skips a video if it is in history **and** the recorded `output_path` still exists
  on disk — delete the file and it will re-download.
- Older history rows (pre-v1.1.0) had no `output_path` and are treated as
  "not downloaded" (so they re-download safely).
- To wipe history entirely:
  ```python
  # From project root with venv active:
  python -c "from storage.db import clear_history; clear_history()"
  ```

### History database is locked

- Another instance of the app may be running.
- Close all instances, then restart.

---

## Updating the stack

YouTube changes its internals frequently. If downloads suddenly fail, update the
whole stack (with the venv active):

```bash
python -m pip install -U yt-dlp yt-dlp-ejs
```

If you bump the `bgutil-ytdlp-pot-provider` pip plugin to a new version, rebuild
the matching Node provider so the versions stay in sync:

```bash
# pip plugin and the cloned server tag must match (e.g. both 1.3.1)
rm -rf pot-provider                # then re-run the deploy script to rebuild
./deploy.sh                        # (or deploy.ps1 / deploy.bat on Windows)
```

Updating yt-dlp + the plugins is the most common fix for unexplained failures.

---

## Reporting a Bug

Include the following when reporting issues:

1. OS and Python version (`python --version`)
2. yt-dlp version (`python -c "import yt_dlp; print(yt_dlp.version.__version__)"`)
3. FFmpeg (`ffmpeg -version`), Deno (`deno --version`), Node (`node --version`)
4. PO token script present? (`pot-provider/server/build/generate_once.js`)
5. The app's **startup log lines** (the `[OK]`/`[!!]` FFmpeg / Deno / Node / PO report)
6. The URL that failed (or a representative substitute)
7. The exact error message from the log panel or terminal

### Quick full-stack health check

Run this from the project root with the venv active — it prints the readiness of
all four components exactly as the app sees them on startup:

```bash
python -c "from downloader import runtime; s=runtime.setup(log=print); print('READY' if all((s['ffmpeg'],s['deno'],s['node'],s['pot'])) else 'NOT READY')"
```
