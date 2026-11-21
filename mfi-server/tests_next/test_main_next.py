"""Offline tests of the entry point of mfi_server_next (EPIC-15).

Migration runs before anything else; the three servers bind 127.0.0.1 on ephemeral ports; SIGTERM stops
them with exit code 0; a migration failure returns 2 with one stderr line that names the file. The UDP
discovery scan is switched off (discovery=False). Standard library only.
Run from mfi-server: python3 -m unittest discover -s tests_next -v
"""
import contextlib
import io
import json
import logging
import os
import re
import signal
import tempfile
import threading
import unittest
from pathlib import Path

from mfi_server_next import devices
from mfi_server_next.__main__ import main, _settings, _parser, _Actions, _apply_log_level, _apply_supervisor_mqtt

LOOPBACK = "127.0.0.1"
SERVERS = ("inform", "web", "compat")


def _argv(data_dir):
    return [
        "--data-dir", data_dir,
        "--host", LOOPBACK,
        "--inform-port", "0",
        "--web-port", "0",
        "--compat-port", "0",
    ]


class TestStartAndStop(unittest.TestCase):
    """CA1: migration at start, three loopback servers on real ports, SIGTERM closes them and main returns 0."""

    def test_migrates_serves_on_loopback_and_stops_on_sigterm(self):
        with tempfile.TemporaryDirectory() as data_dir:
            devices_file = Path(data_dir, "devices.json")
            devices_file.write_text('[{"mac": "001122334455"}]', encoding="utf-8")
            started = []

            def on_ready(app):
                started.append(app)
                threading.Timer(0.2, os.kill, (os.getpid(), signal.SIGTERM)).start()

            code = main(_argv(data_dir), on_ready=on_ready, discovery=False)

            self.assertEqual(code, 0)
            self.assertEqual(len(started), 1)
            app = started[0]
            self.assertEqual(set(app.addresses), set(SERVERS))
            for name in SERVERS:
                host, port = app.addresses[name]
                with self.subTest(server=name):
                    self.assertEqual(host, LOOPBACK)
                    self.assertGreater(port, 0)
                    self.assertEqual(app.servers[name].socket.fileno(), -1)
            record = json.loads(devices_file.read_text(encoding="utf-8"))[0]
            self.assertIn("x_prev_authkey", record)
            self.assertTrue(list(Path(data_dir).glob("devices.json.*.bak")))


class TestStartFailures(unittest.TestCase):
    """CA2: a migration failure returns 2 with one stderr line that names the file, and nothing is served."""

    def test_devices_not_a_list_stops_before_any_server(self):
        with tempfile.TemporaryDirectory() as data_dir:
            Path(data_dir, "devices.json").write_text('{"not": "a list"}', encoding="utf-8")
            ready = []
            out = io.StringIO()
            err = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main(_argv(data_dir), on_ready=ready.append, discovery=False)

            self.assertEqual(code, 2)
            self.assertEqual(out.getvalue(), "")
            self.assertIn("devices.json", err.getvalue())
            self.assertEqual(ready, [])

    def test_port_out_of_range_returns_2(self):
        with tempfile.TemporaryDirectory() as data_dir:
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = main(["--data-dir", data_dir, "--web-port", "70000"], discovery=False)

            self.assertEqual(code, 2)
            self.assertIn("port", err.getvalue())


class TestSettingsOrder(unittest.TestCase):
    """A saved port/host is kept when its flag is absent; the flag overrides; else the default applies."""

    def test_saved_settings_kept_when_flag_absent(self):
        with tempfile.TemporaryDirectory() as data_dir:
            Path(data_dir, "settings.json").write_text(
                '{"host": "127.0.0.1", "web_port": 9000, "compat_port": 9001}', encoding="utf-8")
            args = _parser().parse_args(["--data-dir", data_dir])
            settings = _settings(args)
            self.assertEqual(settings["host"], "127.0.0.1")
            self.assertEqual(settings["web_port"], 9000)
            self.assertEqual(settings["compat_port"], 9001)

    def test_flag_overrides_saved_setting(self):
        with tempfile.TemporaryDirectory() as data_dir:
            Path(data_dir, "settings.json").write_text('{"web_port": 9000}', encoding="utf-8")
            args = _parser().parse_args(["--data-dir", data_dir, "--web-port", "1234"])
            self.assertEqual(_settings(args)["web_port"], 1234)

    def test_default_when_neither_flag_nor_setting(self):
        with tempfile.TemporaryDirectory() as data_dir:
            args = _parser().parse_args(["--data-dir", data_dir])
            settings = _settings(args)
            self.assertEqual(settings["web_port"], 8099)
            self.assertEqual(settings["compat_port"], 8100)
            self.assertEqual(settings["host"], "0.0.0.0")
            self.assertEqual(settings["mode"], "standalone")
            for flag in ("allow_webshell", "allow_browser_ssh", "allow_upnp", "allow_guest_page", "allow_script_action"):
                self.assertFalse(settings[flag])


class _FakeRegistry:
    def __init__(self, known):
        self._known = known
    def get(self, mac):
        return {"mac": mac} if mac in self._known else None


class TestActionsSetOutput(unittest.TestCase):
    """set_output coerces bool to int, refuses a bad port or a value other than 0/1, and 404s an unknown device."""

    def setUp(self):
        self.calls = []
        self.actions = _Actions(_FakeRegistry({"001122334455"}), None, lambda m, p, v: self.calls.append((m, p, v)))

    def test_bool_true_becomes_one(self):
        self.actions.set_output("001122334455", 1, True)
        self.assertEqual(self.calls, [("001122334455", 1, 1)])

    def test_unknown_device_raises_lookup_error(self):
        with self.assertRaises(LookupError):
            self.actions.set_output("ffffffffffff", 1, 1)

    def test_bad_port_raises_value_error(self):
        with self.assertRaises(ValueError):
            self.actions.set_output("001122334455", 0, 1)

    def test_bad_value_raises_value_error(self):
        with self.assertRaises(ValueError):
            self.actions.set_output("001122334455", 1, 2)


MAC = "001122334455"
KNOWN_AUTHKEY = "0123456789abcdef0123456789abcdef"
AUTHKEY_PATTERN = re.compile(r"[0-9a-f]{32}")


class FakeResult:
    """What subprocess.run returns: the exit code and the stderr bytes."""

    def __init__(self, returncode, stderr=b""):
        self.returncode = returncode
        self.stderr = stderr


class FakeRunner:
    """Stand-in for subprocess.run: records each call and answers with the scripted results in order."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((list(command), kwargs))
        if not self.answers:
            raise AssertionError("unexpected ssh call")
        return self.answers.pop(0)


class FakeResponse:
    """Stand-in for the Supervisor answer: a context manager with a status and a body."""

    status = 200

    def __init__(self, body):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class FakeSupervisor:
    """Stand-in for urllib.request.urlopen that answers like the Supervisor and records each request."""

    def __init__(self, body):
        self.body = body
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        return FakeResponse(self.body)


class NeverCalled:
    """An opener that fails the test if it is ever called."""

    def __call__(self, request, timeout=None):
        raise AssertionError("the Supervisor must not be asked")


SUPERVISOR_BODY = json.dumps({
    "data": {"host": "broker.local", "port": 1883, "username": "u", "password": "SecretPw-42", "ssl": False},
}).encode("utf-8")


class TestAdoptAndRepoint(unittest.TestCase):
    """CA4-CA6: Adopt and Repoint call set-adopt through the runner; Repoint reuses the key the device already has."""

    def setUp(self):
        saved = dict(devices._LOCAL_CACHE)
        devices._LOCAL_CACHE.clear()
        devices._LOCAL_CACHE["names"] = None
        self.addCleanup(self._restore_cache, saved)
        self.settings = {
            "device_ssh_username": "mfiadmin",
            "device_ssh_password": "pw",
            "ssh_extra_options": "",
            "server_address": "192.0.2.5",
            "inform_port": 6080,
            "mode": "standalone",
        }
        self.registry = devices.DeviceRegistry()
        self.registry.add(MAC, model="P1E", ip="192.0.2.10")

    @staticmethod
    def _restore_cache(saved):
        devices._LOCAL_CACHE.clear()
        devices._LOCAL_CACHE.update(saved)

    def actions(self, runner, **overrides):
        settings = {**self.settings, **overrides}
        return _Actions(self.registry, None, lambda *args: None, settings=settings, runner=runner)

    def test_adopt_runs_set_adopt_with_admin_user_and_server_address(self):
        runner = FakeRunner(FakeResult(0))
        self.actions(runner).adopt(MAC)
        self.assertEqual(len(runner.calls), 1)
        command = runner.calls[0][0]
        self.assertEqual(command[command.index("-l") + 1], "mfiadmin")
        self.assertIn("set-adopt", command)
        self.assertIn("http://192.0.2.5:6080/inform", command)
        self.assertIsNotNone(AUTHKEY_PATTERN.fullmatch(command[-1]))
        record = self.registry.get(MAC)
        self.assertTrue(record["adopted"])
        self.assertEqual(record["x_authkey"], command[-1])

    def test_adopt_without_known_address_is_refused(self):
        registry = devices.DeviceRegistry()
        registry.add("aabbccddeeff")
        runner = FakeRunner()
        actions = _Actions(registry, None, lambda *args: None, settings=self.settings, runner=runner)
        with self.assertRaisesRegex(ValueError, "no known address"):
            actions.adopt("aabbccddeeff")
        self.assertEqual(runner.calls, [])

    def test_missing_username_raises_naming_the_setting(self):
        runner = FakeRunner()
        with self.assertRaises(PermissionError) as caught:
            self.actions(runner, device_ssh_username="").adopt(MAC)
        self.assertIn("device_ssh_username", str(caught.exception))
        self.assertEqual(runner.calls, [])
        self.assertFalse(self.registry.get(MAC)["adopted"])

    def test_missing_password_raises_naming_the_setting(self):
        runner = FakeRunner()
        with self.assertRaises(PermissionError) as caught:
            self.actions(runner, device_ssh_password="").adopt(MAC)
        self.assertIn("device_ssh_password", str(caught.exception))
        self.assertEqual(runner.calls, [])

    def test_repoint_reuses_the_known_key(self):
        self.registry.adopt(MAC, x_authkey=KNOWN_AUTHKEY, cfgversion="c" * 16, portversion="d" * 16, ip="192.0.2.10")
        runner = FakeRunner(FakeResult(0))
        self.actions(runner).repoint(MAC)
        self.assertEqual(len(runner.calls), 1)
        command = runner.calls[0][0]
        self.assertIn("set-adopt", command)
        self.assertIn("http://192.0.2.5:6080/inform", command)
        self.assertEqual(command[-1], KNOWN_AUTHKEY)
        self.assertEqual(self.registry.get(MAC)["x_authkey"], KNOWN_AUTHKEY)

    def test_repoint_without_key_is_refused(self):
        runner = FakeRunner()
        with self.assertRaisesRegex(ValueError, "no adoption key"):
            self.actions(runner).repoint(MAC)
        self.assertEqual(runner.calls, [])

    def test_adopt_logs_and_raises_when_save_fails(self):
        runner = FakeRunner(FakeResult(0))
        def _boom():
            raise OSError("disk full")
        self.registry.save = _boom
        with self.assertRaises(OSError), self.assertLogs("mfi_server_next.__main__", level="WARNING") as caught:
            self.actions(runner).adopt(MAC)
        self.assertEqual(len(runner.calls), 1)
        authkey = runner.calls[0][0][-1]
        text = "\n".join(caught.output)
        self.assertIn(MAC, text)
        self.assertNotIn(authkey, text)
        self.assertNotIn("pw", text)


class TestLogLevel(unittest.TestCase):
    """CA10: the log_level setting sets the level of the root logger."""

    def test_each_level_name_maps_to_its_logging_level(self):
        root = logging.getLogger()
        previous = root.level
        self.addCleanup(root.setLevel, previous)
        expected = {"debug": logging.DEBUG, "info": logging.INFO, "warning": logging.WARNING, "error": logging.ERROR}
        for name, level in expected.items():
            with self.subTest(log_level=name):
                _apply_log_level({"log_level": name})
                self.assertEqual(root.level, level)


class TestSupervisorMqtt(unittest.TestCase):
    """CA11: in add-on mode the broker comes from the Supervisor unless mqtt_host is set; the password is never logged."""

    def test_broker_from_supervisor_fills_the_settings(self):
        opener = FakeSupervisor(SUPERVISOR_BODY)
        settings = {"mode": "addon"}
        _apply_supervisor_mqtt(settings, environ={"SUPERVISOR_TOKEN": "t"}, opener=opener)
        self.assertEqual(settings["mqtt_host"], "broker.local")
        self.assertEqual(settings["mqtt_port"], 1883)
        self.assertEqual(settings["mqtt_user"], "u")
        self.assertEqual(settings["mqtt_password"], "SecretPw-42")
        self.assertFalse(settings["mqtt_tls"])
        self.assertEqual(opener.requests[0].full_url, "http://supervisor/services/mqtt")
        self.assertEqual(opener.requests[0].get_header("Authorization"), "Bearer t")

    def test_without_token_the_host_is_not_set(self):
        opener = FakeSupervisor(SUPERVISOR_BODY)
        settings = {"mode": "addon"}
        _apply_supervisor_mqtt(settings, environ={}, opener=opener)
        self.assertNotIn("mqtt_host", settings)
        self.assertEqual(opener.requests, [])

    def test_configured_host_skips_the_supervisor(self):
        settings = {"mode": "addon", "mqtt_host": "x"}
        _apply_supervisor_mqtt(settings, environ={"SUPERVISOR_TOKEN": "t"}, opener=NeverCalled())
        self.assertEqual(settings["mqtt_host"], "x")

    def test_password_never_reaches_the_log(self):
        settings = {"mode": "addon"}
        with self.assertLogs(level="INFO") as caught:
            _apply_supervisor_mqtt(settings, environ={"SUPERVISOR_TOKEN": "t"}, opener=FakeSupervisor(SUPERVISOR_BODY))
        text = "\n".join(caught.output)
        self.assertIn("broker.local", text)
        self.assertNotIn("SecretPw-42", text)


if __name__ == "__main__":
    unittest.main()
