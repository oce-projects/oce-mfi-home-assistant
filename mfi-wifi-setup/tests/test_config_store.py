"""Offline tests of config_store: the controller address saved between runs.

Standard library only; every file lives in a temporary folder.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from mfi_wifi_setup import config_store

ADDRESS = "homeassistant.local:6080"


class TestConfigStore(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_round_trip(self):
        path = self.dir / "config.json"
        config_store.save_controller_address(ADDRESS, path=path)
        self.assertEqual(config_store.load_controller_address(path=path), ADDRESS)

    def test_round_trip_non_ascii(self):
        path = self.dir / "config.json"
        config_store.save_controller_address("casa-è.local:6080", path=path)
        self.assertEqual(config_store.load_controller_address(path=path), "casa-è.local:6080")

    def test_missing_file_returns_empty(self):
        path = self.dir / "missing.json"
        self.assertEqual(config_store.load_controller_address(path=path), "")

    def test_corrupt_file_returns_empty(self):
        path = self.dir / "config.json"
        path.write_text("not json", encoding="utf-8")
        self.assertEqual(config_store.load_controller_address(path=path), "")

    def test_json_list_returns_empty(self):
        path = self.dir / "config.json"
        path.write_text("[1, 2]", encoding="utf-8")
        self.assertEqual(config_store.load_controller_address(path=path), "")

    def test_non_text_value_returns_empty(self):
        path = self.dir / "config.json"
        path.write_text('{"controller_address": 6080}', encoding="utf-8")
        self.assertEqual(config_store.load_controller_address(path=path), "")

    def test_saved_file_has_only_controller_address(self):
        path = self.dir / "config.json"
        config_store.save_controller_address(ADDRESS, path=path)
        raw = path.read_text(encoding="utf-8")
        self.assertIn("controller_address", raw)
        self.assertNotIn("password", raw)
        self.assertNotIn("wpa_key", raw)
        self.assertEqual(json.loads(raw), {"controller_address": ADDRESS})

    def test_second_save_replaces_first(self):
        path = self.dir / "config.json"
        config_store.save_controller_address("first.local:6080", path=path)
        config_store.save_controller_address(ADDRESS, path=path)
        self.assertEqual(config_store.load_controller_address(path=path), ADDRESS)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"controller_address": ADDRESS})

    def test_save_creates_missing_parent_folder(self):
        path = self.dir / "nested" / "folder" / "config.json"
        config_store.save_controller_address(ADDRESS, path=path)
        self.assertTrue(path.is_file())
        self.assertEqual(config_store.load_controller_address(path=path), ADDRESS)

    def test_config_file_uses_given_path(self):
        path = self.dir / "custom.json"
        self.assertEqual(config_store.config_file(path=path), path)

    def test_config_dir_name_is_app_name(self):
        self.assertEqual(config_store.config_dir().name, config_store.APP_NAME)


if __name__ == "__main__":
    unittest.main()
