"""Tests of the MQTT 3.1.1 client (mfi_server.mqtt): remaining length, packet bytes and a fake broker on loopback."""
from __future__ import annotations

import socket
import threading
import unittest

from mfi_server.mqtt import (
    CONNECT,
    DISCONNECT,
    PUBLISH,
    MqttClient,
    MqttError,
    build_connect,
    build_disconnect,
    build_pingreq,
    build_publish,
    decode_remaining_length,
    encode_remaining_length,
    parse_packet,
)

PASSWORD = "pw-test"


class FakeBroker:
    """A broker on 127.0.0.1 with a free port: answers CONNECT and QoS 1 PUBLISH, records every packet."""

    def __init__(self, connack_code: int = 0) -> None:
        self.connack_code = connack_code
        self.received: list[tuple[int, int, bytes]] = []
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(1)
        self._listener.settimeout(5)
        self.port = self._listener.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._thread.join(5)
        self._listener.close()

    def _serve(self) -> None:
        try:
            conn, _ = self._listener.accept()
        except OSError:
            return
        with conn:
            conn.settimeout(5)
            buffer = b""
            try:
                while True:
                    chunk = conn.recv(4096)
                    if not chunk:
                        return
                    buffer += chunk
                    packet = parse_packet(buffer)
                    while packet is not None:
                        ptype, flags, body, used = packet
                        buffer = buffer[used:]
                        self._answer(conn, ptype, flags, body)
                        packet = parse_packet(buffer)
            except OSError:
                return  # the client closed the connection

    def _answer(self, conn: socket.socket, ptype: int, flags: int, body: bytes) -> None:
        self.received.append((ptype, flags, body))
        if ptype == CONNECT:
            conn.sendall(bytes([0x20, 0x02, 0x00, self.connack_code]))
        elif ptype == PUBLISH and ((flags >> 1) & 0x03) == 1:
            topic_length = int.from_bytes(body[:2], "big")
            packet_id = body[2 + topic_length : 4 + topic_length]
            conn.sendall(b"\x40\x02" + packet_id)


class RemainingLengthTest(unittest.TestCase):
    CASES = [
        (0, b"\x00"),
        (127, b"\x7f"),
        (128, b"\x80\x01"),
        (16383, b"\xff\x7f"),
        (16384, b"\x80\x80\x01"),
        (268435455, b"\xff\xff\xff\x7f"),
    ]

    def test_encode_matches_contract_values(self):
        for value, expected in self.CASES:
            with self.subTest(value=value):
                self.assertEqual(encode_remaining_length(value), expected)

    def test_out_of_range_values_raise_value_error(self):
        for value in (268435456, -1):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    encode_remaining_length(value)

    def test_decode_round_trip_with_and_without_offset(self):
        for value, _ in self.CASES:
            encoded = encode_remaining_length(value)
            with self.subTest(value=value):
                self.assertEqual(decode_remaining_length(encoded, 0), (value, len(encoded)))
                self.assertEqual(decode_remaining_length(b"\xaa" + encoded, 1), (value, len(encoded)))

    def test_more_than_four_bytes_raise_value_error(self):
        with self.assertRaises(ValueError):
            decode_remaining_length(b"\x80\x80\x80\x80\x01", 0)
        with self.assertRaises(ValueError):
            decode_remaining_length(b"\x80\x80\x80\x80\x80", 0)

    def test_incomplete_length_raises_value_error(self):
        with self.assertRaises(ValueError):
            decode_remaining_length(b"\x80", 0)


class PacketBytesTest(unittest.TestCase):
    def test_pingreq_and_disconnect_bytes(self):
        self.assertEqual(build_pingreq(), b"\xc0\x00")
        self.assertEqual(build_disconnect(), b"\xe0\x00")

    def test_qos1_retained_publish_bytes(self):
        packet = build_publish("a", b"x", qos=1, retain=True, packet_id=7)
        # 0x33 = PUBLISH | QoS 1 | retain; remaining length = 2+1 (topic) + 2 (id) + 1 (payload) = 6
        self.assertEqual(packet, b"\x33\x06\x00\x01a\x00\x07x")

    def test_connect_carries_clean_session_and_credentials(self):
        packet = build_connect("mfi-test", "user-test", PASSWORD, 60, "", b"")
        ptype, _, body, consumed = parse_packet(packet)
        self.assertEqual(ptype, CONNECT)
        self.assertEqual(body[:7], b"\x00\x04MQTT\x04")  # protocol name and level 4
        self.assertEqual(body[7], 0x02 | 0x40 | 0x80)  # clean session, password, username
        self.assertEqual(consumed, len(packet))

    def test_partial_packet_is_not_parsed(self):
        packet = build_pingreq()
        self.assertIsNone(parse_packet(packet[:1]))
        self.assertEqual(parse_packet(packet), (12, 0, b"", 2))


class ClientWithFakeBrokerTest(unittest.TestCase):
    def test_retained_qos1_publish_is_acknowledged_by_puback(self):
        broker = FakeBroker()
        broker.start()
        client = MqttClient(
            "127.0.0.1",
            broker.port,
            "user-test",
            PASSWORD,
            "mfi-test",
            on_message=lambda topic, payload: None,
        )
        client.connect()
        client.publish("mfi/status", b"online", qos=1, retain=True)
        client.disconnect()
        broker.close()

        self.assertEqual([packet[0] for packet in broker.received], [CONNECT, PUBLISH, DISCONNECT])
        self.assertEqual(broker.received[0][2][7], 0x02 | 0x40 | 0x80)
        publish_type, publish_flags, body = broker.received[1]
        self.assertEqual(publish_flags, 0x03)  # QoS 1 and retain
        topic_length = int.from_bytes(body[:2], "big")
        self.assertEqual(body[2 : 2 + topic_length].decode("utf-8"), "mfi/status")
        self.assertEqual(body[2 + topic_length : 4 + topic_length], b"\x00\x01")
        self.assertEqual(body[4 + topic_length :], b"online")

    def test_connack_refusal_raises_mqtt_error_with_code_5(self):
        broker = FakeBroker(connack_code=5)
        broker.start()
        client = MqttClient(
            "127.0.0.1",
            broker.port,
            "user-test",
            PASSWORD,
            "mfi-test",
            on_message=lambda topic, payload: None,
        )
        with self.assertRaises(MqttError) as context:
            client.connect()
        broker.close()
        self.assertEqual(context.exception.code, 5)


if __name__ == "__main__":
    unittest.main()
