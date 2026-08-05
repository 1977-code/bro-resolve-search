"""Container detection and byte-stream extraction for ``.drp`` files.

## Why this module exists

The DaVinci Resolve project export format is not publicly documented, and it has
not been stable across Resolve versions. A search tool that hardcodes "a .drp is
XML" or "a .drp is a zip" is one Resolve update away from silently returning
zero results — which is the worst possible failure for a search tool, because
"not found" and "could not read" look identical to the user.

So this module never assumes. It reads the leading bytes, matches them against
magic numbers, and exposes whatever it finds as a sequence of *streams* of plain
bytes. Everything downstream (matching, reporting) works on streams and does not
care what the container was.

Containers understood:

* ZIP        — every member is a stream.
* gzip/zlib  — one decompressed stream.
* SQLite     — the raw file, scanned as bytes. Page structure is irrelevant to a
               string search, and parsing it would be an assumption about schema.
* text/XML   — the raw file.
* anything else — the raw file, treated as opaque bytes.

A member of a ZIP may itself be gzip- or zlib-compressed; that is unwrapped up to
:data:`MAX_NESTING`. Deeper nesting is left alone rather than guessed at.

## What this module does NOT do

It does not interpret structure. It cannot tell you which timeline or which track
a clip sits on — that is v2, and building it honestly requires real .drp samples.
See ``rps.probe`` for the diagnostic that collects the facts v2 needs.
"""

from __future__ import annotations

import gzip
import zipfile
import zlib
from pathlib import Path
from typing import IO, Iterator

from rps.core.models import ContainerKind

__all__ = [
    "CHUNK_SIZE",
    "MAX_NESTING",
    "detect_container",
    "detect_container_of",
    "iter_streams",
]

CHUNK_SIZE = 1 << 20
"""Read granularity. Large enough to amortise syscalls, small enough that a
20 GB file cannot be pulled into memory by accident."""

MAX_NESTING = 2
"""How many layers of compression to unwrap before giving up and scanning the
compressed bytes as-is."""

_ZIP_MAGIC = b"PK\x03\x04"
_ZIP_EMPTY_MAGIC = b"PK\x05\x06"
_GZIP_MAGIC = b"\x1f\x8b"
_SQLITE_MAGIC = b"SQLite format 3\x00"

_ZLIB_FIRST = 0x78
_ZLIB_SECOND = {0x01, 0x5E, 0x9C, 0xDA}
"""Common zlib CMF/FLG pairs. The check is deliberately narrow: a false positive
here costs a failed decompression, which is caught and falls back to raw bytes."""

_TEXT_CONTROL = bytes(range(0, 9)) + bytes(range(14, 32))


def detect_container(head: bytes) -> ContainerKind:
    """Classify a file from its leading bytes.

    ``head`` should be at least 64 bytes where the file is that long. A short
    read is handled, it just yields a coarser answer.
    """

    if not head:
        return ContainerKind.EMPTY
    if head.startswith(_ZIP_MAGIC) or head.startswith(_ZIP_EMPTY_MAGIC):
        return ContainerKind.ZIP
    if head.startswith(_GZIP_MAGIC):
        return ContainerKind.GZIP
    if head.startswith(_SQLITE_MAGIC):
        return ContainerKind.SQLITE
    if len(head) >= 2 and head[0] == _ZLIB_FIRST and head[1] in _ZLIB_SECOND:
        return ContainerKind.ZLIB

    stripped = head.lstrip(b"\xef\xbb\xbf \t\r\n")
    if stripped.startswith(b"<?xml") or stripped.startswith(b"<"):
        return ContainerKind.XML
    if stripped[:1] in (b"{", b"["):
        return ContainerKind.JSON

    # No magic matched. Decide text vs binary the way `file(1)` does: a run of
    # control characters that are not tab/newline means binary.
    sample = head[:512]
    if not sample.translate(None, _TEXT_CONTROL) == sample:
        return ContainerKind.BINARY
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return ContainerKind.BINARY
    return ContainerKind.TEXT


def detect_container_of(path: Path) -> ContainerKind:
    """Classify a file on disk. Raises ``OSError`` if it cannot be read."""

    with path.open("rb") as handle:
        return detect_container(handle.read(512))


def iter_streams(path: Path) -> Iterator[tuple[str, Iterator[bytes]]]:
    """Yield ``(stream_name, chunk_iterator)`` for every readable stream in *path*.

    The stream name is ``""`` for the file's own bytes and the member path for a
    ZIP member. Chunk iterators must be consumed before advancing to the next
    stream — they read from a shared file handle.

    A member that fails to decompress is not silently dropped: its raw bytes are
    yielded instead, under the same name. Losing data to a container quirk would
    mean reporting "no match" for a project that does contain the clip.
    """

    with path.open("rb") as handle:
        kind = detect_container(handle.read(512))
        handle.seek(0)

        if kind is ContainerKind.EMPTY:
            return

        if kind is ContainerKind.ZIP:
            yield from _iter_zip_streams(path)
            return

        if kind is ContainerKind.GZIP:
            yield "", _iter_gzip(path)
            return

        if kind is ContainerKind.ZLIB:
            yield "", _iter_zlib(handle)
            return

        yield "", _iter_raw(handle)


def _iter_raw(handle: IO[bytes]) -> Iterator[bytes]:
    while True:
        chunk = handle.read(CHUNK_SIZE)
        if not chunk:
            return
        yield chunk


def _iter_gzip(path: Path) -> Iterator[bytes]:
    try:
        with gzip.open(path, "rb") as stream:
            while True:
                chunk = stream.read(CHUNK_SIZE)
                if not chunk:
                    return
                yield chunk
    except (OSError, EOFError, zlib.error):
        # Truncated or mislabelled. Fall back to the compressed bytes so that any
        # readable header text still participates in the search.
        with path.open("rb") as handle:
            yield from _iter_raw(handle)


def _iter_zlib(handle: IO[bytes]) -> Iterator[bytes]:
    handle.seek(0)
    decompressor = zlib.decompressobj()
    produced = False
    while True:
        raw = handle.read(CHUNK_SIZE)
        if not raw:
            break
        try:
            out = decompressor.decompress(raw)
        except zlib.error:
            if not produced:
                handle.seek(0)
                yield from _iter_raw(handle)
            return
        if out:
            produced = True
            yield out
    try:
        tail = decompressor.flush()
    except zlib.error:
        tail = b""
    if tail:
        yield tail
    if not produced:
        handle.seek(0)
        yield from _iter_raw(handle)


def _iter_zip_streams(path: Path) -> Iterator[tuple[str, Iterator[bytes]]]:
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError):
        with path.open("rb") as handle:
            yield "", _iter_raw(handle)
        return

    with archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            yield info.filename, _iter_zip_member(archive, info)


def _iter_zip_member(
    archive: zipfile.ZipFile, info: zipfile.ZipInfo
) -> Iterator[bytes]:
    try:
        member = archive.open(info)
    except (zipfile.BadZipFile, OSError, NotImplementedError, RuntimeError):
        return
    with member:
        first = member.read(CHUNK_SIZE)
        if not first:
            return
        inner = detect_container(first[:512])
        if inner in (ContainerKind.GZIP, ContainerKind.ZLIB):
            yield from _unwrap(first, member, inner, depth=1)
            return
        yield first
        while True:
            chunk = member.read(CHUNK_SIZE)
            if not chunk:
                return
            yield chunk


def _unwrap(
    first: bytes, source: IO[bytes], kind: ContainerKind, depth: int
) -> Iterator[bytes]:
    """Decompress a nested gzip/zlib member, falling back to its raw bytes."""

    wbits = 47 if kind is ContainerKind.GZIP else 15
    decompressor = zlib.decompressobj(wbits)
    buffered = [first]
    produced = False
    chunk = first
    while True:
        try:
            out = decompressor.decompress(chunk)
        except zlib.error:
            if not produced:
                yield from buffered
                yield from _drain(source)
            return
        if out:
            produced = True
            if depth < MAX_NESTING:
                nested = detect_container(out[:512])
                if nested in (ContainerKind.GZIP, ContainerKind.ZLIB):
                    yield from _unwrap(out, _NullStream(), nested, depth + 1)
                    continue
            yield out
        chunk = source.read(CHUNK_SIZE)
        if not chunk:
            break
        if not produced:
            buffered.append(chunk)
    try:
        tail = decompressor.flush()
    except zlib.error:
        tail = b""
    if tail:
        yield tail
    elif not produced:
        yield from buffered


def _drain(source: IO[bytes]) -> Iterator[bytes]:
    while True:
        chunk = source.read(CHUNK_SIZE)
        if not chunk:
            return
        yield chunk


class _NullStream:
    """An exhausted stream, for nested data already held in memory."""

    def read(self, _size: int = -1) -> bytes:
        return b""
