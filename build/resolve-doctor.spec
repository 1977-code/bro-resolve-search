# PyInstaller spec for the diagnostic tool. Run from the repository root:
#
#     pyinstaller build\resolve-doctor.spec
#
# Produces dist\ResolveDoctor.exe — the program that collects facts about a real
# DaVinci Resolve installation.

from pathlib import Path

ROOT = Path(SPECPATH).parent  # noqa: F821 — injected by PyInstaller

block_cipher = None

a = Analysis(  # noqa: F821
    [str(ROOT / "src" / "rps" / "doctor" / "cli.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=[],
    hiddenimports=["rps.doctor.ui", "rps.doctor.probe", "rps.doctor.report"],
    hookspath=[],
    runtime_hooks=[],
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
    name="ResolveDoctor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    icon=str(ROOT / "build" / "icon.ico") if (ROOT / "build" / "icon.ico").exists() else None,
    version=None,
)
