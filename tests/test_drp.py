"""Recognising a Resolve project.

The fixtures mirror what a real machine actually contained: alongside ~70 real
projects there were VideoProc AI models and Reason drum kits, all ending in
``.drp``.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from rps.core.drp import DrpKind, classify, list_members, project_display_name
from rps.core.matcher import Query
from rps.core.scanner import ScanOptions, scan, scan_file


def make_project(path: Path, clip: str = "C6343.MP4") -> Path:
    """A ZIP shaped like the real exports: project.xml plus a media pool tree."""

    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("project.xml", f"<Project><Clip name='{clip}'/></Project>")
        archive.writestr("MediaPool/Master/MpFolder.xml", "<MpFolder/>")
        archive.writestr("MediaPool/Master/000_Timelines/MpFolder.xml", "<MpFolder/>")
        archive.writestr("SeqContainer/c9dd78a8-594a-4198-9c9b-2d9138040406.xml", "<Seq/>")
    return path


def test_zip_with_project_xml_is_a_resolve_project(tmp_path):
    kind, reason = classify(make_project(tmp_path / "BMW.drp"))

    assert kind is DrpKind.RESOLVE
    assert "project.xml" in reason


def test_videoproc_model_is_foreign(tmp_path):
    target = tmp_path / "V3_x2_moreDetail.engine.drp"
    target.write_bytes(b"DIGIZ" + b"\x00" * 64)

    kind, reason = classify(target)

    assert kind is DrpKind.FOREIGN
    assert "VideoProc" in reason


def test_zip_without_resolve_members_is_foreign(tmp_path):
    target = tmp_path / "Dark Kit RDK.drp"
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("samples/kick.wav", "not a project")

    kind, _reason = classify(target)

    assert kind is DrpKind.FOREIGN


def test_unrecognised_container_stays_unknown(tmp_path):
    """An older Resolve format must not be thrown away as foreign."""

    target = tmp_path / "ancient.drp"
    target.write_text("<Project><Clip name='C6343.MP4'/></Project>", encoding="utf-8")

    kind, _reason = classify(target)

    assert kind is DrpKind.UNKNOWN


def test_unknown_files_are_still_searched(tmp_path):
    target = tmp_path / "ancient.drp"
    target.write_text("<Project><Clip name='C6343.MP4'/></Project>", encoding="utf-8")

    result = scan_file(target, Query(text="C6343.MP4"))

    assert result.matched


def test_foreign_files_are_skipped_not_read(tmp_path):
    heavy = tmp_path / "model.drp"
    heavy.write_bytes(b"DIGIZ" + b"\x00" * 1024 + b"C6343.MP4")

    result = scan_file(heavy, Query(text="C6343.MP4"))

    assert result.kind == DrpKind.FOREIGN.value
    assert not result.matched
    assert result.error is None


def test_foreign_files_can_be_searched_on_request(tmp_path):
    heavy = tmp_path / "model.drp"
    heavy.write_bytes(b"DIGIZ" + b"\x00" * 1024 + b"C6343.MP4")

    result = scan_file(heavy, Query(text="C6343.MP4"), skip_foreign=False)

    assert result.matched


def test_summary_counts_foreign_separately(tmp_path):
    make_project(tmp_path / "real.drp")
    (tmp_path / "model.drp").write_bytes(b"DIGIZ" + b"\x00" * 64)

    summary = scan(ScanOptions(root=tmp_path, query=Query(text="C6343.MP4")))

    assert summary.total_files == 2
    assert summary.foreign_files == 1
    assert summary.scanned_files == 1
    assert summary.matched_files == 1


def test_members_are_listed(tmp_path):
    members = list_members(make_project(tmp_path / "BMW.drp"))

    names = [name for name, _c, _u in members]
    assert "project.xml" in names
    assert any(name.startswith("SeqContainer/") for name in names)


def test_archive_folder_name_wins_over_project_drp(tmp_path):
    archive = tmp_path / "федук др.dra"
    archive.mkdir()
    inner = archive / "project.drp"
    inner.touch()

    assert project_display_name(inner) == "федук др"


def test_plain_project_keeps_its_own_name(tmp_path):
    target = tmp_path / "LUGANG vs UB.drp"
    target.touch()

    assert project_display_name(target) == "LUGANG vs UB"
