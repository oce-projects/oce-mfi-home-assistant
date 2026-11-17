"""Firmware upgrade of the devices: one at a time, requested by the user only.

UpgradeManager.request() queues the upgrade command for one connected device
whose firmware is older than the archive. The command is delivered with the
device's next inform (see server.py). The upgrade is confirmed by an inform
that reports the archive version or a newer one within UPGRADE_TIMEOUT_S
seconds after the command was sent. The state is in memory only and is lost
on restart. Standard library only.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from mfi_server.commands import CommandQueue
from mfi_server.firmware import FirmwareArchive, compare_versions, parse_version
from mfi_server.states import DeviceStates

logger = logging.getLogger(__name__)

UPGRADE_TIMEOUT_S = 180


class UpgradeError(Exception):
    """A refused upgrade request; code is the reason, sent to the API client."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _reached(device: str | None, target: str) -> bool:
    """Return True when the device version is readable and not older than target (zero-padded)."""
    device_numbers = parse_version(device)
    target_numbers = parse_version(target)
    if device_numbers is None or target_numbers is None:
        return False
    width = max(len(device_numbers), len(target_numbers))
    device_padded = device_numbers + (0,) * (width - len(device_numbers))
    target_padded = target_numbers + (0,) * (width - len(target_numbers))
    return device_padded >= target_padded


class UpgradeManager:
    """Holds the one active upgrade and the results of the finished ones."""

    def __init__(
        self,
        archive: FirmwareArchive,
        states: DeviceStates,
        queue: CommandQueue,
        clock: Callable[[], float] = time.monotonic,
        timeout_s: float = UPGRADE_TIMEOUT_S,
    ) -> None:
        self.archive = archive
        self._states = states
        self._queue = queue
        self._clock = clock
        self._timeout_s = timeout_s
        self._lock = threading.Lock()
        self._active: dict | None = None
        self._results: dict[str, str] = {}

    def request(self, record: dict) -> None:
        """Queue the upgrade of one device; raise UpgradeError with the reason when it is refused."""
        mac = record["mac"]
        with self._lock:
            self._evaluate()
            if not self.archive.available:
                raise UpgradeError("archive_unavailable")
            bundle = self.archive.bundle_for(record["model"])
            if bundle is None:
                raise UpgradeError("no_bundle")
            if self._states.state(mac) != "connected":
                raise UpgradeError("not_connected")
            comparison = compare_versions(self._states.version(mac), bundle["version"])
            if comparison == "unreadable":
                raise UpgradeError("unreadable_version")
            if comparison != "older":
                raise UpgradeError("not_older")
            if self._active is not None:
                raise UpgradeError("upgrade_in_progress")
            self._queue.put_upgrade(mac, bundle["path"], bundle["version"])
            self._active = {
                "mac": mac,
                "path": bundle["path"],
                "version": bundle["version"],
                "status": "requested",
                "requested_at": self._clock(),
                "sent_at": None,
            }
            self._results.pop(mac, None)

    def mark_sent(self, mac: str) -> None:
        """Record that the upgrade command was written in an inform answer; the 180 s window starts now."""
        with self._lock:
            active = self._active
            if active is not None and active["mac"] == mac and active["status"] == "requested":
                active["status"] = "sent"
                active["sent_at"] = self._clock()

    def on_inform(self, mac: str) -> None:
        """Re-check the active upgrade after an inform of any device."""
        with self._lock:
            self._evaluate()

    def status(self, mac: str) -> str | None:
        """Return the upgrade status of a device: requested, sent, updated, not_confirmed, or None."""
        with self._lock:
            self._evaluate()
            active = self._active
            if active is not None and active["mac"] == mac:
                return active["status"]
            return self._results.get(mac)

    def firmware_view(self, record: dict) -> dict:
        """Return the firmware block of a device for the web API."""
        mac = record["mac"]
        device_version = self._states.version(mac)
        bundle = self.archive.bundle_for(record["model"])
        if not self.archive.available:
            comparison = "no_archive"
        elif bundle is None:
            comparison = "no_bundle"
        else:
            comparison = compare_versions(device_version, bundle["version"])
        return {
            "device_version": device_version or "",
            "archive_version": self.archive.archive_version(),
            "available": self.archive.available,
            "comparison": comparison,
            "upgrade_status": self.status(mac),
        }

    def _evaluate(self) -> None:
        """Finish the active upgrade when it is confirmed, never delivered, or its window is over. The caller holds the lock."""
        active = self._active
        if active is None:
            return
        if active["status"] == "requested":
            if self._clock() - active["requested_at"] > self._timeout_s:
                self._queue.pop_upgrade(active["mac"])
                self._finalize("not_confirmed")
            return
        if active["status"] != "sent":
            return
        if _reached(self._states.version(active["mac"]), active["version"]):
            self._finalize("updated")
        elif self._clock() - active["sent_at"] > self._timeout_s:
            self._finalize("not_confirmed")

    def _finalize(self, status: str) -> None:
        """Store the result of the active upgrade and free the one-at-a-time lock. The caller holds the lock."""
        active = self._active
        self._results[active["mac"]] = status
        self._active = None
        logger.info("firmware upgrade finished: %s", status)
