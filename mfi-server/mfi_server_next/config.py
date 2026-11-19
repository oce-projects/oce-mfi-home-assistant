"""Effective settings: environment, settings file and defaults. Standard library only."""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULTS = {"inform_port": 6080, "history_days": 30, "backup_copies": 5}
ENV_NAMES = {
    "inform_port": "MFI_INFORM_PORT",
    "history_days": "MFI_HISTORY_DAYS",
    "backup_copies": "MFI_BACKUP_COPIES",
}
INT_KEYS = ("inform_port", "history_days", "backup_copies")
SETTINGS_FILE = "settings.json"
DEFAULT_DATA_DIR = "./data"


def load_settings(data_dir=None, environ=None):
    """Load the effective settings of one run: defaults, then settings.json, then environment."""
    folder = Path(data_dir) if data_dir is not None else Path(DEFAULT_DATA_DIR)
    env = os.environ if environ is None else environ
    settings = dict(DEFAULTS)
    settings.update(_read_settings_file(folder / SETTINGS_FILE))
    for key, name in ENV_NAMES.items():
        value = env.get(name, "")
        if value != "":
            settings[key] = value
    for key in INT_KEYS:
        settings[key] = _to_int(key, settings[key])
    _check_ranges(settings)
    settings["data_dir"] = str(folder)
    return settings


def _read_settings_file(path):
    """Read settings.json when it exists; reject bad JSON and a non-object root, naming the file."""
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: not valid JSON ({exc})") from exc
    except UnicodeDecodeError as exc:
        raise ValueError(f"{path}: not UTF-8 text") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: the top level must be a JSON object")
    return raw


def _to_int(key, value):
    """Return an integer setting; bool, float and non-numeric values raise ValueError naming the key."""
    if isinstance(value, (bool, float)):
        raise ValueError(f"{key} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be an integer") from exc


def _check_ranges(settings):
    """Reject values outside their allowed range, naming the key in the message."""
    if not 1 <= settings["inform_port"] <= 65535:
        raise ValueError("inform_port must be between 1 and 65535")
    if settings["history_days"] < 0:
        raise ValueError("history_days must be >= 0")
    if settings["backup_copies"] < 0:
        raise ValueError("backup_copies must be >= 0")
