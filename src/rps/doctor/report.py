"""Rendering the diagnostic run.

Two outputs, on purpose:

* **Markdown** — for a human to read and to paste into a chat. Short lines, no
  raw dumps.
* **JSON** — everything, including the lists that are too long to read. This is
  what the parser gets written from.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from rps.doctor.model import Report, Status

__all__ = ["render_markdown", "render_json", "summary_line"]

PRIVACY_NOTE = (
    "В отчёте есть пути и имена файлов с этого компьютера — так и задумано, "
    "иначе по нему нельзя написать разбор формата. Если что-то из этого не "
    "должно уехать наружу, отредактируй файл перед отправкой: это обычный текст."
)


def render_markdown(report: Report) -> str:
    lines = [
        "# Отчёт Resolve Doctor",
        "",
        f"- Собран: {report.generated_at}",
        f"- Версия инструмента: {report.app_version}",
        "",
        f"> {PRIVACY_NOTE}",
        "",
        "## Коротко",
        "",
    ]
    lines += [f"- {item}" for item in _headline(report)]
    lines.append("")

    for section in report.sections:
        lines += [f"## {section.title}", ""]
        if not section.findings:
            lines += ["_Нечего показать._", ""]
        for finding in section.findings:
            detail = finding.detail.strip()
            lines.append(f"- {finding.status.mark} **{finding.label}** — {detail or '—'}")
        if section.notes:
            lines.append("")
            lines += [f"> {note}" for note in section.notes]
        lines.append("")

    if report.errors:
        lines += ["## Сбои самой диагностики", ""]
        lines += [f"- {error}" for error in report.errors]
        lines += [
            "",
            "> Это ошибки инструмента, а не проблемы Resolve. Их стоит прислать "
            "отдельно — по ним чинится диагностика.",
            "",
        ]

    lines += [
        "## Что дальше",
        "",
        "Полная машинная версия этого отчёта лежит рядом в файле `.json` — "
        "именно она нужна для написания разбора формата. Пришли оба файла.",
        "",
    ]
    return "\n".join(lines)


def _headline(report: Report) -> list[str]:
    """The four answers everything else exists to support."""

    out: list[str] = []

    connect = report.find("Скриптовый API", "connect")
    if connect is None:
        out.append("Скриптовый API Resolve: не проверялся — модуль скриптинга не найден.")
    elif connect.status is Status.OK:
        version = report.find("Скриптовый API", "version")
        out.append(f"Скриптовый API Resolve: работает ({version.detail if version else 'версия не сообщается'}).")
    else:
        out.append(f"Скриптовый API Resolve: не подключился — {connect.detail}")

    projects = report.find("Базы проектов", "projects")
    if projects is not None and projects.status is Status.OK:
        out.append(f"Проекты в базе: {projects.detail}.")
    else:
        out.append("Проекты в базе: пересчитать не удалось.")

    drp = report.find("Файлы .drp на дисках", "count")
    if drp is None:
        out.append("Файлы .drp: поиск не запускался.")
    elif drp.status is Status.OK:
        out.append(f"Файлы .drp на дисках: {drp.detail}.")
    elif isinstance(drp.data, dict) and drp.data.get("truncated"):
        # Nothing found *and* the sweep was cut short proves nothing either way.
        out.append(
            "Файлы .drp на дисках: не найдено, но поиск был прерван по лимиту — "
            "вывод делать рано, нужен полный прогон."
        )
    else:
        out.append(
            "Файлы .drp на дисках: не найдено ни одного — значит проекты живут в "
            "базе, и поиск по папке с .drp этому компьютеру не поможет."
        )

    disk_db = report.find("Базы проектов", "disk_db")
    if disk_db is not None:
        out.append(f"Дисковая база на диске: {disk_db.detail}.")

    return out


def render_json(report: Report) -> str:
    payload: dict[str, Any] = {
        "generated_at": report.generated_at,
        "app_version": report.app_version,
        "errors": report.errors,
        "sections": [
            {
                "title": section.title,
                "notes": section.notes,
                "findings": [_finding_dict(finding) for finding in section.findings],
            }
            for section in report.sections
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, default=_fallback)


def _finding_dict(finding: Any) -> dict[str, Any]:
    data = asdict(finding)
    data["status"] = finding.status.value
    return data


def _fallback(value: Any) -> str:
    """Anything the Resolve API handed back that JSON cannot represent."""

    return f"<{type(value).__name__}>"


def summary_line(report: Report) -> str:
    findings = sum(len(section.findings) for section in report.sections)
    return f"Собрано {findings} наблюдений в {len(report.sections)} разделах."
