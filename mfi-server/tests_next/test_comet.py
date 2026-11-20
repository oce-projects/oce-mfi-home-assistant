"""Tests of the Comet buffer long poll (CA5). Standard library only, offline."""
import threading
import time
import unittest

from mfi_server_next.comet import CometBuffer


class TestCometBuffer(unittest.TestCase):
    def test_two_appends_read_after_zero_returns_both_in_order(self):
        buf = CometBuffer()
        first = buf.append("a")
        second = buf.append("b")
        self.assertEqual(first, 1)
        self.assertEqual(second, 2)
        cursor, messages = buf.read_after(0)
        self.assertEqual(messages, ["a", "b"])
        self.assertEqual(cursor, second)

    def test_read_after_latest_with_timeout_returns_empty_and_same_cursor(self):
        buf = CometBuffer()
        buf.append("a")
        current = buf.latest_cursor()
        started = time.monotonic()
        cursor, messages = buf.read_after(current, timeout=0.05)
        elapsed = time.monotonic() - started
        self.assertEqual(messages, [])
        self.assertEqual(cursor, current)
        self.assertGreaterEqual(elapsed, 0.04)

    def test_read_after_first_returns_only_second(self):
        buf = CometBuffer()
        first = buf.append("a")
        buf.append("b")
        cursor, messages = buf.read_after(first)
        self.assertEqual(messages, ["b"])
        self.assertEqual(cursor, 2)

    def test_small_maxlen_keeps_only_newest_three_of_five(self):
        buf = CometBuffer(maxlen=3)
        for value in range(1, 6):
            buf.append(value)
        cursor, messages = buf.read_after(0)
        self.assertEqual(messages, [3, 4, 5])
        self.assertEqual(cursor, 5)

    def test_append_wakes_a_waiting_reader(self):
        buf = CometBuffer()
        latest = buf.latest_cursor()
        worker = threading.Thread(target=lambda: (time.sleep(0.05), buf.append("new")))
        worker.start()
        try:
            cursor, messages = buf.read_after(latest, timeout=1.0)
        finally:
            worker.join()
        self.assertEqual(messages, ["new"])
        self.assertEqual(cursor, 1)

    def test_empty_buffer_returns_zero_cursor_and_no_messages(self):
        buf = CometBuffer()
        self.assertEqual(buf.latest_cursor(), 0)
        self.assertEqual(buf.read_after(0), (0, []))

    def test_none_and_non_ascii_messages_are_kept_as_given(self):
        buf = CometBuffer()
        buf.append(None)
        buf.append("città ✓")
        cursor, messages = buf.read_after(0)
        self.assertEqual(messages, [None, "città ✓"])
        self.assertEqual(cursor, 2)


if __name__ == "__main__":
    unittest.main()
