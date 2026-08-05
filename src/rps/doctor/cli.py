"""``resolve-doctor`` — window with no arguments, console run with them."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rps import __version__

__all__ = ["main"]


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        from rps.doctor.ui import run

        return run()

    from rps.console import attach_console

    attach_console()

    parser = argparse.ArgumentParser(
        prog="resolve-doctor",
        description=f"Resolve Doctor {__version__} — собрать сведения о DaVinci Resolve на этой машине.",
    )
    parser.add_argument("--out", type=Path, help="куда положить отчёт (по умолчанию — рядом, в текущей папке)")
    parser.add_argument("--no-drp-search", action="store_true", help="не искать файлы .drp на дисках")
    parser.add_argument("--home-only", action="store_true", help="искать .drp только в профиле пользователя")
    parser.add_argument("--seconds", type=float, default=120.0, help="предел времени на поиск .drp")
    parser.add_argument("--quiet", action="store_true", help="без построчного вывода хода работы")
    parsed = parser.parse_args(args)

    from rps.doctor.probe import ScanLimits, collect
    from rps.doctor.report import render_json, render_markdown, summary_line

    limits = ScanLimits(
        search_drp=not parsed.no_drp_search,
        all_drives=not parsed.home_only,
        seconds=parsed.seconds,
    )
    report = collect(limits, progress=None if parsed.quiet else _echo)

    stem = parsed.out or Path.cwd() / f"resolve_doctor_{report.generated_at[:19].replace(':', '-')}"
    markdown = stem.with_suffix(".md")
    payload = stem.with_suffix(".json")
    markdown.write_text(render_markdown(report), encoding="utf-8")
    payload.write_text(render_json(report), encoding="utf-8")

    print()
    print(summary_line(report))
    print(f"Отчёт: {markdown}")
    print(f"Машинная версия: {payload}")
    return 0


def _echo(message: str) -> None:
    print(message, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
