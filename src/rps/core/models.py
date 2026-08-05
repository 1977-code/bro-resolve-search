"""Pure domain models. No Qt, no filesystem side effects.

Every field that depends on something we could not determine is typed ``| None``,
where ``None`` means *"could not be determined"* — never *"absent"* and never a
fabricated default. The .drp container format is not publicly documented, so this
distinction is not academic: a file we failed to read must never be reported as a
file that contained no match.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

__all__ = [
    "ContainerKind",
    "Hit",
    "FileResult",
    "ScanSummary",
]


class ContainerKind(str, Enum):
    """What the first bytes of a file say it is.

    Detected from magic numbers, not from the extension. A ``.drp`` is whatever
    Blackmagic decided it is in the version that wrote it, and that has changed
    across releases — so the scanner asks the bytes rather than assuming.
    """

    ZIP = "zip"
    GZIP = "gzip"
    ZLIB = "zlib"
    SQLITE = "sqlite"
    XML = "xml"
    JSON = "json"
    TEXT = "text"
    BINARY = "binary"
    EMPTY = "empty"

    @property
    def label(self) -> str:
        return {
            "zip": "ZIP-контейнер",
            "gzip": "gzip",
            "zlib": "zlib",
            "sqlite": "SQLite",
            "xml": "XML",
            "json": "JSON",
            "text": "текст",
            "binary": "двоичный",
            "empty": "пустой файл",
        }[self.value]


@dataclass(frozen=True)
class Hit:
    """One matched string inside one file.

    ``offset`` is a *best-effort* byte offset inside ``stream``. For text found in
    a compressed member it is an offset into the decompressed data, and for
    UTF-16 text it is derived from a character index, so it is useful for
    orientation and not for seeking. It is labelled as approximate everywhere it
    is shown.
    """

    stream: str
    """Container member the text came from. ``""`` for the raw file itself."""

    offset: int
    text: str
    encoding: str


@dataclass
class FileResult:
    """Outcome of scanning a single file."""

    path: Path
    size: int
    container: ContainerKind | None = None
    hits: list[Hit] = field(default_factory=list)
    error: str | None = None
    """Set when the file could not be read or decoded. Distinct from "no hits"."""

    duration_s: float = 0.0

    @property
    def matched(self) -> bool:
        return bool(self.hits)

    @property
    def readable(self) -> bool:
        return self.error is None


@dataclass
class ScanSummary:
    """Totals for one scan run."""

    total_files: int = 0

    processed_files: int = 0
    """Files the pool finished handling, whatever the outcome. Drives progress."""

    scanned_files: int = 0
    """Files that produced an actual verdict — match, miss, or read error.
    Excludes files abandoned by Stop, so "просмотрено N" never overstates what
    the user was actually told about."""

    matched_files: int = 0
    failed_files: int = 0
    """Files that could not be read. A real problem worth showing."""

    abandoned_files: int = 0
    """Files dropped part-way through by Stop. Not a fault of the file, and
    reporting them as unreadable would be a lie the user acts on."""

    bytes_read: int = 0
    duration_s: float = 0.0
    cancelled: bool = False

    @property
    def skipped_files(self) -> int:
        """Files that were never opened because the scan was cancelled."""

        return max(0, self.total_files - self.processed_files)

    @property
    def unfinished_files(self) -> int:
        """Everything the scan did not get a verdict on."""

        return self.skipped_files + self.abandoned_files
