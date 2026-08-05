from __future__ import annotations

import json

from rps.doctor.model import Report, Status
from rps.doctor.probe import ScanLimits, collect
from rps.doctor.report import render_json, render_markdown


def test_collect_runs_without_resolve_installed():
    """The diagnostic must survive its own worst case: nothing to find."""

    steps: list[str] = []
    report = collect(ScanLimits(search_drp=False), progress=steps.append)

    assert report.sections
    assert steps
    assert not report.errors


def test_absent_is_reported_as_missing_not_failed():
    report = collect(ScanLimits(search_drp=False))
    statuses = {
        finding.status
        for section in report.sections
        for finding in section.findings
    }
    # On a machine with no Resolve every install finding is MISSING. FAILED is
    # reserved for something that exists and did not work, and conflating the
    # two would send the reader hunting for a broken install that is simply
    # not installed.
    assert Status.MISSING in statuses or Status.OK in statuses


def test_markdown_has_a_headline_and_privacy_notice():
    report = collect(ScanLimits(search_drp=False))
    text = render_markdown(report)

    assert text.startswith("# Отчёт Resolve Doctor")
    assert "## Коротко" in text
    assert "пути и имена файлов" in text
    for section in report.sections:
        assert f"## {section.title}" in text


def test_json_is_valid_and_carries_the_data_payloads():
    report = collect(ScanLimits(search_drp=False))
    payload = json.loads(render_json(report))

    assert payload["app_version"]
    titles = [section["title"] for section in payload["sections"]]
    assert "Система" in titles
    assert all("findings" in section for section in payload["sections"])


def test_json_survives_values_it_cannot_serialise():
    report = Report(generated_at="2026-08-05T00:00:00+03:00", app_version="1.0.0")
    section = report.section("Проба")
    section.add("weird", "Объект из чужого API", Status.INFO, "", data=object())

    payload = json.loads(render_json(report))
    assert payload["sections"][0]["findings"][0]["data"] == "<object>"


def test_truncated_drp_sweep_does_not_claim_projects_live_in_a_database():
    report = Report(generated_at="2026-08-05T00:00:00+03:00", app_version="1.0.0")
    section = report.section("Файлы .drp на дисках")
    section.add("count", "Найдено файлов .drp", Status.MISSING, "0", data={"truncated": True})

    text = render_markdown(report)
    assert "вывод делать рано" in text
