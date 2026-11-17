"""Queue of mfi-output commands: one pending command per device port.

The queue is a plain store and does not know the device states. The rule
"deliver only to a connected device" lives in server.py.
"""
from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)


class CommandQueue:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._queues: dict[str, dict[int, dict]] = {}
        self._upgrades: dict[str, dict] = {}

    def put(self, mac: str, port: int, sensor_id: str, value: int) -> None:
        if type(value) is not int or value not in (0, 1):
            raise ValueError("value must be 0 or 1")
        if type(port) is not int or port < 1:
            raise ValueError("port must be an integer >= 1")
        if not isinstance(sensor_id, str) or not sensor_id:
            raise ValueError("sensor_id must be a non-empty string")
        command = {"mac": mac, "port": port, "sensor_id": sensor_id, "value": value}
        with self._lock:
            queue = self._queues.get(mac)
            if queue is None:
                queue = self._queues[mac] = {}
            # Replacing a command moves it to the end of the queue.
            queue.pop(port, None)
            queue[port] = command

    def pop(self, mac: str) -> dict | None:
        with self._lock:
            queue = self._queues.get(mac)
            if not queue:
                return None
            port = next(iter(queue))
            command = queue.pop(port)
            if not queue:
                del self._queues[mac]
            return command

    def pending(self, mac: str) -> int:
        with self._lock:
            queue = self._queues.get(mac)
            return len(queue) if queue else 0

    def put_upgrade(self, mac: str, path: str, version: str) -> None:
        if not isinstance(path, str) or not path:
            raise ValueError("path must be a non-empty string")
        if not isinstance(version, str) or not version:
            raise ValueError("version must be a non-empty string")
        with self._lock:
            self._upgrades[mac] = {"mac": mac, "path": path, "version": version}

    def pop_upgrade(self, mac: str) -> dict | None:
        with self._lock:
            return self._upgrades.pop(mac, None)

    def pending_upgrade(self, mac: str) -> bool:
        with self._lock:
            return mac in self._upgrades
