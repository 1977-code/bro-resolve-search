"""Making console output work in a windowed Windows build.

A PyInstaller executable built with ``console=False`` has no standard streams:
``sys.stdout`` is ``None``, and the first ``print()`` raises. That is fine while
the program only ever shows a window — but both tools here also accept command
line arguments, and a power user running them from ``cmd`` or PowerShell (or CI
running a smoke test) would otherwise get a silent process and no output at all.

``AttachConsole(ATTACH_PARENT_PROCESS)`` borrows the console of whatever shell
launched us. When there is no such console — a double-click from Explorer — the
streams are pointed at the null device so that printing degrades to doing
nothing instead of crashing.
"""

from __future__ import annotations

import os
import sys

__all__ = ["attach_console"]

_ATTACH_PARENT_PROCESS = -1


def attach_console() -> bool:
    """Give this process usable stdout/stderr. Returns True if a real console
    was attached."""

    if sys.stdout is not None and sys.stderr is not None:
        return True

    attached = False
    if os.name == "nt":
        attached = _attach_windows_console()

    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is not None:
            continue
        try:
            stream = open("CONOUT$" if attached else os.devnull, "w", encoding="utf-8", errors="replace")
        except OSError:
            stream = open(os.devnull, "w", encoding="utf-8", errors="replace")
        setattr(sys, name, stream)

    if getattr(sys, "stdin", None) is None:
        try:
            sys.stdin = open(os.devnull, encoding="utf-8")
        except OSError:
            pass
    return attached


def _attach_windows_console() -> bool:
    try:
        import ctypes  # noqa: PLC0415 — only needed on Windows
    except ImportError:
        return False
    try:
        return bool(ctypes.windll.kernel32.AttachConsole(_ATTACH_PARENT_PROCESS))
    except (AttributeError, OSError):
        return False
