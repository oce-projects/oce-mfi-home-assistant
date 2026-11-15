"""Persistent history of the measurements in sqlite3, kept for retention_days.

History is a Measurements listener: record() has the signature of
Measurements.add_listener callbacks. Standard library only.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

DUPLICATE_WINDOW_MS = 60000
SECONDS_PER_DAY = 86400
MS_PER_SECOND = 1000


class History:
    """Measurement history in one sqlite3 file, guarded by a lock."""

    def __init__(self, path: Path, retention_days: int = 30, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._retention_days = retention_days
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        with self._lock:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS measurement("
                "mac TEXT NOT NULL, sensor_id TEXT NOT NULL, tag TEXT NOT NULL, "
                "time_ms INTEGER NOT NULL, value REAL NOT NULL)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS measurement_series ON measurement(mac, sensor_id, tag, time_ms)"
            )
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            self._conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', '1')")
            self._conn.commit()

    def record(self, mac: str, sensor_id: str, tag: str, value: float, time_ms: int) -> None:
        """Store one value unless it repeats the last stored value within 60 s."""
        with self._lock:
            row = self._conn.execute(
                "SELECT value, time_ms FROM measurement WHERE mac=? AND sensor_id=? AND tag=? "
                "ORDER BY time_ms DESC LIMIT 1",
                (mac, sensor_id, tag),
            ).fetchone()
            if row is not None:
                last_value, last_time = row
                if last_value == value and (time_ms - last_time) < DUPLICATE_WINDOW_MS:
                    return
            self._conn.execute(
                "INSERT INTO measurement(mac, sensor_id, tag, time_ms, value) VALUES (?, ?, ?, ?, ?)",
                (mac, sensor_id, tag, time_ms, value),
            )
            self._conn.commit()

    def query(
        self, mac: str, sensor_id: str, tag: str, from_ms: int, to_ms: int, limit: int = 5000
    ) -> list[tuple[int, float]]:
        """Return (time_ms, value) rows of one series in time order, between from_ms and to_ms."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT time_ms, value FROM measurement WHERE mac=? AND sensor_id=? AND tag=? "
                "AND time_ms BETWEEN ? AND ? ORDER BY time_ms ASC LIMIT ?",
                (mac, sensor_id, tag, from_ms, to_ms, limit),
            ).fetchall()
        return [(int(t), float(v)) for t, v in rows]

    def purge(self) -> int:
        """Delete rows older than the retention period; return how many were deleted."""
        cutoff = int((self._clock() - self._retention_days * SECONDS_PER_DAY) * MS_PER_SECOND)
        with self._lock:
            cur = self._conn.execute("DELETE FROM measurement WHERE time_ms < ?", (cutoff,))
            self._conn.commit()
            deleted = cur.rowcount
        logger.info("history purge: %d rows older than the retention period deleted", deleted)
        return deleted
