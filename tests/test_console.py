from __future__ import annotations

import io

import pytest

from rps.console import _force_utf8, attach_console


def cp1252_stream() -> io.TextIOWrapper:
    """A stream exactly like the one a frozen Windows build gets handed."""

    return io.TextIOWrapper(io.BytesIO(), encoding="cp1252")


def test_cp1252_stream_cannot_write_russian_before_the_fix():
    """The failure this module exists to prevent, pinned so it stays visible."""

    stream = cp1252_stream()
    with pytest.raises(UnicodeEncodeError):
        stream.write("Просмотрено 241 из 241 файлов")
        stream.flush()


def test_force_utf8_makes_russian_writable():
    stream = cp1252_stream()

    _force_utf8(stream)
    stream.write("Просмотрено 241 из 241 файлов")
    stream.flush()

    assert stream.encoding.lower().replace("-", "_") == "utf_8"
    assert "Просмотрено".encode() in stream.buffer.getvalue()


def test_force_utf8_is_idempotent():
    stream = cp1252_stream()

    _force_utf8(stream)
    _force_utf8(stream)

    stream.write("ещё раз")
    stream.flush()
    assert "ещё раз".encode() in stream.buffer.getvalue()


def test_force_utf8_ignores_streams_it_cannot_reconfigure():
    class Captured:
        encoding = "cp1252"

        def write(self, text: str) -> int:
            return len(text)

    stream = Captured()
    _force_utf8(stream)  # must not raise
    assert stream.encoding == "cp1252"


def test_attach_console_leaves_usable_streams():
    import sys

    attach_console()

    assert sys.stdout is not None
    assert sys.stderr is not None
    sys.stdout.write("")
