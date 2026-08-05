from __future__ import annotations

import csv
from pathlib import Path

from rps.core.export import CSV_COLUMNS, write_csv
from rps.core.models import ContainerKind, FileResult, Hit


def read_back(path: Path) -> list[list[str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.reader(handle, delimiter=";"))


def test_header_and_one_row_per_hit(tmp_path):
    result = FileResult(
        path=Path("/projects/BMW_EDIT.drp"),
        size=1024,
        container=ContainerKind.ZIP,
        hits=[
            Hit(stream="project.xml", offset=10, text="D:\\Footage\\C6343.MP4", encoding="utf-8"),
            Hit(stream="project.xml", offset=99, text="C6343.MP4", encoding="utf-16-le"),
        ],
    )

    target = tmp_path / "out.csv"
    assert write_csv(target, [result]) == 2

    rows = read_back(target)
    assert rows[0] == list(CSV_COLUMNS)
    assert len(rows) == 3
    assert rows[1][0] == "BMW_EDIT"
    assert rows[1][9] == "D:\\Footage\\C6343.MP4"


def test_misses_are_skipped_but_errors_are_kept(tmp_path):
    miss = FileResult(path=Path("/p/miss.drp"), size=1, container=ContainerKind.TEXT)
    broken = FileResult(path=Path("/p/broken.drp"), size=1, error="не удалось открыть")

    target = tmp_path / "out.csv"
    assert write_csv(target, [miss, broken]) == 1

    rows = read_back(target)
    assert rows[1][0] == "broken"
    assert rows[1][10] == "не удалось открыть"


def test_include_misses_writes_everything(tmp_path):
    miss = FileResult(path=Path("/p/miss.drp"), size=1, container=ContainerKind.TEXT)

    target = tmp_path / "out.csv"
    assert write_csv(target, [miss], include_misses=True) == 1


def test_newlines_in_a_hit_do_not_break_the_row(tmp_path):
    result = FileResult(
        path=Path("/p/a.drp"),
        size=1,
        hits=[Hit(stream="", offset=0, text="line one\nline two", encoding="utf-8")],
    )

    target = tmp_path / "out.csv"
    write_csv(target, [result])

    rows = read_back(target)
    assert len(rows) == 2
    assert rows[1][9] == "line one line two"


def test_excel_friendly_encoding(tmp_path):
    result = FileResult(
        path=Path("/p/Съёмка.drp"),
        size=1,
        hits=[Hit(stream="", offset=0, text="Интервью.mov", encoding="utf-8")],
    )

    target = tmp_path / "out.csv"
    write_csv(target, [result])

    raw = target.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    assert b";" in raw
