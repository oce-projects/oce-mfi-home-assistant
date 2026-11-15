"""Tests of OutputControl: the command is queued and, when the address is known, a wake-up is sent."""
from __future__ import annotations

import socket
import tempfile
import unittest
from pathlib import Path

from mfi_server.commands import CommandQueue
from mfi_server.control import OutputControl
from mfi_server.states import DeviceStates
from mfi_server.store import DeviceStore

MAC = "02aabbccdd01"


class TestOutputControl(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = DeviceStore(Path(tmp.name))
        self.store.upsert(
            {
                "mac": MAC,
                "model": "m",
                "name": "test",
                "ports": [
                    {"port": 1, "sensor_id": "sensor-1", "label": "outlet 1", "model": "m"},
                    {"port": 2, "sensor_id": "sensor-2", "label": "outlet 2", "model": "m"},
                ],
            }
        )
        self.states = DeviceStates(clock=lambda: 0.0)
        self.queue = CommandQueue()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addCleanup(self.sock.close)
        self.control = OutputControl(self.store, self.states, self.queue, self.sock)

    def test_queues_and_sends_wakeup(self):
        recv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addCleanup(recv.close)
        recv.bind(("127.0.0.1", 0))
        recv.settimeout(2)
        port = recv.getsockname()[1]
        self.states.set_wakeup_target(MAC, "127.0.0.1", port)

        self.control.set_output(MAC, 1, 1)

        cmd = self.queue.pop(MAC)
        self.assertEqual(cmd["port"], 1)
        self.assertEqual(cmd["sensor_id"], "sensor-1")
        self.assertEqual(cmd["value"], 1)
        data, _ = recv.recvfrom(64)
        self.assertEqual(len(data), 20)
        self.assertEqual(data[:2], b"\x88\x88")

    def test_no_target_queues_without_sending(self):
        self.control.set_output(MAC, 2, 0)

        cmd = self.queue.pop(MAC)
        self.assertEqual(cmd["value"], 0)
        self.assertEqual(cmd["sensor_id"], "sensor-2")

    def test_unknown_mac_raises_keyerror(self):
        with self.assertRaises(KeyError):
            self.control.set_output("02aabbccdd09", 1, 1)

    def test_unknown_port_raises_keyerror(self):
        with self.assertRaises(KeyError):
            self.control.set_output(MAC, 99, 1)

    def test_bad_value_raises_valueerror_and_queues_nothing(self):
        with self.assertRaises(ValueError):
            self.control.set_output(MAC, 1, 2)
        self.assertIsNone(self.queue.pop(MAC))


if __name__ == "__main__":
    unittest.main()
