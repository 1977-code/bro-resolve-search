"""Per-user settings. The project folder is never written to."""

from __future__ import annotations

import json
import os
import platform
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

APP_DIR_NAME = "ResolveProjectSearch"
SETTINGS_SCHEMA_VERSION = 1

__all__ = ["Settings", "user_config_dir", "settings_path", "load_settings", "save_settings"]


def user_config_dir() -> Path:
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    if system == "Windows":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_DIR_NAME
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_DIR_NAME


def settings_path() -> Path:
    return user_config_dir() / "settings.json"


@dataclass
class Settings:
    schema_version: int = SETTINGS_SCHEMA_VERSION
    last_folder: str = ""
    last_query: str = ""
    recursive: bool = True
    case_sensitive: bool = False
    extensions: str = ".drp"
    max_hits_per_file: int = 20
    workers: int = 0
    window_width: int = 980
    window_height: int = 640

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Settings":
        """Build from stored data, ignoring unknown keys and bad types.

        A settings file written by a newer version degrades instead of blocking
        startup.
        """

        valid = {f.name: f for f in cls.__dataclass_fields__.values()}
        kwargs: dict[str, Any] = {}
        for key, value in data.items():
            field = valid.get(key)
            if field is None:
                continue
            expected = {"int": int, "bool": bool, "str": str}.get(str(field.type))
            if expected is None or isinstance(value, expected):
                kwargs[key] = value
        return cls(**kwargs)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_settings() -> Settings:
    path = settings_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Settings()
    if not isinstance(data, dict):
        return Settings()
    return Settings.from_dict(data)


def save_settings(settings: Settings) -> None:
    """Write settings, ignoring failure — losing a window size is not worth a
    crash dialog on a read-only profile."""

    path = settings_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(settings.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass
