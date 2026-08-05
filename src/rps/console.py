"""Making console output work in a windowed Windows build.

Two separate problems, both fatal, both invisible until the program runs on
Windows:

1. **No streams at all.** A PyInstaller executable built with ``console=False``
   has ``sys.stdout is None``, and the first ``print()`` raises. Fine while the
   program only ever shows a window — but both tools also accept command line
   arguments, and a user running them from ``cmd`` would get a silent process.
   ``AttachConsole(ATTACH_PARENT_PROCESS)`` borrows the caller's console; with
   no console to borrow, the streams go to the null device so printing degrades
   to doing nothing instead of crashing.

2. **Streams that cannot spell.** When Windows *does* hand over usable streams,
   Python wraps them in the ANSI code page — cp1252 on an English install,
   cp866 in a Russian console. Every user-facing string in this project is in
   Russian, so the first line of output dies with ``UnicodeEncodeError`` and
   takes the whole run with it. The console code page is therefore switched to
   UTF-8 and the streams are reconfigured to match.

``errors="replace"`` is the backstop: if the reconfigure fails on some exotic
setup, output turns into question marks rather than an exception. Mangled text
is a nuisance; a crash while printing the answer is a lost run.
"""

from __future__ import annotations

import io
import os
import sys

__all__ = ["attach_console"]

_ATTACH_PARENT_PROCESS = -1
_CP_UTF8 = 65001


def attach_console() -> bool:
    """Give this process usable, UTF-8 capable stdout/stderr.

    Returns True when a real Windows console was attached.
    """

    needs_attach = sys.stdout is None or sys.stderr is None
    attached = False

    if os.name == "nt":
        if needs_attach:
            attached = _attach_windows_console()
        _use_utf8_code_page()

    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            setattr(sys, name, _open_fallback(attached))
        else:
            _force_utf8(stream)

    if getattr(sys, "stdin", None) is None:
        try:
            sys.stdin = open(os.devnull, encoding="utf-8")
        except OSError:
            pass
    return attached


def _force_utf8(stream: object) -> None:
    """Make a text stream able to write Cyrillic without raising.

    ``reconfigure`` exists on ``io.TextIOWrapper`` from Python 3.7. Anything
    else — a pytest capture object, a custom wrapper — is left alone, because
    those already handle Unicode and are not ours to mutate.
    """

    reconfigure = getattr(stream, "reconfigure", None)
    if not callable(reconfigure):
        return
    encoding = (getattr(stream, "encoding", "") or "").lower().replace("-", "_")
    if encoding in ("utf_8", "utf8") and getattr(stream, "errors", "") == "replace":
        return
    try:
        reconfigure(encoding="utf-8", errors="replace")
    except (ValueError, OSError, io.UnsupportedOperation):
        # Not reconfigurable. Leaving it alone is still better than failing
        # here, and callers only ever lose the non-ASCII characters.
        return


def _open_fallback(attached: bool):
    target = "CONOUT$" if attached else os.devnull
    try:
        return open(target, "w", encoding="utf-8", errors="replace")
    except OSError:
        return open(os.devnull, "w", encoding="utf-8", errors="replace")


def _attach_windows_console() -> bool:
    kernel32 = _kernel32()
    if kernel32 is None:
        return False
    try:
        return bool(kernel32.AttachConsole(_ATTACH_PARENT_PROCESS))
    except (AttributeError, OSError):
        return False


def _use_utf8_code_page() -> None:
    kernel32 = _kernel32()
    if kernel32 is None:
        return
    for setter in ("SetConsoleOutputCP", "SetConsoleCP"):
        try:
            getattr(kernel32, setter)(_CP_UTF8)
        except (AttributeError, OSError):
            continue


def _kernel32():
    try:
        import ctypes  # noqa: PLC0415 — only meaningful on Windows
    except ImportError:
        return None
    try:
        return ctypes.windll.kernel32
    except (AttributeError, OSError):
        return None
