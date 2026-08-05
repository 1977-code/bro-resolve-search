"""The window Ваня runs.

One button. It has to be usable by someone who has never opened a terminal, on a
machine we cannot see, with no way to ask a follow-up question — so the window
says what it will do before it does it, shows every step while it runs, and ends
by putting two files on the Desktop and opening the folder.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from rps import __version__
from rps.doctor.model import Report
from rps.doctor.probe import ScanLimits, collect
from rps.doctor.report import PRIVACY_NOTE, render_json, render_markdown, summary_line
from rps.ui.style import STYLESHEET

__all__ = ["DoctorWindow", "run"]

INTRO = (
    "Программа соберёт сведения о DaVinci Resolve на этом компьютере: версия, "
    "доступность скриптового API, где лежат базы проектов, сколько в них "
    "проектов, есть ли на дисках файлы .drp и что они собой представляют.\n\n"
    "Ничего не изменяется и не удаляется — только чтение. Проекты не "
    "открываются и не загружаются.\n\n"
    "Лучше запускать с открытым DaVinci Resolve: тогда получится проверить "
    "живой API, а не только файлы на диске."
)


class _DoctorWorker(QThread):
    stepped = Signal(str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, limits: ScanLimits, parent=None) -> None:
        super().__init__(parent)
        self._limits = limits

    def run(self) -> None:
        try:
            report = collect(self._limits, progress=self.stepped.emit)
        except Exception as exc:  # noqa: BLE001 — must reach the window, not stderr
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.done.emit(report)


class DoctorWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._worker: _DoctorWorker | None = None
        self._report: Report | None = None
        self._written: list[Path] = []

        self.setWindowTitle(f"Resolve Doctor {__version__}")
        self.setStyleSheet(STYLESHEET)
        self.resize(760, 620)
        self.setMinimumSize(620, 520)
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(12)

        title = QLabel("Диагностика DaVinci Resolve")
        title.setStyleSheet("font-size: 19px; font-weight: 600;")
        root.addWidget(title)

        intro = QLabel(INTRO)
        intro.setProperty("role", "hint")
        intro.setWordWrap(True)
        root.addWidget(intro)

        self.search_box = QCheckBox("Искать файлы .drp на всех дисках (до 2 минут)")
        self.search_box.setChecked(True)
        root.addWidget(self.search_box)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.run_button = QPushButton("Собрать отчёт")
        self.run_button.setProperty("role", "primary")
        self.run_button.setMinimumWidth(160)
        self.run_button.clicked.connect(self._start)
        self.open_button = QPushButton("Открыть папку с отчётом")
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self._open_folder)
        self.save_button = QPushButton("Сохранить копию…")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self._save_copy)
        buttons.addWidget(self.run_button)
        buttons.addWidget(self.open_button)
        buttons.addStretch(1)
        buttons.addWidget(self.save_button)
        root.addLayout(buttons)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 0)
        self.progress.hide()
        root.addWidget(self.progress)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Здесь появится ход проверки.")
        root.addWidget(self.log, 1)

        self.status = QLabel(PRIVACY_NOTE)
        self.status.setProperty("role", "hint")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

    # ------------------------------------------------------------------ run

    def _start(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self.log.clear()
        self._append("Начинаю. Это займёт от нескольких секунд до пары минут.")
        self.run_button.setEnabled(False)
        self.search_box.setEnabled(False)
        self.progress.show()

        limits = ScanLimits(search_drp=self.search_box.isChecked())
        worker = _DoctorWorker(limits, self)
        worker.stepped.connect(self._append)
        worker.done.connect(self._finish)
        worker.failed.connect(self._fail)
        self._worker = worker
        worker.start()

    def _append(self, message: str) -> None:
        self.log.appendPlainText(message)

    def _finish(self, report: Report) -> None:
        self._worker = None
        self._report = report
        self.progress.hide()
        self.run_button.setEnabled(True)
        self.search_box.setEnabled(True)

        try:
            self._written = _write_reports(report)
        except OSError as exc:
            self._append(f"Не удалось сохранить отчёт: {exc}")
            self.status.setText("Отчёт собран, но не сохранился. Нажми «Сохранить копию…».")
            self.save_button.setEnabled(True)
            return

        self._append("")
        self._append(summary_line(report))
        for path in self._written:
            self._append(f"Сохранено: {path}")
        self._append("")
        self._append("Пришли оба файла — .md и .json.")
        self.open_button.setEnabled(True)
        self.save_button.setEnabled(True)
        self.status.setText(PRIVACY_NOTE)
        self._open_folder()

    def _fail(self, message: str) -> None:
        self._worker = None
        self.progress.hide()
        self.run_button.setEnabled(True)
        self.search_box.setEnabled(True)
        self._append(f"Диагностика прервалась: {message}")
        self.status.setText("Пришли текст из окна — по нему чинится сама диагностика.")

    # -------------------------------------------------------------- outputs

    def _open_folder(self) -> None:
        if not self._written:
            return
        target = self._written[0]
        if sys.platform.startswith("win"):
            subprocess.Popen(["explorer", f"/select,{target}"])
            return
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(target)])
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target.parent)))

    def _save_copy(self) -> None:
        if self._report is None:
            return
        suggested = str(_reports_dir() / f"{_stem(self._report)}.md")
        target, _ = QFileDialog.getSaveFileName(self, "Сохранить отчёт", suggested, "Markdown (*.md)")
        if not target:
            return
        path = Path(target)
        try:
            path.write_text(render_markdown(self._report), encoding="utf-8")
            path.with_suffix(".json").write_text(render_json(self._report), encoding="utf-8")
        except OSError as exc:
            self._append(f"Не удалось сохранить: {exc}")
            return
        self._written = [path, path.with_suffix(".json")]
        self._append(f"Сохранено: {path}")

    def closeEvent(self, event) -> None:
        if self._worker is not None:
            self._worker.wait(2000)
        super().closeEvent(event)


def _reports_dir() -> Path:
    """Desktop when there is one, home otherwise.

    ``QStandardPaths`` is used rather than ``~/Desktop`` because a Windows
    profile redirected into OneDrive has no ``~/Desktop``, and a report written
    to a path the user cannot find is a report that never arrives.
    """

    desktop = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
    if desktop and Path(desktop).is_dir():
        return Path(desktop)
    return Path.home()


def _stem(report: Report) -> str:
    stamp = report.generated_at.replace(":", "-").replace("+", "_")
    return f"resolve_doctor_{stamp[:19]}"


def _write_reports(report: Report) -> list[Path]:
    folder = _reports_dir()
    stem = _stem(report)
    markdown = folder / f"{stem}.md"
    payload = folder / f"{stem}.json"
    markdown.write_text(render_markdown(report), encoding="utf-8")
    payload.write_text(render_json(report), encoding="utf-8")
    return [markdown, payload]


def run(argv: list[str] | None = None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("Resolve Doctor")
    app.setApplicationVersion(__version__)
    app.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    window = DoctorWindow()
    window.show()
    return app.exec()
