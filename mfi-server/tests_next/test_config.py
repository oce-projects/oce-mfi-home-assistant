"""Tests for mfi_server_next.config: defaults, settings file and environment precedence."""
import json
import tempfile
import unittest
from pathlib import Path

from mfi_server_next.config import load_settings


class TestLoadSettings(unittest.TestCase):
    def test_defaults_without_file_and_environment(self):
        with tempfile.TemporaryDirectory() as d:
            s = load_settings(d, environ={})
            self.assertEqual(s["inform_port"], 6080)
            self.assertEqual(s["history_days"], 30)
            self.assertEqual(s["backup_copies"], 5)
            self.assertEqual(s["data_dir"], d)

    def test_file_wins_over_default(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "settings.json").write_text(json.dumps({"inform_port": 7000}), encoding="utf-8")
            s = load_settings(d, environ={})
            self.assertEqual(s["inform_port"], 7000)

    def test_environment_wins_over_file(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "settings.json").write_text(json.dumps({"inform_port": 7000}), encoding="utf-8")
            s = load_settings(d, environ={"MFI_INFORM_PORT": "9000"})
            self.assertEqual(s["inform_port"], 9000)
            self.assertIsInstance(s["inform_port"], int)

    def test_environment_integers_are_converted(self):
        with tempfile.TemporaryDirectory() as d:
            s = load_settings(d, environ={"MFI_HISTORY_DAYS": "14", "MFI_BACKUP_COPIES": "3"})
            self.assertEqual(s["history_days"], 14)
            self.assertEqual(s["backup_copies"], 3)

    def test_unknown_key_is_kept(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "settings.json").write_text(json.dumps({"future_key": "x"}), encoding="utf-8")
            s = load_settings(d, environ={})
            self.assertEqual(s["future_key"], "x")

    def test_broken_file_error_names_the_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d, "settings.json")
            path.write_text("not json{", encoding="utf-8")
            with self.assertRaises(ValueError) as cm:
                load_settings(d, environ={})
            self.assertIn(str(path), str(cm.exception))

    def test_non_object_file_error_names_the_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d, "settings.json")
            path.write_text("[1, 2]", encoding="utf-8")
            with self.assertRaises(ValueError) as cm:
                load_settings(d, environ={})
            self.assertIn(str(path), str(cm.exception))


if __name__ == "__main__":
    unittest.main()
