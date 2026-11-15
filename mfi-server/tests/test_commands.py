"""Tests for the mfi-output command queue (mfi_server.commands)."""
from __future__ import annotations

import unittest

from mfi_server.commands import CommandQueue

MAC = "02aabbccdd01"
OTHER = "02aabbccdd02"
UNUSED = "02aabbccdd03"


class TestCommandQueue(unittest.TestCase):
    def setUp(self):
        self.queue = CommandQueue()

    def test_same_port_replaces_previous_command(self):
        self.queue.put(MAC, 1, "sensor1", 1)
        self.queue.put(MAC, 1, "sensor1", 0)
        self.assertEqual(self.queue.pending(MAC), 1)
        self.assertEqual(
            self.queue.pop(MAC),
            {"mac": MAC, "port": 1, "sensor_id": "sensor1", "value": 0},
        )
        self.assertIsNone(self.queue.pop(MAC))
        self.assertEqual(self.queue.pending(MAC), 0)

    def test_replaced_command_goes_to_the_end(self):
        self.queue.put(MAC, 1, "sensor1", 1)
        self.queue.put(MAC, 2, "sensor2", 1)
        self.queue.put(MAC, 1, "sensor1", 0)
        self.assertEqual(self.queue.pop(MAC)["port"], 2)
        self.assertEqual(self.queue.pop(MAC)["value"], 0)
        self.assertIsNone(self.queue.pop(MAC))

    def test_different_ports_pop_in_put_order(self):
        self.queue.put(MAC, 1, "sensor1", 1)
        self.queue.put(MAC, 2, "sensor2", 0)
        self.assertEqual(self.queue.pending(MAC), 2)
        self.assertEqual(self.queue.pop(MAC)["port"], 1)
        self.assertEqual(self.queue.pop(MAC)["port"], 2)
        self.assertIsNone(self.queue.pop(MAC))

    def test_invalid_input_raises_value_error(self):
        bad = [
            (MAC, 1, "sensor1", 2),
            (MAC, 1, "sensor1", True),
            (MAC, 1, "sensor1", None),
            (MAC, 0, "sensor1", 1),
            (MAC, True, "sensor1", 1),
            (MAC, 1, "", 1),
        ]
        for mac, port, sensor_id, value in bad:
            with self.subTest(port=port, sensor_id=sensor_id, value=value):
                with self.assertRaises(ValueError):
                    self.queue.put(mac, port, sensor_id, value)
        self.assertEqual(self.queue.pending(MAC), 0)

    def test_devices_do_not_mix(self):
        self.queue.put(MAC, 1, "sensor1", 1)
        self.queue.put(OTHER, 1, "sensor9", 0)
        self.assertEqual(self.queue.pending(OTHER), 1)
        self.assertEqual(self.queue.pop(OTHER)["mac"], OTHER)
        self.assertEqual(self.queue.pending(MAC), 1)
        self.assertEqual(self.queue.pop(MAC)["sensor_id"], "sensor1")
        self.assertIsNone(self.queue.pop(MAC))
        self.assertEqual(self.queue.pending(UNUSED), 0)


if __name__ == "__main__":
    unittest.main()
