"""Tests for the in-memory device states (mfi_server.states)."""
from __future__ import annotations

import unittest

from mfi_server.states import CONNECTED, LOST_AFTER_S, DeviceStates

MAC = "02aabbccdd01"
OTHER = "02aabbccdd03"


class TestDeviceStates(unittest.TestCase):
    def setUp(self):
        self.t = [1000.0]
        self.states = DeviceStates(clock=lambda: self.t[0])

    def test_constants(self):
        self.assertEqual(CONNECTED, 1)
        self.assertEqual(LOST_AFTER_S, 120)

    def test_unknown_device(self):
        self.assertEqual(self.states.state(OTHER), "unknown")
        self.assertIsNone(self.states.last_seen(OTHER))
        self.assertEqual(self.states.lost_devices(), [])

    def test_connected_until_120_then_lost_at_121(self):
        self.states.seen(MAC)
        self.t[0] = 1119.0
        self.assertEqual(self.states.state(MAC), "connected")
        self.t[0] = 1120.0
        self.assertEqual(self.states.state(MAC), "connected")
        self.t[0] = 1121.0
        self.assertEqual(self.states.state(MAC), "lost")
        self.assertEqual(self.states.lost_devices(), [MAC])

    def test_new_seen_makes_lost_device_connected_again(self):
        self.states.seen(MAC)
        self.t[0] = 1121.0
        self.assertEqual(self.states.state(MAC), "lost")
        self.states.seen(MAC)
        self.assertEqual(self.states.state(MAC), "connected")
        self.assertEqual(self.states.lost_devices(), [])
        self.assertEqual(self.states.last_seen(MAC), 1121.0)

    def test_lost_devices_sorted(self):
        self.states.seen(OTHER)
        self.states.seen(MAC)
        self.t[0] = 1200.0
        self.assertEqual(self.states.lost_devices(), [MAC, OTHER])

    def test_only_old_devices_are_lost(self):
        self.states.seen(MAC)
        self.t[0] = 1100.0
        self.states.seen(OTHER)
        self.t[0] = 1121.0
        self.assertEqual(self.states.state(MAC), "lost")
        self.assertEqual(self.states.state(OTHER), "connected")
        self.assertEqual(self.states.lost_devices(), [MAC])

    def test_default_clock_is_monotonic(self):
        self.assertEqual(DeviceStates().state(MAC), "unknown")


if __name__ == "__main__":
    unittest.main()
