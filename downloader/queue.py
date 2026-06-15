import threading
from queue import Queue, Empty
from typing import Callable, Optional
from concurrent.futures import ThreadPoolExecutor
from models.task import VideoTask, DownloadStatus
from downloader.download import download_task


class DownloadQueue:
    def __init__(self, max_workers: int = 3):
        self._queue: Queue[VideoTask] = Queue()
        self._max_workers = max_workers
        self._executor: Optional[ThreadPoolExecutor] = None
        self._running = False
        self._lock = threading.Lock()
        self.on_task_update: Optional[Callable[[VideoTask], None]] = None

    def add(self, task: VideoTask) -> None:
        self._queue.put(task)

    def add_many(self, tasks: list[VideoTask]) -> None:
        for task in tasks:
            self._queue.put(task)

    def start(self, skip_downloaded: bool = True) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True

        self._executor = ThreadPoolExecutor(max_workers=self._max_workers)
        threading.Thread(target=self._dispatch, args=(skip_downloaded,), daemon=True).start()

    def stop(self) -> None:
        self._running = False
        if self._executor:
            self._executor.shutdown(wait=False)

    def _dispatch(self, skip_downloaded: bool) -> None:
        futures = []
        while self._running:
            try:
                task = self._queue.get(timeout=0.5)
            except Empty:
                if not futures:
                    break
                futures = [f for f in futures if not f.done()]
                continue

            future = self._executor.submit(self._run_task, task, skip_downloaded)
            futures.append(future)

        self._running = False

    def _run_task(self, task: VideoTask, skip_downloaded: bool) -> None:
        # Skip items the user removed before the worker reached them.
        if task.cancelled:
            return

        def hook(d: dict) -> None:
            if d.get("status") == "downloading":
                # Prefer the pre-computed percent string
                pct_str = d.get("_percent_str", "").strip().rstrip("%")
                try:
                    task.progress = float(pct_str)
                except (ValueError, AttributeError):
                    # Fall back to raw byte counts (works for DASH/fragmented streams)
                    downloaded = d.get("downloaded_bytes") or 0
                    total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                    if total > 0:
                        task.progress = min((downloaded / total) * 100, 99.9)
                if self.on_task_update:
                    self.on_task_update(task)

        download_task(task, progress_hook=hook, skip_downloaded=skip_downloaded)

        if self.on_task_update:
            self.on_task_update(task)

    @property
    def is_running(self) -> bool:
        return self._running

    def clear(self) -> None:
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except Empty:
                break
