"""Offline tests for mfi_server.messages: noop and mfi-output response payloads."""
from __future__ import annotations

import unittest

from mfi_server.messages import noop, output_command


class TestMessages(unittest.TestCase):
    def test_noop_default_interval(self):
        self.assertEqual(
            noop(1700000000000),
            {"_type": "noop", "interval": 10, "server_time_in_utc": "1700000000000"},
        )

    def test_noop_custom_interval(self):
        message = noop(5, interval=3)
        self.assertEqual(message["interval"], 3)
        self.assertEqual(message["server_time_in_utc"], "5")

    def test_output_command_on(self):
        self.assertEqual(
            output_command("02aabbccdd01", 1, "sensor1", 1, 5),
            {
                "_type": "cmd",
                "cmd": "mfi-output",
                "mac": "02aabbccdd01",
                "port": 1,
                "sId": "sensor1",
                "val": 1,
                "server_time_in_utc": "5",
            },
        )

    def test_output_command_off(self):
        message = output_command("02aabbccdd02", 2, "sensor2", 0, 7)
        self.assertEqual(message["val"], 0)
        self.assertEqual(message["port"], 2)
        self.assertEqual(message["server_time_in_utc"], "7")


if __name__ == "__main__":
    unittest.main()
