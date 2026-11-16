"""Settings of mfi-server, for the Home Assistant add-on or run by hand.

Add-on mode: Home Assistant writes /data/options.json, and its folder is the
data folder. Standalone mode: --data DIR and an optional DIR/settings.json.
Precedence: environment variable, then file, then default.
"""
from __future__ import annotations

import argparse
import http.client
import ipaddress
import json
import logging
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

ADDON_OPTIONS_PATH = Path("/data/options.json")
LOG_LEVELS = ("debug", "info", "warning", "error")
FILE_KEYS = (
    "inform_port",
    "wakeup_port",
    "bind_address",
    "backup_file",
    "log_level",
    "mqtt_host",
    "mqtt_port",
    "mqtt_username",
    "mqtt_password",
    "mqtt_topic_prefix",
    "mqtt_discovery_prefix",
    "web_port",
    "history_days",
    "ingress_peer",
)
ENV_NAMES = {
    "inform_port": "MFI_INFORM_PORT",
    "wakeup_port": "MFI_WAKEUP_PORT",
    "bind_address": "MFI_BIND_ADDRESS",
    "backup_file": "MFI_BACKUP_FILE",
    "log_level": "MFI_LOG_LEVEL",
    "mqtt_host": "MFI_MQTT_HOST",
    "mqtt_port": "MFI_MQTT_PORT",
    "mqtt_username": "MFI_MQTT_USERNAME",
    "mqtt_password": "MFI_MQTT_PASSWORD",
    "mqtt_topic_prefix": "MFI_MQTT_TOPIC_PREFIX",
    "mqtt_discovery_prefix": "MFI_MQTT_DISCOVERY_PREFIX",
    "web_port": "MFI_WEB_PORT",
    "history_days": "MFI_HISTORY_DAYS",
    "ingress_peer": "MFI_INGRESS_PEER",
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
    mqtt_host: str = ""
    mqtt_port: int = 1883
    mqtt_username: str = ""
    mqtt_password: str = field(default="", repr=False)
    mqtt_topic_prefix: str = "mfi"
    mqtt_discovery_prefix: str = "homeassistant"
    web_port: int = 8099
    history_days: int = 30
    ingress_peer: str = "172.30.32.2"


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
        mqtt_host=_text("mqtt_host", values.get("mqtt_host", base.mqtt_host)),
        mqtt_port=_port("mqtt_port", values.get("mqtt_port", base.mqtt_port)),
        mqtt_username=_text("mqtt_username", values.get("mqtt_username", base.mqtt_username)),
        mqtt_password=_text("mqtt_password", values.get("mqtt_password", base.mqtt_password)),
        mqtt_topic_prefix=_text("mqtt_topic_prefix", values.get("mqtt_topic_prefix", base.mqtt_topic_prefix)),
        mqtt_discovery_prefix=_text(
            "mqtt_discovery_prefix", values.get("mqtt_discovery_prefix", base.mqtt_discovery_prefix)
        ),
        web_port=_port("web_port", values.get("web_port", base.web_port)),
        history_days=_history_days(values.get("history_days", base.history_days)),
        ingress_peer=_ingress_peer(values.get("ingress_peer", base.ingress_peer), base.ingress_peer),
    )
    logger.debug("settings loaded: mode=%s data_dir=%s", mode, data_dir)
    return settings


SUPERVISOR_MQTT_URL = "http://supervisor/services/mqtt"
SUPERVISOR_TIMEOUT_S = 10


def supervisor_mqtt(environ: Mapping[str, str], opener=urllib.request.urlopen) -> dict | None:
    """Ask the Supervisor for the MQTT broker; None when it is not available.

    The password is returned to the caller and is never logged.
    """
    token = environ.get("SUPERVISOR_TOKEN", "")
    if not token:
        logger.info("MQTT disabled")
        return None
    request = urllib.request.Request(SUPERVISOR_MQTT_URL, headers={"Authorization": f"Bearer {token}"})
    try:
        with opener(request, timeout=SUPERVISOR_TIMEOUT_S) as response:
            if response.status != 200:
                logger.info("MQTT disabled")
                return None
            body = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, http.client.HTTPException) as exc:
        logger.info("MQTT disabled: Supervisor request failed (%s)", type(exc).__name__)
        return None
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        logger.info("MQTT disabled")
        return None
    try:
        host = data["host"]
        if not isinstance(host, str) or not host:
            raise ValueError("host")
        port = _port("port", data["port"])
    except (KeyError, ValueError):
        logger.info("MQTT disabled: Supervisor answer has no usable host or port")
        return None
    logger.info("MQTT broker from the Supervisor: %s:%d", host, port)
    return {
        "host": host,
        "port": port,
        "username": data.get("username", ""),
        "password": data.get("password", ""),
    }


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


def _history_days(value: object) -> int:
    """Return the history retention in days (1-3650), or raise ValueError."""
    if isinstance(value, bool):
        raise ValueError("history_days must be 1-3650")
    if isinstance(value, float):
        raise ValueError("history_days must be 1-3650")
    try:
        days = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("history_days must be 1-3650") from exc
    if not 1 <= days <= 3650:
        raise ValueError("history_days must be 1-3650")
    return days


def _text(field: str, value: object) -> str:
    """Return a text setting, or raise ValueError naming the field."""
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    return value


def _ingress_peer(value: object, default: str) -> str:
    """Return the ingress peer IP; an empty or blank value falls back to the default."""
    if not isinstance(value, str):
        raise ValueError("ingress_peer must be a string")
    text = value.strip()
    if text == "":
        return default
    try:
        ipaddress.ip_address(text)
    except ValueError as exc:
        raise ValueError("ingress_peer must be an IP address") from exc
    return text


def _log_level(value: object) -> str:
    """Return the log level in lower case, or raise ValueError."""
    level = value.lower() if isinstance(value, str) else ""
    if level not in LOG_LEVELS:
        raise ValueError(f"log_level must be one of: {', '.join(LOG_LEVELS)}")
    return level
