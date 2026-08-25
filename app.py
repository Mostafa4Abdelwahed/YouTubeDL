import os
import re
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox


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
from downloader.queue import DownloadQueue
from downloader import runtime
from storage import db


# YouTube-style dark theme with a red accent palette
DARK_BG   = "#181818"
PANEL_BG  = "#242424"
PANEL_BG2 = "#2b2b2b"
ACCENT    = "#CE0000"
ACCENT_H  = "#A30003"
SECONDARY = "#780002"
TEXT_PRI  = "#f1f1f1"
TEXT_MUT  = "#9a9a9a"
SUCCESS   = "#22c55e"
WARNING   = "#f59e0b"
ERROR     = "#F90004"
BORDER    = "#3a3a3a"
LOG_BG    = "#0f0f0f"
SELECT_BG = "#5a5a5a"
PROGRESS  = "#947472"
DLOAD_CLR = "#8c9472"

FONT_HDR  = ("Segoe UI", 13, "bold")
FONT_LBL  = ("Segoe UI", 10)
FONT_SM   = ("Segoe UI", 9)
FONT_MONO = ("Consolas", 8)


STATUS_COLOR = {
    DownloadStatus.QUEUED:      TEXT_MUT,
    DownloadStatus.DOWNLOADING: DLOAD_CLR,
    DownloadStatus.COMPLETED:   SUCCESS,
    DownloadStatus.FAILED:      ERROR,
    DownloadStatus.SKIPPED:     WARNING,
    DownloadStatus.PAUSED:      WARNING,
}


class RoundedButton(tk.Button):
    def __init__(self, parent, text, command, bg=ACCENT, fg=TEXT_PRI,
                 hover_bg=ACCENT_H, **kwargs):
        for k in ("width", "height", "radius"):
            kwargs.pop(k, None)
        super().__init__(
            parent, text=text, command=command,
            bg=bg, fg=fg,
            activebackground=hover_bg, activeforeground=fg,
            relief="flat", bd=0, cursor="hand2",
            font=("Segoe UI", 10, "bold"),
            highlightthickness=0,
            padx=10, pady=6,
        )
        self._bg = bg
        self._hover_bg = hover_bg
        self._enabled = True
        self.bind("<Enter>", lambda e: self.config(bg=hover_bg) if self._enabled else None)
        self.bind("<Leave>", lambda e: self.config(bg=bg) if self._enabled else None)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self.config(state="normal" if enabled else "disabled",
                    bg=self._bg if enabled else BORDER)

    def set_text(self, text: str) -> None:
        self.config(text=text)


class IconButton(tk.Button):
    """Small square-ish icon button used in queue rows / headers."""
    def __init__(self, parent, text, command, fg=TEXT_MUT, **kwargs):
        super().__init__(
            parent, text=text, command=command,
            bg=PANEL_BG, fg=fg, relief="flat", bd=0,
            activebackground=PANEL_BG2, activeforeground=fg,
            font=("Segoe UI Symbol", 10), cursor="hand2",
            padx=6, pady=2, takefocus=0,
        )
        self._fg = fg
        self.bind("<Enter>", lambda e: self.config(fg=ACCENT if self._fg != ERROR else ERROR))
        self.bind("<Leave>", lambda e: self.config(fg=self._fg))

    def set_fg(self, fg):
        self._fg = fg
        self.config(fg=fg)


class QueueRow(tk.Frame):
    def __init__(self, parent, task, callbacks, **kwargs):
        super().__init__(parent, bg=PANEL_BG, **kwargs)
        self.task = task
        self._cb = callbacks
        self._build()

    def _build(self) -> None:
        self.columnconfigure(1, weight=1)

        self._dot = tk.Label(self, text="●", fg=STATUS_COLOR[self.task.status],
                             bg=PANEL_BG, font=FONT_SM)
        self._dot.grid(row=0, column=0, padx=(8, 4), pady=(6, 0), sticky="w")

        title = self.task.title
        if len(title) > 70:
            title = title[:70] + "…"
        self._title = tk.Label(self, text=title, fg=TEXT_PRI, bg=PANEL_BG,
                               font=FONT_SM, anchor="w")
        self._title.grid(row=0, column=1, sticky="ew", pady=(6, 0))

        tk.Label(self, text=self.task.output_format.value.upper(),
                 fg=TEXT_MUT, bg=PANEL_BG, font=FONT_SM, width=5).grid(
            row=0, column=2, padx=6)

        # Action buttons (right aligned)
        self._actions = tk.Frame(self, bg=PANEL_BG)
        self._actions.grid(row=0, column=3, padx=(0, 8), pady=(6, 0))

        self._pause_btn = IconButton(self._actions, "⏸", self._cb["on_pause"])
        self._pause_btn.pack(side="left", padx=(0, 2))

        self._retry_btn = IconButton(self._actions, "↻", self._cb["on_retry"], fg=WARNING)
        self._retry_btn.pack(side="left", padx=(0, 2))

        self._del_btn = IconButton(self._actions, "🗑", self._cb["on_delete"], fg=TEXT_MUT)
        self._del_btn.pack(side="left")

        # Progress bar
        self._bar_var = tk.DoubleVar(value=0)
        self._bar = ttk.Progressbar(self, variable=self._bar_var, maximum=100,
                                    mode="determinate")
        self._bar.grid(row=1, column=0, columnspan=4, sticky="ew", padx=8, pady=(2, 2))

        # Info line: speed • ETA • filename / status
        self._info = tk.Label(self, text="", fg=TEXT_MUT, bg=PANEL_BG,
                              font=FONT_MONO, anchor="w")
        self._info.grid(row=2, column=0, columnspan=4, sticky="ew", padx=10, pady=(0, 6))

        sep = tk.Frame(self, bg=BORDER, height=1)
        sep.grid(row=3, column=0, columnspan=4, sticky="ew")

    def refresh(self) -> None:
        color = STATUS_COLOR.get(self.task.status, TEXT_MUT)
        self._dot.config(fg=color)

        # Progress
        if self.task.status in (DownloadStatus.COMPLETED, DownloadStatus.SKIPPED):
            self._bar_var.set(100)
        elif self.task.status == DownloadStatus.PAUSED:
            self._bar_var.set(self.task.progress)
        else:
            self._bar_var.set(self.task.progress)

        # Action buttons visibility
        st = self.task.status
        if st in (DownloadStatus.QUEUED, DownloadStatus.DOWNLOADING):
            self._pause_btn.pack(side="left", padx=(0, 2))
            self._pause_btn.config(text="⏸")
            self._pause_btn.set_fg(TEXT_MUT)
            self._retry_btn.pack_forget()
        elif st == DownloadStatus.PAUSED:
            self._pause_btn.pack(side="left", padx=(0, 2))
            self._pause_btn.config(text="▶")
            self._pause_btn.set_fg(SUCCESS)
            self._retry_btn.pack_forget()
        elif st == DownloadStatus.FAILED:
            self._pause_btn.pack_forget()
            self._retry_btn.pack(side="left", padx=(0, 2))
        else:  # COMPLETED / SKIPPED
            self._pause_btn.pack_forget()
            self._retry_btn.pack_forget()

        # Info line
        self._info.config(text=self._info_text())

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
            return "  •  ".join(parts)
        if st == DownloadStatus.COMPLETED:
            return self.task.final_filename or "Done"
        if st == DownloadStatus.FAILED:
            return f"Failed: {self.task.error_message or 'unknown error'}"
        if st == DownloadStatus.PAUSED:
            return "Paused"
        if st == DownloadStatus.SKIPPED:
            return self.task.error_message or "Skipped"
        return "Queued"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("YouTube Downloader")
        self.configure(bg=DARK_BG)
        self.minsize(960, 600)

        self.option_add("*selectBackground", SELECT_BG)
        self.option_add("*selectForeground", TEXT_PRI)

        self._set_icon()

        self._queue = DownloadQueue(max_workers=3)
        self._queue.on_task_update = self._on_task_update
        self._queue.on_log = self._log_append
        self._rows: dict[str, QueueRow] = {}
        self._tasks: list = []

        self._build_ui()
        self._apply_styles()

        self.update_idletasks()
        header_h = self._header.winfo_reqheight()
        content_h = self._left_inner.winfo_reqheight()
        needed_h = header_h + content_h + 28
        self._center_window(1180, needed_h)

        self.after(500, self._validate_cookie_state)
        self.after(600, self._init_runtime)

        # Periodically sync Start/Pause button states with the queue.
        self._sync_buttons()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self) -> None:
        try:
            self._queue.stop()
        except Exception:
            pass
        try:
            self.destroy()
        finally:
            os._exit(0)

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
                    "YouTubePlaylistDownloader.App.1"
                )
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

    # ── Styles ──────────────────────────────────────────────────────────────

    def _apply_styles(self) -> None:
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TCombobox",
                    fieldbackground=PANEL_BG, background=PANEL_BG,
                    foreground=TEXT_PRI, selectbackground=SELECT_BG,
                    selectforeground=TEXT_PRI, bordercolor=BORDER,
                    arrowcolor=TEXT_MUT)
        s.map("TCombobox", fieldbackground=[("readonly", PANEL_BG)])

        s.configure("Overall.Horizontal.TProgressbar",
                    troughcolor=BORDER, background=PROGRESS,
                    darkcolor=PROGRESS, lightcolor=PROGRESS, bordercolor=PANEL_BG)
        s.configure("Horizontal.TProgressbar",
                    troughcolor=BORDER, background=PROGRESS,
                    darkcolor=PROGRESS, lightcolor=PROGRESS, bordercolor=PANEL_BG)

    # ── UI Build ────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        hdr = tk.Frame(self, bg=PANEL_BG, pady=12)
        hdr.pack(fill="x")
        self._header = hdr
        tk.Label(hdr, text="▶  YouTube Downloader", fg=TEXT_PRI,
                 bg=PANEL_BG, font=("Segoe UI", 16, "bold"), padx=20).pack(side="left")
        tk.Label(hdr, text="Powered by yt-dlp", fg=TEXT_MUT,
                 bg=PANEL_BG, font=FONT_SM).pack(side="right", padx=20)

        body = tk.Frame(self, bg=DARK_BG)
        body.pack(fill="both", expand=True, padx=16, pady=10)

        left_outer = tk.Frame(body, bg=DARK_BG, width=320)
        left_outer.pack(side="left", fill="y", padx=(0, 12))
        left_outer.pack_propagate(False)
        left_outer.grid_columnconfigure(0, weight=1)
        left_outer.grid_rowconfigure(0, weight=1)

        left_canvas = tk.Canvas(left_outer, bg=DARK_BG, highlightthickness=0)
        left_sb = ttk.Scrollbar(left_outer, orient="vertical", command=left_canvas.yview)
        left = tk.Frame(left_canvas, bg=DARK_BG)
        self._left_inner = left
        left_window = left_canvas.create_window((0, 0), window=left, anchor="nw")
        left_canvas.configure(yscrollcommand=left_sb.set)
        left_canvas.grid(row=0, column=0, sticky="nsew")
        left_sb.grid(row=0, column=1, sticky="ns")

        def _sync_left_scroll(event=None):
            left_canvas.update_idletasks()
            content_h = left.winfo_reqheight()
            view_h = left_canvas.winfo_height()
            left_canvas.itemconfigure(left_window, width=left_canvas.winfo_width())
            if content_h > view_h + 1:
                left_canvas.configure(scrollregion=(0, 0, 0, content_h))
                left_sb.grid()
            else:
                left_canvas.yview_moveto(0)
                left_canvas.configure(scrollregion=(0, 0, 0, view_h))
                left_sb.grid_remove()

        left.bind("<Configure>", _sync_left_scroll)
        left_canvas.bind("<Configure>", _sync_left_scroll)
        left_canvas.bind_all("<Shift-MouseWheel>",
                             lambda e: left_canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        self._build_controls(left)

        right = tk.Frame(body, bg=PANEL_BG)
        right.pack(side="left", fill="both", expand=True)
        self._build_queue_panel(right)

    def _build_controls(self, parent: tk.Frame) -> None:
        def card(parent, title=None):
            c = tk.Frame(parent, bg=PANEL_BG, padx=12, pady=10)
            c.pack(fill="x", pady=(0, 10))
            if title:
                tk.Label(c, text=title, fg=TEXT_PRI, bg=PANEL_BG,
                         font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 6))
            return c

        def lbl(c, text):
            tk.Label(c, text=text, fg=TEXT_MUT, bg=PANEL_BG,
                     font=FONT_SM).pack(anchor="w", pady=(6, 2))

        # ── Source card ──
        src = card(parent, "Source")
        lbl(src, "YouTube URL or Playlist URL")
        url_wrap = tk.Frame(src, bg=PANEL_BG,
                            highlightbackground=BORDER, highlightthickness=1)
        url_wrap.pack(fill="x")
        self._url_var = tk.StringVar()
        tk.Entry(url_wrap, textvariable=self._url_var, bg=PANEL_BG,
                 fg=TEXT_PRI, insertbackground=TEXT_PRI,
                 font=FONT_LBL, relief="flat", bd=6).pack(fill="x")

        # ── Options card ──
        opt = card(parent, "Options")
        lbl(opt, "Output Format")
        fmt_row = tk.Frame(opt, bg=PANEL_BG)
        fmt_row.pack(fill="x")
        self._format_var = tk.StringVar(value="MP4")
        for fmt in ("MP4", "MP3", "AAC"):
            tk.Radiobutton(fmt_row, text=fmt, variable=self._format_var, value=fmt,
                           command=self._on_format_change,
                           bg=PANEL_BG, fg=TEXT_PRI, selectcolor="#333333",
                           activebackground=PANEL_BG, activeforeground=TEXT_PRI,
                           font=FONT_LBL).pack(side="left", padx=(0, 6))

        lbl(opt, "Video Quality")
        self._vq_var = tk.StringVar(value="RAW (Best)")
        self._vq_combo = ttk.Combobox(opt, textvariable=self._vq_var,
                                      values=list(VIDEO_QUALITY_LABELS.keys()),
                                      state="readonly", font=FONT_LBL)
        self._vq_combo.pack(fill="x")

        lbl(opt, "Audio Quality")
        self._aq_var = tk.StringVar(value="320 kbps")
        ttk.Combobox(opt, textvariable=self._aq_var,
                     values=list(AUDIO_QUALITY_LABELS.keys()),
                     state="readonly", font=FONT_LBL).pack(fill="x")

        lbl(opt, "Output Folder")
        dir_row = tk.Frame(opt, bg=PANEL_BG)
        dir_row.pack(fill="x")
        self._dir_var = tk.StringVar(value=os.path.abspath("downloads"))
        tk.Entry(dir_row, textvariable=self._dir_var, bg=PANEL_BG, fg=TEXT_PRI,
                 insertbackground=TEXT_PRI, font=FONT_SM, relief="flat", bd=4,
                 highlightthickness=1, highlightbackground=BORDER).pack(
            side="left", fill="x", expand=True)
        tk.Button(dir_row, text="…", command=self._browse_dir,
                  bg=BORDER, fg=TEXT_PRI, relief="flat", font=FONT_LBL,
                  padx=6, cursor="hand2").pack(side="left", padx=(4, 0))

        self._skip_var = tk.BooleanVar(value=True)
        tk.Checkbutton(opt, text="Skip already-downloaded videos",
                       variable=self._skip_var, bg=PANEL_BG, fg=TEXT_MUT,
                       selectcolor="#333333", activebackground=PANEL_BG,
                       activeforeground=TEXT_PRI, font=FONT_SM).pack(
            anchor="w", pady=(8, 0))

        # ── Throttling (avoid IP ban) ──
        lbl(opt, "Delay between downloads (sec)")
        self._delay_var = tk.IntVar(value=0)
        tk.Spinbox(opt, from_=0, to=120, textvariable=self._delay_var,
                   bg=PANEL_BG, fg=TEXT_PRI, font=FONT_SM, width=8,
                   relief="flat", bd=2, highlightthickness=0).pack(anchor="w")

        lbl(opt, "Pause after every N videos")
        self._batch_size_var = tk.IntVar(value=10)
        tk.Spinbox(opt, from_=0, to=200, textvariable=self._batch_size_var,
                   bg=PANEL_BG, fg=TEXT_PRI, font=FONT_SM, width=8,
                   relief="flat", bd=2, highlightthickness=0).pack(anchor="w")

        lbl(opt, "Batch pause duration (sec)")
        self._batch_pause_var = tk.IntVar(value=60)
        tk.Spinbox(opt, from_=0, to=3600, textvariable=self._batch_pause_var,
                   bg=PANEL_BG, fg=TEXT_PRI, font=FONT_SM, width=8,
                   relief="flat", bd=2, highlightthickness=0).pack(anchor="w")

        lbl(opt, "Concurrent Downloads")
        self._workers_var = tk.IntVar(value=3)
        tk.Scale(opt, from_=1, to=6, orient="horizontal",
                 variable=self._workers_var, bg=PANEL_BG, fg=TEXT_PRI,
                 troughcolor="#333333", highlightthickness=0,
                 sliderrelief="flat", activebackground=ACCENT).pack(fill="x")

        # ── Cookies card ──
        ck = card(parent, "Cookies (fixes bot detection)")
        self._cookies_var = tk.StringVar(value="None")
        ttk.Combobox(ck, textvariable=self._cookies_var,
                     values=["None", "chrome", "firefox", "edge", "brave", "opera", "chromium"],
                     state="readonly", font=FONT_LBL).pack(fill="x")
        lbl(ck, "Cookies.txt file (alternative)")
        cfile_row = tk.Frame(ck, bg=PANEL_BG)
        cfile_row.pack(fill="x")
        self._cookiefile_var = tk.StringVar(value="")
        tk.Entry(cfile_row, textvariable=self._cookiefile_var, bg=PANEL_BG,
                 fg=TEXT_PRI, insertbackground=TEXT_PRI, font=FONT_SM,
                 relief="flat", bd=4, highlightthickness=1,
                 highlightbackground=BORDER).pack(side="left", fill="x", expand=True)
        tk.Button(cfile_row, text="…", command=self._browse_cookies,
                  bg=BORDER, fg=TEXT_PRI, relief="flat", font=FONT_LBL,
                  padx=6, cursor="hand2").pack(side="left", padx=(4, 0))
        tk.Button(cfile_row, text="✕", command=lambda: self._cookiefile_var.set(""),
                  bg="#333333", fg=TEXT_PRI, relief="flat", font=FONT_SM,
                  padx=4, cursor="hand2").pack(side="left", padx=(2, 0))
        tk.Label(ck,
                 text="Netscape format. Use 'Get cookies.txt LOCALLY' extension.",
                 fg=TEXT_MUT, bg=PANEL_BG, font=("Segoe UI", 7),
                 wraplength=280, justify="left").pack(anchor="w")

        # ── Action buttons ──
        actions = card(parent, "Actions")
        self._add_btn = RoundedButton(actions, "＋  Add to Queue", self._add_to_queue,
                                      bg="#525252", hover_bg="#636363")
        self._add_btn.pack(fill="x", pady=(0, 6))
        self._start_btn = RoundedButton(actions, "▶  Start", self._start_queue,
                                        bg=SUCCESS, hover_bg="#1ca44e")
        self._start_btn.pack(fill="x", pady=(0, 6))
        self._pause_btn = RoundedButton(actions, "⏸  Pause", self._pause_queue,
                                        bg="#787878", hover_bg="#8a8a8a")
        self._pause_btn.pack(fill="x", pady=(0, 6))
        self._retry_btn = RoundedButton(actions, "↻  Retry Failed", self._retry_failed,
                                        bg="#525252", hover_bg="#636363")
        self._retry_btn.pack(fill="x", pady=(0, 6))
        self._clear_btn = RoundedButton(actions, "🗑  Clear Queue", self._clear_queue,
                                        bg=SECONDARY, hover_bg=ACCENT_H)
        self._clear_btn.pack(fill="x")

    def _build_queue_panel(self, parent: tk.Frame) -> None:
        hdr = tk.Frame(parent, bg=PANEL_BG)
        hdr.pack(fill="x", padx=12, pady=(10, 4))
        tk.Label(hdr, text="Download Queue", fg=TEXT_PRI,
                 bg=PANEL_BG, font=FONT_HDR).pack(side="left")
        self._count_lbl = tk.Label(hdr, text="0 items", fg=TEXT_MUT,
                                   bg=PANEL_BG, font=FONT_SM)
        self._count_lbl.pack(side="right")

        prog_frame = tk.Frame(parent, bg=PANEL_BG)
        prog_frame.pack(fill="x", padx=12, pady=(0, 4))
        self._overall_var = tk.DoubleVar(value=0)
        self._overall_bar = ttk.Progressbar(
            prog_frame, variable=self._overall_var, maximum=100,
            mode="determinate", style="Overall.Horizontal.TProgressbar")
        self._overall_bar.pack(fill="x")
        self._overall_lbl = tk.Label(prog_frame, text="", fg=TEXT_MUT,
                                     bg=PANEL_BG, font=FONT_SM, anchor="w")
        self._overall_lbl.pack(anchor="w")

        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=12)

        container = tk.Frame(parent, bg=PANEL_BG)
        container.pack(fill="both", expand=True, padx=4, pady=(4, 0))

        self._canvas = tk.Canvas(container, bg=PANEL_BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical",
                                  command=self._canvas.yview)
        self._scroll_frame = tk.Frame(self._canvas, bg=PANEL_BG)
        self._scroll_frame.bind(
            "<Configure>",
            lambda e: self._canvas.configure(
                scrollregion=self._canvas.bbox("all")))
        self._scroll_window = self._canvas.create_window(
            (0, 0), window=self._scroll_frame, anchor="nw")
        self._canvas.bind(
            "<Configure>",
            lambda e: self._canvas.itemconfigure(self._scroll_window, width=e.width))
        self._canvas.configure(yscrollcommand=scrollbar.set)
        self._canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self._canvas.bind_all("<MouseWheel>",
                              lambda e: self._canvas.yview_scroll(
                                  int(-1 * (e.delta / 120)), "units"))

        tk.Frame(parent, bg=BORDER, height=1).pack(fill="x", padx=12, pady=(4, 0))
        log_hdr = tk.Frame(parent, bg=PANEL_BG)
        log_hdr.pack(fill="x", padx=12, pady=(4, 2))
        tk.Label(log_hdr, text="Log", fg=TEXT_MUT,
                 bg=PANEL_BG, font=FONT_SM).pack(side="left")
        tk.Button(log_hdr, text="Clear Log", command=self._clear_log,
                  bg=BORDER, fg=TEXT_MUT, relief="flat", font=FONT_SM,
                  cursor="hand2", padx=4).pack(side="right")
        tk.Button(log_hdr, text="Clear Done", command=self._clear_done,
                  bg=BORDER, fg=TEXT_PRI, relief="flat", font=FONT_SM,
                  cursor="hand2", padx=4).pack(side="right", padx=(0, 6))

        log_frame = tk.Frame(parent, bg=LOG_BG)
        log_frame.pack(fill="x", padx=4, pady=(0, 4))
        self._log = tk.Text(log_frame, height=5, bg=LOG_BG, fg=TEXT_MUT,
                            font=FONT_MONO, relief="flat", state="disabled",
                            wrap="word", bd=4, insertbackground=TEXT_MUT)
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical",
                                   command=self._log.yview)
        self._log.configure(yscrollcommand=log_scroll.set)
        self._log.pack(side="left", fill="x", expand=True)
        log_scroll.pack(side="right", fill="y")

        self._status_var = tk.StringVar(value="Ready")
        tk.Label(parent, textvariable=self._status_var, fg=TEXT_MUT,
                 bg=PANEL_BG, font=FONT_SM, anchor="w",
                 pady=5).pack(fill="x", padx=12)

    # ── Format toggle ────────────────────────────────────────────────────────

    def _on_format_change(self) -> None:
        state = "readonly" if self._format_var.get() == "MP4" else "disabled"
        self._vq_combo.config(state=state)

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

    # ── Queue building ────────────────────────────────────────────────────────

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

        self._set_status("Fetching YouTube URL info — please wait…")
        self._log_append(f"Fetching: {url}")
        self._add_btn.set_enabled(False)

        def fetch() -> None:
            try:
                def _log(msg, self=self):
                    self.after(0, lambda m=msg: self._log_append(m))

                browser = self._cookies_var.get()
                cookies_from_browser = browser if browser != "None" else None
                cookiefile = self._valid_cookiefile() or None

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
                self.after(0, lambda: self._enqueue_tasks(tasks))
            except Exception as exc:
                msg = _strip_ansi(str(exc))
                self.after(0, lambda m=msg: self._set_status(f"Error: {m}"))
                self.after(0, lambda m=msg: self._log_append(f"ERROR: {m}"))
                self.after(0, lambda m=msg: messagebox.showerror("Fetch Error", m))
            finally:
                self.after(0, lambda: self._add_btn.set_enabled(True))

        threading.Thread(target=fetch, daemon=True).start()

    def _enqueue_tasks(self, tasks: list) -> None:
        if not tasks:
            self._set_status("No videos found at that URL.")
            self._log_append("No downloadable videos found.")
            messagebox.showwarning("No Items",
                                   "No downloadable videos were found at that URL.")
            return

        added = []
        for task in tasks:
            if task.video_id in self._rows:
                self._log_append(f"Skipped duplicate: {task.title}")
                continue
            task.inter_download_delay = self._delay_var.get()
            self._tasks.append(task)
            self._queue.ensure_pending(task)
            row = QueueRow(self._scroll_frame, task, callbacks={
                "on_pause": self._pause_task,
                "on_resume": self._resume_task,
                "on_retry": self._retry_task,
                "on_delete": self._delete_task,
            })
            row.pack(fill="x")
            row.refresh()
            self._rows[task.video_id] = row
            added.append(task)

        self._canvas.update_idletasks()
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))
        self._count_lbl.config(text=f"{len(self._tasks)} items")
        self._log_append(f"Added {len(added)} item(s) to queue.")
        self._set_status(f"Added {len(added)} item(s). Click Start to begin.")
        self._update_overall()

    # ── Queue controls ────────────────────────────────────────────────────────

    def _apply_throttle(self) -> None:
        self._queue.max_workers = self._workers_var.get()
        self._queue.batch_size = self._batch_size_var.get()
        self._queue.batch_pause = self._batch_pause_var.get()

    def _start_queue(self) -> None:
        if not self._tasks:
            messagebox.showinfo("Queue Empty",
                                "Add items to the queue first, then click Start.")
            return
        self._apply_throttle()
        self._queue.start(skip_downloaded=self._skip_var.get())
        self._log_append(f"Starting downloads ({self._workers_var.get()} concurrent)…")
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
        for task in failed:
            self._reset_task(task)
            self._queue.ensure_pending(task)
        self._apply_throttle()
        self._queue.start(skip_downloaded=self._skip_var.get())
        self._log_append(f"Retrying {len(failed)} failed item(s)…")
        self._set_status(f"Retrying {len(failed)} item(s)…")

    def _clear_queue(self) -> None:
        self._queue.stop()
        self._queue.clear()
        self._tasks.clear()
        self._rows.clear()
        for w in self._scroll_frame.winfo_children():
            w.destroy()
        self._count_lbl.config(text="0 items")
        self._overall_var.set(0)
        self._overall_lbl.config(text="")
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
        self._count_lbl.config(text=f"{len(self._tasks)} items")
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
        self._queue.ensure_pending(task)
        self._apply_throttle()
        self._queue.start(skip_downloaded=self._skip_var.get())

    def _retry_task(self, task) -> None:
        self._reset_task(task)
        self._queue.ensure_pending(task)
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
        row = self._rows.pop(task.video_id, None)
        if row:
            row.destroy()
        self._tasks = [t for t in self._tasks if t.video_id != task.video_id]
        self._count_lbl.config(text=f"{len(self._tasks)} items")
        self._update_overall()
        self._set_status(f"Removed: {task.title[:50]}")

    def _clear_log(self) -> None:
        self._log.config(state="normal")
        self._log.delete("1.0", "end")
        self._log.config(state="disabled")

    # ── Update helpers ────────────────────────────────────────────────────────

    def _on_task_update(self, task) -> None:
        self.after(0, lambda t=task: self._refresh_row(t))

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
            self._log_append(f"✗ {task.title}: {task.error_message or 'unknown error'}")
        elif task.status == DownloadStatus.PAUSED:
            self._log_append(f"⏸ Paused: {task.title}")

        self._update_overall(completed, failed, skipped, paused, total)
        self._set_status(
            f"Completed: {completed}  Failed: {failed}  "
            f"Skipped: {skipped}  Paused: {paused}  Total: {total}")

    def _update_overall(self, completed=None, failed=None, skipped=None,
                        paused=None, total=None) -> None:
        if total is None:
            total = len(self._tasks)
        if total == 0:
            self._overall_var.set(0)
            self._overall_lbl.config(text="")
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
        self._overall_var.set(pct)
        self._overall_lbl.config(
            text=f"{done}/{total} done  •  {completed} completed  •  "
                 f"{failed} failed  •  {skipped} skipped  •  {paused} paused  •  {pct:.0f}%")

    def _sync_buttons(self) -> None:
        running = self._queue.is_running
        self._start_btn.set_enabled(not running)
        self._pause_btn.set_enabled(running)
        self.after(400, self._sync_buttons)

    def _log_append(self, msg: str) -> None:
        self._log.config(state="normal")
        self._log.insert("end", msg + "\n")
        self._log.see("end")
        self._log.config(state="disabled")

    def _set_status(self, msg: str) -> None:
        self._status_var.set(msg)


if __name__ == "__main__":
    app = App()
    app.mainloop()
