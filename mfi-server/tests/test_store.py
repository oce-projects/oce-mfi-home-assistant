"""Tests for mfi_server.store: the devices.json archive.

Each test works in its own temporary folder. Standard library only.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mfi_server.packet import DEFAULT_KEY_HEX
from mfi_server.store import FILE_NAME, DeviceStore

MAC = "02aabbccdd01"
OTHER_MAC = "02aabbccdd09"
FACTORY_KEY = bytes.fromhex(DEFAULT_KEY_HEX)


def make_record(mac: str = MAC, **changes: object) -> dict:
    record: dict = {
        "mac": mac,
        "model": "mPower",
        "name": "strip",
        "authkey": "",
        "ports": [{"port": 1, "sensor_id": "1", "label": "lamp", "model": "mPower"}],
        "state": "connected",
        "last_seen_ms": 5,
    }
    record.update(changes)
    return record


class StoreTestCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.path = self.folder / FILE_NAME
        self.tmp_path = self.folder / (FILE_NAME + ".tmp")


class TestPersistence(StoreTestCase):
    def test_upsert_is_read_back_by_a_new_store_with_defaults(self):
        archive = DeviceStore(self.folder)
        archive.upsert({"mac": "02AABBCCDD01", "ports": [{"port": 2}]})
        reopened = DeviceStore(self.folder)
        self.assertEqual(reopened.get(MAC), {
            "mac": MAC,
            "model": "",
            "name": "",
            "authkey": "",
            "ports": [{"port": 2, "sensor_id": "", "label": "", "model": ""}],
            "state": "unknown",
            "last_seen_ms": 0,
        })
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["schema"], 1)
        self.assertFalse(self.tmp_path.exists())

    def test_non_ascii_name_and_empty_ports_round_trip(self):
        archive = DeviceStore(self.folder)
        archive.upsert(make_record(name="lampada è accesa", ports=[]))
        self.assertEqual(DeviceStore(self.folder).get(MAC)["name"], "lampada è accesa")
        self.assertEqual(DeviceStore(self.folder).get(MAC)["ports"], [])


class TestKeys(StoreTestCase):
    def test_keys_for_follows_the_order_of_the_spec(self):
        key_hex = os.urandom(16).hex()
        archive = DeviceStore(self.folder)
        self.assertEqual(archive.keys_for(OTHER_MAC), [FACTORY_KEY])
        self.assertEqual(archive.keys_for("xyz"), [FACTORY_KEY])
        archive.upsert(make_record(authkey=key_hex))
        self.assertEqual(archive.keys_for(MAC), [bytes.fromhex(key_hex), FACTORY_KEY])
        archive.upsert(make_record(authkey=""))
        self.assertEqual(archive.keys_for(MAC), [FACTORY_KEY])


class TestDamagedFile(StoreTestCase):
    def test_damaged_file_raises_and_is_never_rewritten(self):
        bad_documents = {
            "not json": "{not json",
            "root is a list": "[]",
            "schema 2": json.dumps({"schema": 2, "devices": []}),
            "schema missing": json.dumps({"devices": []}),
            "devices not a list": json.dumps({"schema": 1, "devices": {}}),
        }
        for label, text in bad_documents.items():
            with self.subTest(label=label):
                self.path.write_text(text, encoding="utf-8")
                with self.assertRaises(ValueError) as ctx:
                    DeviceStore(self.folder)
                self.assertIn(FILE_NAME, str(ctx.exception))
                self.assertEqual(self.path.read_text(encoding="utf-8"), text)


class TestAtomicWrite(StoreTestCase):
    def test_failed_replace_keeps_previous_file(self):
        archive = DeviceStore(self.folder)
        archive.upsert(make_record())
        before = self.path.read_text(encoding="utf-8")
        with mock.patch("mfi_server.store.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                archive.upsert(make_record(mac=OTHER_MAC))
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)
        self.assertFalse(self.tmp_path.exists())
        self.assertIsNone(archive.get(OTHER_MAC))


class TestSecrecy(StoreTestCase):
    def test_key_never_reaches_log_or_repr(self):
        key_hex = os.urandom(16).hex()
        archive = DeviceStore(self.folder)
        with self.assertLogs("mfi_server.store", level="DEBUG") as cm:
            archive.upsert(make_record(authkey=key_hex))
        for line in cm.output:
            self.assertNotIn(key_hex, line)
        self.assertNotIn(key_hex, repr(archive))

    def test_bad_authkey_is_rejected_without_echoing_it(self):
        archive = DeviceStore(self.folder)
        with self.assertRaises(ValueError) as ctx:
            archive.upsert(make_record(authkey="abc"))
        self.assertIn(f"authkey of {MAC} must be 32 hex characters", str(ctx.exception))
        self.assertNotIn("abc", str(ctx.exception))
        self.assertFalse(self.path.exists())

    def test_bad_mac_is_rejected(self):
        archive = DeviceStore(self.folder)
        with self.assertRaises(ValueError):
            archive.upsert(make_record(mac="xyz"))
        self.assertIsNone(archive.get("xyz"))
        self.assertFalse(self.path.exists())


class TestImport(StoreTestCase):
    def test_import_keeps_state_and_authkey_of_known_device(self):
        key_hex = os.urandom(16).hex()
        archive = DeviceStore(self.folder)
        archive.upsert(make_record(authkey=key_hex, state="connected", last_seen_ms=5))
        imported = archive.import_records([make_record(authkey="", ports=[{"port": 1}, {"port": 2}])])
        self.assertEqual(imported, (1, 2))
        device = archive.get(MAC)
        self.assertEqual(device["state"], "connected")
        self.assertEqual(device["last_seen_ms"], 5)
        self.assertEqual(device["authkey"], key_hex)
        self.assertEqual([port["port"] for port in device["ports"]], [1, 2])

    def test_import_with_a_bad_record_changes_nothing(self):
        archive = DeviceStore(self.folder)
        with self.assertRaises(ValueError):
            archive.import_records([make_record(), make_record(mac="xyz")])
        self.assertEqual(archive.all(), [])
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
