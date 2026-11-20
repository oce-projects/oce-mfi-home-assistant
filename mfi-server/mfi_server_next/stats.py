"""Statistics: aggregates of the raw readings per interval, energy as a counter, and cost.

Standard library only. The raw table is kept in history.sqlite3 next to the
measurement table of mfi_server.history; this module creates only raw and its index.
"""
import time

INTERVAL_SECONDS = {"minute": 60, "quarterhour": 900, "hour": 3600, "day": 86400}
ENERGY_TAG = "energy_sum"
WH_PER_KWH = 1000.0
SECONDS_PER_DAY = 86400
MS_PER_SECOND = 1000


def _consumed(previous, value):
    """Energy used between two readings of one counter; the first reading and a reset give 0.0."""
    if previous is None:
        return 0.0
    return max(0.0, value - previous)


class Aggregator:
    """Stores raw readings and reads aggregates per interval, energy and cost."""

    def __init__(self, conn, *, retention_days=30, price=0.0, currency="EUR", clock=time.time):
        self.conn = conn
        self.retention_days = retention_days
        self.price = float(price)
        self.currency = currency
        self.clock = clock
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS raw("
            "mac TEXT NOT NULL, sensor_id TEXT NOT NULL, tag TEXT NOT NULL, "
            "time_ms INTEGER NOT NULL, value REAL NOT NULL)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS raw_series ON raw(mac, sensor_id, tag, time_ms)"
        )
        self.conn.commit()

    def add(self, mac, sensor_id, tag, value, time_ms):
        """Store one raw reading."""
        self.conn.execute(
            "INSERT INTO raw(mac, sensor_id, tag, time_ms, value) VALUES (?, ?, ?, ?, ?)",
            (mac, sensor_id, tag, int(time_ms), float(value)),
        )
        self.conn.commit()

    def read(self, interval, mac=None, sensor_id=None, tag=None, from_ms=None, to_ms=None):
        """Return one aggregate dict per series and bucket, sorted by series and start_ms."""
        if interval not in INTERVAL_SECONDS:
            raise ValueError(f"unknown interval: {interval!r}")
        clauses = []
        params = []
        for column, value in (("mac", mac), ("sensor_id", sensor_id), ("tag", tag)):
            if value is not None:
                clauses.append(column + " = ?")
                params.append(value)
        if from_ms is not None:
            clauses.append("time_ms >= ?")
            params.append(int(from_ms))
        if to_ms is not None:
            clauses.append("time_ms <= ?")
            params.append(int(to_ms))
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self.conn.execute(
            "SELECT mac, sensor_id, tag, time_ms, value FROM raw" + where
            + " ORDER BY mac, sensor_id, tag, time_ms",
            params,
        ).fetchall()
        width = INTERVAL_SECONDS[interval] * MS_PER_SECOND
        buckets = {}
        series = None
        previous = None
        for row_mac, row_sensor, row_tag, time_ms, value in rows:
            if (row_mac, row_sensor, row_tag) != series:
                series = (row_mac, row_sensor, row_tag)
                previous = None
            key = series + ((time_ms // width) * width,)
            bucket = buckets.get(key)
            if bucket is None:
                bucket = {"values": [], "last_time": time_ms, "last": value, "energy": 0.0}
                buckets[key] = bucket
            bucket["values"].append(value)
            if time_ms >= bucket["last_time"]:
                bucket["last_time"] = time_ms
                bucket["last"] = value
            if row_tag == ENERGY_TAG:
                bucket["energy"] += _consumed(previous, value)
            previous = value
        result = []
        for key in sorted(buckets):
            row_mac, row_sensor, row_tag, start_ms = key
            bucket = buckets[key]
            values = bucket["values"]
            result.append({
                "mac": row_mac,
                "sensor_id": row_sensor,
                "tag": row_tag,
                "start_ms": start_ms,
                "min": min(values),
                "max": max(values),
                "avg": sum(values) / len(values),
                "last": bucket["last"],
                "count": len(values),
                "energy": bucket["energy"] if row_tag == ENERGY_TAG else None,
            })
        return result

    def monthly_cost(self, mac, sensor_id, from_ms, to_ms):
        """Energy (kWh) and cost of one outlet between from_ms and to_ms, in the configured currency."""
        rows = self.conn.execute(
            "SELECT time_ms, value FROM raw WHERE mac = ? AND sensor_id = ? AND tag = ? "
            "AND time_ms >= ? AND time_ms <= ? ORDER BY time_ms",
            (mac, sensor_id, ENERGY_TAG, int(from_ms), int(to_ms)),
        ).fetchall()
        total_wh = 0.0
        previous = None
        for _, value in rows:
            total_wh += _consumed(previous, value)
            previous = value
        energy_kwh = total_wh / WH_PER_KWH
        return {"energy_kwh": energy_kwh, "cost": energy_kwh * self.price, "currency": self.currency}

    def cost(self, energy_kwh):
        """Cost of an amount of energy in kWh at the configured price."""
        return energy_kwh * self.price

    def purge(self):
        """Delete readings older than the retention period; return how many were deleted."""
        cutoff_ms = int((self.clock() - self.retention_days * SECONDS_PER_DAY) * MS_PER_SECOND)
        cur = self.conn.execute("DELETE FROM raw WHERE time_ms < ?", (cutoff_ms,))
        self.conn.commit()
        return cur.rowcount
