"""Tests for the BSON reader of mfi_server_next (standard library only)."""
import io
import struct
import unittest

from mfi_server_next.bson import read_bson_stream


def doc(elements: bytes) -> bytes:
    """Wrap raw elements in a BSON document: int32 length, elements, 0x00."""
    return struct.pack("<i", len(elements) + 5) + elements + b"\x00"


def element(type_byte: int, name: str, payload: bytes) -> bytes:
    """One BSON element: type byte, name as cstring, raw payload."""
    return bytes([type_byte]) + name.encode("ascii") + b"\x00" + payload


class TestBsonReader(unittest.TestCase):
    def test_all_types_decode_in_one_document(self):
        raw = doc(
            element(0x01, "d", struct.pack("<d", 1.5))
            + element(0x02, "s", struct.pack("<i", 3) + b"ok\x00")
            + element(0x03, "o", doc(element(0x10, "k", struct.pack("<i", 1))))
            + element(
                0x04,
                "a",
                doc(
                    element(0x10, "0", struct.pack("<i", 1))
                    + element(0x10, "1", struct.pack("<i", 2))
                ),
            )
            + element(0x05, "b", struct.pack("<i", 2) + b"\x00" + b"\x01\x02")
            + element(0x07, "x", bytes(range(12)))
            + element(0x08, "t", b"\x01")
            + element(0x09, "m", struct.pack("<q", 1700000000000))
            + element(0x0A, "n", b"")
            + element(0x10, "i", struct.pack("<i", -5))
            + element(0x12, "l", struct.pack("<q", 2**40))
        )
        expected = {
            "d": 1.5,
            "s": "ok",
            "o": {"k": 1},
            "a": [1, 2],
            "b": b"\x01\x02",
            "x": "000102030405060708090a0b",
            "t": True,
            "m": 1700000000000,
            "n": None,
            "i": -5,
            "l": 2**40,
        }
        result = read_bson_stream(io.BytesIO(raw))
        self.assertEqual(result, [expected])
        value = result[0]
        self.assertIs(type(value["d"]), float)
        self.assertIs(type(value["s"]), str)
        self.assertIs(type(value["o"]), dict)
        self.assertIs(type(value["a"]), list)
        self.assertIs(type(value["b"]), bytes)
        self.assertIs(type(value["x"]), str)
        self.assertEqual(len(value["x"]), 24)
        self.assertIs(value["t"], True)
        self.assertIs(type(value["m"]), int)
        self.assertIsNone(value["n"])
        self.assertIs(type(value["i"]), int)
        self.assertIs(type(value["l"]), int)

    def test_two_documents_in_a_row(self):
        first = doc(element(0x10, "a", struct.pack("<i", 1)))
        second = doc(element(0x10, "a", struct.pack("<i", 2)))
        result = read_bson_stream(io.BytesIO(first + second))
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)
        self.assertEqual(result, [{"a": 1}, {"a": 2}])
        for item in result:
            self.assertIsInstance(item, dict)

    def test_empty_input_gives_no_documents(self):
        self.assertEqual(read_bson_stream(io.BytesIO(b"")), [])

    def test_truncated_input_raises_value_error(self):
        raw = doc(
            element(0x02, "s", struct.pack("<i", 3) + b"ok\x00")
            + element(0x10, "i", struct.pack("<i", -5))
        )
        for cut in (1, 2, len(raw) - 4):
            with self.subTest(cut=cut):
                with self.assertRaises(ValueError):
                    read_bson_stream(io.BytesIO(raw[:-cut]))

    def test_declared_length_larger_than_data_raises(self):
        with self.assertRaises(ValueError):
            read_bson_stream(io.BytesIO(struct.pack("<i", 100) + b"\x00" * 4))

    def test_length_below_five_or_negative_raises(self):
        for raw in (struct.pack("<i", 4) + b"\x00", struct.pack("<i", -1) + b"\x00" * 4):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    read_bson_stream(io.BytesIO(raw))

    def test_unknown_type_byte_raises(self):
        with self.assertRaises(ValueError):
            read_bson_stream(io.BytesIO(doc(element(0x7F, "x", b""))))


if __name__ == "__main__":
    unittest.main()
