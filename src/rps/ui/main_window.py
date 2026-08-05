"""Main window.

One screen, one question: which project file contains this clip. Everything that
is not an answer to that question stays out of the way — options are checkboxes
on one row, and the results tree is the only element that grows.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QUrl
from PySide6.QtGui import QAction, QCloseEvent, QColor, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rps import APP_NAME, __version__
from rps.config import Settings, load_settings, save_settings
from rps.core.drp import project_display_name
from rps.core.export import write_csv
from rps.core.matcher import Query
from rps.core.models import FileResult, ScanSummary
from rps.core.scanner import ScanOptions
from rps.ui.style import DANGER, OK, STYLESHEET, TEXT_MUTED
from rps.ui.worker import ScanWorker

__all__ = ["MainWindow"]

COLUMNS = ("Проект", "Совпадений", "Размер", "Расположение")

_RESULT_ROLE = Qt.ItemDataRole.UserRole
_SORT_ROLE = Qt.ItemDataRole.UserRole + 1


class _ResultItem(QTreeWidgetItem):
    """Tree row that sorts on a stored key instead of on its display text.

    Without this, "Совпадений" sorts as text and 10 lands before 2, and "Размер"
    sorts by the formatted string rather than by bytes.
    """

    def __lt__(self, other: QTreeWidgetItem) -> bool:
        tree = self.treeWidget()
        column = tree.sortColumn() if tree is not None else 0
        if self.parent() is not None:
            # Hits inside a file keep the order they were found in, whatever
            # column the top level is sorted by.
            column = 0
        mine = self.data(column, _SORT_ROLE)
        theirs = other.data(column, _SORT_ROLE)
        if mine is None or theirs is None:
            return super().__lt__(other)
        return mine < theirs


class MainWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._settings: Settings = load_settings()
        self._worker: ScanWorker | None = None
        self._results: list[FileResult] = []

        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.setStyleSheet(STYLESHEET)
        self.resize(self._settings.window_width, self._settings.window_height)
        self.setMinimumSize(720, 480)

        self._build()
        self._restore()
        self._update_controls()

    # ------------------------------------------------------------------ build

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(10)

        root.addWidget(_section("Папка с DRP"))
        folder_row = QHBoxLayout()
        folder_row.setSpacing(8)
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText(r"Например: J:\Проекты")
        self.folder_edit.setClearButtonEnabled(True)
        self.folder_edit.textChanged.connect(self._update_controls)
        self.browse_button = QPushButton("Обзор…")
        self.browse_button.clicked.connect(self._choose_folder)
        folder_row.addWidget(self.folder_edit, 1)
        folder_row.addWidget(self.browse_button)
        root.addLayout(folder_row)

        root.addSpacing(4)
        root.addWidget(_section("Имя файла"))
        self.query_edit = QLineEdit()
        self.query_edit.setPlaceholderText("C6343.MP4 — или часть имени")
        self.query_edit.setClearButtonEnabled(True)
        self.query_edit.textChanged.connect(self._update_controls)
        self.query_edit.returnPressed.connect(self._start_or_stop)
        root.addWidget(self.query_edit)

        options_row = QHBoxLayout()
        options_row.setSpacing(16)
        self.recursive_box = QCheckBox("Включая подпапки")
        self.case_box = QCheckBox("Учитывать регистр")
        options_row.addWidget(self.recursive_box)
        options_row.addWidget(self.case_box)
        options_row.addStretch(1)
        root.addLayout(options_row)

        root.addSpacing(4)
        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        self.search_button = QPushButton("Найти")
        self.search_button.setProperty("role", "primary")
        self.search_button.setMinimumWidth(120)
        self.search_button.clicked.connect(self._start_scan)
        self.stop_button = QPushButton("Стоп")
        self.stop_button.clicked.connect(self._stop_scan)
        self.export_button = QPushButton("Экспорт CSV")
        self.export_button.clicked.connect(self._export_csv)
        action_row.addWidget(self.search_button)
        action_row.addWidget(self.stop_button)
        action_row.addStretch(1)
        action_row.addWidget(self.export_button)
        root.addLayout(action_row)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        # Only on screen while something is actually running. A permanently full
        # bar reads as an alert, not as progress.
        self.progress.hide()
        root.addWidget(self.progress)

        separator = QFrame()
        separator.setProperty("role", "separator")
        separator.setFrameShape(QFrame.Shape.HLine)
        root.addWidget(separator)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(len(COLUMNS))
        self.tree.setHeaderLabels(list(COLUMNS))
        self.tree.setAlternatingRowColors(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionBehavior(QTreeWidget.SelectionBehavior.SelectRows)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_menu)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSortIndicator(1, Qt.SortOrder.DescendingOrder)
        self.tree.setColumnWidth(0, 380)
        root.addWidget(self.tree, 1)

        self.status = QLabel("Укажите папку и имя файла.")
        self.status.setProperty("role", "hint")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        QShortcut(QKeySequence.StandardKey.Find, self, self.query_edit.setFocus)
        QShortcut(QKeySequence("Esc"), self, self._stop_scan)

    def _restore(self) -> None:
        self.folder_edit.setText(self._settings.last_folder)
        self.query_edit.setText(self._settings.last_query)
        self.recursive_box.setChecked(self._settings.recursive)
        self.case_box.setChecked(self._settings.case_sensitive)

    # --------------------------------------------------------------- scanning

    @property
    def _scanning(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def _update_controls(self) -> None:
        ready = bool(self.folder_edit.text().strip()) and bool(self.query_edit.text().strip())
        self.search_button.setEnabled(ready and not self._scanning)
        self.stop_button.setEnabled(self._scanning)
        self.browse_button.setEnabled(not self._scanning)
        self.folder_edit.setEnabled(not self._scanning)
        self.query_edit.setEnabled(not self._scanning)
        self.recursive_box.setEnabled(not self._scanning)
        self.case_box.setEnabled(not self._scanning)
        self.export_button.setEnabled(bool(self._results) and not self._scanning)

    def _start_or_stop(self) -> None:
        if self._scanning:
            return
        if self.search_button.isEnabled():
            self._start_scan()

    def _start_scan(self) -> None:
        if self._scanning:
            return
        folder = Path(self.folder_edit.text().strip()).expanduser()
        if not folder.is_dir():
            self._warn("Папка не найдена", f"Не удалось открыть папку:\n{folder}")
            return
        text = self.query_edit.text().strip()
        if not text:
            return

        self.tree.clear()
        self._results.clear()
        # Sorting is off while rows stream in; re-sorting on every insert would
        # cost more than the search itself.
        self.tree.setSortingEnabled(False)
        self.progress.setRange(0, 0)  # indeterminate until discovery finishes
        self.progress.show()
        self.status.setText("Ищу файлы .drp…")

        options = ScanOptions(
            root=folder,
            query=Query(text=text, case_sensitive=self.case_box.isChecked()),
            recursive=self.recursive_box.isChecked(),
            extensions=[e for e in self._settings.extensions.split(",") if e.strip()],
            max_hits_per_file=self._settings.max_hits_per_file,
            workers=self._settings.workers,
        )

        worker = ScanWorker(options, self)
        worker.discovered.connect(self._on_discovered)
        worker.progressed.connect(self._on_progress)
        worker.matched.connect(self._on_result)
        worker.finishedScan.connect(self._on_finished)
        worker.failed.connect(self._on_failed)
        self._worker = worker
        worker.start()
        self._update_controls()

    def _stop_scan(self) -> None:
        if not self._scanning:
            return
        self._worker.cancel()  # type: ignore[union-attr]
        self.status.setText("Останавливаю…")
        self.stop_button.setEnabled(False)

    def _on_discovered(self, total: int) -> None:
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(0)
        if total == 0:
            self.status.setText("В этой папке нет файлов .drp.")
        else:
            self.status.setText(f"Найдено {total} файлов .drp. Сканирую…")

    def _on_progress(self, done: int, total: int) -> None:
        if total:
            self.progress.setValue(done)
            self.status.setText(
                f"Просмотрено {done} из {total} · совпадений: {len(self._results)}"
            )

    def _on_result(self, result: FileResult) -> None:
        self._results.append(result)
        self.tree.addTopLevelItem(_build_item(result))

    def _on_finished(self, summary: ScanSummary) -> None:
        self._worker = None
        self.progress.hide()
        self.status.setText(_summarise(summary, len(self._results)))
        # Most matches first, and header clicks now re-sort.
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(1, Qt.SortOrder.DescendingOrder)
        self._update_controls()
        if self.tree.topLevelItemCount() == 1:
            self.tree.topLevelItem(0).setExpanded(True)

    def _on_failed(self, message: str) -> None:
        self._worker = None
        self.progress.hide()
        self.status.setText(f"Сканирование прервано: {message}")
        self._update_controls()

    # ---------------------------------------------------------------- actions

    def _choose_folder(self) -> None:
        start = self.folder_edit.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "Папка с проектами .drp", start)
        if chosen:
            self.folder_edit.setText(chosen)

    def _export_csv(self) -> None:
        if not self._results:
            return
        suggested = str(Path.home() / "resolve_search.csv")
        target, _ = QFileDialog.getSaveFileName(
            self, "Сохранить результаты", suggested, "CSV (*.csv)"
        )
        if not target:
            return
        path = Path(target)
        try:
            rows = write_csv(path, self._results)
        except OSError as exc:
            self._warn("Не удалось сохранить", str(exc))
            return
        self.status.setText(f"Сохранено {rows} строк: {path}")

    def _selected_result(self) -> FileResult | None:
        item = self.tree.currentItem()
        while item is not None and item.parent() is not None:
            item = item.parent()
        if item is None:
            return None
        data = item.data(0, _RESULT_ROLE)
        return data if isinstance(data, FileResult) else None

    def _on_double_click(self, item: QTreeWidgetItem, _column: int) -> None:
        self.tree.setCurrentItem(item)
        result = self._selected_result()
        if result is not None:
            _reveal(result.path)

    def _show_menu(self, position: QPoint) -> None:
        result = self._selected_result()
        if result is None:
            return
        menu = QMenu(self)

        reveal = QAction("Показать в папке", menu)
        reveal.triggered.connect(lambda: _reveal(result.path))
        menu.addAction(reveal)

        copy_path = QAction("Копировать путь", menu)
        copy_path.triggered.connect(
            lambda: QApplication.clipboard().setText(str(result.path))
        )
        menu.addAction(copy_path)

        copy_name = QAction("Копировать имя проекта", menu)
        copy_name.triggered.connect(
            lambda: QApplication.clipboard().setText(result.path.stem)
        )
        menu.addAction(copy_name)

        menu.addSeparator()
        import_action = QAction("Импортировать в Resolve", menu)
        import_action.setEnabled(False)
        import_action.setToolTip(
            "Появится, когда будет проверен доступ к скриптовому API Resolve. "
            "В версии 1.0 приложение только читает файлы и ничего не запускает."
        )
        menu.addAction(import_action)

        menu.exec(self.tree.viewport().mapToGlobal(position))

    def _warn(self, title: str, text: str) -> None:
        box = QMessageBox(QMessageBox.Icon.Warning, title, text, QMessageBox.StandardButton.Ok, self)
        box.setStyleSheet(STYLESHEET)
        box.exec()

    # ----------------------------------------------------------------- close

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self._worker.wait(3000)
        self._settings.last_folder = self.folder_edit.text().strip()
        self._settings.last_query = self.query_edit.text().strip()
        self._settings.recursive = self.recursive_box.isChecked()
        self._settings.case_sensitive = self.case_box.isChecked()
        self._settings.window_width = self.width()
        self._settings.window_height = self.height()
        save_settings(self._settings)
        super().closeEvent(event)


def _section(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "section")
    return label


def _human_size(size: int) -> str:
    value = float(size)
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if value < 1024 or unit == "ГБ":
            return f"{value:.0f} {unit}" if unit == "Б" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} ГБ"


def _build_item(result: FileResult) -> QTreeWidgetItem:
    if result.error:
        item = _ResultItem(
            [project_display_name(result.path), "—", _human_size(result.size), result.error]
        )
        item.setForeground(3, QColor(DANGER))
        item.setData(0, _RESULT_ROLE, result)
        # Errors sort below every match but above nothing else.
        item.setData(1, _SORT_ROLE, -1)
        item.setData(2, _SORT_ROLE, result.size)
        return item

    item = _ResultItem(
        [
            project_display_name(result.path),
            str(len(result.hits)),
            _human_size(result.size),
            str(result.path.parent),
        ]
    )
    item.setData(0, _RESULT_ROLE, result)
    item.setData(1, _SORT_ROLE, len(result.hits))
    item.setData(2, _SORT_ROLE, result.size)
    item.setForeground(1, QColor(OK))
    container = result.container.label if result.container else "неизвестно"
    item.setToolTip(0, f"{result.path}\nКонтейнер: {container}")

    for index, hit in enumerate(result.hits):
        where = hit.stream or "файл"
        child = _ResultItem(
            [hit.text, "", "", f"{where} · {hit.encoding} · ≈{hit.offset}"]
        )
        child.setData(0, _SORT_ROLE, index)
        child.setForeground(0, QColor(TEXT_MUTED))
        child.setForeground(3, QColor(TEXT_MUTED))
        child.setToolTip(0, hit.text)
        item.addChild(child)
    return item


def _summarise(summary: ScanSummary, shown: int) -> str:
    head = "Отменено." if summary.cancelled else "Готово."
    line = (
        f"{head} Просмотрено {summary.scanned_files} из {summary.total_files} файлов "
        f"за {summary.duration_s:.1f} с."
    )
    if summary.matched_files:
        line += f" Совпадения в {summary.matched_files}."
    elif not summary.cancelled:
        line += " Совпадений нет."
    if summary.foreign_files:
        line += f" Пропущено чужих файлов .drp: {summary.foreign_files}."
    if summary.failed_files:
        line += f" Не удалось прочитать: {summary.failed_files}."
    if summary.unfinished_files:
        line += f" Не досмотрено: {summary.unfinished_files}."
    if shown != summary.matched_files + summary.failed_files:
        line += f" Строк в списке: {shown}."
    return line


def _reveal(path: Path) -> None:
    """Open the containing folder, selecting the file where the OS allows it."""

    folder = path.parent
    if sys.platform.startswith("win"):
        subprocess.Popen(["explorer", f"/select,{path}"])
        return
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
        return
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
