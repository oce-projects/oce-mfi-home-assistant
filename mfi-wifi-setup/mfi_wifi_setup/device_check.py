"""Device check of the setup window: is the device reachable, and does it answer?

Reads GET /status.cgi through a connection supplied by the caller (the window
uses a TLS 1.0 connection, the tests use a plain HTTP one) and maps the outcome
to one of three states. Standard library only; no tkinter.
"""
from __future__ import annotations

import errno
import http.client
import json
import socket
from collections.abc import Callable
from dataclasses import dataclass

CHECK_INTERVAL_S = 2

STATE_FOUND = "found"
STATE_NOT_ON_NETWORK = "not_on_network"
STATE_NOT_ANSWERING = "not_answering"

NOT_ON_NETWORK_ERRNOS = {errno.ECONNREFUSED, errno.ENETUNREACH, errno.EHOSTUNREACH, errno.EHOSTDOWN}


@dataclass
class DeviceStatus:
    state: str
    model: str = ""
    firmware: str = ""


def _text(value: object) -> str:
    """Only text is kept: a device field of another type is shown as empty."""
    return value if isinstance(value, str) else ""


def read_status(
    connect: Callable[[], http.client.HTTPConnection],
    path: str = "/status.cgi",
    timeout: int = 5,
) -> DeviceStatus:
    """Ask the device for its status and map the outcome to one of the three states."""
    try:
        conn = connect()
        conn.timeout = timeout
        try:
            conn.request("GET", path)
            data = conn.getresponse().read()
        finally:
            conn.close()
        payload = json.loads(data)
    except (socket.timeout, TimeoutError):
        return DeviceStatus(STATE_NOT_ANSWERING)
    except OSError as exc:
        if exc.errno in NOT_ON_NETWORK_ERRNOS:
            return DeviceStatus(STATE_NOT_ON_NETWORK)
        return DeviceStatus(STATE_NOT_ANSWERING)
    except ValueError:
        return DeviceStatus(STATE_NOT_ANSWERING)
    if not isinstance(payload, dict):
        return DeviceStatus(STATE_NOT_ANSWERING)
    host = payload.get("host")
    if not isinstance(host, dict):
        host = {}
    return DeviceStatus(
        STATE_FOUND,
        model=_text(host.get("hostname")),
        firmware=_text(host.get("fwversion")),
    )
