"""Effective settings: defaults, settings file, add-on options and environment. Standard library only."""
from __future__ import annotations

import http.client
import ipaddress
import json
import logging
import os
import urllib.request
from pathlib import Path

from mfi_server_next.devices import parse_extra_options

logger = logging.getLogger(__name__)

# Same text as the ssh_extra_options default in mfi-server/config.yaml.
DEFAULT_SSH_EXTRA_OPTIONS = "KexAlgorithms=+diffie-hellman-group1-sha1,diffie-hellman-group14-sha1;HostKeyAlgorithms=+ssh-rsa;Ciphers=+aes128-cbc,3des-cbc"
KNOWN_OPTION_KEYS = frozenset({
    "backup_file",
    "log_level",
    "mqtt_topic_prefix",
    "mqtt_discovery_prefix",
    "ingress_peer",
    "server_address",
    "device_ssh_username",
    "device_ssh_password",
    "ssh_extra_options",
    "allow_webshell",
    "allow_browser_ssh",
    "allow_upnp",
    "allow_guest_page",
    "allow_script_action",
})
DEFAULTS = {
    "inform_port": 6080,
    "history_days": 30,
    "backup_copies": 5,
    "log_level": "info",
    "server_address": "",
    "device_ssh_username": "",
    "device_ssh_password": "",
    "ssh_extra_options": DEFAULT_SSH_EXTRA_OPTIONS,
    "backup_file": "",
    "ingress_peer": "",
}
ENV_NAMES = {
    "inform_port": "MFI_INFORM_PORT",
    "history_days": "MFI_HISTORY_DAYS",
    "backup_copies": "MFI_BACKUP_COPIES",
    "log_level": "MFI_LOG_LEVEL",
    "server_address": "MFI_SERVER_ADDRESS",
    "device_ssh_username": "MFI_DEVICE_SSH_USERNAME",
    "device_ssh_password": "MFI_DEVICE_SSH_PASSWORD",
    "ssh_extra_options": "MFI_SSH_EXTRA_OPTIONS",
    "backup_file": "MFI_BACKUP_FILE",
    "ingress_peer": "MFI_INGRESS_PEER",
}
INT_KEYS = ("inform_port", "history_days", "backup_copies")
LOG_LEVELS = ("debug", "info", "warning", "error")
SETTINGS_FILE = "settings.json"
OPTIONS_FILE = "options.json"
DEFAULT_DATA_DIR = "./data"
# Home Assistant ingress gateway: the ingress_peer used when the option is empty.
TRUSTED_INGRESS_PEER = "172.30.32.2"


def load_settings(data_dir=None, environ=None, mode=None):
    """Load the effective settings of one run: defaults, settings.json, add-on options (addon mode only), then environment."""
    folder = Path(data_dir) if data_dir is not None else Path(DEFAULT_DATA_DIR)
    env = os.environ if environ is None else environ
    settings = dict(DEFAULTS)
    settings.update(_read_settings_file(folder / SETTINGS_FILE))
    if mode == "addon":
        settings.update(_read_settings_file(folder / OPTIONS_FILE))
    for key, name in ENV_NAMES.items():
        value = env.get(name, "")
        if value != "":
            settings[key] = value
    for key in INT_KEYS:
        settings[key] = _to_int(key, settings[key])
    _check_ranges(settings)
    settings["log_level"] = _log_level(settings["log_level"])
    settings["server_address"] = _server_address(settings["server_address"])
    settings["ingress_peer"] = _ingress_peer(settings["ingress_peer"], TRUSTED_INGRESS_PEER)
    settings["ssh_extra_options"] = _ssh_extra_options(settings["ssh_extra_options"])
    settings["data_dir"] = str(folder)
    return settings


def resolve_backup_path(value, share_dir=Path("/share")):
    """Resolve a backup file path: an absolute path is used as is; a bare name is looked up in share_dir when the file is there."""
    path = Path(value)
    if path.is_absolute():
        return path
    candidate = Path(share_dir) / value
    if candidate.is_file():
        return candidate
    return path


SUPERVISOR_MQTT_URL = "http://supervisor/services/mqtt"
SUPERVISOR_TIMEOUT_S = 10


def supervisor_mqtt(environ, opener=urllib.request.urlopen):
    """Ask the Supervisor for the MQTT broker; None when it is not available. The password is never logged."""
    token = environ.get("SUPERVISOR_TOKEN", "")
    if not token:
        logger.info("MQTT disabled")
        return None
    request = urllib.request.Request(SUPERVISOR_MQTT_URL, headers={"Authorization": f"Bearer {token}"})
    try:
        with opener(request, timeout=SUPERVISOR_TIMEOUT_S) as response:
            if response.status != 200:
                logger.info("MQTT disabled: Supervisor answered status %s", response.status)
                return None
            body = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, http.client.HTTPException) as exc:
        logger.info("MQTT disabled: Supervisor request failed (%s)", type(exc).__name__)
        return None
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        logger.info("MQTT disabled: Supervisor answer has no data")
        return None
    host = data.get("host")
    if not isinstance(host, str) or host == "":
        logger.info("MQTT disabled: Supervisor answer has no host")
        return None
    try:
        port = int(data.get("port"))
    except (TypeError, ValueError):
        logger.info("MQTT disabled: Supervisor answer has no usable port")
        return None
    if not 1 <= port <= 65535:
        logger.info("MQTT disabled: Supervisor answer has no usable port")
        return None
    logger.info("MQTT broker from the Supervisor: %s:%d", host, port)
    return {
        "host": host,
        "port": port,
        "username": data.get("username", ""),
        "password": data.get("password", ""),
        "tls": bool(data.get("ssl", False)),
    }


def _read_settings_file(path):
    """Read a settings file when it exists; reject bad JSON and a non-object root, naming the file."""
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


def _log_level(value):
    """Return the log level in lower case; anything but debug, info, warning or error raises ValueError."""
    level = value.lower() if isinstance(value, str) else ""
    if level not in LOG_LEVELS:
        raise ValueError(f"log_level must be one of: {', '.join(LOG_LEVELS)}")
    return level


def _server_address(value):
    """Return the server address; empty or blank means auto-detect, otherwise an IPv4 address."""
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValueError("server_address must be an IPv4 address")
    text = value.strip()
    if text == "":
        return ""
    try:
        ipaddress.IPv4Address(text)
    except ValueError as exc:
        raise ValueError("server_address must be an IPv4 address") from exc
    return text


def _ingress_peer(value, default):
    """Return the ingress peer IP; an empty or blank value gives the default."""
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValueError("ingress_peer must be an IP address")
    text = value.strip()
    if text == "":
        return default
    try:
        ipaddress.ip_address(text)
    except ValueError as exc:
        raise ValueError("ingress_peer must be an IP address") from exc
    return text


def _ssh_extra_options(value):
    """Validate the ssh extra options with the same rules as the ssh adoption, naming the field on error."""
    if not isinstance(value, str):
        raise ValueError("ssh_extra_options must be a string")
    try:
        parse_extra_options(value)
    except ValueError as exc:
        raise ValueError(f"ssh_extra_options: {exc}") from exc
    return value
