# PyInstaller spec. Run from the repository root on Windows:
#
#     pyinstaller build\resolve-project-search.spec
#
# Produces dist\ResolveProjectSearch.exe — one file, no Python required on the
# target machine.

import sys
from pathlib import Path

# PyInstaller runs this file with exec(), so __file__ is not reliable here.
ROOT = Path(SPECPATH).parent  # noqa: F821 — injected by PyInstaller

block_cipher = None

a = Analysis(  # noqa: F821
    [str(ROOT / "src" / "rps" / "__main__.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=[],
    hiddenimports=["rps.app", "rps.ui.main_window"],
    hookspath=[],
    runtime_hooks=[],
    # Qt ships far more than a search window needs. Dropping these keeps the
    # executable around a third smaller with no loss of function.
    excludes=[
        "PySide6.QtNetwork",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuick3D",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets",
        "PySide6.Qt3DCore",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtOpenGL",
        "PySide6.QtPdf",
        "PySide6.QtSql",
        "PySide6.QtTest",
        "PySide6.QtDesigner",
        "tkinter",
        "unittest",
        "pydoc",
    ],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="ResolveProjectSearch",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    icon=str(ROOT / "build" / "icon.ico") if (ROOT / "build" / "icon.ico").exists() else None,
    version=None,
)
