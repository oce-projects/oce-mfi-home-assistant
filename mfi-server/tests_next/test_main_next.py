"""Offline tests of the entry point of mfi_server_next (EPIC-15).

Migration runs before anything else; the three servers bind 127.0.0.1 on ephemeral ports; SIGTERM stops
them with exit code 0; a migration failure returns 2 with one stderr line that names the file. The UDP
discovery scan is switched off (discovery=False). Standard library only.
Run from mfi-server: python3 -m unittest discover -s tests_next -v
"""
import contextlib
import io
import json
import os
import signal
import tempfile
import threading
import unittest
from pathlib import Path

from mfi_server_next.__main__ import main, _settings, _parser, _Actions

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


if __name__ == "__main__":
    unittest.main()
