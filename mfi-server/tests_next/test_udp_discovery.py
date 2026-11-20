"""Tests of udp_discovery (EPIC-03): byte strings and a fake socket only, no network.

Run with the suite of mfi-server:
    python3 -m unittest discover -s mfi-server/tests_next -t mfi-server -v
"""
import socket
import unittest

from mfi_server_next.udp_discovery import (
    BROADCAST_ADDRESS,
    DISCOVERY_PORT,
    MULTICAST_ADDRESS,
    SOCKET_TIMEOUT_S,
    UdpDiscovery,
    UdpDiscoveryError,
    build_request,
    device_info,
    parse_reply,
)

FAKE_MAC = "02000000aa01"
FAKE_MAC_BYTES = bytes.fromhex(FAKE_MAC)
FAKE_IP_BYTES = bytes([192, 0, 2, 10])
FAKE_IP = "192.0.2.10"


def tlv(tlv_type, data):
    """One TLV field: type 1 byte, length 2 bytes big endian, data."""
    return bytes([tlv_type]) + len(data).to_bytes(2, "big") + data


def reply(*fields):
    """A whole reply: version 1, command 0, length of the fields, then the fields."""
    body = b"".join(fields)
    return b"\x01\x00" + len(body).to_bytes(2, "big") + body


def synthetic_reply():
    """Fields in the measured order 2, 1, 10, 11, 12, 13, 14, 3 (P1E, no fields 21/22/23)."""
    return reply(
        tlv(2, FAKE_MAC_BYTES + FAKE_IP_BYTES),
        tlv(1, FAKE_MAC_BYTES),
        tlv(10, (3600).to_bytes(4, "big")),
        tlv(11, b"mfi-test-plug"),
        tlv(12, b"P1E"),
        tlv(13, b"mFi-ABC123"),
        tlv(14, bytes([2])),
        tlv(3, b"MF.ar933x.v2.1.11.1309.150406.1423"),
    )


class FakeClock:
    """A clock that only moves when the fake socket times out."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class FakeSocket:
    """Socket stand-in: records what is sent, returns the queued replies, then times out."""

    def __init__(self, clock, replies=(), recv_error=None, send_error=None):
        self.clock = clock
        self.replies = list(replies)
        self.recv_error = recv_error
        self.send_error = send_error
        self.sent = []
        self.options = []
        self.timeout = None
        self.closed = False

    def setsockopt(self, level, option, value):
        self.options.append((level, option, value))

    def settimeout(self, value):
        self.timeout = value

    def sendto(self, data, address):
        if self.send_error is not None:
            raise self.send_error
        self.sent.append((data, address))
        return len(data)

    def recvfrom(self, size):
        if self.recv_error is not None:
            raise self.recv_error
        if self.replies:
            return self.replies.pop(0), (FAKE_IP, DISCOVERY_PORT)
        self.clock.now += SOCKET_TIMEOUT_S
        raise socket.timeout("no reply")

    def close(self):
        self.closed = True


class TestBuildRequest(unittest.TestCase):
    def test_request_is_four_bytes(self):
        self.assertEqual(build_request(), b"\x01\x00\x00\x00")


class TestParseReply(unittest.TestCase):
    def test_fields_keep_the_measured_order(self):
        parsed = parse_reply(synthetic_reply())
        self.assertEqual([f["type"] for f in parsed["fields"]], [2, 1, 10, 11, 12, 13, 14, 3])

    def test_header_is_read(self):
        data = synthetic_reply()
        parsed = parse_reply(data)
        self.assertEqual(parsed["version"], 1)
        self.assertEqual(parsed["command"], 0)
        self.assertEqual(parsed["length"], len(data) - 4)

    def test_field_data_is_raw_bytes(self):
        fields = parse_reply(synthetic_reply())["fields"]
        self.assertEqual(fields[0]["data"], FAKE_MAC_BYTES + FAKE_IP_BYTES)
        self.assertEqual(fields[6]["data"], b"\x02")

    def test_header_only_has_no_fields(self):
        self.assertEqual(parse_reply(b"\x01\x00\x00\x00")["fields"], [])

    def test_zero_length_field_is_allowed(self):
        fields = parse_reply(reply(tlv(14, b"")))["fields"]
        self.assertEqual(fields, [{"type": 14, "data": b""}])

    def test_long_field_is_read_whole(self):
        fields = parse_reply(reply(tlv(3, b"x" * 300)))["fields"]
        self.assertEqual(len(fields[0]["data"]), 300)

    def test_empty_input_raises(self):
        with self.assertRaises(ValueError):
            parse_reply(b"")

    def test_truncated_header_raises(self):
        with self.assertRaises(ValueError):
            parse_reply(b"\x01\x00\x00")

    def test_truncated_fields_raise(self):
        with self.assertRaises(ValueError):
            parse_reply(synthetic_reply()[:-3])

    def test_tlv_header_cut_short_raises(self):
        with self.assertRaises(ValueError):
            parse_reply(reply(tlv(1, FAKE_MAC_BYTES), b"\x0c\x00"))

    def test_tlv_longer_than_body_raises(self):
        with self.assertRaises(ValueError):
            parse_reply(reply(bytes([1]) + (50).to_bytes(2, "big") + b"abc"))


class TestDeviceInfo(unittest.TestCase):
    def test_full_key_set(self):
        info = device_info(parse_reply(synthetic_reply())["fields"])
        self.assertEqual(
            set(info),
            {"mac", "ip", "hostname", "platform", "model", "firmware", "essid", "default"},
        )

    def test_fields_without_21_22_23_use_platform_and_version(self):
        info = device_info(parse_reply(synthetic_reply())["fields"])
        self.assertEqual(info["mac"], FAKE_MAC)
        self.assertEqual(info["ip"], FAKE_IP)
        self.assertEqual(info["hostname"], "mfi-test-plug")
        self.assertEqual(info["platform"], "P1E")
        self.assertEqual(info["model"], "P1E")
        self.assertEqual(info["firmware"], "2.1.11.1309")
        self.assertEqual(info["essid"], "mFi-ABC123")
        self.assertIsNone(info["default"])

    def test_fields_21_22_23_win_when_present(self):
        fields = parse_reply(reply(
            tlv(1, FAKE_MAC_BYTES),
            tlv(12, b"P1E"),
            tlv(21, b"P3E"),
            tlv(22, b"2.1.11.1309"),
            tlv(23, bytes([1])),
        ))["fields"]
        info = device_info(fields)
        self.assertEqual(info["model"], "P3E")
        self.assertEqual(info["firmware"], "2.1.11.1309")
        self.assertIs(info["default"], True)

    def test_default_flag_zero_is_false(self):
        fields = parse_reply(reply(tlv(1, FAKE_MAC_BYTES), tlv(23, b"\x00")))["fields"]
        self.assertIs(device_info(fields)["default"], False)

    def test_mac_and_ip_from_type_2_when_type_1_is_missing(self):
        fields = parse_reply(reply(tlv(2, FAKE_MAC_BYTES + FAKE_IP_BYTES)))["fields"]
        info = device_info(fields)
        self.assertEqual(info["mac"], FAKE_MAC)
        self.assertEqual(info["ip"], FAKE_IP)

    def test_version_without_firmware_pattern_gives_no_firmware(self):
        fields = parse_reply(reply(tlv(1, FAKE_MAC_BYTES), tlv(3, b"unknown")))["fields"]
        self.assertIsNone(device_info(fields)["firmware"])

    def test_empty_fields_give_none_values(self):
        info = device_info([])
        self.assertIsNone(info["mac"])
        self.assertIsNone(info["model"])
        self.assertIsNone(info["firmware"])
        self.assertIsNone(info["default"])

    def test_non_ascii_hostname_is_decoded(self):
        fields = parse_reply(reply(tlv(1, FAKE_MAC_BYTES), tlv(11, "stanza-è".encode("utf-8"))))["fields"]
        self.assertEqual(device_info(fields)["hostname"], "stanza-è")

    def test_invalid_utf8_is_replaced_not_raised(self):
        fields = parse_reply(reply(tlv(1, FAKE_MAC_BYTES), tlv(12, b"P\xff1E")))["fields"]
        self.assertEqual(device_info(fields)["platform"], "P\ufffd1E")

    def test_nul_padding_is_removed(self):
        fields = parse_reply(reply(tlv(1, FAKE_MAC_BYTES), tlv(13, b"mFi-ABC123\x00\x00")))["fields"]
        self.assertEqual(device_info(fields)["essid"], "mFi-ABC123")


class TestScan(unittest.TestCase):
    def scan_with(self, sock, clock, timeout=1.0):
        return UdpDiscovery(sock_factory=lambda: sock, clock=clock).scan(timeout=timeout)

    def test_query_goes_to_broadcast_and_multicast(self):
        clock = FakeClock()
        sock = FakeSocket(clock)
        self.scan_with(sock, clock)
        self.assertEqual(
            sock.sent,
            [
                (build_request(), (BROADCAST_ADDRESS, DISCOVERY_PORT)),
                (build_request(), (MULTICAST_ADDRESS, DISCOVERY_PORT)),
            ],
        )

    def test_socket_has_timeout_and_broadcast(self):
        clock = FakeClock()
        sock = FakeSocket(clock)
        self.scan_with(sock, clock)
        self.assertEqual(sock.timeout, SOCKET_TIMEOUT_S)
        self.assertIn((socket.SOL_SOCKET, socket.SO_BROADCAST, 1), sock.options)

    def test_socket_is_closed_after_scan(self):
        clock = FakeClock()
        sock = FakeSocket(clock)
        self.scan_with(sock, clock)
        self.assertTrue(sock.closed)

    def test_reply_becomes_device_info(self):
        clock = FakeClock()
        sock = FakeSocket(clock, replies=[synthetic_reply()])
        result = self.scan_with(sock, clock)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["model"], "P1E")
        self.assertEqual(result[0]["firmware"], "2.1.11.1309")

    def test_same_mac_twice_gives_one_entry(self):
        clock = FakeClock()
        sock = FakeSocket(clock, replies=[synthetic_reply(), synthetic_reply()])
        self.assertEqual(len(self.scan_with(sock, clock)), 1)

    def test_two_macs_give_two_entries(self):
        clock = FakeClock()
        second = reply(tlv(1, bytes.fromhex("02000000aa02")), tlv(12, b"P3E"))
        sock = FakeSocket(clock, replies=[synthetic_reply(), second])
        result = self.scan_with(sock, clock)
        self.assertEqual(sorted(item["mac"] for item in result), ["02000000aa01", "02000000aa02"])

    def test_invalid_reply_is_skipped(self):
        clock = FakeClock()
        sock = FakeSocket(clock, replies=[b"\x01\x00\x00", synthetic_reply()])
        self.assertEqual(len(self.scan_with(sock, clock)), 1)

    def test_reply_without_mac_is_skipped(self):
        clock = FakeClock()
        sock = FakeSocket(clock, replies=[reply(tlv(12, b"P1E"))])
        self.assertEqual(self.scan_with(sock, clock), [])

    def test_send_error_is_clear_and_socket_closed(self):
        clock = FakeClock()
        sock = FakeSocket(clock, send_error=OSError("network unreachable"))
        with self.assertRaises(UdpDiscoveryError) as ctx:
            self.scan_with(sock, clock)
        self.assertIn("query", str(ctx.exception))
        self.assertTrue(sock.closed)

    def test_read_error_is_clear_and_socket_closed(self):
        clock = FakeClock()
        sock = FakeSocket(clock, recv_error=OSError("boom"))
        with self.assertRaises(UdpDiscoveryError) as ctx:
            self.scan_with(sock, clock)
        self.assertIn("replies", str(ctx.exception))
        self.assertTrue(sock.closed)

    def test_socket_open_error_is_clear(self):
        def factory():
            raise OSError("no socket")

        with self.assertRaises(UdpDiscoveryError) as ctx:
            UdpDiscovery(sock_factory=factory, clock=FakeClock()).scan(timeout=1.0)
        self.assertIn("UDP socket", str(ctx.exception))

    def test_zero_timeout_is_rejected_before_opening_a_socket(self):
        opened = []

        def factory():
            opened.append(1)
            return FakeSocket(FakeClock())

        with self.assertRaises(ValueError):
            UdpDiscovery(sock_factory=factory, clock=FakeClock()).scan(timeout=0)
        self.assertEqual(opened, [])

    def test_constructor_opens_no_socket(self):
        opened = []

        def factory():
            opened.append(1)
            return FakeSocket(FakeClock())

        UdpDiscovery(sock_factory=factory, clock=FakeClock())
        self.assertEqual(opened, [])

    def test_non_finite_timeout_is_rejected_before_opening_a_socket(self):
        opened = []

        def factory():
            opened.append(1)
            return FakeSocket(FakeClock())

        for bad in (float("inf"), float("nan")):
            with self.subTest(timeout=bad):
                with self.assertRaises(ValueError):
                    UdpDiscovery(sock_factory=factory, clock=FakeClock()).scan(timeout=bad)
        self.assertEqual(opened, [])

    def test_reply_after_deadline_is_not_read(self):
        clock = FakeClock()
        second = reply(tlv(1, bytes.fromhex("02000000aa02")), tlv(12, b"P3E"))

        class DeadlineSocket(FakeSocket):
            def recvfrom(self, size):
                if self.replies:
                    data = self.replies.pop(0)
                    self.clock.now += 2.0
                    return data, (FAKE_IP, DISCOVERY_PORT)
                return super().recvfrom(size)

        sock = DeadlineSocket(clock, replies=[synthetic_reply(), second])
        result = self.scan_with(sock, clock, timeout=1.0)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["mac"], "02000000aa01")

    def test_short_type_1_mac_falls_back_to_type_2(self):
        fields = parse_reply(reply(
            tlv(1, b"\x02\x00\x00"),
            tlv(2, FAKE_MAC_BYTES + FAKE_IP_BYTES),
        ))["fields"]
        info = device_info(fields)
        self.assertEqual(info["mac"], FAKE_MAC)
        self.assertEqual(info["ip"], FAKE_IP)


if __name__ == "__main__":
    unittest.main()
