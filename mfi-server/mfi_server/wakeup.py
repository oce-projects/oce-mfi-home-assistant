"""Wake-up packet that makes a device inform at once.

The controller sends it to connect_request_ip:connect_request_port, taken from
the inform payload. The specification only says 20 bytes starting with
0x88 0x88; the other 18 bytes are zero here.
UNVERIFIED: the content of the other 18 bytes is not checked on a real device.
"""
from __future__ import annotations

import logging
import socket

logger = logging.getLogger(__name__)

WAKEUP_LEN = 20


def build_wakeup() -> bytes:
    return b"\x88\x88" + bytes(WAKEUP_LEN - 2)


def wakeup_target(payload: dict) -> tuple[str, int] | None:
    ip = payload.get("connect_request_ip")
    if not isinstance(ip, str) or not ip:
        return None
    try:
        port = int(payload.get("connect_request_port"))
    except (TypeError, ValueError) as exc:
        logger.debug("no valid wake-up port in payload: %s", exc)
        return None
    if not 1 <= port <= 65535:
        return None
    return ip, port


def send_wakeup(sock: socket.socket, ip: str, port: int) -> None:
    if not ip or not isinstance(port, int) or not 1 <= port <= 65535:
        logger.debug("wake-up skipped: no valid target")
        return
    try:
        sock.sendto(build_wakeup(), (ip, port))
    except OSError as exc:
        logger.warning("wake-up to %s:%s failed: %s", ip, port, exc)
