"""Tests for mfi_server.unf: backups and ZIP entries built in memory, nothing written to disk."""
from __future__ import annotations

import gzip
import io
import os
import struct
import unittest
import zipfile
import zlib

from mfi_server import aes, bson
from mfi_server.unf import UNF_IV, UNF_KEY, UnfError, decrypt_unf, import_backup, read_zip_entries

MAC_A = "02aabbccdd01"
MAC_B = "02aabbccdd02"
MAC_COLON = ":".join(["02", "aa", "bb", "cc", "dd", "01"])


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def _encrypt(zip_data: bytes) -> bytes:
    padding = -len(zip_data) % 16
    return aes.encrypt_cbc(UNF_KEY, UNF_IV, zip_data + b"\x00" * padding)


def make_backup(db_docs: list[dict], extra: dict[str, bytes]) -> bytes:
    db = gzip.compress(b"".join(bson.encode_document(doc) for doc in db_docs))
    entries = {"format": b"2", "version": b"2.1.11", "timestamp": b"0", "db.gz": db}
    entries.update(extra)
    return _encrypt(_zip_bytes(entries))


def _local_header(name: bytes, flags: int, method: int, comp_size: int, size: int) -> bytes:
    return struct.pack(
        "<IHHHHHIIIHH", 0x04034B50, 20, flags, method, 0, 0, 0, comp_size, size, len(name), 0
    ) + name


class TestDecryptUnf(unittest.TestCase):
    def test_keeps_whole_blocks_and_drops_partial_tail(self):
        plain = b"x" * 16
        cipher = aes.encrypt_cbc(UNF_KEY, UNF_IV, plain)
        self.assertEqual(decrypt_unf(cipher + b"\x01"), plain)

    def test_too_short_raises(self):
        with self.assertRaisesRegex(UnfError, "backup is too short"):
            decrypt_unf(b"0123456789")

    def test_unf_error_is_a_value_error(self):
        self.assertTrue(issubclass(UnfError, ValueError))


class TestReadZipEntries(unittest.TestCase):
    def test_descriptor_entry_and_stored_entry(self):
        raw = b"hello" * 50
        c = zlib.compressobj(9, zlib.DEFLATED, -15)
        comp = c.compress(raw) + c.flush()
        descriptor = struct.pack("<IIII", 0x08074B50, zlib.crc32(raw), len(comp), len(raw))
        data = (
            _local_header(b"a.txt", 0x08, 8, 0, 0)
            + comp
            + descriptor
            + _local_header(b"b.txt", 0, 0, 3, 3)
            + b"abc"
        )
        self.assertEqual(read_zip_entries(data), {"a.txt": raw, "b.txt": b"abc"})

    def test_empty_input_gives_no_entries(self):
        self.assertEqual(read_zip_entries(b""), {})

    def test_stops_at_a_non_local_signature(self):
        data = _local_header(b"a.txt", 0, 0, 3, 3) + b"abc" + b"PK\x01\x02" + b"\x00" * 20
        self.assertEqual(read_zip_entries(data), {"a.txt": b"abc"})

    def test_truncated_stored_entry_raises(self):
        data = _local_header(b"a.txt", 0, 0, 10, 10) + b"abc"
        with self.assertRaisesRegex(UnfError, "truncated entry"):
            read_zip_entries(data)

    def test_unsupported_method_raises(self):
        data = _local_header(b"a.txt", 0, 9, 3, 3) + b"abc"
        with self.assertRaisesRegex(UnfError, "unsupported compression method 9"):
            read_zip_entries(data)

    def test_bad_deflate_raises(self):
        data = _local_header(b"a.txt", 0, 8, 4, 4) + b"nope"
        with self.assertRaisesRegex(UnfError, "bad deflate data"):
            read_zip_entries(data)

    def test_descriptor_with_stored_method_raises(self):
        data = _local_header(b"a.txt", 0x08, 0, 0, 0) + b"abc"
        with self.assertRaisesRegex(UnfError, "data descriptor but method 0"):
            read_zip_entries(data)

    def test_incomplete_deflate_with_descriptor_raises(self):
        c = zlib.compressobj(9, zlib.DEFLATED, -15)
        partial = c.compress(b"hello" * 50)
        with self.assertRaisesRegex(UnfError, "truncated entry"):
            read_zip_entries(_local_header(b"a.txt", 0x08, 8, 0, 0) + partial)


class TestImportBackup(unittest.TestCase):
    def test_device_with_key_and_sorted_ports(self):
        key_hex = os.urandom(16).hex()
        docs = [
            {"__cmd": "select", "collection": "device"},
            {"mac": MAC_A, "model": "P3E", "name": "strip one", "x_authkey": key_hex},
            {"__cmd": "select", "collection": "sensor"},
            {"_id": "sensor2", "mac": MAC_A, "port": 2, "model": "Outlet", "label": "Lamp"},
            {"_id": "sensor1", "mac": MAC_A, "port": 1, "model": "Outlet", "label": "Fan"},
        ]
        records = import_backup(make_backup(docs, {"notes.txt": b"nothing secret"}))
        self.assertEqual(len(records), 1)
        device = records[0]
        self.assertEqual(device["mac"], MAC_A)
        self.assertEqual(device["authkey"], key_hex)
        self.assertEqual(device["model"], "P3E")
        self.assertEqual(device["name"], "strip one")
        self.assertEqual(device["state"], "unknown")
        self.assertEqual(device["last_seen_ms"], 0)
        self.assertEqual(
            device["ports"],
            [
                {"port": 1, "sensor_id": "sensor1", "label": "Fan", "model": "Outlet"},
                {"port": 2, "sensor_id": "sensor2", "label": "Lamp", "model": "Outlet"},
            ],
        )

    def test_colon_mac_is_normalized(self):
        docs = [
            {"__cmd": "select", "collection": "device"},
            {"mac": MAC_COLON, "model": "P3E", "x_authkey": os.urandom(16).hex()},
        ]
        records = import_backup(make_backup(docs, {}))
        self.assertEqual(records[0]["mac"], MAC_A)

    def test_sensors_before_devices_are_attached(self):
        key_hex = os.urandom(16).hex()
        docs = [
            {"__cmd": "select", "collection": "sensor"},
            {"_id": "sensor1", "mac": MAC_A, "port": 1, "model": "Outlet", "label": "Fan"},
            {"__cmd": "select", "collection": "device"},
            {"mac": MAC_A, "model": "P1E", "x_authkey": key_hex},
        ]
        records = import_backup(make_backup(docs, {}))
        self.assertEqual(records[0]["authkey"], key_hex)
        self.assertEqual(records[0]["ports"][0]["sensor_id"], "sensor1")

    def test_devices_sorted_by_mac_and_incomplete_sensors_skipped(self):
        docs = [
            {"__cmd": "select", "collection": "device"},
            {"mac": MAC_B, "model": "P1E", "name": "b"},
            {"mac": MAC_A, "model": "P1E", "name": "a"},
            {"__cmd": "select", "collection": "sensor"},
            {"_id": "s9", "mac": MAC_A, "model": "Outlet", "label": "No port"},
            {"_id": "s7", "mac": MAC_B, "port": 3, "model": "Outlet", "label": "Third"},
        ]
        records = import_backup(make_backup(docs, {}))
        self.assertEqual([record["mac"] for record in records], [MAC_A, MAC_B])
        self.assertEqual(records[0]["ports"], [])
        self.assertEqual(records[1]["ports"], [{"port": 3, "sensor_id": "s7", "label": "Third", "model": "Outlet"}])

    def test_authkey_is_lowercased_and_invalid_is_blank(self):
        key_hex = os.urandom(16).hex()
        docs = [
            {"__cmd": "select", "collection": "device"},
            {"mac": MAC_A, "model": "P1E", "x_authkey": key_hex.upper()},
            {"mac": MAC_B, "model": "P1E", "x_authkey": "not-a-key"},
        ]
        records = import_backup(make_backup(docs, {}))
        self.assertEqual(records[0]["authkey"], key_hex)
        self.assertEqual(records[1]["authkey"], "")

    def test_sensor_with_zero_port_is_skipped_not_fatal(self):
        docs = [
            {"__cmd": "select", "collection": "device"},
            {"mac": MAC_A, "model": "P1E", "name": "a"},
            {"__cmd": "select", "collection": "sensor"},
            {"_id": "s0", "mac": MAC_A, "port": 0, "model": "Outlet", "label": "Zero"},
            {"_id": "s1", "mac": MAC_A, "port": 1, "model": "Outlet", "label": "One"},
        ]
        records = import_backup(make_backup(docs, {}))
        self.assertEqual(len(records), 1)
        self.assertEqual(
            records[0]["ports"],
            [{"port": 1, "sensor_id": "s1", "label": "One", "model": "Outlet"}],
        )

    def test_missing_db_gz_raises(self):
        with self.assertRaisesRegex(UnfError, "db.gz not found in backup"):
            import_backup(_encrypt(_zip_bytes({"format": b"2"})))

    def test_too_short_backup_raises(self):
        with self.assertRaises(UnfError):
            import_backup(b"0" * 10)

    def test_invalid_gzip_raises(self):
        with self.assertRaisesRegex(UnfError, "not valid gzip"):
            import_backup(_encrypt(_zip_bytes({"db.gz": b"not gzip"})))

    def test_invalid_bson_raises(self):
        db = gzip.compress(b"\x05\x00\x00\x00")
        with self.assertRaisesRegex(UnfError, "not valid BSON"):
            import_backup(_encrypt(_zip_bytes({"db.gz": db})))

    def test_logs_skipped_records_without_the_key(self):
        key_hex = os.urandom(16).hex()
        docs = [
            {"__cmd": "select", "collection": "device"},
            {"model": "P1E", "name": "no mac", "x_authkey": key_hex},
            {"__cmd": "select", "collection": "sensor"},
            {"_id": "sensor9", "mac": MAC_B, "port": 1, "model": "Outlet", "label": "Orphan"},
        ]
        with self.assertLogs("mfi_server.unf", level="DEBUG") as logs:
            records = import_backup(make_backup(docs, {}))
        self.assertEqual(records, [])
        text = "\n".join(logs.output)
        self.assertIn("skipped device without a valid MAC", text)
        self.assertIn("skipped sensor of a device not in the backup", text)
        self.assertNotIn(key_hex, text)


if __name__ == "__main__":
    unittest.main()
