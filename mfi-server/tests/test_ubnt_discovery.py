"""Tests of the UDP discovery of mFi devices (ubnt_discovery): reply parsing and the scanner, offline."""
from __future__ import annotations

import socket
import struct
import unittest

from mfi_server.ubnt_discovery import (
    BROADCAST_ADDRESS,
    DISCOVERY_PORT,
    MULTICAST_ADDRESS,
    QUERY,
    DiscoveryError,
    ScanInProgress,
    Scanner,
    parse_reply,
)

MAC_HEX = "02aabbccdd01"
MAC = bytes.fromhex(MAC_HEX)
IP_BYTES = bytes([192, 168, 1, 20])


def tlv(t, payload):
    return struct.pack(">BH", t, len(payload)) + payload


def reply(*fields):
    body = b"".join(fields)
    return struct.pack(">BBH", 1, 0, len(body)) + body


class FakeSocket:
    """Stands in for a UDP socket: returns the given replies, then times out."""

    def __init__(self, replies):
        self._replies = list(replies)
        self.sent = []

    def setsockopt(self, *args):
        pass

    def settimeout(self, timeout):
        pass

    def sendto(self, data, addr):
        self.sent.append((data, addr))

    def recvfrom(self, size):
        if self._replies:
            return self._replies.pop(0), ("192.168.1.20", DISCOVERY_PORT)
        raise socket.timeout()

    def close(self):
        pass


class SendFailingSocket(FakeSocket):
    """A FakeSocket whose sendto always fails."""

    def sendto(self, data, addr):
        raise OSError("x")


class ParseReplyTest(unittest.TestCase):
    def test_full_reply_gives_every_field(self):
        data = reply(
            tlv(2, MAC + IP_BYTES),
            tlv(3, b"1.2.3"),
            tlv(10, struct.pack(">I", 3600)),
            tlv(11, b"mfi-host"),
            tlv(12, b"MPOWER"),
            tlv(21, b"mPower"),
            tlv(22, b"2.1.11"),
            tlv(23, b"\x01"),
            tlv(99, b"\xde\xad"),
        )
        expected = {
            "mac": MAC_HEX,
            "ip": "192.168.1.20",
            "model": "mPower",
            "firmware": "2.1.11",
            "hostname": "mfi-host",
            "platform": "MPOWER",
            "uptime_s": 3600,
            "is_default": True,
            "unknown": {"99": "dead"},
        }
        self.assertEqual(parse_reply(data), expected)

    def test_missing_fields_are_none_and_unknown_is_empty(self):
        expected = {
            "mac": MAC_HEX,
            "ip": None,
            "model": None,
            "firmware": None,
            "hostname": None,
            "platform": None,
            "uptime_s": None,
            "is_default": None,
            "unknown": {},
        }
        self.assertEqual(parse_reply(reply(tlv(1, MAC))), expected)

    def test_default_flag_zero_or_empty_is_not_default(self):
        self.assertIs(parse_reply(reply(tlv(1, MAC), tlv(23, b"\x00")))["is_default"], False)
        self.assertIs(parse_reply(reply(tlv(1, MAC), tlv(23, b"")))["is_default"], False)

    def test_non_utf8_text_is_replaced(self):
        device = parse_reply(reply(tlv(1, MAC), tlv(21, b"\xff")))
        self.assertEqual(device["model"], "\ufffd")

    def test_utf8_text_is_kept(self):
        device = parse_reply(reply(tlv(1, MAC), tlv(21, "mPòwer".encode("utf-8"))))
        self.assertEqual(device["model"], "mPòwer")


class ParseReplyErrorTest(unittest.TestCase):
    def test_shorter_than_header_is_rejected(self):
        with self.assertRaises(DiscoveryError):
            parse_reply(b"\x01\x00\x00")

    def test_wrong_length_field_is_rejected(self):
        with self.assertRaises(DiscoveryError):
            parse_reply(struct.pack(">BBH", 1, 0, 99) + b"\x01\x02")

    def test_tlv_running_past_the_data_is_rejected(self):
        with self.assertRaises(DiscoveryError):
            parse_reply(reply(struct.pack(">BH", 21, 50) + b"abc"))

    def test_one_or_two_leftover_bytes_are_rejected(self):
        with self.assertRaises(DiscoveryError):
            parse_reply(reply(tlv(1, MAC), b"\x01\x02"))

    def test_reply_without_mac_is_rejected(self):
        with self.assertRaises(DiscoveryError):
            parse_reply(reply(tlv(3, b"1.0")))

    def test_mac_field_shorter_than_six_bytes_is_rejected(self):
        with self.assertRaises(DiscoveryError):
            parse_reply(reply(tlv(1, MAC[:4])))

    def test_query_echo_is_rejected(self):
        with self.assertRaises(DiscoveryError):
            parse_reply(QUERY)


class ScannerTest(unittest.TestCase):
    def test_scan_queries_both_addresses_and_keeps_last_reply_per_mac(self):
        first = reply(tlv(2, MAC + IP_BYTES), tlv(21, b"mPower"))
        second = reply(tlv(2, MAC + IP_BYTES), tlv(21, b"mPort"))
        fake = FakeSocket([first, second, b"\x01"])
        counter = {"n": 0}

        def clock():
            counter["n"] += 1
            return 0.0 if counter["n"] <= 1000 else 100.0

        scanner = Scanner(sock_factory=lambda: fake, clock=clock)
        result = scanner.scan(timeout_s=3.0)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["model"], "mPort")
        self.assertIn((QUERY, (BROADCAST_ADDRESS, DISCOVERY_PORT)), fake.sent)
        self.assertIn((QUERY, (MULTICAST_ADDRESS, DISCOVERY_PORT)), fake.sent)
        self.assertEqual(scanner.last_results(), result)

    def test_send_error_gives_empty_result_without_raising(self):
        scanner = Scanner(sock_factory=lambda: SendFailingSocket([]), clock=lambda: 0.0)
        with self.assertLogs("mfi_server.ubnt_discovery", level="WARNING"):
            result = scanner.scan(timeout_s=3.0)
        self.assertEqual(result, [])
        self.assertEqual(scanner.last_results(), [])

    def test_second_scan_while_one_runs_is_refused(self):
        scanner = Scanner(sock_factory=lambda: FakeSocket([]), clock=lambda: 0.0)
        scanner._lock.acquire()
        try:
            with self.assertRaises(ScanInProgress):
                scanner.scan(timeout_s=0.0)
        finally:
            scanner._lock.release()


if __name__ == "__main__":
    unittest.main()
