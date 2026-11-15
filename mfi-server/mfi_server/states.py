"""In-memory connection states of the mFi devices.

A device is "connected" while its last inform is at most LOST_AFTER_S seconds
old, "lost" after that, and "unknown" if it never informed. The states are not
written to disk: devices.json keeps the import values only.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

logger = logging.getLogger(__name__)

CONNECTED = 1
LOST_AFTER_S = 120


class DeviceStates:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._last_seen: dict[str, float] = {}

    def seen(self, mac: str) -> None:
        with self._lock:
            self._last_seen[mac] = self._clock()

    def state(self, mac: str) -> str:
        with self._lock:
            last = self._last_seen.get(mac)
            if last is None:
                return "unknown"
            if self._clock() - last <= LOST_AFTER_S:
                return "connected"
            return "lost"

    def lost_devices(self) -> list[str]:
        with self._lock:
            now = self._clock()
            return sorted(
                mac for mac, last in self._last_seen.items() if now - last > LOST_AFTER_S
            )

    def last_seen(self, mac: str) -> float | None:
        with self._lock:
            return self._last_seen.get(mac)
