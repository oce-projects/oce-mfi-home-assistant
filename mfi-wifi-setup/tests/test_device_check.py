"""Offline tests of mfi_wifi_setup.device_check: the three states of GET /status.cgi.

Run from the mfi-wifi-setup folder:
    python3 -m unittest discover -s tests -t . -v

Standard library only; no tkinter, no device: the fake status.cgi listens on 127.0.0.1.
"""
from __future__ import annotations

import errno
import http.client
import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from mfi_wifi_setup import device_check

FOUND_BODY = b'{"host": {"hostname": "mFi-mPowerMini-A1B2C3", "fwversion": "v2.1.11"}}'


class _StatusHandler(BaseHTTPRequestHandler):
    body = b""

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, fmt, *args):
        pass


def _fake_status(body: bytes) -> ThreadingHTTPServer:
    """Start a fake status.cgi on 127.0.0.1 on a free port; stop it with _stop."""
    handler = type("Handler", (_StatusHandler,), {"body": body})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _stop(server: ThreadingHTTPServer) -> None:
    server.shutdown()
    server.server_close()


def _http_to(server: ThreadingHTTPServer):
    """Connect factory for the fake server: a plain HTTP connection to 127.0.0.1."""
    port = server.server_address[1]
    return lambda: http.client.HTTPConnection("127.0.0.1", port, timeout=5)


def _raising(exc: BaseException):
    """Connect factory that fails with exc, as a closed or unreachable device does."""

    def connect():
        raise exc

    return connect


class TestFound(unittest.TestCase):
    def test_json_gives_found_with_model_and_firmware(self):
        server = _fake_status(FOUND_BODY)
        self.addCleanup(_stop, server)
        status = device_check.read_status(_http_to(server))
        self.assertEqual(status.state, device_check.STATE_FOUND)
        self.assertEqual(status.model, "mFi-mPowerMini-A1B2C3")
        self.assertEqual(status.firmware, "v2.1.11")

    def test_missing_firmware_gives_empty_text(self):
        server = _fake_status(b'{"host": {"hostname": "mFi-mPowerMini-A1B2C3"}}')
        self.addCleanup(_stop, server)
        status = device_check.read_status(_http_to(server))
        self.assertEqual(status.state, device_check.STATE_FOUND)
        self.assertEqual(status.model, "mFi-mPowerMini-A1B2C3")
        self.assertEqual(status.firmware, "")


class TestNotOnNetwork(unittest.TestCase):
    def test_refused_connection_gives_not_on_network(self):
        status = device_check.read_status(_raising(OSError(errno.ECONNREFUSED, "refused")))
        self.assertEqual(status.state, device_check.STATE_NOT_ON_NETWORK)

    def test_unreachable_network_gives_not_on_network(self):
        status = device_check.read_status(_raising(OSError(errno.ENETUNREACH, "net")))
        self.assertEqual(status.state, device_check.STATE_NOT_ON_NETWORK)

    def test_all_no_route_errnos_give_not_on_network(self):
        for code in (errno.ECONNREFUSED, errno.ENETUNREACH, errno.EHOSTUNREACH, errno.EHOSTDOWN):
            with self.subTest(errno=errno.errorcode[code]):
                status = device_check.read_status(_raising(OSError(code, "no route")))
                self.assertEqual(status.state, device_check.STATE_NOT_ON_NETWORK)


class TestNotAnswering(unittest.TestCase):
    def test_timeout_gives_not_answering(self):
        status = device_check.read_status(_raising(socket.timeout("timed out")))
        self.assertEqual(status.state, device_check.STATE_NOT_ANSWERING)

    def test_other_os_error_gives_not_answering(self):
        status = device_check.read_status(_raising(OSError(errno.ECONNRESET, "reset")))
        self.assertEqual(status.state, device_check.STATE_NOT_ANSWERING)

    def test_invalid_response_gives_not_answering(self):
        for body in (b"not-json", b"", b"[]"):
            with self.subTest(body=body):
                server = _fake_status(body)
                try:
                    status = device_check.read_status(_http_to(server))
                finally:
                    _stop(server)
                self.assertEqual(status.state, device_check.STATE_NOT_ANSWERING)


class TestSettings(unittest.TestCase):
    def test_check_interval_is_2_seconds(self):
        self.assertEqual(device_check.CHECK_INTERVAL_S, 2)
        self.assertIsInstance(device_check.CHECK_INTERVAL_S, int)

    def test_three_distinct_states(self):
        states = {device_check.STATE_FOUND, device_check.STATE_NOT_ON_NETWORK, device_check.STATE_NOT_ANSWERING}
        self.assertEqual(len(states), 3)


if __name__ == "__main__":
    unittest.main()
