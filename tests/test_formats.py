from __future__ import annotations

import gzip
import io
import zipfile
import zlib

import pytest

from rps.core.formats import detect_container, iter_streams
from rps.core.models import ContainerKind


def _collect(path):
    return {name: b"".join(chunks) for name, chunks in iter_streams(path)}


@pytest.mark.parametrize(
    "data, expected",
    [
        (b"", ContainerKind.EMPTY),
        (b"PK\x03\x04rest", ContainerKind.ZIP),
        (b"PK\x05\x06" + b"\x00" * 18, ContainerKind.ZIP),
        (b"\x1f\x8b\x08\x00", ContainerKind.GZIP),
        (b"SQLite format 3\x00page", ContainerKind.SQLITE),
        (b"\x78\x9c\x01\x02", ContainerKind.ZLIB),
        (b'<?xml version="1.0"?><a/>', ContainerKind.XML),
        (b'\xef\xbb\xbf<Project/>', ContainerKind.XML),
        (b'{"project": 1}', ContainerKind.JSON),
        (b"plain readable text\n", ContainerKind.TEXT),
        (b"\x00\x01\x02\x03binary\x00\x00", ContainerKind.BINARY),
    ],
)
def test_detect_container(data, expected):
    assert detect_container(data) is expected


def test_zip_members_are_separate_streams(tmp_path):
    target = tmp_path / "project.drp"
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("project.xml", "<clip>C6343.MP4</clip>")
        archive.writestr("media/list.txt", "D:\\Footage\\C6343.MP4")

    streams = _collect(target)
    assert set(streams) == {"project.xml", "media/list.txt"}
    assert b"C6343.MP4" in streams["project.xml"]


def test_gzip_is_decompressed(tmp_path):
    target = tmp_path / "project.drp"
    target.write_bytes(gzip.compress(b"clip C6343.MP4 on V2"))

    streams = _collect(target)
    assert streams[""] == b"clip C6343.MP4 on V2"


def test_zlib_is_decompressed(tmp_path):
    target = tmp_path / "project.drp"
    target.write_bytes(zlib.compress(b"clip C6343.MP4 on V2"))

    streams = _collect(target)
    assert streams[""] == b"clip C6343.MP4 on V2"


def test_zip_member_compressed_again_is_unwrapped(tmp_path):
    target = tmp_path / "project.drp"
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("inner.gz", gzip.compress(b"nested C6343.MP4"))

    streams = _collect(target)
    assert b"nested C6343.MP4" in streams["inner.gz"]


def test_truncated_gzip_falls_back_to_raw_bytes(tmp_path):
    """A container we cannot unpack must not become an empty result.

    Reporting "no match" for a file we simply failed to open is the one outcome
    this tool must never produce.
    """

    target = tmp_path / "project.drp"
    target.write_bytes(gzip.compress(b"readable C6343.MP4 tail")[:12])

    streams = _collect(target)
    assert streams[""].startswith(b"\x1f\x8b")


def test_broken_zip_falls_back_to_raw_bytes(tmp_path):
    target = tmp_path / "project.drp"
    target.write_bytes(b"PK\x03\x04 not really a zip C6343.MP4")

    streams = _collect(target)
    assert b"C6343.MP4" in streams[""]


def test_empty_file_yields_no_streams(tmp_path):
    target = tmp_path / "empty.drp"
    target.write_bytes(b"")

    assert _collect(target) == {}


def test_large_raw_file_is_chunked(tmp_path):
    target = tmp_path / "big.drp"
    payload = b"\x00" * (3 << 20) + b"C6343.MP4"
    target.write_bytes(payload)

    chunk_counts = [len(list(chunks)) for _name, chunks in iter_streams(target)]
    assert chunk_counts[0] > 1


def test_sqlite_is_scanned_as_bytes(tmp_path):
    target = tmp_path / "project.drp"
    target.write_bytes(b"SQLite format 3\x00" + b"\x00" * 32 + b"C6343.MP4")

    streams = _collect(target)
    assert b"C6343.MP4" in streams[""]


def test_stream_iteration_closes_handles(tmp_path):
    target = tmp_path / "project.drp"
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("a.txt", "one")
        archive.writestr("b.txt", "two")

    for _name, chunks in iter_streams(target):
        io.BytesIO(b"".join(chunks))
    # Windows would raise here if a handle were still open.
    target.unlink()
