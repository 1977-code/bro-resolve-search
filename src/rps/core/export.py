"""CSV export of scan results.

Written with a UTF-8 BOM and ``;`` delimiter because the overwhelmingly likely
destination is Excel on a Russian-locale Windows machine, where a comma-delimited
UTF-8 file without a BOM opens as one mangled column.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, Sequence

from rps.core.models import FileResult

__all__ = ["CSV_COLUMNS", "write_csv"]

CSV_COLUMNS: Sequence[str] = (
    "Проект",
    "Путь к проекту",
    "Папка",
    "Размер, байт",
    "Контейнер",
    "Совпадений",
    "Поток",
    "Смещение (прибл.)",
    "Кодировка",
    "Найденная строка",
    "Ошибка",
)


def write_csv(
    target: Path,
    results: Iterable[FileResult],
    include_misses: bool = False,
) -> int:
    """Write *results* to *target*. Returns the number of data rows written.

    A file that failed to read is always written out, even when ``include_misses``
    is false: "could not read" is a result the user needs to see, not a miss.
    One row per hit; a matched file with several hits produces several rows.
    """

    rows = 0
    with target.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=";", quoting=csv.QUOTE_MINIMAL)
        writer.writerow(CSV_COLUMNS)
        for result in results:
            if not result.matched and not result.error and not include_misses:
                continue
            base = [
                result.path.stem,
                str(result.path),
                str(result.path.parent),
                result.size,
                result.container.label if result.container else "",
            ]
            if not result.hits:
                writer.writerow(base + [0, "", "", "", "", result.error or ""])
                rows += 1
                continue
            for hit in result.hits:
                writer.writerow(
                    base
                    + [
                        len(result.hits),
                        hit.stream,
                        hit.offset,
                        hit.encoding,
                        _clean(hit.text),
                        result.error or "",
                    ]
                )
                rows += 1
    return rows


def _clean(text: str) -> str:
    """Flatten a matched run so one hit stays one CSV row."""

    return " ".join(text.split())
