import os
import re
import sys
import subprocess
import ctypes
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


from models.task import (
    OutputFormat,
    VideoQuality,
    AudioQuality,
    DownloadStatus,
    VIDEO_QUALITY_LABELS,
    AUDIO_QUALITY_LABELS,
)
from downloader.playlist import build_tasks
from downloader.queue import DownloadQueue, MAX_QUEUE_SIZE
from downloader import runtime
from storage import db

QUEUE_CHUNK_SIZE = 50  # rows created per idle batch — keeps UI responsive at 1000 items


ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")


# ── Palette ────────────────────────────────────────────────────────────────
BG       = "#0e0e0e"
PANEL    = "#161616"
CARD     = "#1d1d1d"
ENTRY    = "#262626"
BORDER   = "#2e2e2e"
ACCENT   = "#CE0000"
ACCENT_H = "#A30003"
TEXT     = "#f1f1f1"
MUT      = "#9a9a9a"
SUCCESS  = "#22c55e"
WARN     = "#f59e0b"
ERR      = "#F90004"
PROGRESS = "#947472"

FONT_HDR = ("Segoe UI", 14, "bold")
FONT_LBL = ("Segoe UI", 10)
FONT_SM  = ("Segoe UI", 9)
FONT_MONO = ("Consolas", 8)


STATUS_COLOR = {
    DownloadStatus.QUEUED:      MUT,
    DownloadStatus.DOWNLOADING: "#8c9472",
    DownloadStatus.COMPLETED:   SUCCESS,
    DownloadStatus.FAILED:      ERR,
    DownloadStatus.SKIPPED:     WARN,
    DownloadStatus.PAUSED:      WARN,
}


class QueueRow(ctk.CTkFrame):
    def __init__(self, parent, task, callbacks, **kwargs):
        super().__init__(parent, fg_color=CARD, corner_radius=8, **kwargs)
        self.task = task
        self._cb = callbacks
        self._sig = None          # last rendered state signature
        self._last_status = None  # status used for the current widget layout
        self._last_pct = -1       # last percent drawn on the progress bar
        self._build()

    def _build(self) -> None:
        self.grid_columnconfigure(1, weight=1)

        self._dot = ctk.CTkLabel(self, text="●",
                                 text_color=STATUS_COLOR[self.task.status],
                                 font=("Segoe UI", 12))
        self._dot.grid(row=0, column=0, padx=(10, 4), pady=(8, 0), sticky="w")

        title = self.task.title
        if len(title) > 72:
            title = title[:72] + "…"
        self._title = ctk.CTkLabel(self, text=title, text_color=TEXT,
                                   anchor="w", font=FONT_SM)
        self._title.grid(row=0, column=1, sticky="ew", pady=(8, 0))

        self._fmt = ctk.CTkLabel(self, text=self.task.output_format.value.upper(),
                                 text_color=MUT, font=FONT_SM, width=40)
        self._fmt.grid(row=0, column=2, padx=6)

        self._actions = ctk.CTkFrame(self, fg_color="transparent")
        self._actions.grid(row=0, column=3, padx=(0, 10), pady=(8, 0))

        self._pause_btn = ctk.CTkButton(self._actions, text="⏸", width=30, height=26,
                                        fg_color="transparent", hover_color="#333333",
                                        text_color=TEXT, font=("Segoe UI Symbol", 11),
                                        command=lambda: self._cb["on_pause"](self.task))
        self._pause_btn.pack(side="left", padx=(0, 2))

        self._retry_btn = ctk.CTkButton(self._actions, text="↻", width=30, height=26,
                                        fg_color="transparent", hover_color="#333333",
                                        text_color=WARN, font=("Segoe UI Symbol", 11),
                                        command=lambda: self._cb["on_retry"](self.task))
        self._retry_btn.pack(side="left", padx=(0, 2))

        self._del_btn = ctk.CTkButton(self._actions, text="🗑", width=30, height=26,
                                      fg_color="transparent", hover_color="#333333",
                                      text_color=MUT, font=("Segoe UI", 11),
                                      command=lambda: self._cb["on_delete"](self.task))
        self._del_btn.pack(side="left")

        self._bar = ctk.CTkProgressBar(self, height=6, corner_radius=3,
                                      fg_color=BORDER, progress_color=ACCENT)
        self._bar.grid(row=1, column=0, columnspan=4, sticky="ew", padx=10, pady=(4, 2))
        self._bar.set(0)

        self._info = ctk.CTkLabel(self, text="", text_color=MUT, anchor="w",
                                  font=FONT_MONO)
        self._info.grid(row=2, column=0, columnspan=4, sticky="ew", padx=12, pady=(0, 8))

    def refresh(self) -> None:
        t = self.task
        st = t.status
        # Skip entirely when nothing visible changed — configure() calls are
        # what make the UI sluggish when progress ticks arrive rapidly.
        sig = (st, int(t.progress), t.speed_str, t.eta_str, t.current_filename,
               t.final_filename, t.error_message)
        if sig == self._sig:
            return
        status_changed = st != self._last_status
        self._sig = sig

        self._dot.configure(text_color=STATUS_COLOR.get(st, MUT))

        if status_changed:
            self._last_status = st
            if st in (DownloadStatus.COMPLETED, DownloadStatus.SKIPPED):
                self._bar.set(1.0)
                self._last_pct = 100
                self._bar.configure(progress_color=SUCCESS
                                    if st == DownloadStatus.COMPLETED else WARN)
            elif st == DownloadStatus.PAUSED:
                self._bar.configure(progress_color=WARN)
            else:
                self._bar.configure(progress_color=ACCENT)

            if st in (DownloadStatus.QUEUED, DownloadStatus.DOWNLOADING):
                self._pause_btn.pack(side="left", padx=(0, 2))
                self._pause_btn.configure(text="⏸", text_color=TEXT)
                self._retry_btn.pack_forget()
            elif st == DownloadStatus.PAUSED:
                self._pause_btn.pack(side="left", padx=(0, 2))
                self._pause_btn.configure(text="▶", text_color=SUCCESS)
                self._retry_btn.pack_forget()
            elif st == DownloadStatus.FAILED:
                self._pause_btn.pack_forget()
                self._retry_btn.pack(side="left", padx=(0, 2))
            else:
                self._pause_btn.pack_forget()
                self._retry_btn.pack_forget()

        pct = int(t.progress)
        if st in (DownloadStatus.COMPLETED, DownloadStatus.SKIPPED):
            pct = 100
        if pct != self._last_pct:
            self._bar.set(pct / 100.0)
            self._last_pct = pct

        self._info.configure(text=self._info_text())

    def _info_text(self) -> str:
        st = self.task.status
        if st == DownloadStatus.DOWNLOADING:
            parts = []
            if self.task.speed_str:
                parts.append(self.task.speed_str)
            if self.task.eta_str:
                parts.append(f"ETA {self.task.eta_str}")
            fn = self.task.current_filename or ""
            if fn:
                parts.append(fn)
            return "    ".join(parts)
        if st == DownloadStatus.COMPLETED:
            return self.task.final_filename or "Done"
        if st == DownloadStatus.FAILED:
            return f"Failed: {self.task.error_message or 'unknown error'}"
        if st == DownloadStatus.PAUSED:
            return "Paused"
        if st == DownloadStatus.SKIPPED:
            return self.task.error_message or "Skipped"
        return "Queued"


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("YouTube Downloader")
        self.configure(fg_color=BG)
        self.minsize(1024, 660)

        self._set_icon()

        self._queue = DownloadQueue(max_workers=1)
        self._queue.on_task_update = self._on_task_update
        self._queue.on_log = self._log_append
        self._rows: dict[str, QueueRow] = {}
        self._tasks: list = []
        # Coalesced refresh: progress events just mark rows dirty; a single
        # scheduled flush redraws them. Prevents event-loop flooding.
        self._pending_refresh: dict[str, object] = {}
        self._refresh_job: str | None = None
        self._last_running: bool | None = None
        # Auto-scroll: follow active downloads in large queues (1000 items)
        self._auto_scroll_enabled: bool = True
        self._auto_scroll_job: str | None = None

        self._build_ui()
        self._fix_mousewheel_scroll()

        self.after(500, self._validate_cookie_state)
        self.after(600, self._init_runtime)
        self._sync_buttons()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _fix_mousewheel_scroll(self) -> None:
        """Make the mouse wheel scroll the scrollable area under the pointer.
        customtkinter's built-in global <MouseWheel> handler only fires when
        the widget directly under the cursor is recognised, and rows inside
        CTkScrollableFrame contain nested canvases whose master chain never
        reaches the scrollable frame — so the wheel appears dead and only the
        scrollbar works. We drop their handler and route the event ourselves
        by hit-testing each scrollable frame's actual canvas rectangle."""
        self.unbind_all("<MouseWheel>")

        frames = [self._left_panel, self._scroll]

        def _on_wheel(event):
            px, py = event.x_root, event.y_root
            for fr in frames:
                cv = fr._parent_canvas
                x1 = cv.winfo_rootx()
                y1 = cv.winfo_rooty()
                x2 = x1 + cv.winfo_width()
                y2 = y1 + cv.winfo_height()
                if x1 <= px <= x2 and y1 <= py <= y2:
                    cv.yview_scroll(int(-event.delta / 6), "units")
                    return

        self.bind_all("<MouseWheel>", _on_wheel, add="+")

    def _on_close(self) -> None:
        try:
            self._queue.stop()
        except Exception:
            pass
        try:
            self.destroy()
        finally:
            os._exit(0)

    # ── Helpers ────────────────────────────────────────────────────────────

    def _card(self, parent, title=None):
        c = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=10)
        c.pack(fill="x", pady=(0, 12), padx=4)
        if title:
            ctk.CTkLabel(c, text=title, text_color=TEXT,
                         font=("Segoe UI", 11, "bold")).pack(anchor="w",
                                                             padx=12, pady=(10, 6))
        return c

    def _lbl(self, parent, text):
        ctk.CTkLabel(parent, text=text, text_color=MUT,
                     font=FONT_SM).pack(anchor="w", padx=12, pady=(8, 2))

    def _int_val(self, var, default):
        try:
            return int(str(var.get()).strip() or default)
        except Exception:
            return default

    # ── Window placement ─────────────────────────────────────────────────────

    def _center_window(self, width: int, height: int) -> None:
        work_left = work_top = 0
        work_w = self.winfo_screenwidth()
        work_h = self.winfo_screenheight()
        if sys.platform == "win32":
            try:
                import ctypes

                class RECT(ctypes.Structure):
                    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

                rect = RECT()
                if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
                    work_left, work_top = rect.left, rect.top
                    work_w = rect.right - rect.left
                    work_h = rect.bottom - rect.top
            except Exception:
                pass
        width = min(width, work_w)
        height = min(height, work_h)
        x = work_left + (work_w - width) // 2
        y = work_top + (work_h - height) // 2
        self.geometry(f"{width}x{height}+{x}+{y}")

    # ── Icon ────────────────────────────────────────────────────────────────

    def _set_icon(self) -> None:
        base = os.path.dirname(os.path.abspath(__file__))
        png_path = os.path.join(base, "assets", "icon.png")
        ico_path = os.path.join(base, "assets", "icon.ico")
        if not os.path.isfile(png_path):
            return
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                    "YouTubePlaylistDownloader.App.1")
            except Exception:
                pass
        try:
            icon = tk.PhotoImage(file=png_path)
            self.iconphoto(True, icon)
            self._icon_ref = icon
            if sys.platform == "win32" and os.path.isfile(ico_path):
                self.iconbitmap(ico_path)
        except Exception:
            pass

    # ── UI Build ────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        hdr = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=0, height=54)
        hdr.pack(fill="x")
        ctk.CTkLabel(hdr, text="▶  YouTube Downloader", text_color=TEXT,
                     font=FONT_HDR, padx=20).pack(side="left")

        body = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        body.pack(fill="both", expand=True, padx=14, pady=10)

        self._left_panel = ctk.CTkScrollableFrame(body, width=330, fg_color=PANEL,
                                      corner_radius=10,
                                      scrollbar_button_color=BORDER,
                                      scrollbar_button_hover_color=ACCENT)
        self._left_panel.pack(side="left", fill="y", padx=(0, 12))
        self._build_controls(self._left_panel)

        right = ctk.CTkFrame(body, fg_color=PANEL, corner_radius=10)
        right.pack(side="left", fill="both", expand=True)
        self._build_queue_panel(right)

        self._center_window(1240, 780)

    def _build_controls(self, parent: ctk.CTkScrollableFrame) -> None:
        # ── Source ──
        src = self._card(parent, "Source")
        ctk.CTkLabel(src, text="YouTube URL or Playlist URL", text_color=MUT,
                     font=FONT_SM).pack(anchor="w", padx=12)
        self._url_var = tk.StringVar()
        ctk.CTkEntry(src, textvariable=self._url_var, fg_color=ENTRY,
                     text_color=TEXT, border_color=BORDER, height=32,
                     font=FONT_LBL).pack(fill="x", padx=12, pady=(4, 0))

        rng = ctk.CTkFrame(src, fg_color="transparent")
        rng.pack(fill="x", padx=12, pady=(8, 0))
        ctk.CTkLabel(rng, text="From #", text_color=MUT, font=FONT_SM).pack(side="left")
        self._range_start_var = tk.StringVar(value="1")
        ctk.CTkEntry(rng, textvariable=self._range_start_var, width=52, height=26,
                     fg_color=ENTRY, text_color=TEXT, border_color=BORDER,
                     font=FONT_SM).pack(side="left", padx=(4, 8))
        ctk.CTkLabel(rng, text="To #", text_color=MUT, font=FONT_SM).pack(side="left")
        self._range_end_var = tk.StringVar(value="0")
        ctk.CTkEntry(rng, textvariable=self._range_end_var, width=52, height=26,
                     fg_color=ENTRY, text_color=TEXT, border_color=BORDER,
                     font=FONT_SM).pack(side="left", padx=(4, 0))
        ctk.CTkLabel(rng, text="(0 = end)", text_color=MUT,
                     font=("Segoe UI", 7)).pack(side="left", padx=(6, 0))

        # ── Options ──
        opt = self._card(parent, "Options")
        ctk.CTkLabel(opt, text="Output Format", text_color=MUT,
                     font=FONT_SM).pack(anchor="w", padx=12)
        self._format_var = tk.StringVar(value="MP4")
        fmt_row = ctk.CTkFrame(opt, fg_color="transparent")
        fmt_row.pack(fill="x", padx=12, pady=(2, 0))
        for f in ("MP4", "MP3", "AAC"):
            ctk.CTkRadioButton(fmt_row, text=f, variable=self._format_var, value=f,
                               command=self._on_format_change, fg_color=ACCENT,
                               border_color=BORDER, text_color=TEXT,
                               font=FONT_LBL).pack(side="left", padx=(0, 10))

        ctk.CTkLabel(opt, text="Video Quality", text_color=MUT,
                     font=FONT_SM).pack(anchor="w", padx=12, pady=(8, 2))
        self._vq_var = tk.StringVar(value="RAW (Best)")
        self._vq_combo = ctk.CTkComboBox(opt, values=list(VIDEO_QUALITY_LABELS.keys()),
                                        variable=self._vq_var, state="readonly",
                                        fg_color=ENTRY, text_color=TEXT,
                                        button_color=BORDER, dropdown_fg_color=PANEL,
                                        border_color=BORDER, font=FONT_LBL)
        self._vq_combo.pack(fill="x", padx=12)

        ctk.CTkLabel(opt, text="Audio Quality", text_color=MUT,
                     font=FONT_SM).pack(anchor="w", padx=12, pady=(8, 2))
        self._aq_var = tk.StringVar(value="320 kbps")
        ctk.CTkComboBox(opt, values=list(AUDIO_QUALITY_LABELS.keys()),
                        variable=self._aq_var, state="readonly", fg_color=ENTRY,
                        text_color=TEXT, button_color=BORDER,
                        dropdown_fg_color=PANEL, border_color=BORDER,
                        font=FONT_LBL).pack(fill="x", padx=12)

        ctk.CTkLabel(opt, text="Output Folder", text_color=MUT,
                     font=FONT_SM).pack(anchor="w", padx=12, pady=(8, 2))
        dir_row = ctk.CTkFrame(opt, fg_color="transparent")
        dir_row.pack(fill="x", padx=12)
        self._dir_var = tk.StringVar(value=os.path.abspath("downloads"))
        ctk.CTkEntry(dir_row, textvariable=self._dir_var, fg_color=ENTRY,
                     text_color=TEXT, border_color=BORDER, height=28,
                     font=FONT_SM).pack(side="left", fill="x", expand=True)
        ctk.CTkButton(dir_row, text="Browse", command=self._browse_dir, width=70,
                      height=28, fg_color=BORDER, hover_color=ACCENT,
                      text_color=TEXT, font=FONT_SM).pack(side="left", padx=(6, 0))

        self._skip_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(opt, text="Skip already-downloaded videos",
                        variable=self._skip_var, fg_color=ACCENT,
                        border_color=BORDER, text_color=MUT,
                        font=FONT_SM).pack(anchor="w", padx=12, pady=(10, 0))

        # ── Throttling ──
        thr = self._card(parent, "Throttling (avoid IP ban)")
        ctk.CTkLabel(thr, text="Delay between downloads (sec)", text_color=MUT,
                     font=FONT_SM).pack(anchor="w", padx=12)
        self._delay_var = tk.StringVar(value="5")
        ctk.CTkEntry(thr, textvariable=self._delay_var, width=60, height=26,
                     fg_color=ENTRY, text_color=TEXT, border_color=BORDER,
                     font=FONT_SM).pack(anchor="w", padx=12, pady=(2, 0))

        ctk.CTkLabel(thr, text="Pause after every N videos", text_color=MUT,
                     font=FONT_SM).pack(anchor="w", padx=12, pady=(8, 2))
        self._batch_size_var = tk.StringVar(value="10")
        ctk.CTkEntry(thr, textvariable=self._batch_size_var, width=60, height=26,
                     fg_color=ENTRY, text_color=TEXT, border_color=BORDER,
                     font=FONT_SM).pack(anchor="w", padx=12, pady=(2, 0))

        ctk.CTkLabel(thr, text="Batch pause duration (sec)", text_color=MUT,
                     font=FONT_SM).pack(anchor="w", padx=12, pady=(8, 2))
        self._batch_pause_var = tk.StringVar(value="60")
        ctk.CTkEntry(thr, textvariable=self._batch_pause_var, width=60, height=26,
                     fg_color=ENTRY, text_color=TEXT, border_color=BORDER,
                     font=FONT_SM).pack(anchor="w", padx=12, pady=(2, 4))

        # ── Cookies ──
        ck = self._card(parent, "Cookies (fixes bot detection)")
        self._cookies_var = tk.StringVar(value="firefox")
        ctk.CTkComboBox(ck, values=["None", "chrome", "firefox", "edge",
                                    "brave", "opera", "chromium"],
                        variable=self._cookies_var, state="readonly",
                        fg_color=ENTRY, text_color=TEXT, button_color=BORDER,
                        dropdown_fg_color=PANEL, border_color=BORDER,
                        font=FONT_LBL).pack(fill="x", padx=12)
        ctk.CTkLabel(ck, justify="left", text_color=MUT,
                     text="Note: Chrome/Edge 127+ block cookie decryption for external apps "
                          "(DPAPI / App-Bound Encryption). If extraction fails, use "
                          "'firefox' here or a cookies.txt file below.",
                     font=FONT_SM).pack(anchor="w", padx=12, pady=(4, 0))
        ctk.CTkLabel(ck, text="Cookies.txt file (alternative)", text_color=MUT,
                     font=FONT_SM).pack(anchor="w", padx=12, pady=(8, 2))
        cfile_row = ctk.CTkFrame(ck, fg_color="transparent")
        cfile_row.pack(fill="x", padx=12)
        self._cookiefile_var = tk.StringVar(value="")
        ctk.CTkEntry(cfile_row, textvariable=self._cookiefile_var, fg_color=ENTRY,
                     text_color=TEXT, border_color=BORDER, height=28,
                     font=FONT_SM).pack(side="left", fill="x", expand=True)
        ctk.CTkButton(cfile_row, text="Browse", command=self._browse_cookies,
                      width=70, height=28, fg_color=BORDER, hover_color=ACCENT,
                      text_color=TEXT, font=FONT_SM).pack(side="left", padx=(6, 0))
        ctk.CTkButton(cfile_row, text="✕", command=lambda: self._cookiefile_var.set(""),
                      width=30, height=28, fg_color="#333333", hover_color=ACCENT,
                      text_color=TEXT, font=FONT_SM).pack(side="left", padx=(4, 0))
        ctk.CTkLabel(ck, text="Netscape format. Use 'Get cookies.txt LOCALLY'.",
                     text_color=MUT, font=("Segoe UI", 7),
                     wraplength=290, justify="left").pack(anchor="w", padx=12, pady=(4, 0))

        # ── Actions ──
        act = self._card(parent, "Actions")
        self._add_btn = ctk.CTkButton(act, text="＋  Add to Queue",
                                      command=self._add_to_queue, height=34,
                                      fg_color="#525252", hover_color="#636363",
                                      text_color=TEXT, font=("Segoe UI", 11, "bold"))
        self._add_btn.pack(fill="x", padx=12, pady=(2, 6))
        self._start_btn = ctk.CTkButton(act, text="▶  Start", command=self._start_queue,
                                        height=34, fg_color=SUCCESS, hover_color="#1ca44e",
                                        text_color="#06210f",
                                        font=("Segoe UI", 11, "bold"))
        self._start_btn.pack(fill="x", padx=12, pady=(0, 6))
        self._pause_btn = ctk.CTkButton(act, text="⏸  Pause", command=self._pause_queue,
                                        height=34, fg_color="#787878", hover_color="#8a8a8a",
                                        text_color=TEXT, font=("Segoe UI", 11, "bold"))
        self._pause_btn.pack(fill="x", padx=12, pady=(0, 6))
        self._retry_btn = ctk.CTkButton(act, text="↻  Retry Failed",
                                        command=self._retry_failed, height=34,
                                        fg_color="#525252", hover_color="#636363",
                                        text_color=TEXT, font=("Segoe UI", 11, "bold"))
        self._retry_btn.pack(fill="x", padx=12, pady=(0, 6))
        self._clear_btn = ctk.CTkButton(act, text="🗑  Clear Queue",
                                        command=self._clear_queue, height=34,
                                        fg_color="#780002", hover_color=ACCENT_H,
                                        text_color=TEXT,
                                        font=("Segoe UI", 11, "bold"))
        self._clear_btn.pack(fill="x", padx=12, pady=(0, 6))

    def _build_queue_panel(self, parent: ctk.CTkFrame) -> None:
        hdr = ctk.CTkFrame(parent, fg_color="transparent")
        hdr.pack(fill="x", padx=14, pady=(12, 4))
        ctk.CTkLabel(hdr, text="Download Queue", text_color=TEXT,
                     font=("Segoe UI", 14, "bold")).pack(side="left")
        self._count_lbl = ctk.CTkLabel(hdr, text="0 items", text_color=MUT,
                                       font=FONT_SM)
        self._count_lbl.pack(side="right")
        # Auto-scroll toggle — lets user keep manual control if needed
        self._auto_scroll_var = tk.BooleanVar(value=True)
        self._auto_scroll_chk = ctk.CTkCheckBox(
            hdr, text="Auto-scroll", variable=self._auto_scroll_var,
            command=self._on_auto_scroll_toggle,
            fg_color=ACCENT, border_color=BORDER, text_color=MUT,
            font=FONT_SM, checkbox_width=14, checkbox_height=14)
        self._auto_scroll_chk.pack(side="right", padx=(0, 10))

        opf = ctk.CTkFrame(parent, fg_color="transparent")
        opf.pack(fill="x", padx=14, pady=(0, 4))
        self._overall_bar = ctk.CTkProgressBar(opf, height=8, corner_radius=4,
                                               fg_color=BORDER, progress_color=PROGRESS)
        self._overall_bar.pack(fill="x")
        self._overall_bar.set(0)
        self._overall_lbl = ctk.CTkLabel(opf, text="", text_color=MUT,
                                         font=FONT_SM, anchor="w")
        self._overall_lbl.pack(anchor="w")

        self._scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent",
                                             corner_radius=0,
                                             scrollbar_button_color=BORDER,
                                             scrollbar_button_hover_color=ACCENT)
        self._scroll.pack(fill="both", expand=True, padx=6, pady=(4, 0))

        log_hdr = ctk.CTkFrame(parent, fg_color="transparent")
        log_hdr.pack(fill="x", padx=14, pady=(4, 2))
        ctk.CTkLabel(log_hdr, text="Log", text_color=MUT,
                     font=FONT_SM).pack(side="left")
        ctk.CTkButton(log_hdr, text="Clear Log", command=self._clear_log, width=74,
                      height=24, fg_color=BORDER, hover_color=ACCENT, text_color=TEXT,
                      font=FONT_SM).pack(side="right")
        ctk.CTkButton(log_hdr, text="Clear Done", command=self._clear_done, width=74,
                      height=24, fg_color=BORDER, hover_color=ACCENT, text_color=TEXT,
                      font=FONT_SM).pack(side="right", padx=(0, 6))

        self._log = ctk.CTkTextbox(parent, height=96, fg_color="#0c0c0c",
                                   text_color=MUT, border_color=BORDER,
                                   font=FONT_MONO, corner_radius=6)
        self._log.pack(fill="x", padx=10, pady=(0, 6))
        self._log.configure(state="disabled")

        self._status_var = tk.StringVar(value="Ready")
        ctk.CTkLabel(parent, textvariable=self._status_var, text_color=MUT,
                     font=FONT_SM, anchor="w").pack(fill="x", padx=14, pady=(0, 8))

    # ── Format toggle ────────────────────────────────────────────────────────

    def _on_format_change(self) -> None:
        if self._format_var.get() == "MP4":
            self._vq_combo.configure(state="readonly")
        else:
            self._vq_combo.configure(state="disabled")

    # ── Runtime init ──────────────────────────────────────────────────────────

    def _init_runtime(self) -> None:
        def work():
            status = runtime.setup(log=lambda m: self.after(0, lambda msg=m: self._log_append(msg)))
            missing = []
            if not status.get("ffmpeg"):
                missing.append("FFmpeg (required)")
            if not status.get("deno"):
                missing.append("Deno")
            if not status.get("pot"):
                missing.append("PO token provider")
            if not missing:
                self.after(0, lambda: self._set_status("Ready — download engine fully configured."))
            else:
                self.after(0, lambda: self._set_status(
                    "⚠ Downloads may fail — missing: " + ", ".join(missing)))
        threading.Thread(target=work, daemon=True).start()

    def _validate_cookie_state(self) -> None:
        path = self._cookiefile_var.get().strip()
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                first = f.readline().strip()
            if "Netscape" not in first and "HTTP Cookie" not in first:
                self._cookiefile_var.set("")
                self._log_append(
                    f"Cleared invalid cookies.txt (not Netscape format): {path}\n"
                    "Use the 'Get cookies.txt LOCALLY' Chrome extension to export a valid file."
                )
        except Exception:
            self._cookiefile_var.set("")

    # ── Browsers ──────────────────────────────────────────────────────────────

    def _browse_dir(self) -> None:
        path = filedialog.askdirectory(initialdir=self._dir_var.get())
        if path:
            self._dir_var.set(path)

    def _browse_cookies(self) -> None:
        path = filedialog.askopenfilename(
            title="Select cookies.txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                first_line = f.readline().strip()
            if "Netscape" not in first_line and "HTTP Cookie" not in first_line:
                messagebox.showerror(
                    "Invalid Cookie File",
                    "This file is not in Netscape format.\n\n"
                    "Export cookies using the 'Get cookies.txt LOCALLY' Chrome extension "
                    "or 'cookies.txt' Firefox extension, then try again.\n\n"
                    f"First line found:\n{first_line[:120]}"
                )
                return
        except Exception:
            pass
        self._cookiefile_var.set(path)

    def _browser_running(self, browser: str) -> bool:
        if sys.platform != "win32":
            return False
        exe = {
            "chrome": "chrome.exe", "firefox": "firefox.exe", "edge": "msedge.exe",
            "brave": "brave.exe", "opera": "opera.exe", "chromium": "chrome.exe",
        }.get(browser)
        if not exe:
            return False
        try:
            out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {exe}"],
                                 capture_output=True, text=True, timeout=5).stdout
            return exe.lower() in out.lower()
        except Exception:
            return False

    def _is_elevated(self) -> bool:
        if sys.platform != "win32":
            return False
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False

    def _valid_cookiefile(self) -> str:
        path = self._cookiefile_var.get().strip()
        if not path:
            return ""
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                first = f.readline().strip()
            if "Netscape" in first or "HTTP Cookie" in first:
                return path
        except Exception:
            pass
        return ""

    # ── Queue building ────────────────────────────────────────────────────────

    def _add_to_queue(self) -> None:
        url = self._url_var.get().strip()
        if not url:
            messagebox.showwarning("No URL", "Please enter a YouTube URL.")
            return

        fmt_map = {"MP4": OutputFormat.MP4, "MP3": OutputFormat.MP3,
                   "AAC": OutputFormat.AAC}
        output_format = fmt_map[self._format_var.get()]
        video_quality = VIDEO_QUALITY_LABELS.get(
            self._vq_var.get(), list(VIDEO_QUALITY_LABELS.values())[0])
        audio_quality = AUDIO_QUALITY_LABELS.get(
            self._aq_var.get(), list(AUDIO_QUALITY_LABELS.values())[0])
        delay = self._int_val(self._delay_var, 0)

        self._set_status("Fetching YouTube URL info — please wait…")
        self._log_append(f"Fetching: {url}")
        self._add_btn.configure(state="disabled")

        def fetch() -> None:
            try:
                def _log(msg, self=self):
                    self.after(0, lambda m=msg: self._log_append(m))

                browser = self._cookies_var.get()
                cookies_from_browser = browser if browser != "None" else None
                cookiefile = self._valid_cookiefile() or None

                if cookies_from_browser and self._browser_running(cookies_from_browser):
                    self._log_append(
                        f"NOTE: {cookies_from_browser} is still running (possibly background "
                        f"processes). The app will force-unlock its cookie database automatically; "
                        f"you can proceed. To stop the warnings, fully end all {cookies_from_browser} "
                        f"processes in Task Manager (or run: taskkill /IM {cookies_from_browser}.exe /F), "
                        f"or disable 'Continue running background apps' in the browser settings.")

                if cookies_from_browser and self._is_elevated():
                    self._log_append(
                        "WARNING: app is running as Administrator - Chrome/Edge cookie "
                        "decryption (DPAPI) will likely fail. Run as your normal user, "
                        "or use a cookies.txt file.")
                    messagebox.showwarning(
                        "Running as Administrator",
                        "You are running this app with Administrator privileges.\n\n"
                        "Chrome/Edge cookies are encrypted with DPAPI and can only be decrypted by "
                        "the same Windows user that opened the browser. If the browser isn't also "
                        "elevated, cookie decryption fails with 'Failed to decrypt with DPAPI'.\n\n"
                        "Fix: launch the app as your normal (non-Admin) user, or export a cookies.txt "
                        "with the 'Get cookies.txt LOCALLY' extension and use that instead.")

                tasks = build_tasks(
                    url=url,
                    output_format=output_format,
                    video_quality=video_quality,
                    audio_quality=audio_quality,
                    output_dir=self._dir_var.get(),
                    skip_downloaded=self._skip_var.get(),
                    log_callback=_log,
                    cookies_from_browser=cookies_from_browser,
                    cookiefile=cookiefile,
                )
                self.after(0, lambda: self._enqueue_tasks(tasks, delay))
            except Exception as exc:
                msg = _strip_ansi(str(exc))
                self.after(0, lambda m=msg: self._set_status(f"Error: {m}"))
                self.after(0, lambda m=msg: self._log_append(f"ERROR: {m}"))
                self.after(0, lambda m=msg: messagebox.showerror("Fetch Error", m))
            finally:
                self.after(0, lambda: self._add_btn.configure(state="normal"))

        threading.Thread(target=fetch, daemon=True).start()

    def _enqueue_tasks(self, tasks: list, delay: int = 0) -> None:
        if not tasks:
            self._set_status("No videos found at that URL.")
            self._log_append("No downloadable videos found.")
            messagebox.showwarning("No Items",
                                   "No downloadable videos were found at that URL.")
            return

        if len(tasks) > 1:
            start = max(1, self._int_val(self._range_start_var, 1))
            end = self._int_val(self._range_end_var, 0)
            if end <= 0 or end > len(tasks):
                end = len(tasks)
            if start > 1 or end < len(tasks):
                total = len(tasks)
                tasks = tasks[start - 1:end]
                self._log_append(
                    f"Range applied: videos {start}–{end} of {total} "
                    f"({len(tasks)} item(s)).")

        # ── Queue capacity guard (MAX_QUEUE_SIZE = 1000) ──────────────────
        remaining = MAX_QUEUE_SIZE - len(self._tasks)
        if remaining <= 0:
            self._log_append(f"Queue full ({MAX_QUEUE_SIZE}/{MAX_QUEUE_SIZE}) — clear items before adding more.")
            messagebox.showwarning(
                "Queue Full",
                f"The queue is at its limit of {MAX_QUEUE_SIZE} videos.\n\n"
                "Remove completed/failed items (Clear Done) or clear the queue before adding more.")
            self._update_count_label()
            return

        # Filter duplicates first so capacity accounting is accurate.
        unique = []
        dup_count = 0
        for t in tasks:
            if t.video_id in self._rows:
                dup_count += 1
            else:
                unique.append(t)
        if dup_count:
            self._log_append(f"Skipped {dup_count} duplicate(s) already in queue.")

        if not unique:
            self._set_status("All videos were already in the queue.")
            self._update_count_label()
            return

        truncated = 0
        if len(unique) > remaining:
            truncated = len(unique) - remaining
            unique = unique[:remaining]
            self._log_append(
                f"Queue limit: only {remaining} of {remaining + truncated} new video(s) can be added "
                f"(cap {MAX_QUEUE_SIZE}). {truncated} video(s) not added — clear done items or increase range filtering.")
            messagebox.showwarning(
                "Queue Limit Reached",
                f"Only {remaining} more video(s) can be added (limit {MAX_QUEUE_SIZE}).\n\n"
                f"{truncated} video(s) were not added.\n"
                "Tip: use 'From # / To #' range or 'Clear Done' to make space.")

        # Large playlists can freeze the UI if all 1000 rows are created at once.
        # Create rows in small chunks via after() so the event loop stays responsive.
        # total_target is dynamic (starting + to_add), not static 1000.
        target_total = len(self._tasks) + len(unique)
        if len(unique) > QUEUE_CHUNK_SIZE:
            self._set_status(f"Adding {len(unique)} item(s) to queue…")
            self._enqueue_chunked(unique, delay, 0, truncated, dup_count, target_total)
        else:
            added = self._add_tasks_sync(unique, delay)
            self._finish_enqueue(added, truncated, dup_count)

    def _add_tasks_sync(self, tasks: list, delay: int) -> list:
        """Synchronously add a small batch and create rows. Returns added list."""
        added = []
        for task in tasks:
            task.inter_download_delay = delay
            ok = self._queue.ensure_pending(task)
            if not ok:
                self._log_append(f"Queue full — could not add: {task.title}")
                break
            self._tasks.append(task)
            row = QueueRow(self._scroll, task, callbacks={
                "on_pause": self._pause_task,
                "on_resume": self._resume_task,
                "on_retry": self._retry_task,
                "on_delete": self._delete_task,
            })
            row.pack(fill="x", padx=4, pady=4)
            row.refresh()
            self._rows[task.video_id] = row
            added.append(task)
        self._update_count_label()
        self._update_overall()
        return added

    def _enqueue_chunked(self, tasks: list, delay: int, offset: int,
                         truncated: int, dup_count: int, target_total: int) -> None:
        chunk = tasks[offset: offset + QUEUE_CHUNK_SIZE]
        for task in chunk:
            task.inter_download_delay = delay
            ok = self._queue.ensure_pending(task)
            if not ok:
                self._log_append(f"Queue full — stopped at {len(self._tasks)}/{MAX_QUEUE_SIZE}.")
                break
            self._tasks.append(task)
            row = QueueRow(self._scroll, task, callbacks={
                "on_pause": self._pause_task,
                "on_resume": self._resume_task,
                "on_retry": self._retry_task,
                "on_delete": self._delete_task,
            })
            row.pack(fill="x", padx=4, pady=4)
            row.refresh()
            self._rows[task.video_id] = row

        # Dynamic: loaded / totalItems (progressive), not loaded/1000
        self._update_count_label(total=target_total)
        self._update_overall()

        nxt = offset + QUEUE_CHUNK_SIZE
        if nxt < len(tasks):
            # Schedule next chunk without blocking UI (progress bar stays alive)
            self.after(15, lambda: self._enqueue_chunked(tasks, delay, nxt, truncated, dup_count, target_total))
        else:
            added_count = len(tasks)
            self._finish_enqueue(tasks[:added_count], truncated, dup_count)

    def _finish_enqueue(self, added: list, truncated: int, dup_count: int) -> None:
        self._log_append(f"Added {len(added)} item(s) to queue.")
        if truncated:
            self._set_status(
                f"Added {len(added)} item(s) (limit {MAX_QUEUE_SIZE}, {truncated} not added). Click Start to begin.")
        else:
            self._set_status(f"Added {len(added)} item(s). Click Start to begin.")
        self._update_count_label()
        self._update_overall()

    def _update_count_label(self, total: int | None = None) -> None:
        n = len(self._tasks)
        # Dynamic denominator: loaded / total in queue, NOT static 1000.
        # While chunk-adding, show progress e.g. 120/500; otherwise just "N items".
        if total is not None and total != n and total > 0:
            self._count_lbl.configure(text=f"{n}/{total} items")
        else:
            self._count_lbl.configure(text=f"{n} items")
        # Warn visually as we approach the hard cap (still enforced in queue.py)
        if n >= MAX_QUEUE_SIZE:
            self._count_lbl.configure(text_color=ERR)
        elif n >= int(MAX_QUEUE_SIZE * 0.8):
            self._count_lbl.configure(text_color=WARN)
        else:
            self._count_lbl.configure(text_color=MUT)

    # ── Queue controls ────────────────────────────────────────────────────────

    def _apply_throttle(self) -> None:
        self._queue.max_workers = int(self._workers_var.get()) if hasattr(self, "_workers_var") else 1
        self._queue.batch_size = self._int_val(self._batch_size_var, 0)
        self._queue.batch_pause = self._int_val(self._batch_pause_var, 0)

    def _start_queue(self) -> None:
        if not self._tasks:
            messagebox.showinfo("Queue Empty",
                                "Add items to the queue first, then click Start.")
            return
        self._apply_throttle()
        self._queue.start(skip_downloaded=self._skip_var.get())
        self._log_append(f"Starting downloads ({self._queue.max_workers} concurrent)…")
        self._set_status("Downloading…")

    def _pause_queue(self) -> None:
        self._queue.pause_all()
        self._log_append("Queue paused — you can resume anytime.")
        self._set_status("Paused.")

    def _retry_failed(self) -> None:
        failed = [t for t in self._tasks if t.status == DownloadStatus.FAILED]
        if not failed:
            messagebox.showinfo("Nothing to Retry", "No failed items in the queue.")
            return
        requeued = 0
        for task in failed:
            self._reset_task(task)
            if self._queue.ensure_pending(task):
                requeued += 1
            else:
                self._log_append(f"Queue full — could not requeue: {task.title}")
        if requeued == 0:
            messagebox.showwarning("Queue Full", f"Queue is at limit ({MAX_QUEUE_SIZE}). Clear space before retrying.")
            return
        self._apply_throttle()
        self._queue.start(skip_downloaded=self._skip_var.get())
        self._log_append(f"Retrying {requeued}/{len(failed)} failed item(s)…")
        self._set_status(f"Retrying {requeued} item(s)…")

    def _clear_queue(self) -> None:
        self._queue.stop()
        self._queue.clear()
        self._tasks.clear()
        self._rows.clear()
        self._pending_refresh.clear()
        for w in self._scroll.winfo_children():
            w.destroy()
        self._update_count_label()
        self._overall_bar.set(0)
        self._overall_lbl.configure(text="")
        self._log_append("Queue cleared.")
        self._set_status("Queue cleared.")

    def _clear_done(self) -> None:
        finished = {DownloadStatus.COMPLETED, DownloadStatus.FAILED,
                    DownloadStatus.SKIPPED}
        still_active = []
        for task in self._tasks:
            if task.status in finished:
                row = self._rows.pop(task.video_id, None)
                if row:
                    row.destroy()
            else:
                still_active.append(task)
        self._tasks = still_active
        self._update_count_label()
        self._update_overall()
        self._set_status(f"Cleared finished items. {len(self._tasks)} remaining.")

    # ── Per-item controls ─────────────────────────────────────────────────────

    def _pause_task(self, task) -> None:
        if task.status == DownloadStatus.DOWNLOADING:
            task.pause_requested = True
        elif task.status == DownloadStatus.QUEUED:
            task.status = DownloadStatus.PAUSED
            self._refresh_row(task)

    def _resume_task(self, task) -> None:
        if task.status not in (DownloadStatus.PAUSED, DownloadStatus.FAILED,
                               DownloadStatus.QUEUED):
            return
        self._reset_task(task)
        if not self._queue.ensure_pending(task):
            messagebox.showwarning("Queue Full", f"Queue is at limit ({MAX_QUEUE_SIZE}). Clear space before resuming.")
            self._log_append(f"Queue full — could not resume: {task.title}")
            return
        self._apply_throttle()
        self._queue.start(skip_downloaded=self._skip_var.get())

    def _retry_task(self, task) -> None:
        self._reset_task(task)
        if not self._queue.ensure_pending(task):
            messagebox.showwarning("Queue Full", f"Queue is at limit ({MAX_QUEUE_SIZE}). Clear space before retrying.")
            self._log_append(f"Queue full — could not retry: {task.title}")
            return
        self._apply_throttle()
        self._queue.start(skip_downloaded=self._skip_var.get())

    def _reset_task(self, task) -> None:
        task.status = DownloadStatus.QUEUED
        task.progress = 0.0
        task.error_message = None
        task.pause_requested = False
        task.cancelled = False
        task.speed_str = ""
        task.eta_str = ""
        task.current_filename = ""
        self._refresh_row(task)

    def _delete_task(self, task) -> None:
        task.cancelled = True
        self._pending_refresh.pop(task.video_id, None)
        row = self._rows.pop(task.video_id, None)
        if row:
            row.destroy()
        self._tasks = [t for t in self._tasks if t.video_id != task.video_id]
        self._update_count_label()
        self._update_overall()
        self._set_status(f"Removed: {task.title[:50]}")

    def _clear_log(self) -> None:
        self._log.configure(state="normal")
        self._log.delete("0.0", "end")
        self._log.configure(state="disabled")

    # ── Update helpers ────────────────────────────────────────────────────────

    def _on_task_update(self, task) -> None:
        # Called from worker threads — just mark dirty; the flush redraws.
        self._pending_refresh[task.video_id] = task
        if self._refresh_job is None:
            self._refresh_job = self.after(150, self._flush_pending)

    def _flush_pending(self) -> None:
        self._refresh_job = None
        pending, self._pending_refresh = self._pending_refresh, {}
        for task in pending.values():
            self._refresh_row(task)

    def _refresh_row(self, task) -> None:
        row = self._rows.get(task.video_id)
        if row:
            row.refresh()

        completed = sum(1 for t in self._tasks if t.status == DownloadStatus.COMPLETED)
        failed    = sum(1 for t in self._tasks if t.status == DownloadStatus.FAILED)
        skipped   = sum(1 for t in self._tasks if t.status == DownloadStatus.SKIPPED)
        paused    = sum(1 for t in self._tasks if t.status == DownloadStatus.PAUSED)
        total     = len(self._tasks)

        if task.status == DownloadStatus.COMPLETED:
            self._log_append(f"✓ {task.title}")
        elif task.status == DownloadStatus.FAILED:
            line = f"✗ {task.title}: {task.error_message or 'unknown error'}"
            if task.error_suggestion:
                line += f"  →  {task.error_suggestion}"
            self._log_append(line)
        elif task.status == DownloadStatus.PAUSED:
            self._log_append(f"⏸ Paused: {task.title}")

        self._update_overall(completed, failed, skipped, paused, total)
        self._set_status(
            f"Completed: {completed}  Failed: {failed}  "
            f"Skipped: {skipped}  Paused: {paused}  Total: {total}")

        # Auto-scroll to next active video once the top batch finishes,
        # so user doesn't need manual scrolling in 1000-item queues.
        if task.status in (DownloadStatus.COMPLETED, DownloadStatus.FAILED,
                          DownloadStatus.SKIPPED, DownloadStatus.DOWNLOADING):
            self._schedule_auto_scroll()

    def _update_overall(self, completed=None, failed=None, skipped=None,
                        paused=None, total=None) -> None:
        if total is None:
            total = len(self._tasks)
        if total == 0:
            self._overall_bar.set(0)
            self._overall_lbl.configure(text="")
            return
        if completed is None:
            completed = sum(1 for t in self._tasks if t.status == DownloadStatus.COMPLETED)
        if failed is None:
            failed = sum(1 for t in self._tasks if t.status == DownloadStatus.FAILED)
        if skipped is None:
            skipped = sum(1 for t in self._tasks if t.status == DownloadStatus.SKIPPED)
        if paused is None:
            paused = sum(1 for t in self._tasks if t.status == DownloadStatus.PAUSED)

        done = completed + failed + skipped
        pct = (done / total) * 100
        self._overall_bar.set(pct / 100.0)
        self._overall_lbl.configure(
            text=f"{done}/{total} done  •  {completed} completed  •  "
                 f"{failed} failed  •  {skipped} skipped  •  {paused} paused  •  {pct:.0f}%")

    # ── Auto-scroll (queue follow) ───────────────────────────────────────────
    def _on_auto_scroll_toggle(self) -> None:
        self._auto_scroll_enabled = bool(self._auto_scroll_var.get())
        if self._auto_scroll_enabled:
            self._schedule_auto_scroll()

    def _schedule_auto_scroll(self) -> None:
        if not getattr(self, "_auto_scroll_enabled", True):
            return
        if self._auto_scroll_job is not None:
            try:
                self.after_cancel(self._auto_scroll_job)
            except Exception:
                pass
        # Debounce — many COMPLETED events can fire together in a batch
        self._auto_scroll_job = self.after(280, self._do_auto_scroll)

    def _do_auto_scroll(self) -> None:
        self._auto_scroll_job = None
        if not getattr(self, "_auto_scroll_enabled", True):
            return
        if not self._tasks or not hasattr(self, "_scroll"):
            return
        if not self._queue.is_running:
            return
        try:
            # Prefer the currently DOWNLOADING item, otherwise next QUEUED
            active_idx: int | None = None
            for idx, t in enumerate(self._tasks):
                if t.status == DownloadStatus.DOWNLOADING:
                    active_idx = idx
                    break
            if active_idx is None:
                for idx, t in enumerate(self._tasks):
                    if t.status == DownloadStatus.QUEUED:
                        active_idx = idx
                        break
            if active_idx is None:
                return
            canvas = self._scroll._parent_canvas  # CTkScrollableFrame internals
            total = len(self._tasks)
            # Skip if active already comfortably inside viewport (avoid jitter)
            try:
                first, last = canvas.yview()
                frac = active_idx / max(1, total)
                # 8% hysteresis — only scroll if active is off-screen or near edge
                if first + 0.06 <= frac <= last - 0.06:
                    return
            except Exception:
                pass
            # Place active ~12% from top so a couple of preceding rows stay visible
            target = max(0.0, min(1.0, (active_idx - 1) / max(1, total)))
            # Ensure geometry is up to date before scrolling
            try:
                self.update_idletasks()
            except Exception:
                pass
            canvas.yview_moveto(target)
        except Exception:
            pass

    def _sync_buttons(self) -> None:
        running = self._queue.is_running
        if running != self._last_running:
            self._last_running = running
            self._start_btn.configure(state="normal" if not running else "disabled")
            self._pause_btn.configure(state="disabled" if not running else "normal")
        # Disable Add when at capacity to prevent accidental 1000+ growth
        try:
            is_full = len(self._tasks) >= MAX_QUEUE_SIZE
            self._add_btn.configure(state="disabled" if is_full else "normal")
        except Exception:
            pass
        self.after(400, self._sync_buttons)

    def _log_append(self, msg: str) -> None:
        self._log.configure(state="normal")
        self._log.insert("end", msg + "\n")
        # Trim log to keep memory/UI responsive with large queues (1000 items → many log lines)
        try:
            line_count = int(self._log.index("end-1c").split(".")[0])
            if line_count > 1200:
                self._log.delete("1.0", f"{line_count - 1000}.0")
        except Exception:
            pass
        self._log.see("end")
        self._log.configure(state="disabled")

    def _set_status(self, msg: str) -> None:
        self._status_var.set(msg)


if __name__ == "__main__":
    app = App()
    app.mainloop()
