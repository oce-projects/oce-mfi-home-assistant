"""Tests of mfi_server_next.stats: aggregates, energy counter, cost and retention (EPIC-07).

Standard library only, offline. The history table statements are copied from
mfi_server/history.py (CA5); that module is not imported.
"""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from mfi_server_next.stats import Aggregator

MAC = "aabbccddeeff"
SENSOR = "1"
MINUTE_MS = 60000
HISTORY_STATEMENTS = (
    "CREATE TABLE IF NOT EXISTS measurement("
    "mac TEXT NOT NULL, sensor_id TEXT NOT NULL, tag TEXT NOT NULL, "
    "time_ms INTEGER NOT NULL, value REAL NOT NULL)",
    "CREATE INDEX IF NOT EXISTS measurement_series ON measurement(mac, sensor_id, tag, time_ms)",
    "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', '1')",
)


class TestAggregates(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.agg = Aggregator(self.conn)

    def add_two_hours(self):
        for i in range(120):
            self.agg.add(MAC, SENSOR, "active_pwr", float(i), i * MINUTE_MS)

    def test_two_hours_give_120_minute_8_quarterhour_and_2_hour_buckets(self):
        self.add_two_hours()
        self.assertEqual(len(self.agg.read("minute")), 120)
        self.assertEqual(len(self.agg.read("quarterhour")), 8)
        self.assertEqual(len(self.agg.read("hour")), 2)

    def test_first_quarterhour_bucket_has_right_min_max_avg_last(self):
        self.add_two_hours()
        first = self.agg.read("quarterhour")[0]
        self.assertEqual(first["start_ms"], 0)
        self.assertEqual(first["count"], 15)
        self.assertEqual(first["min"], 0.0)
        self.assertEqual(first["max"], 14.0)
        self.assertEqual(first["avg"], 7.0)
        self.assertEqual(first["last"], 14.0)
        self.assertIsNone(first["energy"])

    def test_empty_store_gives_empty_list(self):
        self.assertEqual(self.agg.read("day"), [])

    def test_unknown_interval_raises_value_error(self):
        with self.assertRaises(ValueError):
            self.agg.read("week")

    def test_day_buckets_split_readings_one_day_apart(self):
        self.agg.add(MAC, SENSOR, "active_pwr", 1.0, 0)
        self.agg.add(MAC, SENSOR, "active_pwr", 2.0, 86400000)
        rows = self.agg.read("day")
        self.assertEqual([row["start_ms"] for row in rows], [0, 86400000])

    def test_time_filter_is_inclusive(self):
        for i in range(5):
            self.agg.add(MAC, SENSOR, "active_pwr", float(i), i * MINUTE_MS)
        rows = self.agg.read("minute", from_ms=MINUTE_MS, to_ms=3 * MINUTE_MS)
        self.assertEqual([row["last"] for row in rows], [1.0, 2.0, 3.0])

    def test_energy_counter_reset_gives_no_negative_consumption(self):
        for time_ms, value in ((0, 100.0), (60000, 200.0), (120000, 50.0), (180000, 90.0)):
            self.agg.add(MAC, SENSOR, "energy_sum", value, time_ms)
        bucket = self.agg.read("hour")[0]
        self.assertEqual(bucket["tag"], "energy_sum")
        self.assertAlmostEqual(bucket["energy"], 140.0)
        self.assertGreaterEqual(bucket["energy"], 0.0)


class TestCost(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.agg = Aggregator(self.conn, price=0.25, currency="USD")

    def test_ten_kwh_at_quarter_price_costs_two_fifty_in_usd(self):
        self.agg.add(MAC, SENSOR, "energy_sum", 0.0, 0)
        self.agg.add(MAC, SENSOR, "energy_sum", 10000.0, 3600000)
        cost = self.agg.monthly_cost(MAC, SENSOR, 0, 3600000)
        self.assertAlmostEqual(cost["energy_kwh"], 10.0)
        self.assertAlmostEqual(cost["cost"], 2.5)
        self.assertEqual(cost["currency"], "USD")
        self.assertAlmostEqual(self.agg.cost(10), 2.5)


class TestRetention(unittest.TestCase):
    NOW = 1700000000.0

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.agg = Aggregator(self.conn, retention_days=30, clock=lambda: self.NOW)

    def test_rows_older_than_retention_are_removed(self):
        old_ms = int((self.NOW - 31 * 86400) * 1000)
        recent_ms = int((self.NOW - 86400) * 1000)
        self.agg.add(MAC, SENSOR, "active_pwr", 1.0, old_ms)
        self.agg.add(MAC, SENSOR, "active_pwr", 2.0, recent_ms)
        self.assertEqual(self.agg.purge(), 1)
        rows = self.agg.read("minute")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["last"], 2.0)
        self.assertEqual(rows[0]["start_ms"], (recent_ms // MINUTE_MS) * MINUTE_MS)


class TestExistingHistoryDatabase(unittest.TestCase):
    def test_history_file_of_today_stays_readable(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "history.sqlite3"
            conn = sqlite3.connect(str(path))
            try:
                for statement in HISTORY_STATEMENTS:
                    conn.execute(statement)
                conn.execute(
                    "INSERT INTO measurement(mac, sensor_id, tag, time_ms, value) VALUES (?, ?, ?, ?, ?)",
                    (MAC, SENSOR, "active_pwr", 1700000000000, 5.0),
                )
                conn.commit()
                agg = Aggregator(conn)
                self.assertEqual(agg.read("minute"), [])
                count = conn.execute("SELECT COUNT(*) FROM measurement").fetchone()[0]
                self.assertEqual(count, 1)
                agg.add(MAC, SENSOR, "active_pwr", 3.0, 1700000000000)
                rows = agg.read("minute")
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["count"], 1)
                self.assertEqual(rows[0]["last"], 3.0)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
