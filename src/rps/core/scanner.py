"""Walking a folder of ``.drp`` files and searching each one.

Threads, not processes. The work is dominated by reading files and by zlib
decompression, and zlib releases the GIL — so threads give real parallelism here
while keeping cancellation instant and start-up free, which a process pool does
not on Windows.

Cancellation is cooperative and checked between chunks, so a single 4 GB project
file cannot hold the Stop button hostage.
"""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Iterator, Sequence

from rps.core.formats import detect_container, iter_streams
from rps.core.matcher import Query, search_stream
from rps.core.models import ContainerKind, FileResult, Hit, ScanSummary

__all__ = ["ScanOptions", "discover", "scan_file", "scan"]

DEFAULT_EXTENSIONS: tuple[str, ...] = (".drp",)

CANCELLED_ERROR = "отменено"
"""Marker put in :attr:`FileResult.error` for a file abandoned mid-read. It is
an error rather than a miss on purpose — the file was not cleared, it was simply
never finished — but the UI does not list it as a problem."""

_MAX_INFLIGHT_PER_WORKER = 4
"""Bound on queued futures, so a folder with 100 000 files does not materialise
100 000 pending tasks before the first result appears."""


@dataclass
class ScanOptions:
    """Everything one scan run needs."""

    root: Path
    query: Query
    recursive: bool = True
    extensions: Sequence[str] = DEFAULT_EXTENSIONS
    max_hits_per_file: int = 20
    """Stop collecting after this many hits in one file. A project that
    references the same clip 400 times does not need 400 rows to answer the
    question "is it in here"."""

    workers: int = 0
    """0 selects a default from the CPU count."""

    follow_symlinks: bool = False

    def worker_count(self) -> int:
        if self.workers > 0:
            return self.workers
        return max(2, min(16, (os.cpu_count() or 4)))

    def normalised_extensions(self) -> tuple[str, ...]:
        out = []
        for raw in self.extensions:
            ext = raw.strip().lower()
            if not ext:
                continue
            if not ext.startswith("."):
                ext = "." + ext
            out.append(ext)
        return tuple(out) or DEFAULT_EXTENSIONS


class _Cancelled(Exception):
    """Raised inside a worker when the user pressed Stop."""


class _HitLimit(Exception):
    """Raised when a file has produced as many hits as the caller asked for."""


def discover(
    root: Path,
    extensions: Sequence[str] = DEFAULT_EXTENSIONS,
    recursive: bool = True,
    follow_symlinks: bool = False,
    cancel: threading.Event | None = None,
) -> list[Path]:
    """List candidate files under *root*, sorted for a stable UI order.

    Unreadable subdirectories are skipped rather than aborting the walk: one
    permission-denied folder on a shared drive should not cost the user the
    whole scan.
    """

    wanted = tuple(e.lower() for e in extensions)
    found: list[Path] = []

    if not recursive:
        try:
            entries = list(os.scandir(root))
        except OSError:
            return []
        for entry in entries:
            if cancel is not None and cancel.is_set():
                return sorted(found)
            try:
                if entry.is_file(follow_symlinks=follow_symlinks) and entry.name.lower().endswith(wanted):
                    found.append(Path(entry.path))
            except OSError:
                continue
        return sorted(found)

    for dirpath, dirnames, filenames in os.walk(root, followlinks=follow_symlinks):
        if cancel is not None and cancel.is_set():
            break
        dirnames.sort()
        for name in sorted(filenames):
            if name.lower().endswith(wanted):
                found.append(Path(dirpath) / name)
    return found


def _guarded(chunks: Iterable[bytes], cancel: threading.Event | None) -> Iterator[bytes]:
    for chunk in chunks:
        if cancel is not None and cancel.is_set():
            raise _Cancelled()
        yield chunk


def scan_file(
    path: Path,
    query: Query,
    max_hits: int = 20,
    cancel: threading.Event | None = None,
) -> FileResult:
    """Search a single file. Never raises for an unreadable file — records it."""

    started = time.perf_counter()
    result = FileResult(path=path, size=0)
    try:
        result.size = path.stat().st_size
    except OSError:
        result.size = 0

    try:
        with path.open("rb") as handle:
            result.container = detect_container(handle.read(512))
    except OSError as exc:
        result.error = f"не удалось открыть: {exc.strerror or exc}"
        result.duration_s = time.perf_counter() - started
        return result

    if result.container is ContainerKind.EMPTY:
        result.duration_s = time.perf_counter() - started
        return result

    hits: list[Hit] = []
    try:
        for stream_name, chunks in iter_streams(path):
            for hit in search_stream(_guarded(chunks, cancel), query, stream_name):
                hits.append(hit)
                if len(hits) >= max_hits:
                    raise _HitLimit
    except _HitLimit:
        pass
    except _Cancelled:
        result.error = CANCELLED_ERROR
    except (OSError, ValueError, MemoryError) as exc:
        result.error = f"ошибка чтения: {exc}"

    result.hits = hits
    result.duration_s = time.perf_counter() - started
    return result


def scan(
    options: ScanOptions,
    on_result: Callable[[FileResult], None] | None = None,
    on_progress: Callable[[int, int], None] | None = None,
    on_discovered: Callable[[int], None] | None = None,
    cancel: threading.Event | None = None,
) -> ScanSummary:
    """Run a full scan.

    Callbacks fire from worker threads. The Qt layer marshals them onto the GUI
    thread via signals; a CLI caller can use them directly.
    """

    started = time.perf_counter()
    summary = ScanSummary()

    files = discover(
        options.root,
        options.normalised_extensions(),
        options.recursive,
        options.follow_symlinks,
        cancel,
    )
    summary.total_files = len(files)
    if on_discovered is not None:
        on_discovered(len(files))
    if not files or (cancel is not None and cancel.is_set()):
        summary.cancelled = bool(cancel is not None and cancel.is_set())
        summary.duration_s = time.perf_counter() - started
        return summary

    workers = options.worker_count()
    max_inflight = workers * _MAX_INFLIGHT_PER_WORKER
    pending = iter(files)
    done_count = 0

    def _consume(result: FileResult) -> None:
        nonlocal done_count
        done_count += 1
        summary.processed_files += 1
        summary.bytes_read += result.size
        if result.error == CANCELLED_ERROR:
            summary.abandoned_files += 1
        else:
            summary.scanned_files += 1
            if result.error:
                summary.failed_files += 1
            elif result.matched:
                summary.matched_files += 1
        if on_result is not None:
            on_result(result)
        if on_progress is not None:
            on_progress(done_count, summary.total_files)

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="rps-scan") as pool:
        futures = set()
        for path in pending:
            futures.add(
                pool.submit(scan_file, path, options.query, options.max_hits_per_file, cancel)
            )
            if len(futures) < max_inflight:
                continue
            finished, futures = wait(futures, return_when=FIRST_COMPLETED)
            for future in finished:
                _consume(future.result())
            if cancel is not None and cancel.is_set():
                break

        if cancel is not None and cancel.is_set():
            for future in futures:
                future.cancel()

        for future in futures:
            if future.cancelled():
                continue
            try:
                _consume(future.result())
            except Exception as exc:  # a bug in a worker must not lose the run
                summary.failed_files += 1
                done_count += 1
                if on_result is not None:
                    on_result(FileResult(path=Path("?"), size=0, error=str(exc)))

    summary.cancelled = bool(cancel is not None and cancel.is_set())
    summary.duration_s = time.perf_counter() - started
    return summary
