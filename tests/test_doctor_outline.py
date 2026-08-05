"""The XML outline is the input to the version 2.0 parser, so it is tested.

Member names mirror the ones a real Resolve 21 export actually contained:
``project.xml``, ``MediaPool/**/MpFolder.xml`` and ``SeqContainer/<uuid>.xml``.
"""

from __future__ import annotations

import zipfile

from rps.doctor.probe import _describe_drp, _members_worth_outlining, _xml_outline


def make_export(path, timelines=("Final_v12", "Reels")):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("project.xml", '<Project name="LUGANG vs UB"/>')
        archive.writestr(
            "MediaPool/Master/MpFolder.xml",
            '<MpFolder name="Master">'
            '<MediaPoolItem name="C6343.MP4" FilePath="D:\\F\\C6343.MP4" ReelName="A001"/>'
            "</MpFolder>",
        )
        for index, name in enumerate(timelines):
            archive.writestr(
                f"SeqContainer/{index:08d}-594a-4198-9c9b-2d9138040406.xml",
                f'<Sequence name="{name}" StartTC="01:00:00:00">'
                f'<Track type="video" index="2">'
                f'<Item name="C6343.MP4" RecordFrame="108311"/>'
                f"</Track></Sequence>",
            )
    return path


def test_outline_reports_tags_and_attributes(tmp_path):
    target = make_export(tmp_path / "LUGANG.drp")

    outline = _xml_outline(target, "SeqContainer/00000000-594a-4198-9c9b-2d9138040406.xml")

    assert outline["tags"]["Sequence"]["attrs"]["name"] == ["Final_v12"]
    assert outline["tags"]["Track"]["attrs"]["type"] == ["video"]
    assert "RecordFrame" in outline["tags"]["Item"]["attrs"]


def test_outline_of_a_missing_member_is_empty(tmp_path):
    target = make_export(tmp_path / "LUGANG.drp")

    assert _xml_outline(target, "SeqContainer/nope.xml") == {}


def test_outline_survives_a_truncated_member(tmp_path, monkeypatch):
    """A cap on how much is read must produce a partial map, not an exception."""

    import rps.doctor.probe as probe

    target = tmp_path / "big.drp"
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr(
            "project.xml",
            '<Project name="x">' + '<Setting name="a" value="b"/>' * 2000 + "</Project>",
        )
    monkeypatch.setattr(probe, "OUTLINE_BYTES", 512)

    outline = _xml_outline(target, "project.xml")

    assert outline["truncated"] is True
    assert "Project" in outline["tags"]


def test_members_worth_outlining_prefers_structure(tmp_path):
    target = make_export(tmp_path / "LUGANG.drp", timelines=("A", "B", "C", "D"))
    with zipfile.ZipFile(target) as archive:
        members = [(i.filename, i.compress_size, i.file_size) for i in archive.infolist()]

    chosen = _members_worth_outlining(members)

    assert chosen[0] == "project.xml"
    assert sum(1 for name in chosen if name.startswith("SeqContainer/")) == 2
    assert any(name.endswith("MpFolder.xml") for name in chosen)


def test_zip_project_is_described_by_structure_not_by_noise(tmp_path):
    """A ZIP must be reported through its members, not by grepping its bytes.

    Scanning compressed bytes for printable runs is what filled the first real
    report with mojibake.
    """

    target = make_export(tmp_path / "LUGANG.drp")

    finding = _describe_drp(target)

    assert finding.data["container"] == "zip"
    assert "samples" not in finding.data
    names = [member["name"] for member in finding.data["members"]]
    assert "project.xml" in names
    assert finding.data["xml_outline"]["project.xml"]["tags"]["Project"]["attrs"]["name"] == [
        "LUGANG vs UB"
    ]
