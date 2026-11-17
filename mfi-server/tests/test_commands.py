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

    def test_upgrade_is_put_popped_and_cleared(self):
        self.queue.put_upgrade(MAC, "M2M/2.1.11.1309/firmware.bin", "2.1.11.1309")
        self.assertTrue(self.queue.pending_upgrade(MAC))
        self.assertEqual(
            self.queue.pop_upgrade(MAC),
            {"mac": MAC, "path": "M2M/2.1.11.1309/firmware.bin", "version": "2.1.11.1309"},
        )
        self.assertIsNone(self.queue.pop_upgrade(MAC))
        self.assertFalse(self.queue.pending_upgrade(MAC))

    def test_second_upgrade_replaces_the_first(self):
        self.queue.put_upgrade(MAC, "M2M/old/firmware.bin", "2.1.9")
        self.queue.put_upgrade(MAC, "M2M/new/firmware.bin", "2.1.11.1309")
        self.assertEqual(
            self.queue.pop_upgrade(MAC),
            {"mac": MAC, "path": "M2M/new/firmware.bin", "version": "2.1.11.1309"},
        )
        self.assertIsNone(self.queue.pop_upgrade(MAC))

    def test_invalid_upgrade_raises_value_error(self):
        bad = [
            ("", "2.1.11.1309"),
            ("M2M/x/firmware.bin", ""),
            (None, "2.1.11.1309"),
            ("M2M/x/firmware.bin", None),
        ]
        for path, version in bad:
            with self.subTest(path=path, version=version):
                with self.assertRaises(ValueError):
                    self.queue.put_upgrade(MAC, path, version)
        self.assertFalse(self.queue.pending_upgrade(MAC))

    def test_upgrade_and_output_commands_are_independent(self):
        self.queue.put(MAC, 1, "sensor1", 1)
        self.queue.put_upgrade(MAC, "M2M/x/firmware.bin", "2.1.11.1309")
        self.assertEqual(self.queue.pending(MAC), 1)
        self.assertEqual(
            self.queue.pop(MAC),
            {"mac": MAC, "port": 1, "sensor_id": "sensor1", "value": 1},
        )
        self.assertTrue(self.queue.pending_upgrade(MAC))
        self.assertEqual(self.queue.pending(MAC), 0)
        self.queue.put(MAC, 2, "sensor2", 0)
        self.assertEqual(self.queue.pop_upgrade(MAC)["version"], "2.1.11.1309")
        self.assertEqual(self.queue.pop(MAC)["port"], 2)
        self.assertIsNone(self.queue.pop(MAC))
        self.assertIsNone(self.queue.pop_upgrade(MAC))


if __name__ == "__main__":
    unittest.main()
