"""``rps-probe`` — describe real ``.drp`` files so the format can be parsed later.

Run this on a machine that has actual projects:

    rps-probe "J:\\Проекты" --out drp_report.md

It writes a Markdown report describing, for each file: its magic bytes, the
container the bytes say it is, how its text is encoded, which structural markers
are present, and a sample of the strings inside. That report is the input to the
version 2 parser.

**The report contains text taken from your projects**, including media file
paths and clip names. Use ``--redact`` to replace the sample strings with their
shapes (lengths and character classes) if the report is going somewhere the
paths should not.
"""

from __future__ import annotations

import argparse
import collections
import math
import re
import sys
import zipfile
from pathlib import Path

from rps.core.formats import detect_container, iter_streams
from rps.core.matcher import extract_runs
from rps.core.models import ContainerKind

__all__ = ["main"]

SAMPLE_BYTES = 4 << 20
"""How much of each file to read for the report. Enough to characterise the
format without dragging a 2 GB project through memory."""

MARKERS: tuple[str, ...] = (
    "Timeline",
    "MediaPool",
    "MediaPoolItem",
    "TimelineItem",
    "ClipProperty",
    "FilePath",
    "File Path",
    "ReelName",
    "Reel Name",
    "TapeName",
    "CameraRoll",
    "Camera Roll",
    "StartTC",
    "Start TC",
    "RecordFrame",
    "SourceFrame",
    "Marker",
    "TextPlus",
    "Text+",
    "Fusion",
    "ProjectSetting",
    "DaVinci",
    "BlackmagicDesign",
)

MEDIA_EXTENSIONS: tuple[str, ...] = (
    ".mp4", ".mov", ".mxf", ".braw", ".r3d", ".arri", ".ari",
    ".wav", ".aif", ".aiff", ".mp3", ".png", ".jpg", ".exr", ".dpx", ".tif",
)

_TIMECODE = re.compile(r"\b\d{2}:\d{2}:\d{2}[:;]\d{2}\b")
_WINDOWS_PATH = re.compile(r"\b[A-Za-z]:\\[^\s\"'<>|]{3,}")
_POSIX_PATH = re.compile(r"(?:/[^\s\"'<>|/]{1,}){2,}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rps-probe",
        description="Собрать отчёт о структуре файлов .drp.",
    )
    parser.add_argument("path", type=Path, help="файл .drp или папка с ними")
    parser.add_argument("--out", type=Path, help="куда записать отчёт (по умолчанию — в stdout)")
    parser.add_argument("--limit", type=int, default=10, help="сколько файлов разобрать")
    parser.add_argument("--samples", type=int, default=25, help="сколько строк-образцов на файл")
    parser.add_argument(
        "--redact",
        action="store_true",
        help="не включать содержимое строк, только их форму",
    )
    parsed = parser.parse_args(argv if argv is not None else sys.argv[1:])

    targets = _targets(parsed.path, parsed.limit)
    if not targets:
        print(f"Файлы .drp не найдены: {parsed.path}", file=sys.stderr)
        return 2

    report = _report(targets, parsed.samples, parsed.redact)
    if parsed.out is None:
        print(report)
    else:
        parsed.out.write_text(report, encoding="utf-8")
        print(f"Отчёт записан: {parsed.out} ({len(targets)} файлов)")
    return 0


def _targets(path: Path, limit: int) -> list[Path]:
    if path.is_file():
        return [path]
    if not path.is_dir():
        return []
    found = sorted(p for p in path.rglob("*") if p.is_file() and p.suffix.lower() == ".drp")
    return found[:limit]


def _report(targets: list[Path], samples: int, redact: bool) -> str:
    lines = [
        "# Отчёт о формате .drp",
        "",
        f"Файлов разобрано: {len(targets)}",
        "",
        "Отчёт описывает, чем на самом деле являются файлы проектов на этой машине.",
        "Ничего не изменяется — файлы открываются только на чтение.",
        "",
    ]
    for target in targets:
        lines.extend(_describe(target, samples, redact))
        lines.append("")
    return "\n".join(lines)


def _describe(path: Path, samples: int, redact: bool) -> list[str]:
    out = [f"## {path.name}", ""]
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            head = handle.read(512)
    except OSError as exc:
        return out + [f"Не удалось прочитать: {exc}", ""]

    kind = detect_container(head)
    out += [
        f"- Путь: `{path}`",
        f"- Размер: {size} байт ({size / 1048576:.1f} МБ)",
        f"- Первые 16 байт: `{head[:16].hex(' ')}`",
        f"- Печатное начало: `{_printable(head[:32])}`",
        f"- Определён как: **{kind.value}** ({kind.label})",
    ]

    if kind is ContainerKind.ZIP:
        out += _describe_zip(path)

    counts: collections.Counter[str] = collections.Counter()
    marker_hits: collections.Counter[str] = collections.Counter()
    extension_hits: collections.Counter[str] = collections.Counter()
    timecodes = 0
    win_paths = 0
    posix_paths = 0
    collected: list[tuple[str, str]] = []
    total_bytes = 0
    entropy_source = b""

    for stream_name, chunks in iter_streams(path):
        for chunk in chunks:
            if total_bytes >= SAMPLE_BYTES:
                break
            total_bytes += len(chunk)
            if not entropy_source:
                entropy_source = chunk[:65536]
            for codec in ("utf-8", "utf-16-le"):
                for _index, run in extract_runs(chunk, codec, 4):
                    # Counting only readable runs is what makes the number an
                    # answer to "which encoding is this file in" rather than a
                    # count of decoding artefacts.
                    if _readable_ratio(run) < 0.6:
                        continue
                    counts[codec] += 1
                    lowered = run.lower()
                    for marker in MARKERS:
                        if marker.lower() in lowered:
                            marker_hits[marker] += 1
                    for ext in MEDIA_EXTENSIONS:
                        if ext in lowered:
                            extension_hits[ext] += 1
                    timecodes += len(_TIMECODE.findall(run))
                    win_paths += len(_WINDOWS_PATH.findall(run))
                    posix_paths += len(_POSIX_PATH.findall(run))
                    if len(collected) < samples * 4 and len(run) >= 8:
                        collected.append((f"{stream_name or 'файл'} · {codec}", run))
        if total_bytes >= SAMPLE_BYTES:
            break

    out += [
        f"- Прочитано для анализа: {total_bytes} байт",
        f"- Энтропия первых 64 КБ: {_entropy(entropy_source):.2f} бит/байт "
        f"({'похоже на сжатые данные' if _entropy(entropy_source) > 7.5 else 'есть читаемая структура'})",
        f"- Читаемых строк: utf-8 — {counts['utf-8']}, utf-16-le — {counts['utf-16-le']} "
        f"(перевес показывает, в какой кодировке файл на самом деле)",
        f"- Таймкодов вида 00:00:00:00: {timecodes}",
        f"- Путей Windows (`C:\\…`): {win_paths}; путей POSIX (`/…`): {posix_paths}",
        "",
        "### Структурные маркеры",
        "",
    ]
    if marker_hits:
        for marker, count in marker_hits.most_common():
            out.append(f"- `{marker}` — {count}")
    else:
        out.append("- ни один известный маркер не встретился (формат непрозрачный)")

    out += ["", "### Расширения медиафайлов", ""]
    if extension_hits:
        out += [f"- `{ext}` — {count}" for ext, count in extension_hits.most_common()]
    else:
        out.append("- имена медиафайлов в открытом виде не найдены")

    out += ["", "### Образцы строк", ""]
    if not collected:
        out.append("_Читаемых строк не найдено._")
    else:
        interesting = _rank(collected)[:samples]
        out.append("```")
        for origin, run in interesting:
            text = _shape(run) if redact else run[:200]
            out.append(f"[{origin}] {text}")
        out.append("```")
    return out


def _describe_zip(path: Path) -> list[str]:
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
    except (zipfile.BadZipFile, OSError) as exc:
        return [f"- ZIP не открылся: {exc}"]
    out = [f"- Элементов внутри: {len(infos)}", "", "| Элемент | Сжат | Распакован |", "| --- | --- | --- |"]
    for info in infos[:40]:
        out.append(f"| `{info.filename}` | {info.compress_size} | {info.file_size} |")
    if len(infos) > 40:
        out.append(f"| … ещё {len(infos) - 40} | | |")
    return out


def _rank(collected: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Put the structurally interesting strings first.

    A report full of GUIDs teaches nothing; one containing paths, timecodes and
    key names is what a parser gets written from.
    """

    def score(item: tuple[str, str]) -> tuple[int, int]:
        _origin, run = item
        points = 0
        # Decoding UTF-8 bytes as UTF-16 yields long runs of plausible-looking
        # CJK. Those are artefacts of the probe, not content of the file, and a
        # report full of them teaches nothing.
        if _readable_ratio(run) < 0.6:
            points -= 10
        if _WINDOWS_PATH.search(run) or _POSIX_PATH.search(run):
            points += 4
        if _TIMECODE.search(run):
            points += 3
        lowered = run.lower()
        if any(ext in lowered for ext in MEDIA_EXTENSIONS):
            points += 3
        if any(marker.lower() in lowered for marker in MARKERS):
            points += 2
        if "=" in run or ":" in run:
            points += 1
        return (-points, -len(run))

    return sorted(collected, key=score)


def _readable_ratio(run: str) -> float:
    """Share of characters that a Latin/Cyrillic project file would contain."""

    if not run:
        return 0.0
    readable = sum(1 for c in run if c.isascii() or "Ѐ" <= c <= "ӿ")
    return readable / len(run)


def _entropy(data: bytes) -> float:
    if not data:
        return 0.0
    counts = collections.Counter(data)
    total = len(data)
    return -sum((c / total) * math.log2(c / total) for c in counts.values())


def _printable(data: bytes) -> str:
    return "".join(chr(b) if 32 <= b < 127 else "." for b in data)


def _shape(run: str) -> str:
    """Describe a string without disclosing it."""

    kinds = {
        "a": sum(c.isalpha() and c.isascii() for c in run),
        "я": sum(c.isalpha() and not c.isascii() for c in run),
        "9": sum(c.isdigit() for c in run),
    }
    described = ", ".join(f"{k}×{v}" for k, v in kinds.items() if v)
    return f"<len={len(run)} {described}>"


if __name__ == "__main__":
    raise SystemExit(main())
