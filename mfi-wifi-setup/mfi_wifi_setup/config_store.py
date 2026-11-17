"""Store of the controller address between runs of mfi-wifi-setup.

The file holds only the controller address, which is not a secret. Passwords
and Wi-Fi data are never written here. Standard library only.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

APP_NAME = "mfi-wifi-setup"
CONFIG_FILE_NAME = "config.json"
CONTROLLER_KEY = "controller_address"


def config_dir() -> Path:
    """Folder of the settings: %APPDATA% on Windows, ~/.config elsewhere."""
    if os.name == "nt":
        appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(appdata) / APP_NAME
    return Path.home() / ".config" / APP_NAME


def config_file(path: str | Path | None = None) -> Path:
    """Settings file: `path` when given (tests), else config.json in config_dir()."""
    if path is not None:
        return Path(path)
    return config_dir() / CONFIG_FILE_NAME


def load_controller_address(path: str | Path | None = None) -> str:
    """Saved controller address, or "" when the file is missing, unreadable or corrupt."""
    try:
        data = json.loads(config_file(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if not isinstance(data, dict):
        return ""
    address = data.get(CONTROLLER_KEY, "")
    return address if isinstance(address, str) else ""


def save_controller_address(address: str, path: str | Path | None = None) -> None:
    """Write the controller address only; the parent folder is created when missing."""
    target = config_file(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({CONTROLLER_KEY: address}, indent=2) + "\n", encoding="utf-8")
