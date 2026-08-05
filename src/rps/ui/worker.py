"""Qt bridge around :func:`rps.core.scanner.scan`.

The scan itself runs in a plain thread pool created by the core. This class owns
one QThread whose only job is to call into that core and turn its callbacks into
signals, so the GUI thread never touches a file.

Progress signals are throttled. A folder of 5 000 projects would otherwise post
5 000 cross-thread events into the GUI queue faster than it can repaint, and the
window would appear frozen for exactly the reason the progress bar exists to
prevent.
"""

from __future__ import annotations

import threading
import time

from PySide6.QtCore import QThread, Signal

from rps.core.models import FileResult, ScanSummary
from rps.core.scanner import CANCELLED_ERROR, ScanOptions, scan

__all__ = ["ScanWorker"]

_PROGRESS_INTERVAL_S = 0.05


class ScanWorker(QThread):
    discovered = Signal(int)
    progressed = Signal(int, int)
    matched = Signal(object)
    """Emits a :class:`FileResult` that either has hits or has an error."""

    finishedScan = Signal(object)
    """Emits a :class:`ScanSummary`."""

    failed = Signal(str)

    def __init__(self, options: ScanOptions, parent=None) -> None:
        super().__init__(parent)
        self._options = options
        self._cancel = threading.Event()
        self._last_progress = 0.0
        self._lock = threading.Lock()

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def run(self) -> None:
        try:
            summary = scan(
                self._options,
                on_result=self._on_result,
                on_progress=self._on_progress,
                on_discovered=self.discovered.emit,
                cancel=self._cancel,
            )
        except Exception as exc:  # noqa: BLE001 — a crash here must reach the UI
            self.failed.emit(str(exc))
            return
        self.progressed.emit(summary.processed_files, summary.total_files)
        self.finishedScan.emit(summary)

    def _on_result(self, result: FileResult) -> None:
        # Misses are the common case and carry no information worth a row.
        # A file abandoned by Stop is neither a hit nor a fault of the file.
        if result.error == CANCELLED_ERROR:
            return
        if result.matched or result.error:
            self.matched.emit(result)

    def _on_progress(self, done: int, total: int) -> None:
        now = time.monotonic()
        with self._lock:
            if done < total and now - self._last_progress < _PROGRESS_INTERVAL_S:
                return
            self._last_progress = now
        self.progressed.emit(done, total)
