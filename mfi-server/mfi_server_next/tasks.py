"""Queue of commands waiting for the next inform of each device.

Clean room, standard library only. The wake-up packet makes a device inform at
once; only its first two bytes are known, see build_wakeup().
"""
from __future__ import annotations

import logging
import socket
import threading

logger = logging.getLogger(__name__)

WAKEUP_PORT = 3478
WAKEUP_LEN = 20
OUTPUT_CMD = "mfi-output"
MAX_QUEUE_PER_MAC = 64
NTP_CFG_KEY = "ntpclient.1.server"
TIMEZONE_CFG_KEY = "system.timezone"


def build_wakeup() -> bytes:
    # UNVERIFIED (needs device test R-POWER): only the first two bytes 0x88 0x88 are
    # specified; the 18 bytes after them are zero here and not checked on a device.
    return b"\x88\x88" + bytes(WAKEUP_LEN - 2)


def build_output_command(mac, port, val, **extra) -> dict:
    """Return the command that sets one port of a device to val (1 on, 0 off)."""
    return {"_type": "cmd", "cmd": OUTPUT_CMD, "mac": mac, "port": port, "val": val, **extra}


def _valid_cfg_value(value):
    return isinstance(value, str) and value and not any(c in value for c in ("\n", "\r", "=", "\x00"))


def build_system_cfg(*, ntp_server=None, timezone=None) -> str:
    """Return the system_cfg text of a setparam: one key=value line per given value, sorted by key."""
    values = {}
    if _valid_cfg_value(ntp_server):
        values[NTP_CFG_KEY] = ntp_server
    if _valid_cfg_value(timezone):
        values[TIMEZONE_CFG_KEY] = timezone
    return "\n".join(f"{key}={values[key]}" for key in sorted(values))


def build_setparam(cfgversion=None, *, system_cfg=None, **extra) -> dict:
    """Return a setparam message; cfgversion and system_cfg are added only when given."""
    message = {"_type": "setparam"}
    if cfgversion is not None:
        message["cfgversion"] = cfgversion
    if isinstance(system_cfg, str) and system_cfg:
        message["system_cfg"] = system_cfg
    message.update(extra)
    return message


def send_wakeup(sock: socket.socket, ip: str, port: int) -> None:
    """Send the wake-up packet to ip:port; a send error is logged, never raised."""
    try:
        sock.sendto(build_wakeup(), (ip, port))
    except OSError as exc:
        logger.warning("wake-up to %s:%s failed: %s", ip, port, exc)


class TaskQueue:
    """Commands queued for the devices, delivered on their next inform."""

    def __init__(self):
        self._lock = threading.Lock()
        self._queues: dict[str, list[dict]] = {}

    def enqueue(self, task):
        """Add a command for task["mac"]; a new mfi-output replaces a queued one for the same port. At most MAX_QUEUE_PER_MAC commands are kept per device; the oldest is dropped when the cap is passed."""
        if not isinstance(task, dict) or not isinstance(task.get("mac"), str):
            raise ValueError("task needs a mac address")
        item = dict(task)
        with self._lock:
            queue = self._queues.setdefault(item["mac"], [])
            if item.get("cmd") == OUTPUT_CMD:
                for index, queued in enumerate(queue):
                    if queued.get("cmd") == OUTPUT_CMD and queued.get("port") == item.get("port"):
                        queue[index] = item
                        return
            queue.append(item)
            if len(queue) > MAX_QUEUE_PER_MAC:
                # Bound memory per device: drop the oldest queued command.
                queue.pop(0)

    def pop_for_mac(self, mac=None):
        """Remove and return the oldest queued command of mac, or None when there is none."""
        with self._lock:
            queue = self._queues.get(mac)
            if not queue:
                return None
            task = queue.pop(0)
            if not queue:
                del self._queues[mac]
            return task
