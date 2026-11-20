"""Tests for the migration, backup copies, .unf import and Support Info of mfi_server_next (standard library only)."""
import gzip
import io
import json
import os
import stat
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path

from mfi_server_next import crypto, migrate


def element(type_byte, name, payload):
    """One BSON element: type byte, name as cstring, raw payload."""
    return bytes([type_byte]) + name.encode("ascii") + b"\x00" + payload


def doc(elements):
    """Wrap raw elements in a BSON document: int32 length, elements, 0x00."""
    return struct.pack("<i", len(elements) + 5) + elements + b"\x00"


def string_element(name, value):
    raw = value.encode("utf-8") + b"\x00"
    return element(0x02, name, struct.pack("<i", len(raw)) + raw)


def int_element(name, value):
    return element(0x10, name, struct.pack("<i", value))


def build_unf_bytes():
    """A synthetic .unf: one device and one sensor, encrypted like a real backup."""
    documents = (
        doc(string_element("__cmd", "select") + string_element("collection", "device"))
        + doc(
            string_element("mac", "002722aabbcc")
            + string_element("x_authkey", "ab" * 16)
            + string_element("model", "mPower")
            + string_element("name", "strip")
        )
        + doc(string_element("__cmd", "select") + string_element("collection", "sensor"))
        + doc(
            string_element("mac", "002722aabbcc")
            + int_element("port", 1)
            + string_element("_id", "s1")
            + string_element("label", "L")
            + string_element("model", "")
        )
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr("db.gz", gzip.compress(documents))
    return crypto.aes128_encrypt(migrate.UNF_KEY, migrate.UNF_IV, buffer.getvalue())


class TestMigrateAll(unittest.TestCase):
    def test_ca1_adds_defaults_and_second_run_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "devices.json"
            records = [
                {"mac": "002722aabbcc", "model": "mPower", "adopted": True},
                {"mac": "002722ddeeff", "model": "P1E", "adopted": False},
            ]
            path.write_text(json.dumps(records), encoding="utf-8")
            first = migrate.migrate_all(tmp)
            self.assertEqual(len(first), 1)
            self.assertTrue(first[0].startswith("devices.json."))
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(saved), 2)
            for index, record in enumerate(saved):
                for key in migrate.DEVICE_DEFAULTS:
                    with self.subTest(record=index, key=key):
                        self.assertIn(key, record)
                        self.assertIsNone(record[key])
            self.assertEqual(saved[0]["mac"], "002722aabbcc")
            self.assertEqual(saved[0]["model"], "mPower")
            self.assertIs(saved[0]["adopted"], True)
            self.assertIs(saved[1]["adopted"], False)
            before = path.read_bytes()
            self.assertEqual(migrate.migrate_all(tmp), [])
            self.assertEqual(path.read_bytes(), before)


class TestBackupCopies(unittest.TestCase):
    def test_ca2_keeps_five_newest_copies_with_mode_0600(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.json"
            path.write_text("x", encoding="utf-8")
            for i in range(7):
                migrate.backup_copy(path, keep=5, stamp=f"{i:04d}")
            copies = sorted(p.name for p in Path(tmp).glob("data.json.*.bak"))
            self.assertEqual(copies, [f"data.json.{i:04d}.bak" for i in range(2, 7)])
            for name in copies:
                with self.subTest(copy=name):
                    mode = stat.S_IMODE(os.stat(Path(tmp) / name).st_mode)
                    self.assertEqual(mode, 0o600)


class TestProtectedWrite(unittest.TestCase):
    def test_ca3_failed_write_restores_file_and_error_names_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "devices.json"
            path.write_text("X", encoding="utf-8")

            def writer():
                path.write_text("CHANGED", encoding="utf-8")
                raise RuntimeError("disk full")

            with self.assertRaises(migrate.MigrateError) as ctx:
                migrate.protected_write(path, writer, keep=5)
            self.assertIn("devices.json", str(ctx.exception))
            self.assertEqual(ctx.exception.path, str(path))
            self.assertIsInstance(ctx.exception.__cause__, RuntimeError)
            self.assertEqual(path.read_text(encoding="utf-8"), "X")


class TestImportBackup(unittest.TestCase):
    def test_ca4_imports_devices_and_leaves_backup_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            backup = Path(tmp) / "backup.unf"
            backup.write_bytes(build_unf_bytes())
            before = backup.read_bytes()
            result = migrate.import_backup(backup, data_dir=tmp)
            self.assertEqual(backup.read_bytes(), before)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["mac"], "002722aabbcc")
            self.assertEqual(result[0]["x_authkey"], "ab" * 16)
            devices_file = Path(tmp) / "devices.json"
            self.assertEqual(stat.S_IMODE(os.stat(devices_file).st_mode), 0o600)
            saved = json.loads(devices_file.read_text(encoding="utf-8"))
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0]["mac"], "002722aabbcc")
            self.assertEqual(saved[0]["x_authkey"], "ab" * 16)
            self.assertEqual(len(saved[0]["ports"]), 1)
            self.assertEqual(saved[0]["ports"][0]["port"], 1)
            self.assertEqual(saved[0]["ports"][0]["sensor_id"], "s1")


class TestSupportInfo(unittest.TestCase):
    def test_ca5_report_has_no_keys_passwords_or_macs(self):
        info = migrate.build_support_info(
            version="0.25.0",
            settings={
                "password": "s3cret-pass",
                "timezone": "Europe/Rome",
                "device_authkey": "ab" * 16,
            },
            log_lines=["device 002722aabbcc informed", "key " + "cd" * 16],
        )
        self.assertNotIn("s3cret-pass", info)
        self.assertNotIn("ab" * 16, info)
        self.assertNotIn("cd" * 16, info)
        self.assertNotIn("002722aabbcc", info)
        self.assertIn("Europe/Rome", info)
        self.assertIn("0.25.0", info)
        self.assertIn("***", info)


class TestImportBackupErrors(unittest.TestCase):
    def test_empty_backup_raises_and_leaves_no_devices(self):
        with tempfile.TemporaryDirectory() as tmp:
            backup = Path(tmp) / "empty.unf"
            backup.write_bytes(b"")
            with self.assertRaises(migrate.MigrateError):
                migrate.import_backup(backup, data_dir=tmp)
            self.assertFalse((Path(tmp) / "devices.json").exists())

    def test_wrong_key_raises_and_leaves_no_devices(self):
        with tempfile.TemporaryDirectory() as tmp:
            backup = Path(tmp) / "garbage.unf"
            backup.write_bytes(b"\x11" * 48)
            with self.assertRaises(migrate.MigrateError) as ctx:
                migrate.import_backup(backup, data_dir=tmp)
            self.assertEqual(ctx.exception.path, str(backup))
            self.assertFalse((Path(tmp) / "devices.json").exists())

    def test_zip_without_db_gz_raises(self):
        import io as _io
        buffer = _io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
            archive.writestr("other.txt", b"hello")
        payload = crypto.aes128_encrypt(migrate.UNF_KEY, migrate.UNF_IV, buffer.getvalue())
        with tempfile.TemporaryDirectory() as tmp:
            backup = Path(tmp) / "nodb.unf"
            backup.write_bytes(payload)
            with self.assertRaises(migrate.MigrateError):
                migrate.import_backup(backup, data_dir=tmp)
            self.assertFalse((Path(tmp) / "devices.json").exists())


class TestImportBackupMerge(unittest.TestCase):
    def test_import_keeps_existing_runtime_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            devices_file = Path(tmp) / "devices.json"
            devices_file.write_text(json.dumps([
                {"mac": "002722aabbcc", "model": "mPower", "name": "old",
                 "x_authkey": "ab" * 16, "ports": [], "state": "online",
                 "cfgversion": 7}
            ]), encoding="utf-8")
            backup = Path(tmp) / "backup.unf"
            backup.write_bytes(build_unf_bytes())
            migrate.import_backup(backup, data_dir=tmp)
            saved = json.loads(devices_file.read_text(encoding="utf-8"))
            self.assertEqual(len(saved), 1)
            device = saved[0]
            self.assertEqual(device["state"], "online")
            self.assertEqual(device["cfgversion"], 7)
            self.assertEqual(device["x_authkey"], "ab" * 16)
            self.assertEqual(len(device["ports"]), 1)
            copies = list(Path(tmp).glob("devices.json.*.bak"))
            self.assertTrue(copies)


class TestSupportInfoScrub(unittest.TestCase):
    def test_passwords_and_dash_or_upper_macs_are_removed(self):
        colon_mac = ":".join(["00", "27", "22", "AA", "BB", "CC"])
        info = migrate.build_support_info(
            version="0.25.0",
            settings={"timezone": "Europe/Rome"},
            log_lines=[
                "password=hunter2",
                "token: abc123def456",
                "mac 00-27-22-aa-bb-cc seen",
                "mac " + colon_mac + " seen",
            ],
        )
        self.assertNotIn("hunter2", info)
        self.assertNotIn("abc123def456", info)
        self.assertNotIn("00-27-22-aa-bb-cc", info)
        self.assertNotIn(colon_mac, info)
        self.assertIn("Europe/Rome", info)
        self.assertIn("***", info)


class TestRefinements(unittest.TestCase):
    def test_history_index_created_when_only_table_exists(self):
        import sqlite3
        from mfi_server_next import store
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / store.HISTORY_DB
            conn = sqlite3.connect(db_path)
            conn.execute(migrate.RAW_TABLE_DDL)
            conn.commit()
            conn.close()
            migrate.migrate_all(tmp)
            conn = sqlite3.connect(db_path)
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='raw_series'"
            ).fetchone()
            conn.close()
            self.assertIsNotNone(row)

    def test_missing_backup_path_raises_migrate_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(migrate.MigrateError):
                migrate.import_backup(Path(tmp) / "nope.unf", data_dir=tmp)

    def test_quoted_json_secret_and_bearer_are_scrubbed(self):
        info = migrate.build_support_info(
            version="0.25.0",
            settings={"timezone": "Europe/Rome"},
            log_lines=['"password": "hunter2secret"', "authorization: Bearer abcTOKENxyz"],
        )
        self.assertNotIn("hunter2secret", info)
        self.assertNotIn("abcTOKENxyz", info)
        self.assertIn("***", info)

    def test_import_saves_previous_authkey_when_it_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            devices_file = Path(tmp) / "devices.json"
            devices_file.write_text(json.dumps([
                {"mac": "002722aabbcc", "model": "mPower", "name": "old",
                 "x_authkey": "cd" * 16, "ports": [], "state": "online"}
            ]), encoding="utf-8")
            backup = Path(tmp) / "backup.unf"
            backup.write_bytes(build_unf_bytes())
            migrate.import_backup(backup, data_dir=tmp)
            saved = json.loads(devices_file.read_text(encoding="utf-8"))
            self.assertEqual(saved[0]["x_authkey"], "ab" * 16)
            self.assertEqual(saved[0]["x_prev_authkey"], "cd" * 16)


if __name__ == "__main__":
    unittest.main()
