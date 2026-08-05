"""Entry point.

No arguments opens the window. Arguments run the same search headlessly, which
is what makes the engine testable on a machine with no display and scriptable on
a render node.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rps import APP_NAME, __version__

__all__ = ["main"]


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        from rps.app import run

        return run()

    # A windowed Windows build has no streams until we borrow the caller's.
    from rps.console import attach_console

    attach_console()

    parser = argparse.ArgumentParser(
        prog="resolve-project-search",
        description=f"{APP_NAME} {__version__} — поиск клипа по файлам проектов .drp.",
    )
    parser.add_argument("folder", type=Path, help="папка с файлами .drp")
    parser.add_argument("query", help="имя файла или его часть")
    parser.add_argument("--no-recursive", action="store_true", help="не заходить в подпапки")
    parser.add_argument("--case-sensitive", action="store_true", help="учитывать регистр")
    parser.add_argument("--ext", default=".drp", help="расширения через запятую (по умолчанию .drp)")
    parser.add_argument("--max-hits", type=int, default=20, help="максимум совпадений на файл")
    parser.add_argument("--workers", type=int, default=0, help="число потоков (0 — авто)")
    parser.add_argument("--csv", type=Path, help="записать результаты в CSV")
    parser.add_argument("--verbose", action="store_true", help="показывать найденные строки")
    parsed = parser.parse_args(args)

    return _run_cli(parsed)


def _run_cli(parsed: argparse.Namespace) -> int:
    from rps.core.export import write_csv
    from rps.core.matcher import Query
    from rps.core.models import FileResult
    from rps.core.scanner import CANCELLED_ERROR, ScanOptions, scan

    if not parsed.folder.is_dir():
        print(f"Папка не найдена: {parsed.folder}", file=sys.stderr)
        return 2

    options = ScanOptions(
        root=parsed.folder,
        query=Query(text=parsed.query, case_sensitive=parsed.case_sensitive),
        recursive=not parsed.no_recursive,
        extensions=parsed.ext.split(","),
        max_hits_per_file=parsed.max_hits,
        workers=parsed.workers,
    )

    collected: list[FileResult] = []

    def on_result(result: FileResult) -> None:
        if result.error == CANCELLED_ERROR:
            return
        if not result.matched and not result.error:
            return
        collected.append(result)
        if result.error:
            print(f"!  {result.path}  —  {result.error}")
            return
        print(f"{len(result.hits):>3}  {result.path}")
        if parsed.verbose:
            for hit in result.hits:
                where = hit.stream or "файл"
                print(f"       [{where} · {hit.encoding}] {hit.text}")

    summary = scan(options, on_result=on_result)

    tail = ""
    if summary.unfinished_files:
        tail = f" Не досмотрено: {summary.unfinished_files}."
    print(
        f"\nПросмотрено {summary.scanned_files} из {summary.total_files} файлов "
        f"за {summary.duration_s:.1f} с. "
        f"Совпадения: {summary.matched_files}. Ошибок чтения: {summary.failed_files}.{tail}"
    )

    if parsed.csv is not None:
        rows = write_csv(parsed.csv, collected)
        print(f"CSV: {parsed.csv} ({rows} строк)")

    return 0 if summary.matched_files else 1


if __name__ == "__main__":
    raise SystemExit(main())
