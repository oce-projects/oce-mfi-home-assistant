"""Tests for the wake-up packet (mfi_server.wakeup). UDP on 127.0.0.1 only."""
from __future__ import annotations

import socket
import unittest

from mfi_server.wakeup import WAKEUP_LEN, build_wakeup, send_wakeup, wakeup_target


class TestWakeupPacket(unittest.TestCase):
    def test_packet_is_20_bytes_starting_with_0x88(self):
        packet = build_wakeup()
        self.assertEqual(WAKEUP_LEN, 20)
        self.assertEqual(len(packet), 20)
        self.assertEqual(packet[:2], b"\x88\x88")
        self.assertEqual(packet[2:], bytes(18))


class TestSendWakeup(unittest.TestCase):
    def _receiver(self) -> socket.socket:
        recv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addCleanup(recv.close)
        recv.bind(("127.0.0.1", 0))
        recv.settimeout(2)
        return recv

    def _sender(self) -> socket.socket:
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addCleanup(sender.close)
        return sender

    def test_sends_packet_to_target(self):
        recv = self._receiver()
        port = recv.getsockname()[1]
        send_wakeup(self._sender(), "127.0.0.1", port)
        data, _addr = recv.recvfrom(64)
        self.assertEqual(data, build_wakeup())

    def test_empty_ip_sends_nothing(self):
        recv = self._receiver()
        recv.settimeout(0.2)
        port = recv.getsockname()[1]
        send_wakeup(self._sender(), "", port)
        with self.assertRaises(socket.timeout):
            recv.recvfrom(64)

    def test_invalid_port_is_skipped_without_raising(self):
        sender = self._sender()
        for port in (0, 70000, None):
            with self.subTest(port=port):
                with self.assertLogs("mfi_server.wakeup", level="DEBUG"):
                    send_wakeup(sender, "127.0.0.1", port)

    def test_os_error_is_logged_not_raised(self):
        closed = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        closed.close()
        with self.assertLogs("mfi_server.wakeup", level="WARNING"):
            send_wakeup(closed, "127.0.0.1", 40000)


class TestWakeupTarget(unittest.TestCase):
    def test_valid_payload(self):
        payload = {"connect_request_ip": "127.0.0.1", "connect_request_port": "40000"}
        self.assertEqual(wakeup_target(payload), ("127.0.0.1", 40000))

    def test_missing_fields(self):
        self.assertIsNone(wakeup_target({}))

    def test_invalid_values(self):
        bad = [
            {"connect_request_ip": "127.0.0.1", "connect_request_port": "70000"},
            {"connect_request_ip": "127.0.0.1", "connect_request_port": "0"},
            {"connect_request_ip": "127.0.0.1", "connect_request_port": "abc"},
            {"connect_request_ip": "127.0.0.1", "connect_request_port": None},
            {"connect_request_ip": "", "connect_request_port": "40000"},
            {"connect_request_ip": "127.0.0.1", "connect_request_port": float("inf")},
            {"connect_request_ip": "127.0.0.1", "connect_request_port": True},
        ]
        for payload in bad:
            with self.subTest(payload=payload):
                self.assertIsNone(wakeup_target(payload))


if __name__ == "__main__":
    unittest.main()
