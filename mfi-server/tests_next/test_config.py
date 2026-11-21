"""Tests for mfi_server_next.config: defaults, settings file, add-on options, environment and validation."""
import json
import tempfile
import unittest
from pathlib import Path

from mfi_server_next import config
from mfi_server_next.config import load_settings, resolve_backup_path, supervisor_mqtt

CONFIG_YAML = Path(__file__).resolve().parent.parent / "config.yaml"


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

    def test_port_out_of_range_raises(self):
        for value in ("0", "70000", "-5"):
            with self.subTest(value=value):
                with tempfile.TemporaryDirectory() as d:
                    with self.assertRaises(ValueError) as cm:
                        load_settings(d, environ={"MFI_INFORM_PORT": value})
                    self.assertIn("inform_port", str(cm.exception))

    def test_port_bounds_are_accepted(self):
        for value, expected in (("1", 1), ("65535", 65535)):
            with self.subTest(value=value):
                with tempfile.TemporaryDirectory() as d:
                    s = load_settings(d, environ={"MFI_INFORM_PORT": value})
                    self.assertEqual(s["inform_port"], expected)

    def test_non_integer_env_raises(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                load_settings(d, environ={"MFI_INFORM_PORT": "abc"})

    def test_empty_env_is_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            s = load_settings(d, environ={"MFI_INFORM_PORT": ""})
            self.assertEqual(s["inform_port"], 6080)

    def test_negative_history_and_backup_raise(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError) as cm:
                load_settings(d, environ={"MFI_HISTORY_DAYS": "-1"})
            self.assertIn("history_days", str(cm.exception))
            with self.assertRaises(ValueError) as cm:
                load_settings(d, environ={"MFI_BACKUP_COPIES": "-1"})
            self.assertIn("backup_copies", str(cm.exception))


class _FakeResponse:
    """Stands in for the object urlopen returns: a context manager with status and read()."""

    def __init__(self, status, body):
        self.status = status
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


def _opener_answering(status, body):
    """Return an opener that answers every request with the given status and body; no network."""

    def opener(request, timeout=None):
        return _FakeResponse(status, body)

    return opener


def _config_options_block():
    """Return the raw values of the options block of config.yaml, read up to the schema: line."""
    values = {}
    inside = False
    for line in CONFIG_YAML.read_text(encoding="utf-8").splitlines():
        if line == "options:":
            inside = True
            continue
        if line == "schema:":
            break
        if inside and line.startswith("  ") and ":" in line:
            key, _, raw = line[2:].partition(":")
            values[key.strip()] = raw.strip().strip('"')
    return values


def _addon_load(folder, options):
    """Write options.json in folder and load the settings in add-on mode."""
    Path(folder, "options.json").write_text(json.dumps(options), encoding="utf-8")
    return load_settings(folder, environ={}, mode="addon")


class TestSshDefaults(unittest.TestCase):
    def test_config_yaml_default_matches_code(self):
        options = _config_options_block()
        self.assertEqual(options["ssh_extra_options"], config.DEFAULT_SSH_EXTRA_OPTIONS)

    def test_code_default_is_used_when_unset(self):
        with tempfile.TemporaryDirectory() as d:
            s = load_settings(d, environ={})
            self.assertEqual(s["ssh_extra_options"], config.DEFAULT_SSH_EXTRA_OPTIONS)


class TestAddonOptions(unittest.TestCase):
    def test_six_options_reach_the_settings(self):
        with tempfile.TemporaryDirectory() as d:
            s = _addon_load(
                d,
                {
                    "backup_file": "backup.unf",
                    "log_level": "debug",
                    "server_address": "192.0.2.5",
                    "device_ssh_username": "mfiadmin",
                    "device_ssh_password": "pw",
                    "ssh_extra_options": config.DEFAULT_SSH_EXTRA_OPTIONS,
                },
            )
            self.assertEqual(s["backup_file"], "backup.unf")
            self.assertEqual(s["log_level"], "debug")
            self.assertEqual(s["server_address"], "192.0.2.5")
            self.assertEqual(s["device_ssh_username"], "mfiadmin")
            self.assertEqual(s["device_ssh_password"], "pw")
            self.assertEqual(s["ssh_extra_options"], config.DEFAULT_SSH_EXTRA_OPTIONS)

    def test_options_win_over_settings_file(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "settings.json").write_text(
                json.dumps({"log_level": "warning", "server_address": "192.0.2.1"}), encoding="utf-8"
            )
            s = _addon_load(d, {"log_level": "debug", "server_address": "192.0.2.5"})
            self.assertEqual(s["log_level"], "debug")
            self.assertEqual(s["server_address"], "192.0.2.5")

    def test_environment_wins_over_options(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "options.json").write_text(
                json.dumps({"log_level": "debug", "server_address": "192.0.2.5"}), encoding="utf-8"
            )
            s = load_settings(
                d,
                environ={"MFI_LOG_LEVEL": "error", "MFI_SERVER_ADDRESS": "192.168.1.20"},
                mode="addon",
            )
            self.assertEqual(s["log_level"], "error")
            self.assertEqual(s["server_address"], "192.168.1.20")

    def test_options_ignored_outside_addon_mode(self):
        for mode in ("standalone", None):
            with self.subTest(mode=mode):
                with tempfile.TemporaryDirectory() as d:
                    Path(d, "options.json").write_text(
                        json.dumps({"log_level": "debug", "server_address": "192.0.2.5"}), encoding="utf-8"
                    )
                    s = load_settings(d, environ={}, mode=mode)
                    self.assertEqual(s["log_level"], "info")
                    self.assertEqual(s["server_address"], "")

    def test_broken_options_file_error_names_the_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d, "options.json")
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(ValueError) as cm:
                load_settings(d, environ={}, mode="addon")
            self.assertIn(str(path), str(cm.exception))


class TestOptionValidation(unittest.TestCase):
    def test_bad_value_error_names_the_field(self):
        cases = (
            ("log_level", "nope"),
            ("server_address", "nonip"),
            ("ingress_peer", "nonip"),
            ("ssh_extra_options", "Foo=bar"),
        )
        for key, value in cases:
            with self.subTest(field=key):
                with tempfile.TemporaryDirectory() as d:
                    with self.assertRaises(ValueError) as cm:
                        _addon_load(d, {key: value})
                    self.assertIn(key, str(cm.exception))

    def test_blank_values_fall_back(self):
        with tempfile.TemporaryDirectory() as d:
            s = _addon_load(d, {"server_address": "   ", "ingress_peer": ""})
            self.assertEqual(s["server_address"], "")
            self.assertEqual(s["ingress_peer"], config.TRUSTED_INGRESS_PEER)

    def test_log_level_is_lower_cased(self):
        with tempfile.TemporaryDirectory() as d:
            s = _addon_load(d, {"log_level": "WARNING"})
            self.assertEqual(s["log_level"], "warning")


class TestOptionKeysMatchConfig(unittest.TestCase):
    def test_every_yaml_option_is_known_to_the_code(self):
        options = _config_options_block()
        self.assertEqual(sorted(set(options) - config.KNOWN_OPTION_KEYS), [])


class TestResolveBackupPath(unittest.TestCase):
    def test_absolute_path_is_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(resolve_backup_path("/data/backup.unf", share_dir=Path(d)), Path("/data/backup.unf"))

    def test_bare_name_found_in_share(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "backup.unf").write_bytes(b"x")
            self.assertEqual(resolve_backup_path("backup.unf", share_dir=Path(d)), Path(d, "backup.unf"))

    def test_bare_name_absent_is_returned_as_given(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(resolve_backup_path("missing.unf", share_dir=Path(d)), Path("missing.unf"))


class TestSupervisorMqtt(unittest.TestCase):
    def test_no_token_means_no_broker_and_is_logged(self):
        with self.assertLogs("mfi_server_next.config", level="INFO") as cm:
            self.assertIsNone(supervisor_mqtt({}, opener=_opener_answering(200, b"{}")))
        self.assertIn("MQTT disabled", cm.output[0])

    def test_broker_is_returned_and_password_is_not_logged(self):
        body = json.dumps(
            {"data": {"host": "broker.local", "port": 1883, "username": "u", "password": "pw-secret-7"}}
        ).encode("utf-8")
        with self.assertLogs("mfi_server_next.config", level="INFO") as cm:
            broker = supervisor_mqtt({"SUPERVISOR_TOKEN": "t"}, opener=_opener_answering(200, body))
        self.assertEqual(broker["host"], "broker.local")
        self.assertEqual(broker["port"], 1883)
        self.assertEqual(broker["username"], "u")
        self.assertEqual(broker["password"], "pw-secret-7")
        self.assertIs(broker["tls"], False)
        for line in cm.output:
            self.assertNotIn("pw-secret-7", line)

    def test_non_200_status_means_no_broker(self):
        with self.assertLogs("mfi_server_next.config", level="INFO"):
            self.assertIsNone(supervisor_mqtt({"SUPERVISOR_TOKEN": "t"}, opener=_opener_answering(503, b"{}")))

    def test_unreachable_supervisor_means_no_broker(self):
        def failing_opener(request, timeout=None):
            raise OSError("no route to host")

        with self.assertLogs("mfi_server_next.config", level="INFO"):
            self.assertIsNone(supervisor_mqtt({"SUPERVISOR_TOKEN": "t"}, opener=failing_opener))

    def test_answer_without_host_means_no_broker(self):
        body = json.dumps({"data": {"port": 1883}}).encode("utf-8")
        with self.assertLogs("mfi_server_next.config", level="INFO"):
            self.assertIsNone(supervisor_mqtt({"SUPERVISOR_TOKEN": "t"}, opener=_opener_answering(200, body)))

    def test_non_json_answer_means_no_broker(self):
        with self.assertLogs("mfi_server_next.config", level="INFO"):
            self.assertIsNone(
                supervisor_mqtt({"SUPERVISOR_TOKEN": "t"}, opener=_opener_answering(200, b"not json"))
            )


if __name__ == "__main__":
    unittest.main()
