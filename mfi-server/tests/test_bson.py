"""Tests for the minimal BSON reader and writer used by the .unf backup import."""
from __future__ import annotations

import struct
import unittest

from mfi_server.bson import BsonError, encode_document, iter_documents

SPEC_HELLO = b"\x16\x00\x00\x00\x02hello\x00\x06\x00\x00\x00world\x00\x00"


def doc(elements: bytes) -> bytes:
    return struct.pack("<i", len(elements) + 5) + elements + b"\x00"


def one(type_byte: int, payload: bytes) -> bytes:
    """A document with one element named "v" of the given BSON type."""
    return doc(bytes([type_byte]) + b"v\x00" + payload)


class TestSpecVector(unittest.TestCase):
    def test_decodes_spec_example(self):
        self.assertEqual(list(iter_documents(SPEC_HELLO)), [{"hello": "world"}])

    def test_encodes_spec_example(self):
        self.assertEqual(encode_document({"hello": "world"}), SPEC_HELLO)


class TestTypes(unittest.TestCase):
    def test_each_type_decodes(self):
        cases = [
            ("0x01 double", struct.pack("<d", 1.5), 1.5),
            ("0x02 string", struct.pack("<i", 3) + b"ok\x00", "ok"),
            ("0x05 binary", struct.pack("<i", 2) + b"\x00" + b"\x01\x02", b"\x01\x02"),
            ("0x07 ObjectId", bytes(range(12)), "000102030405060708090a0b"),
            ("0x08 bool true", b"\x01", True),
            ("0x08 bool false", b"\x00", False),
            ("0x09 datetime", struct.pack("<q", 1700000000000), 1700000000000),
            ("0x0A null", b"", None),
            ("0x10 int32", struct.pack("<i", -5), -5),
            ("0x11 timestamp", struct.pack("<Q", 7), 7),
            ("0x12 int64", struct.pack("<q", 2**40), 2**40),
        ]
        type_bytes = [0x01, 0x02, 0x05, 0x07, 0x08, 0x08, 0x09, 0x0A, 0x10, 0x11, 0x12]
        for (name, payload, expected), type_byte in zip(cases, type_bytes):
            with self.subTest(name=name):
                self.assertEqual(list(iter_documents(one(type_byte, payload))), [{"v": expected}])

    def test_document_type_decodes_to_dict(self):
        inner = doc(b"\x10" + b"b\x00" + struct.pack("<i", 1))
        self.assertEqual(list(iter_documents(doc(b"\x03" + b"a\x00" + inner))), [{"a": {"b": 1}}])

    def test_array_type_decodes_to_list_in_order(self):
        inner = doc(
            b"\x10" + b"0\x00" + struct.pack("<i", 1)
            + b"\x10" + b"1\x00" + struct.pack("<i", 2)
        )
        self.assertEqual(list(iter_documents(doc(b"\x04" + b"l\x00" + inner))), [{"l": [1, 2]}])

    def test_two_documents_in_a_row(self):
        first = doc(b"\x10" + b"a\x00" + struct.pack("<i", 1))
        second = doc(b"\x10" + b"a\x00" + struct.pack("<i", 2))
        self.assertEqual(list(iter_documents(first + second)), [{"a": 1}, {"a": 2}])

    def test_empty_input_gives_no_documents(self):
        self.assertEqual(list(iter_documents(b"")), [])


class TestErrors(unittest.TestCase):
    def test_bson_error_is_value_error(self):
        self.assertTrue(issubclass(BsonError, ValueError))

    def test_unknown_type_raises_with_type_and_offset(self):
        with self.assertRaises(BsonError) as ctx:
            list(iter_documents(doc(b"\x13v\x00")))
        self.assertIn("0x13", str(ctx.exception))
        self.assertIn("offset 4", str(ctx.exception))

    def test_malformed_input_raises_bson_error(self):
        cases = [
            ("length beyond data", struct.pack("<i", 100) + b"\x00" * 5),
            ("three trailing bytes", b"\x05\x00\x00"),
            ("length below 5", struct.pack("<i", 4) + b"\x00"),
            ("missing final 0x00", struct.pack("<i", 5) + b"\x01"),
            ("string beyond document", doc(b"\x02" + b"s\x00" + struct.pack("<i", 50) + b"abc\x00")),
            ("string not UTF-8", doc(b"\x02" + b"s\x00" + struct.pack("<i", 2) + b"\xff\x00")),
            ("unterminated name", doc(b"\x10ab")),
        ]
        for name, raw in cases:
            with self.subTest(name=name):
                with self.assertRaises(BsonError):
                    list(iter_documents(raw))

    def test_deeply_nested_document_raises_bson_error(self):
        nested = {"v": 1}
        for _ in range(200):
            nested = {"v": nested}
        with self.assertRaises(BsonError):
            list(iter_documents(encode_document(nested)))


class TestEncode(unittest.TestCase):
    def test_round_trip_all_supported_types(self):
        sample = {
            "s": "x",
            "u": "città",
            "i": 3,
            "big": 2**40,
            "f": 0.5,
            "t": True,
            "n": None,
            "d": {"k": "v"},
            "l": [1, "a"],
            "b": b"\x00",
        }
        self.assertEqual(list(iter_documents(encode_document(sample))), [sample])

    def test_integer_width_and_bool_type_bytes(self):
        self.assertEqual(encode_document({"x": 3})[4], 0x10)
        self.assertEqual(encode_document({"x": 2**40})[4], 0x12)
        self.assertEqual(encode_document({"x": True})[4], 0x08)

    def test_unsupported_value_raises(self):
        with self.assertRaises(BsonError):
            encode_document({"x": object()})

    def test_integer_beyond_int64_raises(self):
        with self.assertRaises(BsonError):
            encode_document({"x": 2**63})

    def test_non_str_key_raises(self):
        with self.assertRaises(BsonError):
            encode_document({1: "a"})


if __name__ == "__main__":
    unittest.main()
