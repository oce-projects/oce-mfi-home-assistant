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

from mfi_server_next.__main__ import main

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


if __name__ == "__main__":
    unittest.main()
