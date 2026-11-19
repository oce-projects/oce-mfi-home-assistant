"""Tests for mfi_server_next.store: sqlite3 transactions and atomic JSON files.

Each test works in its own temporary folder. Standard library only.
"""
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mfi_server_next.store import Store

FAKE_AUTHKEY = "deadbeef"


class StoreTestCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.store = Store.open(self.folder)
        self.addCleanup(self.store.close)


class TestJson(StoreTestCase):
    def test_write_then_read_round_trip(self):
        self.store.write_json("devices.json", {"a": 1})
        self.assertEqual(self.store.read_json("devices.json"), {"a": 1})

    def test_missing_file_returns_default(self):
        self.assertEqual(self.store.read_json("absent.json", default={}), {})
        self.assertIsNone(self.store.read_json("absent.json"))

    def test_write_leaves_no_temporary_file(self):
        self.store.write_json("devices.json", {"a": 1})
        self.assertTrue((self.folder / "devices.json").is_file())
        self.assertEqual([p.name for p in self.folder.iterdir() if p.name.endswith(".tmp")], [])

    def test_failed_replace_keeps_previous_file_and_removes_temporary(self):
        self.store.write_json("devices.json", {"a": 1})
        with mock.patch("mfi_server_next.store.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.store.write_json("devices.json", {"a": 2})
        self.assertEqual(self.store.read_json("devices.json"), {"a": 1})
        self.assertFalse((self.folder / "devices.json.tmp").exists())

    def test_unsafe_names_are_rejected(self):
        for name in ("../x.json", "/etc/x.json", "", ".", ".."):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    self.store.write_json(name, {})
                with self.assertRaises(ValueError):
                    self.store.read_json(name)

    def test_corrupt_json_raises_value_error_naming_file(self):
        (self.folder / "bad.json").write_text("{oops", encoding="utf-8")
        with self.assertRaises(ValueError) as cm:
            self.store.read_json("bad.json")
        self.assertIn("bad.json", str(cm.exception))


class TestPrivateFile(StoreTestCase):
    def test_private_file_has_mode_0600(self):
        self.store.write_json("keys.json", {"authkey": FAKE_AUTHKEY}, private=True)
        path = self.folder / "keys.json"
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertEqual(self.store.read_json("keys.json"), {"authkey": FAKE_AUTHKEY})

    def test_private_write_over_residual_tmp_is_0600(self):
        tmp_path = self.folder / "keys.json.tmp"
        tmp_path.write_text("", encoding="utf-8")
        os.chmod(tmp_path, 0o644)
        self.store.write_json("keys.json", {"authkey": FAKE_AUTHKEY}, private=True)
        self.assertEqual(stat.S_IMODE(os.stat(self.folder / "keys.json").st_mode), 0o600)
        self.assertFalse(tmp_path.exists())


class TestFolderAndConnections(StoreTestCase):
    def test_open_creates_folder_with_mode_0700_and_both_databases(self):
        folder = self.folder / "data"
        store = Store.open(folder)
        self.addCleanup(store.close)
        self.assertEqual(stat.S_IMODE(os.stat(folder).st_mode), 0o700)
        self.assertTrue((folder / "state.sqlite3").is_file())
        self.assertTrue((folder / "history.sqlite3").is_file())

    def test_sqlite_files_have_mode_0600(self):
        folder = self.folder / "sqlite"
        store = Store.open(folder)
        self.addCleanup(store.close)
        self.assertEqual(stat.S_IMODE(os.stat(folder / "state.sqlite3").st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(folder / "history.sqlite3").st_mode), 0o600)


class TestTransaction(StoreTestCase):
    def names(self) -> list:
        with self.store.transaction() as conn:
            return conn.execute("SELECT name FROM items ORDER BY name").fetchall()

    def test_committed_row_stays_after_exit(self):
        with self.store.transaction() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS items (name TEXT NOT NULL)")
            conn.execute("INSERT INTO items (name) VALUES (?)", ("lamp",))
        self.assertEqual(self.names(), [("lamp",)])

    def test_exception_rolls_back_row_inserted_before_it(self):
        with self.store.transaction() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS items (name TEXT NOT NULL)")
            conn.execute("INSERT INTO items (name) VALUES (?)", ("lamp",))
        with self.assertRaises(RuntimeError):
            with self.store.transaction() as conn:
                conn.execute("INSERT INTO items (name) VALUES (?)", ("ghost",))
                raise RuntimeError("planned failure")
        self.assertEqual(self.names(), [("lamp",)])


if __name__ == "__main__":
    unittest.main()
