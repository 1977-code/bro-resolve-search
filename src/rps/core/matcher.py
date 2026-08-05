"""Finding a query string inside opaque byte streams.

The strategy is deliberately the same one ``strings | grep`` uses, because it is
the only one that survives a container format we cannot fully parse: pull every
run of printable characters out of the bytes, decode it under each plausible
encoding, and match against that.

Three encodings are tried:

* **UTF-8** — also covers plain ASCII and, for ASCII-only text, every
  ASCII-compatible single-byte encoding.
* **UTF-16-LE**, at both byte alignments — Windows-authored strings frequently
  land in a project file this way, and a naive byte search misses all of them.
* **CP1251** — only when the query itself contains non-ASCII characters, since
  for an ASCII query the UTF-8 pass already covers it.

A cheap byte-level pre-filter runs first so that the expensive decode work only
happens on blocks that can possibly match.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Iterator

from rps.core.models import Hit

__all__ = ["Query", "search_stream", "extract_runs"]

MIN_RUN = 4
"""Shortest run of printable characters treated as a string. Below this the
output is dominated by coincidental byte pairs."""

CONTEXT_CHARS = 70
"""How much text around a match is kept when no field boundary is found."""

FIELD_DELIMITERS = "\"'<>=|"
"""Characters that end a field in every serialisation Resolve could plausibly
use. Trimming to these turns "the whole XML document" into "the one attribute
that matched", which is what the user is actually looking at."""

MAX_SNIPPET = 220

_NON_PRINTABLE = "\x00-\x1f\x7f�"
"""Every control character ends a run, newlines and tabs included. A line-per-
record text file would otherwise come back as one run spanning the whole file,
and the snippet shown for a match would start on some unrelated earlier line."""
_RUN_CACHE: dict[int, re.Pattern[str]] = {}


@dataclass(frozen=True)
class Query:
    """A user's search string plus how to interpret it."""

    text: str
    case_sensitive: bool = False
    min_run: int = MIN_RUN

    def __post_init__(self) -> None:
        if not self.text:
            raise ValueError("Пустой поисковый запрос")

    @property
    def needle(self) -> str:
        return self.text if self.case_sensitive else self.text.casefold()

    @property
    def is_ascii(self) -> bool:
        return self.text.isascii()


def _run_pattern(min_run: int) -> re.Pattern[str]:
    pattern = _RUN_CACHE.get(min_run)
    if pattern is None:
        pattern = re.compile(f"[^{_NON_PRINTABLE}]{{{min_run},}}")
        _RUN_CACHE[min_run] = pattern
    return pattern


def extract_runs(data: bytes, encoding: str, min_run: int = MIN_RUN) -> Iterator[tuple[int, str]]:
    """Yield ``(char_index, text)`` for printable runs decoded under *encoding*.

    Undecodable bytes become U+FFFD, which is excluded from the run character
    class — so garbage terminates a run instead of joining two unrelated strings
    into one false match.
    """

    try:
        text = data.decode(encoding, errors="replace")
    except (LookupError, UnicodeDecodeError):
        return
    for match in _run_pattern(min_run).finditer(text):
        yield match.start(), match.group()


def _encodings_for(query: Query) -> tuple[tuple[str, int, int], ...]:
    """``(codec, byte_alignment, bytes_per_char)`` passes to run for *query*."""

    passes: list[tuple[str, int, int]] = [
        ("utf-8", 0, 1),
        ("utf-16-le", 0, 2),
        ("utf-16-le", 1, 2),
    ]
    if not query.is_ascii:
        passes.append(("cp1251", 0, 1))
    return tuple(passes)


def _byte_variants(query: Query) -> tuple[bytes, ...]:
    """Encoded forms of the needle used by the pre-filter.

    Only meaningful for an ASCII query: ``bytes.lower()`` folds ASCII and leaves
    every other byte alone, which is exactly what makes the UTF-16-LE variant
    work too (its interleaved NUL bytes are untouched).
    """

    text = query.text if query.case_sensitive else query.text.lower()
    return (
        text.encode("utf-8", errors="ignore"),
        text.encode("utf-16-le", errors="ignore"),
    )


def _prefilter(data: bytes, query: Query, variants: tuple[bytes, ...]) -> bool:
    if not query.is_ascii:
        # Multi-byte and legacy encodings do not fold predictably at byte level.
        return True
    haystack = data if query.case_sensitive else data.lower()
    return any(variant and variant in haystack for variant in variants)


def _clip(text: str, index: int, length: int) -> str:
    """Trim a long run down to the part worth reading.

    A whole project serialised as one line is a single printable run, so showing
    the run verbatim would put a screenful of XML in every row. Preference order:
    the enclosing field, then a fixed window, then the run as it is.
    """

    if len(text) <= MAX_SNIPPET:
        return text

    end_index = index + length
    field_start = max(
        (text.rfind(d, 0, index) for d in FIELD_DELIMITERS),
        default=-1,
    )
    field_end = min(
        (pos for pos in (text.find(d, end_index) for d in FIELD_DELIMITERS) if pos >= 0),
        default=-1,
    )
    if field_start >= 0 and field_end >= 0 and field_end - field_start <= MAX_SNIPPET:
        return text[field_start + 1 : field_end]

    start = max(0, index - CONTEXT_CHARS)
    stop = min(len(text), end_index + CONTEXT_CHARS)
    prefix = "…" if start > 0 else ""
    suffix = "…" if stop < len(text) else ""
    return f"{prefix}{text[start:stop]}{suffix}"


def _search_block(
    data: bytes, base: int, query: Query, stream: str, variants: tuple[bytes, ...]
) -> Iterator[Hit]:
    if not _prefilter(data, query, variants):
        return
    needle = query.needle
    for codec, alignment, width in _encodings_for(query):
        payload = data[alignment:] if alignment else data
        encoding = codec if not alignment else f"{codec}+{alignment}"
        for char_index, run in extract_runs(payload, codec, query.min_run):
            haystack = run if query.case_sensitive else run.casefold()
            # Every occurrence, not just the first: an uncompressed XML project
            # is a single printable run, so stopping at the first match would
            # report one hit for a file that references the clip forty times.
            found = haystack.find(needle)
            while found >= 0:
                yield Hit(
                    stream=stream,
                    offset=base + alignment + (char_index + found) * width,
                    text=_clip(run, found, len(needle)),
                    encoding=encoding,
                )
                found = haystack.find(needle, found + len(needle))


def search_stream(
    chunks: Iterable[bytes], query: Query, stream: str = ""
) -> Iterator[Hit]:
    """Search a chunked byte stream, yielding one :class:`Hit` per matched run.

    Chunks are re-joined with an overlap so that a string split across a read
    boundary is still found. Hits inside the overlap are de-duplicated by their
    absolute offset, so an overlapping match is reported once.
    """

    variants = _byte_variants(query)
    # Enough to hold the longest run we would still want to match across a
    # boundary, doubled for UTF-16 and padded for the surrounding context.
    overlap = max(len(query.text) * 4, query.min_run * 4, 256)

    tail = b""
    base = 0
    previous: set[tuple[str, int, str]] = set()

    for chunk in chunks:
        data = tail + chunk
        current: set[tuple[str, int, str]] = set()
        for hit in _search_block(data, base, query, stream, variants):
            key = (hit.encoding, hit.offset, hit.text)
            current.add(key)
            if key in previous:
                continue
            yield hit
        previous = current

        keep = min(len(data), overlap)
        base += len(data) - keep
        tail = data[len(data) - keep :] if keep else b""
