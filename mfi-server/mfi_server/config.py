"""Settings of mfi-server, for the Home Assistant add-on or run by hand.

Add-on mode: Home Assistant writes /data/options.json, and its folder is the
data folder. Standalone mode: --data DIR and an optional DIR/settings.json.
Precedence: environment variable, then file, then default.
"""
from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

ADDON_OPTIONS_PATH = Path("/data/options.json")
LOG_LEVELS = ("debug", "info", "warning", "error")
FILE_KEYS = ("inform_port", "wakeup_port", "bind_address", "backup_file", "log_level")
ENV_NAMES = {
    "inform_port": "MFI_INFORM_PORT",
    "wakeup_port": "MFI_WAKEUP_PORT",
    "bind_address": "MFI_BIND_ADDRESS",
    "backup_file": "MFI_BACKUP_FILE",
    "log_level": "MFI_LOG_LEVEL",
}


@dataclass
class Settings:
    """Effective settings of one run of mfi-server."""

    data_dir: Path
    inform_port: int = 6080
    wakeup_port: int = 3478
    bind_address: str = "0.0.0.0"
    backup_file: str = ""
    log_level: str = "info"
    mode: str = "standalone"
    request_timeout_s: float = 10.0
    max_body_bytes: int = 65536


def load_settings(argv: list[str], environ: Mapping[str, str], options_path: Path = ADDON_OPTIONS_PATH) -> Settings:
    """Build the settings from the add-on options file or from the command line."""
    if options_path.is_file():
        mode = "addon"
        data_dir = options_path.parent
        settings_file = options_path
    else:
        mode = "standalone"
        parser = argparse.ArgumentParser(prog="mfi_server")
        parser.add_argument("--data", default="./data")
        args = parser.parse_args(argv)
        data_dir = Path(args.data)
        settings_file = data_dir / "settings.json"

    values: dict[str, object] = {}
    if settings_file.is_file():
        values.update(_read_file(settings_file))
    values.update(_read_environ(environ))

    base = Settings(data_dir=data_dir, mode=mode)
    settings = Settings(
        data_dir=data_dir,
        inform_port=_port("inform_port", values.get("inform_port", base.inform_port)),
        wakeup_port=_port("wakeup_port", values.get("wakeup_port", base.wakeup_port)),
        bind_address=_text("bind_address", values.get("bind_address", base.bind_address)),
        backup_file=_text("backup_file", values.get("backup_file", base.backup_file)),
        log_level=_log_level(values.get("log_level", base.log_level)),
        mode=mode,
        request_timeout_s=base.request_timeout_s,
        max_body_bytes=base.max_body_bytes,
    )
    logger.debug("settings loaded: mode=%s data_dir=%s", mode, data_dir)
    return settings


def _read_file(path: Path) -> dict[str, object]:
    """Read a settings file; reject bad JSON, a non-object root and unknown keys."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: not valid JSON ({exc})") from exc
    except UnicodeDecodeError as exc:
        raise ValueError(f"{path}: not UTF-8 text") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: the top level must be a JSON object")
    for key in raw:
        if key not in FILE_KEYS:
            raise ValueError(f"{path}: unknown setting {key!r}")
    return raw


def _read_environ(environ: Mapping[str, str]) -> dict[str, object]:
    """Collect the MFI_* variables that are set; an empty value counts as unset."""
    values: dict[str, object] = {}
    for key, name in ENV_NAMES.items():
        value = environ.get(name, "")
        if value != "":
            values[key] = value
    return values


def _port(field: str, value: object) -> int:
    """Return a port number, or raise ValueError naming the field."""
    if isinstance(value, bool):
        raise ValueError(f"{field} must be 1-65535")
    if isinstance(value, float):
        raise ValueError(f"{field} must be 1-65535")
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be 1-65535") from exc
    if not 1 <= port <= 65535:
        raise ValueError(f"{field} must be 1-65535")
    return port


def _text(field: str, value: object) -> str:
    """Return a text setting, or raise ValueError naming the field."""
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    return value


def _log_level(value: object) -> str:
    """Return the log level in lower case, or raise ValueError."""
    level = value.lower() if isinstance(value, str) else ""
    if level not in LOG_LEVELS:
        raise ValueError(f"log_level must be one of: {', '.join(LOG_LEVELS)}")
    return level
