"""JSON messages the server sends back in an inform response.

Only the heartbeat (noop), the mfi-output command and the upgrade command are built here.
A factory reset message is never built by this server.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

NOOP_INTERVAL_S = 10


def noop(now_ms: int, interval: int = NOOP_INTERVAL_S) -> dict:
    """Heartbeat: the device informs again after `interval` seconds."""
    return {"_type": "noop", "interval": interval, "server_time_in_utc": str(now_ms)}


def output_command(mac_hex: str, port: int, sensor_id: str, value: int, now_ms: int) -> dict:
    """Switch one output: value 1 is on, 0 is off."""
    return {
        "_type": "cmd",
        "cmd": "mfi-output",
        "mac": mac_hex,
        "port": port,
        "sId": sensor_id,
        "val": value,
        "server_time_in_utc": str(now_ms),
    }


def upgrade_command(url: str, version: str) -> dict:
    """Firmware upgrade: the device downloads the archive at url and installs version."""
    return {"_type": "upgrade", "url": url, "version": version}
