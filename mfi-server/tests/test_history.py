"""Tests for the sqlite3 measurement history."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mfi_server.history import History

MAC = "02aabbccdd01"


class TestHistory(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "h.sqlite3"

    def test_store_and_query_in_time_order(self):
        h = History(self.path, clock=lambda: 0.0)
        self.addCleanup(h._conn.close)
        h.record(MAC, "s1", "active_pwr", 12.5, 1000)
        h.record(MAC, "s1", "active_pwr", 13.0, 3000)
        h.record(MAC, "s1", "active_pwr", 11.0, 2000)
        self.assertEqual(
            h.query(MAC, "s1", "active_pwr", 0, 5000),
            [(1000, 12.5), (2000, 11.0), (3000, 13.0)],
        )

    def test_equal_value_within_60s_is_not_saved(self):
        h = History(self.path, clock=lambda: 0.0)
        self.addCleanup(h._conn.close)
        h.record(MAC, "s1", "v_rms", 230.0, 1000)
        h.record(MAC, "s1", "v_rms", 230.0, 1000 + 59000)
        self.assertEqual(h.query(MAC, "s1", "v_rms", 0, 100000), [(1000, 230.0)])
        h.record(MAC, "s1", "v_rms", 230.0, 1000 + 61000)
        self.assertEqual(
            h.query(MAC, "s1", "v_rms", 0, 100000),
            [(1000, 230.0), (62000, 230.0)],
        )

    def test_purge_deletes_rows_older_than_retention(self):
        now = [0.0]
        h = History(self.path, retention_days=30, clock=lambda: now[0])
        self.addCleanup(h._conn.close)
        h.record(MAC, "s1", "pf", 0.5, 0)
        h.record(MAC, "s1", "pf", 0.9, int((31 * 86400 - 86400) * 1000))
        now[0] = 31 * 86400
        deleted = h.purge()
        self.assertEqual(deleted, 1)
        self.assertEqual(
            h.query(MAC, "s1", "pf", 0, 10**13),
            [(int((31 * 86400 - 86400) * 1000), 0.9)],
        )

    def test_sql_injection_tag_returns_empty_and_keeps_table(self):
        h = History(self.path, clock=lambda: 0.0)
        self.addCleanup(h._conn.close)
        h.record(MAC, "s1", "pf", 0.9, 1000)
        result = h.query(MAC, "s1", "x'; DROP TABLE measurement;--", 0, 5000)
        self.assertEqual(result, [])
        self.assertEqual(h.query(MAC, "s1", "pf", 0, 5000), [(1000, 0.9)])


if __name__ == "__main__":
    unittest.main()
