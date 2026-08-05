from __future__ import annotations

import os
import threading
import zipfile

import pytest

from rps.core.matcher import Query
from rps.core.scanner import ScanOptions, discover, scan, scan_file


def make_project(folder, name: str, body: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(body, encoding="utf-8")


def test_discover_finds_only_matching_extensions(tmp_path):
    make_project(tmp_path, "a.drp", "x")
    make_project(tmp_path, "b.txt", "x")
    make_project(tmp_path / "sub", "c.drp", "x")

    found = discover(tmp_path)
    assert [p.name for p in found] == ["a.drp", "c.drp"]


def test_discover_respects_non_recursive(tmp_path):
    make_project(tmp_path, "a.drp", "x")
    make_project(tmp_path / "sub", "c.drp", "x")

    found = discover(tmp_path, recursive=False)
    assert [p.name for p in found] == ["a.drp"]


def test_scan_reports_only_files_that_match(tmp_path):
    make_project(tmp_path, "BMW_EDIT.drp", "clip D:\\Footage\\C6343.MP4 on V2")
    make_project(tmp_path, "PODCAST.drp", "clip D:\\Audio\\voice.wav")

    results = []
    summary = scan(
        ScanOptions(root=tmp_path, query=Query(text="C6343.MP4")),
        on_result=results.append,
    )

    assert summary.total_files == 2
    assert summary.scanned_files == 2
    assert summary.matched_files == 1
    matched = [r for r in results if r.matched]
    assert [r.path.name for r in matched] == ["BMW_EDIT.drp"]


def test_scan_reads_inside_zip_container(tmp_path):
    target = tmp_path / "MUSIC_VIDEO.drp"
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("project.xml", "<clip path='D:\\Footage\\C6343.MP4'/>")

    summary = scan(ScanOptions(root=tmp_path, query=Query(text="C6343.MP4")))
    assert summary.matched_files == 1


def test_hit_limit_stops_collecting(tmp_path):
    make_project(tmp_path, "many.drp", "C6343.MP4 " * 500)

    result = scan_file(tmp_path / "many.drp", Query(text="C6343.MP4"), max_hits=5)
    assert len(result.hits) == 5


def test_unopenable_path_is_an_error_not_a_miss(tmp_path):
    """A path that cannot be opened must never be reported as "no match".

    A directory is used as the stand-in because it is unopenable on every
    platform — ``chmod(0o000)`` does not deny read access on Windows, so a
    permission-based test would pass there while proving nothing.
    """

    target = tmp_path / "locked.drp"
    target.mkdir()

    result = scan_file(target, Query(text="C6343.MP4"))

    assert result.error is not None
    assert not result.matched
    assert not result.readable


@pytest.mark.skipif(os.name == "nt", reason="chmod does not deny read access on Windows")
def test_permission_denied_is_an_error_not_a_miss(tmp_path):
    target = tmp_path / "locked.drp"
    target.write_text("C6343.MP4", encoding="utf-8")
    target.chmod(0o000)
    try:
        result = scan_file(target, Query(text="C6343.MP4"))
    finally:
        target.chmod(0o644)

    assert result.error is not None
    assert not result.matched


def test_cancelled_scan_is_reported_as_cancelled(tmp_path):
    for index in range(20):
        make_project(tmp_path, f"p{index:02d}.drp", "C6343.MP4")

    cancel = threading.Event()
    cancel.set()
    summary = scan(ScanOptions(root=tmp_path, query=Query(text="C6343.MP4")), cancel=cancel)

    assert summary.cancelled
    assert summary.scanned_files < summary.total_files or summary.total_files == 0


def test_cancelled_files_are_not_counted_as_unreadable(tmp_path):
    """Stop must not make the report claim the files were broken."""

    for index in range(6):
        make_project(tmp_path, f"p{index}.drp", "C6343.MP4")

    cancel = threading.Event()
    cancel.set()
    summary = scan(ScanOptions(root=tmp_path, query=Query(text="C6343.MP4")), cancel=cancel)

    assert summary.failed_files == 0
    assert summary.unfinished_files == summary.abandoned_files + summary.skipped_files


def test_progress_reaches_the_total(tmp_path):
    for index in range(8):
        make_project(tmp_path, f"p{index}.drp", "nothing here")

    seen: list[tuple[int, int]] = []
    summary = scan(
        ScanOptions(root=tmp_path, query=Query(text="C6343.MP4")),
        on_progress=lambda done, total: seen.append((done, total)),
    )

    assert summary.scanned_files == 8
    assert seen[-1] == (8, 8)


def test_empty_folder_finishes_cleanly(tmp_path):
    summary = scan(ScanOptions(root=tmp_path, query=Query(text="C6343.MP4")))
    assert summary.total_files == 0
    assert not summary.cancelled
