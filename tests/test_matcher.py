from __future__ import annotations

import pytest

from rps.core.matcher import CONTEXT_CHARS, Query, search_stream


def hits(data: bytes, text: str, **kwargs) -> list:
    return list(search_stream([data], Query(text=text, **kwargs)))


def test_finds_ascii_in_utf8():
    found = hits(b"\x00\x01path=D:\\Footage\\C6343.MP4\x00", "C6343.MP4")
    assert found
    assert "C6343.MP4" in found[0].text


def test_finds_ascii_in_utf16le():
    payload = "D:\\Footage\\C6343.MP4".encode("utf-16-le")
    found = hits(b"\x00\x00" + payload, "C6343.MP4")
    assert any(h.encoding.startswith("utf-16-le") for h in found)


def test_finds_utf16le_at_odd_alignment():
    payload = b"\x07" + "C6343.MP4".encode("utf-16-le")
    found = hits(payload, "C6343.MP4")
    assert any("utf-16-le" in h.encoding for h in found)


def test_case_insensitive_by_default():
    assert hits(b"clip c6343.mp4 here", "C6343.MP4")


def test_case_sensitive_when_asked():
    assert not hits(b"clip c6343.mp4 here", "C6343.MP4", case_sensitive=True)
    assert hits(b"clip C6343.MP4 here", "C6343.MP4", case_sensitive=True)


def test_finds_cyrillic_utf8():
    data = "путь=D:\\Съёмка\\Интервью.mov".encode("utf-8")
    assert hits(data, "Интервью")


def test_finds_cyrillic_cp1251():
    data = "путь=Интервью.mov".encode("cp1251")
    assert hits(data, "Интервью")


def test_partial_name_matches():
    assert hits(b"...A001_C6343_231107.MP4...", "6343")


def test_every_occurrence_inside_one_run_is_reported():
    """An uncompressed XML project is one long printable run.

    Reporting only the first match there would collapse forty references down to
    one, and the count column would lie.
    """

    data = b"<t><c>C6343.MP4</c><c>C6343.MP4</c><c>C6343.MP4</c></t>"
    found = [h for h in hits(data, "C6343.MP4") if h.encoding == "utf-8"]
    assert len(found) == 3
    assert len({h.offset for h in found}) == 3


def test_no_false_positive():
    assert not hits(b"nothing relevant in this buffer at all", "C6343.MP4")


def test_newline_ends_a_run():
    """One record per line must stay one record per snippet."""

    data = b"D:\\Footage\\other.mov\nD:\\Footage\\C6343.MP4\nD:\\Footage\\third.mov"
    found = [h for h in hits(data, "C6343.MP4") if h.encoding == "utf-8"]
    assert found[0].text == "D:\\Footage\\C6343.MP4"


def test_binary_noise_does_not_join_unrelated_strings():
    """A run must not span a NUL, or two neighbouring fields would fuse."""

    data = b"C6343\x00.MP4 extra text here"
    assert not hits(data, "C6343.MP4")


def test_match_split_across_chunks_is_found():
    chunks = [b"prefix D:\\Footage\\C63", b"43.MP4 suffix padding"]
    found = list(search_stream(chunks, Query(text="C6343.MP4")))
    assert found


def test_overlapping_match_reported_once():
    payload = b"x" * 64 + b" D:\\Footage\\C6343.MP4 " + b"y" * 64
    chunks = [payload[:80], payload[80:]]
    found = [h for h in search_stream(chunks, Query(text="C6343.MP4")) if h.encoding == "utf-8"]
    assert len(found) == 1


def test_snippet_is_trimmed_to_the_enclosing_field():
    """A whole project on one line must not become a whole row of XML."""

    filler = "<Clip name='other.mov' path='D:\\x\\other.mov'/>" * 20
    data = (
        f"<Timeline>{filler}<Clip path='D:\\Footage\\C6343.MP4'/>{filler}</Timeline>"
    ).encode()

    found = [h for h in hits(data, "C6343.MP4") if h.encoding == "utf-8"]
    assert found[0].text == "D:\\Footage\\C6343.MP4"


def test_long_run_is_clipped_around_the_match():
    filler = "z" * (CONTEXT_CHARS * 3)
    data = (filler + "C6343.MP4" + filler).encode()
    found = hits(data, "C6343.MP4")
    assert found
    assert len(found[0].text) < len(filler) * 2
    assert "C6343.MP4" in found[0].text


def test_empty_query_rejected():
    with pytest.raises(ValueError):
        Query(text="")


def test_offset_points_into_the_stream():
    data = b"padding padding " + b"C6343.MP4"
    found = hits(data, "C6343.MP4")
    assert found[0].offset == data.index(b"C6343.MP4")
