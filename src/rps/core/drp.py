"""Telling a Resolve project apart from everything else called ``.drp``.

## Why this is needed

The first diagnostic report from a real machine found 125 files with a ``.drp``
extension. Only about 70 of them were Resolve projects. The rest:

* VideoProc Converter AI neural-network models — magic ``DIGI``, up to 100 MB
  each, twelve of them in one folder;
* Reason drum kits, which have used ``.drp`` since long before Resolve existed.

Scanning those wastes minutes on hundreds of megabytes and puts nonsense in the
results. So a file is classified before it is searched.

## What is actually known about the format

Measured on real files (Resolve 21.0, Windows), not assumed:

* the container is a **ZIP archive**;
* it contains ``project.xml`` at the root;
* the media pool is a tree of ``MediaPool/**/MpFolder.xml``, including a
  ``000_Timelines`` folder;
* each timeline appears to be a ``SeqContainer/<uuid>.xml`` member.

That is the whole basis. The XML schema inside those members is still unread, so
nothing here parses them — this module only recognises the shape.

## The classification is deliberately three-way

Positively foreign files are skipped. Positively Resolve files are scanned.
Anything unrecognised is **also scanned**, because an older Resolve version may
have written a container nobody here has seen. Skipping the unknown would turn
one unfamiliar file into a silent missing result, which is the failure this
project refuses to produce.
"""

from __future__ import annotations

import zipfile
from enum import Enum
from pathlib import Path

__all__ = [
    "DrpKind",
    "RESOLVE_MEMBER_HINTS",
    "classify",
    "decode_member_name",
    "list_members",
    "project_display_name",
]

RESOLVE_MEMBER_HINTS: tuple[str, ...] = (
    "project.xml",
    "mediapool/",
    "seqcontainer/",
)
"""Member names that mark a ZIP as a Resolve project export."""

_FOREIGN_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"DIGI", "модель VideoProc Converter AI"),
    (b"SQLite format 3\x00", "база SQLite, не проект Resolve"),
)

_ARCHIVE_SUFFIX = ".dra"
_ARCHIVE_MEMBER = "project.drp"


class DrpKind(str, Enum):
    RESOLVE = "resolve"
    """A Resolve project export."""

    FOREIGN = "foreign"
    """Positively identified as something else that shares the extension."""

    UNKNOWN = "unknown"
    """Not recognised either way. Searched anyway."""

    @property
    def label(self) -> str:
        return {
            "resolve": "проект Resolve",
            "foreign": "не проект Resolve",
            "unknown": "неопознанный формат",
        }[self.value]


def classify(path: Path) -> tuple[DrpKind, str]:
    """Return what this file is and why we think so.

    Never raises: an unreadable file is ``UNKNOWN`` with the reason attached,
    so the caller still scans it and still reports the read error.
    """

    try:
        with path.open("rb") as handle:
            head = handle.read(64)
    except OSError as exc:
        return DrpKind.UNKNOWN, f"не удалось прочитать заголовок: {exc.strerror or exc}"

    for magic, description in _FOREIGN_MAGIC:
        if head.startswith(magic):
            return DrpKind.FOREIGN, description

    if not head.startswith(b"PK"):
        return DrpKind.UNKNOWN, "не ZIP-контейнер"

    try:
        with zipfile.ZipFile(path) as archive:
            names = [name.lower() for name in archive.namelist()[:400]]
    except (zipfile.BadZipFile, OSError) as exc:
        return DrpKind.UNKNOWN, f"ZIP не открылся: {exc}"

    matched = [hint for hint in RESOLVE_MEMBER_HINTS if any(hint in name for name in names)]
    if matched:
        return DrpKind.RESOLVE, "внутри: " + ", ".join(matched)
    return DrpKind.FOREIGN, "ZIP без файлов проекта Resolve"


def list_members(path: Path, limit: int = 200) -> list[tuple[str, int, int]]:
    """``(name, compressed_size, uncompressed_size)`` for each ZIP member."""

    try:
        with zipfile.ZipFile(path) as archive:
            return [
                (info.filename, info.compress_size, info.file_size)
                for info in archive.infolist()[:limit]
                if not info.is_dir()
            ]
    except (zipfile.BadZipFile, OSError):
        return []


def decode_member_name(name: str) -> str:
    """Recover a ZIP member name that Resolve wrote as UTF-8 without saying so.

    A ZIP entry only counts as UTF-8 when bit 11 of its flags is set; otherwise
    the spec says CP437 and ``zipfile`` obeys. Resolve writes UTF-8 bytes and
    leaves the flag clear, so a folder called ``2025.03.07 к 8 марта`` arrives
    as ``2025.03.07 ╨║ 8 ╨╝╨░╤Ç╤é╨░``. Re-encoding through CP437 undoes it.

    Only applied when the round-trip succeeds — a genuinely CP437 name is left
    exactly as it was.
    """

    try:
        return name.encode("cp437").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return name


def project_display_name(path: Path) -> str:
    """The name worth putting in a results row.

    A Resolve archive is a ``<project name>.dra`` folder holding a file called
    ``project.drp``. Showing "project.drp" for forty different archives would be
    useless, so the folder name wins in that case.
    """

    if path.name.lower() == _ARCHIVE_MEMBER and path.parent.suffix.lower() == _ARCHIVE_SUFFIX:
        return path.parent.stem
    return path.stem
