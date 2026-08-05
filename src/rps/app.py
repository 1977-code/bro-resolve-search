"""Application bootstrap."""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from rps import APP_NAME, __version__

__all__ = ["run"]


def run(argv: list[str] | None = None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setOrganizationName(APP_NAME)
    # Qt 6 handles per-monitor DPI itself; this only affects icon crispness on
    # fractional-scaled Windows displays, which is the target platform.
    app.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)

    from rps.ui.main_window import MainWindow

    window = MainWindow()
    window.show()
    return app.exec()
