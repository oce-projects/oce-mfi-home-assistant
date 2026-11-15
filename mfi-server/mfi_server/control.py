"""Single entry point to command a mFi output: queue the command and wake the device up.

set_output checks the device and the port, queues the command for the next
inform and, when the device's connect_request address is known, sends it a
wake-up packet so the output changes at once. Standard library only.
"""
from __future__ import annotations

import logging
import socket

from mfi_server import wakeup
from mfi_server.commands import CommandQueue
from mfi_server.states import DeviceStates
from mfi_server.store import DeviceStore

logger = logging.getLogger(__name__)


class OutputControl:
    """Queues output commands and sends the wake-up packet when the device address is known."""

    def __init__(
        self,
        store: DeviceStore,
        states: DeviceStates,
        queue: CommandQueue,
        sock: socket.socket | None,
    ) -> None:
        self.store = store
        self.states = states
        self.queue = queue
        self.sock = sock

    def set_output(self, mac: str, port: int, value: int) -> None:
        """Queue ON (1) or OFF (0) for one port; raise KeyError or ValueError on bad input."""
        device = self.store.get(mac)
        if device is None:
            raise KeyError(mac)
        port_rec = next((p for p in device["ports"] if p["port"] == port), None)
        if port_rec is None:
            raise KeyError((mac, port))
        if value not in (0, 1):
            raise ValueError("value must be 0 or 1")
        self.queue.put(mac, port, port_rec["sensor_id"], value)
        target = self.states.wakeup_target(mac)
        if target is not None and self.sock is not None:
            wakeup.send_wakeup(self.sock, target[0], target[1])
