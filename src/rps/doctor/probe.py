"""Collectors. Each answers one question about this machine.

Everything is wrapped: a collector that fails records the failure and the run
continues. A diagnostic that dies halfway is worse than no diagnostic, because
it produces a report that looks complete.
"""

from __future__ import annotations

import collections
import importlib.util
import os
import platform
import shutil
import string
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from rps import __version__
from rps.core.formats import detect_container
from rps.core.matcher import extract_runs
from rps.doctor.model import Finding, Report, Section, Status

__all__ = ["collect", "ScanLimits"]

Progress = Callable[[str], None]


# --------------------------------------------------------------------- limits


class ScanLimits:
    """Bounds on the filesystem sweep, so the tool cannot run for an hour."""

    def __init__(
        self,
        search_drp: bool = True,
        all_drives: bool = True,
        seconds: float = 120.0,
        max_files: int = 4000,
        analyse: int = 6,
    ) -> None:
        self.search_drp = search_drp
        self.all_drives = all_drives
        self.seconds = seconds
        self.max_files = max_files
        self.analyse = analyse


# ------------------------------------------------------------------- helpers


def _safe(obj: Any, name: str, *args: Any) -> Any:
    """Call ``obj.name(*args)`` and return None on anything going wrong."""

    method = getattr(obj, name, None)
    if method is None or not callable(method):
        return None
    try:
        return method(*args)
    except Exception:  # noqa: BLE001 — a foreign API may raise anything
        return None


def _has(obj: Any, name: str) -> bool:
    return callable(getattr(obj, name, None))


def _run(command: list[str], timeout: float = 10.0) -> str:
    try:
        done = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout or ""


def _exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


# -------------------------------------------------------------------- system


def _collect_system(report: Report) -> None:
    section = report.section("Система")
    section.add(
        "os",
        "Операционная система",
        Status.INFO,
        f"{platform.system()} {platform.release()} ({platform.version()})",
        data={"system": platform.system(), "release": platform.release()},
    )
    section.add("arch", "Архитектура", Status.INFO, platform.machine())
    section.add(
        "runtime",
        "Как запущено",
        Status.INFO,
        "собранный .exe" if getattr(sys, "frozen", False) else f"Python {platform.python_version()}",
    )

    drives = []
    for root in _drive_roots():
        try:
            usage = shutil.disk_usage(root)
        except OSError:
            continue
        drives.append(
            {
                "root": str(root),
                "total_gb": round(usage.total / 1024**3, 1),
                "free_gb": round(usage.free / 1024**3, 1),
            }
        )
    section.add(
        "drives",
        "Диски",
        Status.INFO if drives else Status.UNKNOWN,
        ", ".join(f"{d['root']} ({d['free_gb']} ГБ свободно)" for d in drives) or "не определились",
        data=drives,
    )


def _drive_roots() -> list[Path]:
    if os.name != "nt":
        roots = [Path("/")]
        volumes = Path("/Volumes")
        if _exists(volumes):
            roots += [p for p in volumes.iterdir() if p.is_dir()]
        return roots
    return [Path(f"{letter}:\\") for letter in string.ascii_uppercase if _exists(Path(f"{letter}:\\"))]


# ------------------------------------------------------- Resolve installation

WINDOWS_APP_CANDIDATES = (
    r"C:\Program Files\Blackmagic Design\DaVinci Resolve",
    r"C:\Program Files (x86)\Blackmagic Design\DaVinci Resolve",
)

MAC_APP_CANDIDATES = (
    "/Applications/DaVinci Resolve/DaVinci Resolve.app",
    "/Applications/DaVinci Resolve.app",
)

SCRIPTING_CANDIDATES_WINDOWS = (
    r"%PROGRAMDATA%\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting",
    r"%PROGRAMFILES%\Blackmagic Design\DaVinci Resolve\Developer\Scripting",
)

SCRIPTING_CANDIDATES_MAC = (
    "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting",
)

SCRIPTING_CANDIDATES_LINUX = (
    "/opt/resolve/Developer/Scripting",
    "/home/resolve/Developer/Scripting",
)

LIBRARY_CANDIDATES_WINDOWS = (
    r"%PROGRAMFILES%\Blackmagic Design\DaVinci Resolve\fusionscript.dll",
)

LIBRARY_CANDIDATES_MAC = ("/Applications/DaVinci Resolve/fusionscript.so",)

LIBRARY_CANDIDATES_LINUX = ("/opt/resolve/libs/Fusion/fusionscript.so",)

ENV_VARS = ("RESOLVE_SCRIPT_API", "RESOLVE_SCRIPT_LIB", "PYTHONPATH")


def _expand(candidate: str) -> Path:
    return Path(os.path.expandvars(candidate))


def _collect_installation(report: Report) -> None:
    section = report.section("Установка DaVinci Resolve")

    if os.name == "nt":
        app_candidates = WINDOWS_APP_CANDIDATES
    elif sys.platform == "darwin":
        app_candidates = MAC_APP_CANDIDATES
    else:
        app_candidates = ("/opt/resolve",)

    found_apps = [str(_expand(c)) for c in app_candidates if _exists(_expand(c))]
    section.add(
        "app",
        "Папка приложения",
        Status.OK if found_apps else Status.MISSING,
        "; ".join(found_apps) or "ни один из известных путей не существует",
        data={"checked": [str(_expand(c)) for c in app_candidates], "found": found_apps},
    )

    section.add(
        "running",
        "Resolve запущен",
        *_resolve_process(),
    )

    for var in ENV_VARS:
        value = os.environ.get(var)
        section.add(
            f"env_{var.lower()}",
            f"Переменная {var}",
            Status.OK if value else Status.MISSING,
            value or "не задана",
        )

    if os.name == "nt":
        _collect_registry(section)


def _resolve_process() -> tuple[Status, str]:
    if os.name == "nt":
        output = _run(["tasklist", "/FI", "IMAGENAME eq Resolve.exe"])
        if not output:
            return Status.UNKNOWN, "не удалось выполнить tasklist"
        return (
            (Status.OK, "процесс Resolve.exe найден")
            if "Resolve.exe" in output
            else (Status.MISSING, "процесс Resolve.exe не найден")
        )
    output = _run(["ps", "-Ao", "comm"])
    if not output:
        return Status.UNKNOWN, "не удалось выполнить ps"
    running = any("resolve" in line.lower() for line in output.splitlines())
    return (Status.OK, "процесс найден") if running else (Status.MISSING, "процесс не найден")


def _collect_registry(section: Section) -> None:
    """Installed version from the uninstall registry.

    Reads only ``HKLM``/``HKCU`` uninstall entries, which is where every Windows
    installer publishes its display name and version. Nothing is written.
    """

    try:
        import winreg  # noqa: PLC0415 — Windows-only import
    except ImportError:
        return

    roots = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    )
    entries: list[dict[str, str]] = []
    for hive, path in roots:
        try:
            key = winreg.OpenKey(hive, path)
        except OSError:
            continue
        with key:
            index = 0
            while True:
                try:
                    name = winreg.EnumKey(key, index)
                except OSError:
                    break
                index += 1
                try:
                    with winreg.OpenKey(key, name) as sub:
                        display = str(winreg.QueryValueEx(sub, "DisplayName")[0])
                        if "davinci" not in display.lower():
                            continue
                        entry = {"name": display}
                        for value in ("DisplayVersion", "InstallLocation", "Publisher"):
                            try:
                                entry[value] = str(winreg.QueryValueEx(sub, value)[0])
                            except OSError:
                                continue
                        entries.append(entry)
                except OSError:
                    continue

    section.add(
        "registry",
        "Запись в реестре",
        Status.OK if entries else Status.MISSING,
        "; ".join(f"{e['name']} {e.get('DisplayVersion', '')}".strip() for e in entries)
        or "установка DaVinci в реестре не найдена",
        data=entries,
    )


# ------------------------------------------------------------ scripting API


def _scripting_candidates() -> tuple[tuple[str, ...], tuple[str, ...]]:
    if os.name == "nt":
        return SCRIPTING_CANDIDATES_WINDOWS, LIBRARY_CANDIDATES_WINDOWS
    if sys.platform == "darwin":
        return SCRIPTING_CANDIDATES_MAC, LIBRARY_CANDIDATES_MAC
    return SCRIPTING_CANDIDATES_LINUX, LIBRARY_CANDIDATES_LINUX


def _collect_scripting(report: Report, progress: Progress) -> Any:
    """Locate, import and introspect the Resolve scripting module.

    Returns the live ``Resolve`` object, or None. Read-only: only getters are
    called, and nothing in a project is modified.
    """

    section = report.section("Скриптовый API")
    script_dirs, lib_files = _scripting_candidates()

    modules_dirs = []
    for candidate in script_dirs:
        base = _expand(candidate)
        modules = base / "Modules"
        if _exists(modules):
            modules_dirs.append(modules)
        elif _exists(base):
            modules_dirs.append(base)

    env_api = os.environ.get("RESOLVE_SCRIPT_API")
    if env_api:
        env_modules = Path(env_api) / "Modules"
        if _exists(env_modules):
            modules_dirs.insert(0, env_modules)

    section.add(
        "modules_dir",
        "Каталог Modules",
        Status.OK if modules_dirs else Status.MISSING,
        "; ".join(str(p) for p in modules_dirs) or "не найден ни по одному известному пути",
        data={"checked": [str(_expand(c)) for c in script_dirs], "found": [str(p) for p in modules_dirs]},
    )

    stub = None
    for directory in modules_dirs:
        candidate = directory / "DaVinciResolveScript.py"
        if _exists(candidate):
            stub = candidate
            break
    section.add(
        "stub",
        "Модуль DaVinciResolveScript.py",
        Status.OK if stub else Status.MISSING,
        str(stub) if stub else "не найден",
    )

    libs = [str(_expand(c)) for c in lib_files if _exists(_expand(c))]
    env_lib = os.environ.get("RESOLVE_SCRIPT_LIB")
    if env_lib and _exists(Path(env_lib)):
        libs.insert(0, env_lib)
    section.add(
        "library",
        "Библиотека fusionscript",
        Status.OK if libs else Status.MISSING,
        "; ".join(libs) or "не найдена",
        data={"checked": [str(_expand(c)) for c in lib_files], "found": libs},
    )

    if stub is None:
        section.notes.append(
            "Без DaVinciResolveScript.py живая проверка API невозможна. "
            "Обычно это значит, что Resolve не установлен или установлен без "
            "компонента скриптинга."
        )
        return None

    progress("Импортирую модуль скриптинга…")
    module = _import_stub(stub, libs, section)
    if module is None:
        return None

    progress("Подключаюсь к Resolve…")
    resolve = _safe(module, "scriptapp", "Resolve")
    if resolve is None:
        section.add(
            "connect",
            "Подключение к Resolve",
            Status.FAILED,
            "scriptapp('Resolve') вернул пустое значение. Частые причины: Resolve "
            "не запущен; в Preferences → System → General выключено External "
            "scripting using; версия ограничивает доступ.",
        )
        return None

    section.add("connect", "Подключение к Resolve", Status.OK, "scriptapp('Resolve') вернул объект")
    section.add(
        "version",
        "Версия Resolve",
        Status.OK,
        str(_safe(resolve, "GetVersionString") or _safe(resolve, "GetVersion") or "не сообщается"),
    )
    product = _safe(resolve, "GetProductName")
    section.add(
        "product",
        "Редакция",
        Status.OK if product else Status.UNKNOWN,
        str(product or "не сообщается"),
        data={"is_studio": bool(product and "studio" in str(product).lower())},
    )
    return resolve


def _import_stub(stub: Path, libs: list[str], section: Section) -> Any:
    """Import the stub by path, telling it where the native library is.

    The stub reads ``RESOLVE_SCRIPT_LIB`` at import time, so it is set here when
    it was not already in the environment. The change lives in this process only.
    """

    if libs and not os.environ.get("RESOLVE_SCRIPT_LIB"):
        os.environ["RESOLVE_SCRIPT_LIB"] = libs[0]
    if not os.environ.get("RESOLVE_SCRIPT_API"):
        os.environ["RESOLVE_SCRIPT_API"] = str(stub.parent.parent)

    try:
        spec = importlib.util.spec_from_file_location("DaVinciResolveScript", stub)
        if spec is None or spec.loader is None:
            section.add("import", "Импорт модуля", Status.FAILED, "importlib не построил спецификацию")
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 — a foreign module may raise anything
        section.add(
            "import",
            "Импорт модуля",
            Status.FAILED,
            f"{type(exc).__name__}: {exc}",
        )
        return None

    section.add("import", "Импорт модуля", Status.OK, "DaVinciResolveScript импортирован")
    return module


# ------------------------------------------------------ capability matrix

RESOLVE_METHODS = (
    "GetProjectManager",
    "GetVersionString",
    "GetProductName",
    "OpenPage",
    "GetCurrentPage",
    "ImportRenderPreset",
)

MANAGER_METHODS = (
    "GetCurrentProject",
    "GetProjectListInCurrentFolder",
    "GetFolderListInCurrentFolder",
    "GotoRootFolder",
    "GotoParentFolder",
    "OpenFolder",
    "GetCurrentFolder",
    "LoadProject",
    "GetDatabaseList",
    "GetCurrentDatabase",
    "SetCurrentDatabase",
    "ExportProject",
    "ImportProject",
    "ArchiveProject",
)

PROJECT_METHODS = (
    "GetName",
    "GetUniqueId",
    "GetTimelineCount",
    "GetTimelineByIndex",
    "GetCurrentTimeline",
    "GetMediaPool",
    "GetSetting",
)

MEDIA_POOL_METHODS = (
    "GetRootFolder",
    "GetCurrentFolder",
    "GetSelectedClips",
)

FOLDER_METHODS = ("GetName", "GetClipList", "GetSubFolderList", "GetUniqueId")

CLIP_METHODS = ("GetName", "GetClipProperty", "GetMetadata", "GetMediaId", "GetMarkers")

TIMELINE_METHODS = (
    "GetName",
    "GetTrackCount",
    "GetItemListInTrack",
    "GetStartFrame",
    "GetStartTimecode",
    "GetMarkers",
    "GetSetting",
)

CLIP_PROPERTY_KEYS = (
    "File Path",
    "File Name",
    "Clip Name",
    "Reel Name",
    "Camera Roll",
    "Tape Name",
    "Start TC",
    "End TC",
    "Duration",
    "FPS",
    "Resolution",
    "Type",
    "Video Codec",
    "Audio Codec",
    "Date Created",
    "Date Modified",
)
"""Property names version 3.0 would search by. Presence is measured on a real
clip, not assumed — a key that is absent must produce a disabled filter with a
reason, not an empty result set."""


def _methods(section: Section, key: str, label: str, obj: Any, names: tuple[str, ...]) -> None:
    if obj is None:
        section.add(key, label, Status.UNKNOWN, "объект недоступен, проверить нечего")
        return
    present = [name for name in names if _has(obj, name)]
    absent = [name for name in names if name not in present]
    section.add(
        key,
        label,
        Status.OK if present else Status.FAILED,
        f"есть {len(present)} из {len(names)}"
        + (f"; отсутствуют: {', '.join(absent)}" if absent else ""),
        data={"present": present, "absent": absent},
    )


def _collect_capabilities(report: Report, resolve: Any, progress: Progress) -> Any:
    section = report.section("Возможности API")
    _methods(section, "resolve", "Объект Resolve", resolve, RESOLVE_METHODS)

    manager = _safe(resolve, "GetProjectManager")
    _methods(section, "manager", "ProjectManager", manager, MANAGER_METHODS)
    if manager is None:
        return None

    project = _safe(manager, "GetCurrentProject")
    _methods(section, "project", "Project", project, PROJECT_METHODS)
    if project is None:
        section.notes.append("Открытого проекта нет — часть проверок пропущена.")
        return manager

    section.add(
        "project_name",
        "Текущий проект",
        Status.OK,
        str(_safe(project, "GetName") or "без имени"),
    )

    timeline = _safe(project, "GetCurrentTimeline")
    _methods(section, "timeline", "Timeline", timeline, TIMELINE_METHODS)

    progress("Смотрю медиапул…")
    pool = _safe(project, "GetMediaPool")
    _methods(section, "media_pool", "MediaPool", pool, MEDIA_POOL_METHODS)

    root = _safe(pool, "GetRootFolder") if pool is not None else None
    _methods(section, "folder", "Folder", root, FOLDER_METHODS)

    clip = _first_clip(root)
    _methods(section, "clip", "MediaPoolItem", clip, CLIP_METHODS)
    if clip is None:
        section.notes.append(
            "В медиапуле текущего проекта не нашлось ни одного клипа, поэтому "
            "список доступных свойств клипа снять не удалось."
        )
        return manager

    _collect_clip_properties(section, clip)
    return manager


def _first_clip(folder: Any, depth: int = 0) -> Any:
    """First clip found anywhere in the media pool tree."""

    if folder is None or depth > 6:
        return None
    clips = _safe(folder, "GetClipList") or []
    if isinstance(clips, dict):
        clips = list(clips.values())
    for clip in clips:
        if clip is not None:
            return clip
    subfolders = _safe(folder, "GetSubFolderList") or []
    if isinstance(subfolders, dict):
        subfolders = list(subfolders.values())
    for sub in subfolders:
        found = _first_clip(sub, depth + 1)
        if found is not None:
            return found
    return None


def _collect_clip_properties(section: Section, clip: Any) -> None:
    """Which clip properties actually exist, measured on a real clip."""

    everything = _safe(clip, "GetClipProperty")
    available: dict[str, str] = {}
    if isinstance(everything, dict):
        available = {str(k): str(v) for k, v in everything.items()}

    per_key: dict[str, bool] = {}
    for key in CLIP_PROPERTY_KEYS:
        value = available.get(key)
        if value is None:
            value = _safe(clip, "GetClipProperty", key)
        per_key[key] = bool(value)

    present = [k for k, ok in per_key.items() if ok]
    section.add(
        "clip_properties",
        "Свойства клипа",
        Status.OK if present else Status.FAILED,
        f"заполнены {len(present)} из {len(CLIP_PROPERTY_KEYS)}: {', '.join(present) or '—'}",
        data={"checked": per_key, "all_keys": sorted(available)},
    )
    section.notes.append(
        "Полный список ключей свойств этого клипа сохранён в JSON-версии отчёта — "
        "именно он определит, по каким полям сможет искать версия 3.0."
    )


# ---------------------------------------------------------------- databases

DISK_DB_CANDIDATES_WINDOWS = (
    r"%PROGRAMDATA%\Blackmagic Design\DaVinci Resolve\Support\Resolve Disk Database",
    r"%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Resolve Disk Database",
    r"%LOCALAPPDATA%\Blackmagic Design\DaVinci Resolve\Resolve Disk Database",
)

DISK_DB_CANDIDATES_MAC = (
    "~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Resolve Disk Database",
    "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Resolve Disk Database",
)

DISK_DB_CANDIDATES_LINUX = ("~/.local/share/DaVinciResolve/Resolve Disk Database",)


def _collect_databases(report: Report, manager: Any, progress: Progress) -> None:
    """Where the projects actually live.

    This is the question that decides whether searching a folder of ``.drp`` is
    the right tool at all: a project only exists as a file on disk if somebody
    exported it. Normally projects live inside a database and there is no file
    to search.
    """

    section = report.section("Базы проектов")

    if manager is not None:
        current = _safe(manager, "GetCurrentDatabase")
        section.add(
            "current_db",
            "Текущая база (по API)",
            Status.OK if current else Status.UNKNOWN,
            _describe_db(current),
            data=current if isinstance(current, dict) else None,
        )
        databases = _safe(manager, "GetDatabaseList")
        if isinstance(databases, (list, tuple)):
            section.add(
                "db_list",
                "Все базы (по API)",
                Status.OK if databases else Status.MISSING,
                "; ".join(_describe_db(db) for db in databases) or "список пуст",
                data=list(databases),
            )
        else:
            section.add("db_list", "Все базы (по API)", Status.UNKNOWN, "GetDatabaseList недоступен")

        progress("Считаю проекты в текущей папке базы…")
        _collect_project_tree(section, manager)
    else:
        section.notes.append("API недоступен — база опрошена только по файловой системе.")

    if os.name == "nt":
        candidates = DISK_DB_CANDIDATES_WINDOWS
    elif sys.platform == "darwin":
        candidates = DISK_DB_CANDIDATES_MAC
    else:
        candidates = DISK_DB_CANDIDATES_LINUX

    found: list[dict[str, Any]] = []
    for candidate in candidates:
        path = Path(os.path.expandvars(os.path.expanduser(candidate)))
        if not _exists(path):
            continue
        entry: dict[str, Any] = {"path": str(path)}
        try:
            entry["children"] = sorted(p.name for p in path.iterdir())[:40]
        except OSError as exc:
            entry["error"] = str(exc)
        found.append(entry)

    section.add(
        "disk_db",
        "Дисковая база на файловой системе",
        Status.OK if found else Status.MISSING,
        "; ".join(str(e["path"]) for e in found) or "ни один из известных путей не существует",
        data={
            "checked": [
                str(Path(os.path.expandvars(os.path.expanduser(c)))) for c in candidates
            ],
            "found": found,
        },
    )
    section.notes.append(
        "Пути дисковой базы — кандидаты, а не утверждение: инструмент проверяет "
        "их существование и сообщает результат, ничего не предполагая заранее."
    )


def _describe_db(db: Any) -> str:
    if isinstance(db, dict):
        parts = [f"{k}={v}" for k, v in db.items() if v]
        return ", ".join(parts) or "пусто"
    return str(db) if db else "не сообщается"


def _collect_project_tree(section: Section, manager: Any) -> None:
    """Count projects and folders without loading a single project.

    ``LoadProject`` is deliberately never called: opening a project would change
    what the editor sees on screen, and a diagnostic has no business doing that.
    """

    if not _has(manager, "GetProjectListInCurrentFolder"):
        section.add("projects", "Проекты в базе", Status.UNKNOWN, "GetProjectListInCurrentFolder недоступен")
        return

    _safe(manager, "GotoRootFolder")
    total = 0
    folders_seen = 0
    tree: list[dict[str, Any]] = []
    queue: list[tuple[str, int]] = [("", 0)]
    visited = 0

    while queue and visited < 200:
        name, depth = queue.pop(0)
        visited += 1
        projects = _safe(manager, "GetProjectListInCurrentFolder") or []
        if isinstance(projects, dict):
            projects = list(projects.values())
        subfolders = _safe(manager, "GetFolderListInCurrentFolder") or []
        if isinstance(subfolders, dict):
            subfolders = list(subfolders.values())

        total += len(projects)
        folders_seen += 1
        tree.append(
            {
                "folder": name or "(корень)",
                "depth": depth,
                "projects": [str(p) for p in projects][:200],
                "subfolders": [str(s) for s in subfolders][:200],
            }
        )

        # Depth-first by hand: the API navigates a cursor, not a tree object.
        for sub in subfolders:
            if depth >= 4:
                break
            if _safe(manager, "OpenFolder", sub):
                queue.insert(0, (str(sub), depth + 1))
                break
        else:
            _safe(manager, "GotoParentFolder")

    section.add(
        "projects",
        "Проекты в базе",
        Status.OK if total else Status.MISSING,
        f"найдено {total} проектов в {folders_seen} папках базы",
        data=tree,
    )
    _safe(manager, "GotoRootFolder")


# --------------------------------------------------------------- .drp files

SKIP_DIR_NAMES = {
    "$recycle.bin",
    "system volume information",
    "windows",
    "winsxs",
    "node_modules",
    ".git",
    "__pycache__",
}


def _collect_drp_files(report: Report, limits: ScanLimits, progress: Progress) -> list[Path]:
    section = report.section("Файлы .drp на дисках")
    if not limits.search_drp:
        section.add("search", "Поиск отключён", Status.UNKNOWN, "пользователь отказался от сканирования дисков")
        return []

    roots = _drive_roots() if limits.all_drives else [Path.home()]
    deadline = time.monotonic() + limits.seconds
    found: list[Path] = []
    scanned_dirs = 0

    for root in roots:
        if time.monotonic() > deadline or len(found) >= limits.max_files:
            break
        progress(f"Ищу .drp на {root}…")
        for path in _walk_for_drp(root, deadline, limits.max_files - len(found)):
            found.append(path)
        scanned_dirs += 1

    by_folder = collections.Counter(str(p.parent) for p in found)
    caveats = []
    if len(found) >= limits.max_files:
        caveats.append(f"достигнут предел в {limits.max_files} файлов")
    if time.monotonic() > deadline:
        caveats.append(f"поиск остановлен по времени ({limits.seconds:.0f} с)")
    section.add(
        "count",
        "Найдено файлов .drp",
        Status.OK if found else Status.MISSING,
        f"{len(found)}" + (f" ({'; '.join(caveats)})" if caveats else ""),
        data={
            "count": len(found),
            "paths": [str(p) for p in found[:500]],
            "truncated": bool(caveats),
        },
    )
    if by_folder:
        top = by_folder.most_common(15)
        section.add(
            "folders",
            "Где они лежат",
            Status.INFO,
            "; ".join(f"{folder} — {count}" for folder, count in top),
            data=dict(by_folder),
        )
    else:
        section.notes.append(
            "Ни одного .drp не найдено. Это ожидаемо, если проекты никогда не "
            "экспортировали вручную: обычно они хранятся в базе Resolve, а не "
            "файлами на диске. В этом случае поиск по папке с .drp работать не "
            "будет, и основным режимом должен стать поиск по базе."
        )
    return found


def _walk_for_drp(root: Path, deadline: float, budget: int) -> Iterator[Path]:
    if budget <= 0:
        return
    produced = 0
    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        if time.monotonic() > deadline or produced >= budget:
            return
        dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIR_NAMES and not d.startswith(".")]
        for name in filenames:
            if name.lower().endswith(".drp"):
                yield Path(dirpath) / name
                produced += 1
                if produced >= budget:
                    return


# -------------------------------------------------------------- drp format


def _collect_drp_format(report: Report, files: list[Path], limits: ScanLimits, progress: Progress) -> None:
    section = report.section("Формат .drp")
    if not files:
        section.add("files", "Файлы для анализа", Status.MISSING, "нечего разбирать")
        return

    sample = files[: limits.analyse]
    for path in sample:
        progress(f"Разбираю {path.name}…")
        section.findings.append(_describe_drp(path))
    section.notes.append(
        "Разбор описывает контейнер и кодировку, а не структуру: структура — это "
        "версия 2.0, и она пишется уже по этим фактам."
    )


def _describe_drp(path: Path) -> Finding:
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            head = handle.read(512)
            handle.seek(0)
            body = handle.read(4 << 20)
    except OSError as exc:
        return Finding(
            key=f"drp_{path.name}",
            label=path.name,
            status=Status.FAILED,
            detail=f"не удалось прочитать: {exc}",
        )

    kind = detect_container(head)
    counts = {"utf-8": 0, "utf-16-le": 0}
    samples: list[str] = []
    for codec in counts:
        for _index, run in extract_runs(body, codec, 6):
            if _readable_ratio(run) < 0.6:
                continue
            counts[codec] += 1
            if len(samples) < 12 and ("\\" in run or "/" in run or "=" in run):
                samples.append(run[:200])

    detail = (
        f"{size} байт, контейнер {kind.value}, "
        f"читаемых строк utf-8 — {counts['utf-8']}, utf-16-le — {counts['utf-16-le']}"
    )
    return Finding(
        key=f"drp_{path.name}",
        label=path.name,
        status=Status.OK,
        detail=detail,
        data={
            "path": str(path),
            "size": size,
            "container": kind.value,
            "magic_hex": head[:16].hex(" "),
            "printable_head": "".join(chr(b) if 32 <= b < 127 else "." for b in head[:48]),
            "readable_runs": counts,
            "samples": samples,
        },
    )


def _readable_ratio(run: str) -> float:
    if not run:
        return 0.0
    readable = sum(1 for c in run if c.isascii() or "Ѐ" <= c <= "ӿ")
    return readable / len(run)


# ------------------------------------------------------------------ collect


def collect(limits: ScanLimits | None = None, progress: Progress | None = None) -> Report:
    """Run every collector. Never raises."""

    limits = limits or ScanLimits()
    emit: Progress = progress or (lambda _message: None)

    report = Report(
        generated_at=datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        app_version=__version__,
    )

    manager: Any = None

    def step(message: str, func: Callable[[], Any]) -> Any:
        emit(message)
        try:
            return func()
        except Exception as exc:  # noqa: BLE001 — one bad collector must not end the run
            report.errors.append(f"{message}: {type(exc).__name__}: {exc}")
            return None

    step("Собираю сведения о системе…", lambda: _collect_system(report))
    step("Ищу установленный Resolve…", lambda: _collect_installation(report))
    resolve = step("Проверяю скриптовый API…", lambda: _collect_scripting(report, emit))
    if resolve is not None:
        manager = step("Снимаю матрицу возможностей…", lambda: _collect_capabilities(report, resolve, emit))
    step("Ищу базы проектов…", lambda: _collect_databases(report, manager, emit))
    files = step("Ищу файлы .drp…", lambda: _collect_drp_files(report, limits, emit)) or []
    step("Разбираю формат .drp…", lambda: _collect_drp_format(report, files, limits, emit))

    emit("Готово.")
    return report
