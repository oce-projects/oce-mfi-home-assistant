"""Measurements reported by mFi devices in the inform "alarm" list.

Flattens the alarm entries, keeps the energy counter increasing across counter
resets and stores the latest values per device and sensor. Kept in memory only.
"""
from __future__ import annotations

import logging
import threading
from copy import deepcopy

logger = logging.getLogger(__name__)

TAGS = ("output", "active_pwr", "v_rms", "i_rms", "pf", "energy_sum")
MAX_WH_PER_MS = 0.001
RESET_RATIO = 0.9


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def flatten_alarm(alarm: list) -> list[dict]:
    """Return one flat dict per measurement; entries inherit the parent fields."""
    if not isinstance(alarm, list):
        return []
    flat: list[dict] = []
    for item in alarm:
        if not isinstance(item, dict):
            logger.debug("skipped alarm item that is not a dict: %r", item)
            continue
        parent = {key: value for key, value in item.items() if key != "entries"}
        entries = item.get("entries")
        if not isinstance(entries, list) or not entries:
            flat.append(parent)
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                logger.debug("skipped alarm entry that is not a dict: %r", entry)
                continue
            flat.append({**parent, **entry})
    return flat


class EnergyCounter:
    """Cumulative energy per sensor, kept increasing across counter resets.

    Not thread-safe: Measurements calls it under its own lock.
    """

    def __init__(self) -> None:
        self._sensors: dict[str, dict[str, float]] = {}

    def update(self, sensor_id: str, value_wh: float, time_ms: int) -> float:
        state = self._sensors.get(sensor_id)
        if state is None:
            self._sensors[sensor_id] = {"last": value_wh, "last_time": time_ms, "base": 0.0}
            return value_wh
        last = state["last"]
        if value_wh < RESET_RATIO * last:
            state["base"] += last
        elif value_wh > last and (
            time_ms <= state["last_time"]
            or (value_wh - last) / (time_ms - state["last_time"]) > MAX_WH_PER_MS
        ):
            logger.debug("discarded energy jump for %s", sensor_id)
            return state["base"] + last
        state["last"] = value_wh
        state["last_time"] = time_ms
        return state["base"] + value_wh


class Measurements:
    """Latest measurements per device, shaped as {sensor_id: {tag: value}}."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counter = EnergyCounter()
        self._latest: dict[str, dict[str, dict[str, float]]] = {}

    def ingest(self, mac: str, payload: dict, now_ms: int) -> None:
        items = flatten_alarm(payload.get("alarm", []))
        with self._lock:
            for item in items:
                sensor_id = item.get("sId")
                tag = item.get("tag")
                val = item.get("val")
                if not isinstance(sensor_id, str) or tag not in TAGS or not _is_number(val):
                    continue
                if tag == "energy_sum":
                    time_ms = item.get("time") or now_ms
                    if not _is_number(time_ms):
                        logger.debug("skipped energy value with bad time for %s", sensor_id)
                        continue
                    val = float(self._counter.update(sensor_id, float(val), int(time_ms)))
                self._latest.setdefault(mac, {}).setdefault(sensor_id, {})[tag] = val

    def latest(self, mac: str) -> dict:
        with self._lock:
            return deepcopy(self._latest.get(mac, {}))
