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


def test_outline_of_a_missing_member_says_so(tmp_path):
    """Absent must not look the same as "has no structure"."""

    target = make_export(tmp_path / "LUGANG.drp")

    outline = _xml_outline(target, "SeqContainer/nope.xml")

    assert outline["error"]
    assert not outline.get("tags")


def test_element_text_is_captured():
    """Resolve puts its values in element text, not in attributes.

    A real timeline stores <MediaFilePath>D:\\...</MediaFilePath>; only DbId is
    an attribute. An outline of attributes alone described almost nothing.
    """

    import zipfile as zf
    import tempfile
    from pathlib import Path as P

    with tempfile.TemporaryDirectory() as tmp:
        target = P(tmp) / "t.drp"
        with zf.ZipFile(target, "w") as archive:
            archive.writestr(
                "SeqContainer/x.xml",
                "<Sm2SequenceContainer DbId='cf2d'>"
                "<Sm2TiVideoClip DbId='d1c2'>"
                "<Name>C6343.MP4</Name>"
                "<MediaFilePath>D:\\Footage\\C6343.MP4</MediaFilePath>"
                "<MediaReelNumber>A001</MediaReelNumber>"
                "<Start>108311</Start>"
                "</Sm2TiVideoClip></Sm2SequenceContainer>",
            )

        outline = _xml_outline(target, "SeqContainer/x.xml")

    assert outline["tags"]["MediaFilePath"]["text"] == ["D:\\Footage\\C6343.MP4"]
    assert outline["tags"]["Name"]["text"] == ["C6343.MP4"]
    assert outline["tags"]["Sm2TiVideoClip"]["attrs"]["DbId"] == ["d1c2"]


def test_malformed_tail_keeps_what_was_already_parsed(tmp_path):
    """The bug that made a real report show "0 tags" for almost every member.

    Draining the event queue with list() discards every event when the final one
    raises, turning "the tail is malformed" into "this file has no structure".
    """

    target = tmp_path / "broken.drp"
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr(
            "project.xml",
            "<Project><Setting><Name>frameRate</Name></Setting><Broken",
        )

    outline = _xml_outline(target, "project.xml")

    assert "Project" in outline["tags"]
    assert outline["tags"]["Name"]["text"] == ["frameRate"]
    assert "error" in outline


def test_event_budget_marks_truncation(tmp_path, monkeypatch):
    import rps.doctor.probe as probe

    target = tmp_path / "big.drp"
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr(
            "project.xml",
            "<Project>" + "<Setting name='a' value='b'/>" * 2000 + "</Project>",
        )
    monkeypatch.setattr(probe, "OUTLINE_EVENT_BUDGET", 40)

    outline = _xml_outline(target, "project.xml")

    assert outline["truncated"] is True
    assert "Project" in outline["tags"]


def test_members_worth_outlining_prefers_structure(tmp_path):
    target = make_export(tmp_path / "LUGANG.drp", timelines=("A", "B", "C", "D"))
    with zipfile.ZipFile(target) as archive:
        members = [(i.filename, i.compress_size, i.file_size) for i in archive.infolist()]

    chosen = _members_worth_outlining(members)

    assert chosen[0] == "project.xml"
    assert sum(1 for name in chosen if name.startswith("SeqContainer/")) == 3
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
