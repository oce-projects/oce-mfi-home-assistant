"""Offline tests for mfi_server.packet: TNBU inform packets and their responses."""
from __future__ import annotations

import os
import unittest

from mfi_server import aes
from mfi_server.packet import (
    DEFAULT_KEY_HEX,
    FLAG_COMPRESSED,
    FLAG_ENCRYPTED,
    HEADER_STRUCT,
    MAGIC,
    PacketError,
    decode,
    encode,
    encode_response,
    normalize_mac,
    parse_header,
)

MAC = bytes.fromhex("02aabbccdd01")
KEY = bytes.fromhex(DEFAULT_KEY_HEX)
PAYLOAD = {"mac": "02aabbccdd01", "model": "P3E"}


class TestPacket(unittest.TestCase):
    def test_encode_decode_round_trip(self):
        pkt = encode(MAC, KEY, PAYLOAD, os.urandom(16))
        header, payload, key = decode(pkt, [KEY])
        self.assertEqual(payload, PAYLOAD)
        self.assertEqual(key, KEY)
        self.assertEqual(header.mac, MAC)

    def test_compressed_round_trip(self):
        pkt = encode(MAC, KEY, PAYLOAD, os.urandom(16), flags=FLAG_ENCRYPTED | FLAG_COMPRESSED)
        header, payload, _ = decode(pkt, [KEY])
        self.assertEqual(header.flags, FLAG_ENCRYPTED | FLAG_COMPRESSED)
        self.assertEqual(payload, PAYLOAD)

    def test_non_ascii_payload_round_trip(self):
        payload = {"mac": "02aabbccdd01", "label": "caffè"}
        _, decoded, _ = decode(encode(MAC, KEY, payload, os.urandom(16)), [KEY])
        self.assertEqual(decoded, payload)

    def test_returns_the_key_that_decrypts(self):
        wrong = os.urandom(16)
        pkt = encode(MAC, KEY, PAYLOAD, os.urandom(16))
        _, payload, key = decode(pkt, [wrong, KEY])
        self.assertEqual(key, KEY)
        self.assertEqual(payload, PAYLOAD)

    def test_recovers_zero_padding(self):
        iv = os.urandom(16)
        body = b'{"mac":"02aabbccdd01"}'
        plain = body + b"\x00" * (-len(body) % 16)
        cipher = aes.encrypt_cbc(KEY, iv, plain)
        pkt = HEADER_STRUCT.pack(MAGIC, 0, MAC, FLAG_ENCRYPTED, iv, 1, len(cipher)) + cipher
        _, payload, _ = decode(pkt, [KEY])
        self.assertEqual(payload, {"mac": "02aabbccdd01"})

    def test_response_keeps_header_and_iv(self):
        iv = os.urandom(16)
        request = encode(MAC, KEY, {"mac": "02aabbccdd01"}, iv)
        header = parse_header(request)
        response = encode_response(header, KEY, {"_type": "noop"})
        resp_header = parse_header(response)
        self.assertEqual(resp_header.iv, iv)
        self.assertEqual(resp_header.mac, header.mac)
        self.assertEqual(resp_header.version, header.version)
        self.assertEqual(resp_header.data_version, header.data_version)
        self.assertEqual(resp_header.flags, FLAG_ENCRYPTED)
        self.assertEqual(response[:32], request[:32])
        _, payload, _ = decode(response, [KEY])
        self.assertEqual(payload, {"_type": "noop"})

    def test_parse_header_fields(self):
        iv = os.urandom(16)
        pkt = encode(MAC, KEY, PAYLOAD, iv, version=3)
        header = parse_header(pkt)
        self.assertEqual(
            (header.version, header.mac, header.flags, header.iv, header.data_version),
            (3, MAC, FLAG_ENCRYPTED, iv, 1),
        )
        self.assertEqual(header.data_length, len(pkt) - 40)

    def test_rejected_packets_have_status_400(self):
        iv = os.urandom(16)
        good = encode(MAC, KEY, PAYLOAD, iv)
        cases = [
            ("header is too short", good[:39]),
            ("bad packet magic", b"\x00" * 4 + good[4:]),
            ("unsupported data version", good[:32] + (2).to_bytes(4, "big") + good[36:]),
            ("truncated payload", good[:-1]),
            ("unencrypted packet not accepted", encode(MAC, KEY, PAYLOAD, iv, flags=0)),
            ("bad payload length", HEADER_STRUCT.pack(MAGIC, 0, MAC, FLAG_ENCRYPTED, iv, 1, 0)),
            (
                "bad payload length",
                HEADER_STRUCT.pack(MAGIC, 0, MAC, FLAG_ENCRYPTED, iv, 1, 17) + b"\x00" * 17,
            ),
        ]
        for reason, data in cases:
            with self.subTest(reason=reason):
                with self.assertRaises(PacketError) as ctx:
                    decode(data, [KEY])
                self.assertEqual(ctx.exception.status, 400)
                self.assertEqual(ctx.exception.reason, reason)
                self.assertEqual(str(ctx.exception), reason)

    def test_no_valid_key_has_status_400(self):
        pkt = encode(MAC, KEY, PAYLOAD, os.urandom(16))
        for keys, count in (([os.urandom(16)], 1), ([], 0)):
            with self.subTest(count=count):
                with self.assertRaises(PacketError) as ctx:
                    decode(pkt, keys)
                self.assertEqual(ctx.exception.status, 400)
                self.assertEqual(
                    ctx.exception.reason,
                    f"inform decrypt error (tried all {count} keys)",
                )

    def test_encode_rejects_bad_lengths(self):
        with self.assertRaises(ValueError):
            encode(bytes(5), KEY, PAYLOAD, os.urandom(16))
        with self.assertRaises(ValueError):
            encode(MAC, KEY, PAYLOAD, os.urandom(15))

    def test_normalize_mac(self):
        self.assertEqual(normalize_mac("02AABBCCDD01"), "02aabbccdd01")
        self.assertEqual(normalize_mac("-".join(["02", "aa", "bb", "cc", "dd", "01"])), "02aabbccdd01")
        with self.assertRaises(ValueError):
            normalize_mac("xyz")
        with self.assertRaises(ValueError):
            normalize_mac("02aabbccdd0")
        with self.assertRaises(ValueError):
            normalize_mac(12)


if __name__ == "__main__":
    unittest.main()
