import threading
import time
from typing import Callable, Optional
from concurrent.futures import ThreadPoolExecutor
from models.task import VideoTask, DownloadStatus
from downloader.download import download_task, _PauseRequested


class DownloadQueue:
    def __init__(self, max_workers: int = 3):
        self._pending: list[VideoTask] = []
        self._max_workers = max_workers
        self._executor: Optional[ThreadPoolExecutor] = None
        self._running = False
        self._lock = threading.Lock()
        self._in_flight: list[VideoTask] = []
        self.on_task_update: Optional[Callable[[VideoTask], None]] = None

    @property
    def max_workers(self) -> int:
        return self._max_workers

    @max_workers.setter
    def max_workers(self, value: int) -> None:
        self._max_workers = value

    def add(self, task: VideoTask) -> None:
        with self._lock:
            self._pending.append(task)

    def add_many(self, tasks: list[VideoTask]) -> None:
        with self._lock:
            self._pending.extend(tasks)

    def ensure_pending(self, task: VideoTask) -> None:
        """Add the task only if it is not already tracked (identity check)."""
        with self._lock:
            if not any(t is task for t in self._pending):
                self._pending.append(task)

    def start(self, skip_downloaded: bool = True) -> None:
        with self._lock:
            if self._running:
                return
            # Resume any paused tasks so the dispatcher can pick them up again.
            for t in self._pending:
                if t.status == DownloadStatus.PAUSED and not t.cancelled:
                    t.status = DownloadStatus.QUEUED
                    t.pause_requested = False
            self._running = True

        if self._executor is None or getattr(self._executor, "_shutdown", False):
            self._executor = ThreadPoolExecutor(max_workers=self._max_workers)

        threading.Thread(target=self._dispatch, args=(skip_downloaded,),
                         daemon=True).start()

    def pause_all(self) -> None:
        """Soft stop: halt the queue but keep tasks so they can be resumed."""
        with self._lock:
            self._running = False
            for t in self._pending:
                if t.status == DownloadStatus.QUEUED:
                    t.status = DownloadStatus.PAUSED
        for t in list(self._in_flight):
            t.pause_requested = True

    def stop(self) -> None:
        """Hard stop: abort everything currently active and clear the queue."""
        with self._lock:
            self._running = False
            self._pending.clear()
        for t in list(self._in_flight):
            t.pause_requested = True
            t.cancelled = True
        if self._executor:
            self._executor.shutdown(wait=False)

    def clear(self) -> None:
        with self._lock:
            self._pending.clear()

    def _dispatch(self, skip_downloaded: bool) -> None:
        while True:
            with self._lock:
                if not self._running:
                    break
                task = None
                for i, t in enumerate(self._pending):
                    if t.status == DownloadStatus.QUEUED and not t.cancelled:
                        task = self._pending.pop(i)
                        break

            if task is None:
                # Nothing ready to start; exit only when nothing is in flight.
                if not self._in_flight:
                    break
                time.sleep(0.2)
                continue

            self._in_flight.append(task)
            self._executor.submit(self._run_task, task, skip_downloaded)

        with self._lock:
            self._running = False

    def _run_task(self, task: VideoTask, skip_downloaded: bool) -> None:
        if task.cancelled:
            with self._lock:
                self._in_flight.discard(task)
            return

        def hook(d: dict) -> None:
            if task.pause_requested:
                raise _PauseRequested()
            if self.on_task_update:
                self.on_task_update(task)

        try:
            download_task(task, progress_hook=hook, skip_downloaded=skip_downloaded)
        finally:
            with self._lock:
                if task in self._in_flight:
                    self._in_flight.remove(task)
                # Keep paused tasks tracked so they can be resumed globally.
                if task.status == DownloadStatus.PAUSED and \
                        not any(t is task for t in self._pending):
                    self._pending.append(task)

        if self.on_task_update:
            self.on_task_update(task)

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def active_count(self) -> int:
        return len(self._in_flight)
