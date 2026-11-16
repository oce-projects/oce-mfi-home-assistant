"""Tests for mfi_server.config: add-on mode, standalone mode and value precedence."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from mfi_server.config import load_settings, supervisor_mqtt


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


class _FakeResponse:
    """Stands in for the object urlopen returns: a context manager with status and read()."""

    def __init__(self, status: int, body: bytes):
        self.status = status
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


def _opener_answering(status: int, body: bytes):
    """Return an opener that answers every request with the given status and body; no network."""

    def opener(request, timeout=None):
        return _FakeResponse(status, body)

    return opener


class TestMqttSettings(unittest.TestCase):
    def test_mqtt_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            s = _load({}, d)
            self.assertEqual(s.mqtt_host, "")
            self.assertEqual(s.mqtt_port, 1883)
            self.assertEqual(s.mqtt_topic_prefix, "mfi")
            self.assertEqual(s.mqtt_discovery_prefix, "homeassistant")

    def test_mqtt_environment_is_read(self):
        with tempfile.TemporaryDirectory() as d:
            environ = {
                "MFI_MQTT_HOST": "core-mosquitto",
                "MFI_MQTT_PORT": "1884",
                "MFI_MQTT_TOPIC_PREFIX": "casa",
            }
            s = _load(environ, d)
            self.assertEqual(s.mqtt_host, "core-mosquitto")
            self.assertEqual(s.mqtt_port, 1884)
            self.assertEqual(s.mqtt_topic_prefix, "casa")

    def test_mqtt_port_out_of_range_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError) as cm:
                _load({"MFI_MQTT_PORT": "70000"}, d)
            self.assertIn("mqtt_port", str(cm.exception))

    def test_mqtt_port_non_numeric_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError) as cm:
                _load({"MFI_MQTT_PORT": "abc"}, d)
            self.assertIn("mqtt_port", str(cm.exception))

    def test_mqtt_discovery_prefix_from_environment(self):
        with tempfile.TemporaryDirectory() as d:
            s = _load({"MFI_MQTT_DISCOVERY_PREFIX": "ha"}, d)
            self.assertEqual(s.mqtt_discovery_prefix, "ha")


class TestWebAndHistorySettings(unittest.TestCase):
    def test_web_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            s = _load({}, d)
            self.assertEqual(s.web_port, 8099)
            self.assertEqual(s.history_days, 30)

    def test_from_settings_file(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "settings.json").write_text('{"web_port": 9000, "history_days": 7}', encoding="utf-8")
            s = _load({}, d)
            self.assertEqual(s.web_port, 9000)
            self.assertEqual(s.history_days, 7)

    def test_from_environment(self):
        with tempfile.TemporaryDirectory() as d:
            s = _load({"MFI_WEB_PORT": "9001", "MFI_HISTORY_DAYS": "14"}, d)
            self.assertEqual(s.web_port, 9001)
            self.assertEqual(s.history_days, 14)

    def test_history_days_out_of_range_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            for value in ("0", "4000"):
                with self.subTest(value=value):
                    with self.assertRaises(ValueError) as cm:
                        _load({"MFI_HISTORY_DAYS": value}, d)
                    self.assertIn("history_days", str(cm.exception))


class TestSupervisorMqtt(unittest.TestCase):
    def test_no_token_means_no_broker(self):
        with self.assertLogs("mfi_server.config", level="INFO") as cm:
            self.assertIsNone(supervisor_mqtt({}, _opener_answering(200, b"{}")))
        self.assertIn("MQTT disabled", cm.output[0])

    def test_addon_answer_sets_host_port_and_credentials_without_logging_password(self):
        body = json.dumps(
            {
                "result": "ok",
                "data": {"host": "core-mosquitto", "port": 1883, "username": "addon", "password": "pw-test"},
            }
        ).encode("utf-8")
        seen = {}

        def fake_opener(request, timeout=None):
            seen["authorization"] = request.get_header("Authorization")
            seen["timeout"] = timeout
            return _FakeResponse(200, body)

        with self.assertLogs("mfi_server.config", level="INFO") as cm:
            broker = supervisor_mqtt({"SUPERVISOR_TOKEN": "tok"}, fake_opener)
        self.assertEqual(
            broker,
            {"host": "core-mosquitto", "port": 1883, "username": "addon", "password": "pw-test"},
        )
        self.assertEqual(seen["authorization"], "Bearer tok")
        self.assertEqual(seen["timeout"], 10)
        for line in cm.output:
            self.assertNotIn("pw-test", line)

    def test_non_200_status_means_no_broker(self):
        self.assertIsNone(supervisor_mqtt({"SUPERVISOR_TOKEN": "tok"}, _opener_answering(503, b"{}")))

    def test_answer_without_data_means_no_broker(self):
        body = json.dumps({"result": "error", "message": "not running"}).encode("utf-8")
        self.assertIsNone(supervisor_mqtt({"SUPERVISOR_TOKEN": "tok"}, _opener_answering(200, body)))

    def test_answer_without_host_means_no_broker(self):
        body = json.dumps({"result": "ok", "data": {"port": 1883}}).encode("utf-8")
        self.assertIsNone(supervisor_mqtt({"SUPERVISOR_TOKEN": "tok"}, _opener_answering(200, body)))

    def test_unreachable_supervisor_means_no_broker(self):
        def failing_opener(request, timeout=None):
            raise OSError("no route to host")

        with self.assertLogs("mfi_server.config", level="INFO"):
            self.assertIsNone(supervisor_mqtt({"SUPERVISOR_TOKEN": "tok"}, failing_opener))

    def test_non_json_body_with_status_200_means_no_broker(self):
        self.assertIsNone(
            supervisor_mqtt({"SUPERVISOR_TOKEN": "tok"}, _opener_answering(200, b"not json"))
        )


class TestIngressPeerSetting(unittest.TestCase):
    def test_ingress_peer_default(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(_load({}, d).ingress_peer, "172.30.32.2")

    def test_ingress_peer_from_environment(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(_load({"MFI_INGRESS_PEER": "127.0.0.1"}, d).ingress_peer, "127.0.0.1")

    def test_ingress_peer_from_file(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "settings.json").write_text('{"ingress_peer": "127.0.0.1"}', encoding="utf-8")
            self.assertEqual(_load({}, d).ingress_peer, "127.0.0.1")

    def test_empty_ingress_peer_in_options_falls_back_to_default(self):
        with tempfile.TemporaryDirectory() as d:
            options = Path(d) / "options.json"
            options.write_text('{"ingress_peer": ""}', encoding="utf-8")
            s = load_settings([], {}, options_path=options)
            self.assertEqual(s.mode, "addon")
            self.assertEqual(s.ingress_peer, "172.30.32.2")

    def test_whitespace_ingress_peer_is_stripped(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "settings.json").write_text('{"ingress_peer": " 127.0.0.1 "}', encoding="utf-8")
            self.assertEqual(_load({}, d).ingress_peer, "127.0.0.1")

    def test_invalid_ingress_peer_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "settings.json").write_text('{"ingress_peer": "not-an-ip"}', encoding="utf-8")
            with self.assertRaises(ValueError):
                _load({}, d)


if __name__ == "__main__":
    unittest.main()
