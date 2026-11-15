"""Tests for mfi_server.config: add-on mode, standalone mode and value precedence."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from mfi_server.config import load_settings


def _load(environ: dict[str, str], folder: str):
    """Standalone load with --data pointing at folder and no add-on options file."""
    return load_settings(["--data", folder], environ, options_path=Path(folder) / "no-options.json")


class TestAddonMode(unittest.TestCase):
    def test_options_json_is_read_in_addon_mode(self):
        with tempfile.TemporaryDirectory() as d:
            options = Path(d) / "options.json"
            options.write_text(
                json.dumps({"backup_file": "/share/mfi/backup.unf", "log_level": "debug"}),
                encoding="utf-8",
            )
            s = load_settings([], {}, options_path=options)
            self.assertEqual(s.mode, "addon")
            self.assertEqual(s.data_dir, Path(d))
            self.assertEqual(s.backup_file, "/share/mfi/backup.unf")
            self.assertEqual(s.log_level, "debug")
            self.assertEqual(s.inform_port, 6080)
            self.assertEqual(s.wakeup_port, 3478)

    def test_unknown_key_in_options_json_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            options = Path(d) / "options.json"
            options.write_text('{"color": 1}', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_settings([], {}, options_path=options)


class TestStandaloneMode(unittest.TestCase):
    def test_data_argument_and_environment(self):
        with tempfile.TemporaryDirectory() as d:
            environ = {"MFI_INFORM_PORT": "7080", "MFI_BIND_ADDRESS": "127.0.0.1"}
            s = _load(environ, d)
            self.assertEqual(s.mode, "standalone")
            self.assertEqual(s.data_dir, Path(d))
            self.assertEqual(s.inform_port, 7080)
            self.assertEqual(s.bind_address, "127.0.0.1")

    def test_file_value_is_used_without_environment(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "settings.json").write_text('{"inform_port": 6081}', encoding="utf-8")
            self.assertEqual(_load({}, d).inform_port, 6081)

    def test_environment_wins_over_file(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "settings.json").write_text('{"inform_port": 6081}', encoding="utf-8")
            self.assertEqual(_load({"MFI_INFORM_PORT": "6082"}, d).inform_port, 6082)

    def test_empty_environment_value_counts_as_unset(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "settings.json").write_text('{"inform_port": 6081}', encoding="utf-8")
            self.assertEqual(_load({"MFI_INFORM_PORT": ""}, d).inform_port, 6081)

    def test_defaults_without_arguments(self):
        with tempfile.TemporaryDirectory() as d:
            s = load_settings([], {}, options_path=Path(d) / "no-options.json")
            self.assertEqual(s.data_dir, Path("data"))
            self.assertEqual(s.log_level, "info")
            self.assertEqual(s.inform_port, 6080)


class TestValidation(unittest.TestCase):
    def test_invalid_inform_port_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            for value in ("70000", "0", "abc"):
                with self.subTest(value=value):
                    with self.assertRaises(ValueError) as cm:
                        _load({"MFI_INFORM_PORT": value}, d)
                    self.assertIn("inform_port", str(cm.exception))

    def test_wakeup_port_out_of_range_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError) as cm:
                _load({"MFI_WAKEUP_PORT": "70000"}, d)
            self.assertIn("wakeup_port", str(cm.exception))

    def test_invalid_log_level_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                _load({"MFI_LOG_LEVEL": "verbose"}, d)

    def test_log_level_is_lower_cased(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(_load({"MFI_LOG_LEVEL": "WARNING"}, d).log_level, "warning")

    def test_invalid_json_names_the_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "settings.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(ValueError) as cm:
                _load({}, d)
            self.assertIn(str(path), str(cm.exception))

    def test_unknown_key_in_settings_json_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "settings.json").write_text('{"color": 1}', encoding="utf-8")
            with self.assertRaises(ValueError):
                _load({}, d)

    def test_float_port_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "settings.json").write_text('{"inform_port": 80.7}', encoding="utf-8")
            with self.assertRaises(ValueError) as cm:
                _load({}, d)
            self.assertIn("inform_port", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
