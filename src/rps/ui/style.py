"""Visual theme.

Dark neutral surfaces with a single amber accent, so the app sits next to
Resolve without pretending to be it. Only one element on screen is amber at a
time — the primary action — which is what makes it read as an accent rather than
as decoration.
"""

from __future__ import annotations

BACKGROUND = "#17181c"
SURFACE = "#1f2126"
SURFACE_RAISED = "#262930"
BORDER = "#33373f"
TEXT = "#e6e8ec"
TEXT_MUTED = "#9aa0ab"
ACCENT = "#f2921d"
ACCENT_HOVER = "#ffa634"
ACCENT_PRESSED = "#d97f12"
DANGER = "#e5544b"
OK = "#5bbd6a"

STYLESHEET = f"""
QWidget {{
    background: {BACKGROUND};
    color: {TEXT};
    font-size: 13px;
}}

QLabel[role="section"] {{
    color: {TEXT_MUTED};
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    padding-bottom: 2px;
}}

QLabel[role="hint"] {{
    color: {TEXT_MUTED};
}}

QLineEdit {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 8px 10px;
    selection-background-color: {ACCENT};
    selection-color: #1b1b1b;
}}
QLineEdit:focus {{
    border-color: {ACCENT};
}}
QLineEdit:disabled {{
    color: {TEXT_MUTED};
}}

QPushButton {{
    background: {SURFACE_RAISED};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 8px 16px;
    color: {TEXT};
}}
QPushButton:hover {{
    background: #2e323a;
}}
QPushButton:pressed {{
    background: #22252b;
}}
QPushButton:disabled {{
    color: {TEXT_MUTED};
    background: {SURFACE};
}}

QPushButton[role="primary"] {{
    background: {ACCENT};
    border: 1px solid {ACCENT};
    color: #17181c;
    font-weight: 600;
}}
QPushButton[role="primary"]:hover {{
    background: {ACCENT_HOVER};
    border-color: {ACCENT_HOVER};
}}
QPushButton[role="primary"]:pressed {{
    background: {ACCENT_PRESSED};
    border-color: {ACCENT_PRESSED};
}}
QPushButton[role="primary"]:disabled {{
    background: {SURFACE};
    border-color: {BORDER};
    color: {TEXT_MUTED};
}}

QCheckBox {{
    spacing: 8px;
    color: {TEXT_MUTED};
}}
QCheckBox::indicator {{
    width: 15px;
    height: 15px;
    border: 1px solid {BORDER};
    border-radius: 4px;
    background: {SURFACE};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}

QPlainTextEdit {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px;
    selection-background-color: {ACCENT};
    selection-color: #1b1b1b;
}}

QTreeWidget {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    alternate-background-color: #22242a;
    outline: none;
}}
QTreeWidget::item {{
    padding: 5px 4px;
    border: none;
}}
QTreeWidget::item:selected {{
    background: #33383f;
    color: {TEXT};
}}
QHeaderView::section {{
    background: {SURFACE_RAISED};
    color: {TEXT_MUTED};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 7px 8px;
    font-weight: 600;
}}

QProgressBar {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 5px;
    height: 8px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background: {ACCENT};
    border-radius: 4px;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 4px 2px;
}}
QScrollBar::handle:vertical {{
    background: #3a3f47;
    border-radius: 4px;
    min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{
    background: #4a505a;
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px 4px;
}}
QScrollBar::handle:horizontal {{
    background: #3a3f47;
    border-radius: 4px;
    min-width: 28px;
}}

QMenu {{
    background: {SURFACE_RAISED};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 22px 6px 12px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background: #363b43;
}}
QMenu::item:disabled {{
    color: {TEXT_MUTED};
}}

QToolTip {{
    background: {SURFACE_RAISED};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 6px 8px;
}}

QFrame[role="separator"] {{
    background: {BORDER};
    max-height: 1px;
    border: none;
}}
"""
