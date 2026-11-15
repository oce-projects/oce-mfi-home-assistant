"""Device archive of mfi-server: devices.json with the device keys.

One record per device: MAC, model, name, authkey (from a backup, or empty),
the sensor ports, and the import values of state and last_seen_ms. A missing
file is an empty archive. A damaged file raises ValueError and is never
rewritten. Writes go to a temporary file first, then replace the old file.
Authkeys never go to the log, to repr() or to error messages.
Standard library only.
"""
from __future__ import annotations

import copy
import json
import logging
import os
import re
import threading
from pathlib import Path

from mfi_server.packet import DEFAULT_KEY_HEX, normalize_mac

logger = logging.getLogger(__name__)

SCHEMA = 1
FILE_NAME = "devices.json"
DEFAULT_STATE = "unknown"
_AUTHKEY_RE = re.compile(r"[0-9a-f]{32}")


def _mac_or_none(mac: str) -> str | None:
    """Return the normalized MAC, or None if it is not a valid MAC."""
    try:
        return normalize_mac(mac)
    except ValueError:
        return None


def _text(record: dict, name: str, default: str) -> str:
    value = record.get(name, default)
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    return value


def _integer(value: object, name: str, minimum: int) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _normalize_port(item: object) -> dict:
    if not isinstance(item, dict):
        raise ValueError("each port must be an object")
    return {
        "port": _integer(item.get("port"), "port", 1),
        "sensor_id": _text(item, "sensor_id", ""),
        "label": _text(item, "label", ""),
        "model": _text(item, "model", ""),
    }


def _normalize_record(record: object) -> dict:
    """Validate one device record and fill the defaults of the contract."""
    if not isinstance(record, dict):
        raise ValueError("device record must be an object")
    mac = normalize_mac(record.get("mac"))
    authkey = _text(record, "authkey", "").lower()
    if authkey and not _AUTHKEY_RE.fullmatch(authkey):
        raise ValueError(f"authkey of {mac} must be 32 hex characters")
    ports = record.get("ports", [])
    if not isinstance(ports, list):
        raise ValueError(f"ports of {mac} must be a list")
    return {
        "mac": mac,
        "model": _text(record, "model", ""),
        "name": _text(record, "name", ""),
        "authkey": authkey,
        "ports": [_normalize_port(item) for item in ports],
        "state": _text(record, "state", DEFAULT_STATE),
        "last_seen_ms": _integer(record.get("last_seen_ms", 0), "last_seen_ms", 0),
    }


class DeviceStore:
    """devices.json in data_dir: loaded at start, rewritten on every change."""

    def __init__(self, data_dir: Path) -> None:
        data_dir.mkdir(parents=True, exist_ok=True)
        self.path = data_dir / FILE_NAME
        self._lock = threading.RLock()
        self._devices: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except UnicodeDecodeError as exc:
            raise ValueError(f"{self.path}: not UTF-8 text") from exc
        except json.JSONDecodeError as exc:
            raise ValueError(f"{self.path}: not valid JSON ({exc})") from exc
        if not isinstance(raw, dict):
            raise ValueError(f"{self.path}: the top level must be a JSON object")
        schema = raw.get("schema")
        if type(schema) is not int or schema != SCHEMA:
            raise ValueError(f"{self.path}: schema must be {SCHEMA}")
        devices = raw.get("devices")
        if not isinstance(devices, list):
            raise ValueError(f"{self.path}: devices must be a list")
        for item in devices:
            try:
                record = _normalize_record(item)
            except ValueError as exc:
                raise ValueError(f"{self.path}: {exc}") from exc
            if record["mac"] in self._devices:
                raise ValueError(f"{self.path}: duplicate device {record['mac']}")
            self._devices[record["mac"]] = record
        logger.debug("loaded %d devices from %s", len(self._devices), self.path)

    def _write(self) -> None:
        """Write the whole archive to a temporary file, then replace the old one."""
        tmp = self.path.with_name(FILE_NAME + ".tmp")
        devices = [self._devices[mac] for mac in sorted(self._devices)]
        text = json.dumps({"schema": SCHEMA, "devices": devices}, indent=2, sort_keys=True)
        try:
            with open(tmp, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise

    def get(self, mac: str) -> dict | None:
        """Return a copy of one device, or None if it is unknown or the MAC is invalid."""
        key = _mac_or_none(mac)
        if key is None:
            return None
        with self._lock:
            record = self._devices.get(key)
            return None if record is None else copy.deepcopy(record)

    def upsert(self, record: dict) -> None:
        """Validate and store one device, then write the archive."""
        clean = _normalize_record(record)
        with self._lock:
            snapshot = dict(self._devices)
            self._devices[clean["mac"]] = clean
            try:
                self._write()
            except Exception:
                self._devices = snapshot
                raise
        logger.info("saved device %s (%d ports)", clean["mac"], len(clean["ports"]))

    def all(self) -> list[dict]:
        """Return copies of all devices, ordered by MAC."""
        with self._lock:
            return [copy.deepcopy(self._devices[mac]) for mac in sorted(self._devices)]

    def keys_for(self, mac: str) -> list[bytes]:
        """Keys to try on a packet from mac: the device authkey first, then the factory key."""
        factory = bytes.fromhex(DEFAULT_KEY_HEX)
        key = _mac_or_none(mac)
        with self._lock:
            record = None if key is None else self._devices.get(key)
            if record is None or not record["authkey"]:
                return [factory]
            return [bytes.fromhex(record["authkey"]), factory]

    def import_records(self, records: list[dict]) -> tuple[int, int]:
        """Import backup devices; state, last_seen_ms and a missing authkey of a known device are kept."""
        if not isinstance(records, list):
            raise ValueError("records must be a list")
        clean = [_normalize_record(item) for item in records]
        with self._lock:
            snapshot = dict(self._devices)
            try:
                for record in clean:
                    old = self._devices.get(record["mac"])
                    if old is not None:
                        record["state"] = old["state"]
                        record["last_seen_ms"] = old["last_seen_ms"]
                        if not record["authkey"]:
                            record["authkey"] = old["authkey"]
                    self._devices[record["mac"]] = record
                self._write()
            except Exception:
                self._devices = snapshot
                raise
        devices = len(clean)
        ports = sum(len(record["ports"]) for record in clean)
        logger.info("imported %d devices, %d ports", devices, ports)
        return devices, ports

    def __repr__(self) -> str:
        with self._lock:
            count = len(self._devices)
        return f"DeviceStore({str(self.path)!r}, {count} devices)"
