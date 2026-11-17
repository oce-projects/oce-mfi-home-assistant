"""Tests of the core bridge: pure functions, request flow, log privacy, port choice.

Everything runs on 127.0.0.1 with a plain-HTTP fake device: no TLS, no network,
no tkinter.
"""
from __future__ import annotations

import argparse
import contextlib
import http.client
import io
import socket
import ssl
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from mfi_wifi_setup.bridge import (
    Bridge,
    device_tls_context,
    device_url_pattern,
    hide_query,
    parse_map,
    rewrite_body,
    rewrite_cookie,
    rewrite_location,
    rewrite_request_origin,
)

DEVICE_HOST = "192.168.2.20"


class FakeDeviceHandler(BaseHTTPRequestHandler):
    """Plain-HTTP stand-in for the device setup page: records the request headers, answers with the device headers."""

    def do_GET(self):
        self.server.last_headers = self.headers
        body = b'<a href="https://192.168.2.20/app">app</a>'
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Location", "https://192.168.2.20/next")
        self.send_header("Set-Cookie", "S=1; Secure")
        self.send_header("Strict-Transport-Security", "max-age=1")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        """Silent: the fake device writes nothing, so the tests see only the bridge log."""


def get(port, path, headers=None):
    """GET through 127.0.0.1:port; returns the response and its body."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("GET", path, headers=headers or {})
        resp = conn.getresponse()
        return resp, resp.read()
    finally:
        conn.close()


class PureFunctionTest(unittest.TestCase):
    def setUp(self):
        self.pattern = device_url_pattern(DEVICE_HOST, 443)

    def test_rewrite_cookie_drops_secure_flag(self):
        self.assertEqual(rewrite_cookie("AIROS=1; Secure; HttpOnly"), "AIROS=1; HttpOnly")
        self.assertEqual(rewrite_cookie("A=1; Path=/"), "A=1; Path=/")

    def test_hide_query_replaces_query_string_only(self):
        self.assertEqual(hide_query("GET /x?wpa_key=K HTTP/1.1"), "GET /x?<hidden> HTTP/1.1")
        self.assertNotIn("wpa_key", hide_query("GET /x?wpa_key=K HTTP/1.1"))
        self.assertEqual(hide_query("GET /status.cgi HTTP/1.1"), "GET /status.cgi HTTP/1.1")

    def test_rewrite_location_turns_device_redirect_into_path(self):
        self.assertEqual(rewrite_location("https://192.168.2.20/foo", self.pattern), "/foo")
        self.assertEqual(rewrite_location("https://192.168.2.20", self.pattern), "/")
        self.assertEqual(rewrite_location("https://192.168.2.20:443/a", self.pattern), "/a")
        self.assertEqual(rewrite_location("https://other.example/x", self.pattern), "https://other.example/x")
        self.assertEqual(rewrite_location("/x", self.pattern), "/x")

    def test_rewrite_body_removes_device_origin_from_text(self):
        data = b'<a href="https://192.168.2.20/x">'
        self.assertEqual(rewrite_body(data, "text/html", self.pattern), b'<a href="/x">')
        self.assertEqual(rewrite_body(data, "image/png", self.pattern), data)
        self.assertEqual(rewrite_body(b"", "text/html", self.pattern), b"")

    def test_rewrite_request_origin_points_to_device(self):
        self.assertEqual(rewrite_request_origin("http://127.0.0.1:8020", DEVICE_HOST), "https://192.168.2.20")
        self.assertEqual(
            rewrite_request_origin("http://127.0.0.1:8020/setup", DEVICE_HOST),
            "https://192.168.2.20/setup",
        )

    def test_parse_map_reads_port_host_and_device_port(self):
        self.assertEqual(parse_map("8020=192.168.2.20"), (8020, "192.168.2.20", 443))
        self.assertEqual(parse_map("8021=192.168.2.20:8443"), (8021, "192.168.2.20", 8443))

    def test_parse_map_rejects_bad_text(self):
        for text in ("8020", "8020=", "x=192.168.2.20"):
            with self.subTest(text=text), self.assertRaises(argparse.ArgumentTypeError):
                parse_map(text)

    def test_device_tls_context_allows_tls_1_0_without_certificate_check(self):
        ctx = device_tls_context()
        self.assertEqual(ctx.minimum_version, ssl.TLSVersion.TLSv1)
        self.assertFalse(ctx.check_hostname)
        self.assertEqual(ctx.verify_mode, ssl.CERT_NONE)


class BridgeFlowTest(unittest.TestCase):
    def start_fake_device(self):
        device = ThreadingHTTPServer(("127.0.0.1", 0), FakeDeviceHandler)
        threading.Thread(target=device.serve_forever, daemon=True).start()
        self.addCleanup(device.server_close)
        self.addCleanup(device.shutdown)
        return device

    def start_bridge(self, device, **options):
        port = device.server_address[1]
        options.setdefault("preferred_port", 0)
        bridge = Bridge(
            host=DEVICE_HOST,
            device_port=port,
            connect=lambda: http.client.HTTPConnection("127.0.0.1", port, timeout=5),
            **options,
        )
        self.addCleanup(bridge.stop)
        bridge.start()
        return bridge

    def test_request_through_bridge_is_rewritten_both_ways(self):
        device = self.start_fake_device()
        bridge = self.start_bridge(device)
        resp, body = get(
            bridge.port,
            "/",
            headers={
                "Origin": f"http://127.0.0.1:{bridge.port}",
                "Referer": f"http://127.0.0.1:{bridge.port}/setup",
            },
        )
        # what the browser receives
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.getheader("Location"), "/next")
        self.assertEqual([v for k, v in resp.getheaders() if k.lower() == "set-cookie"], ["S=1"])
        self.assertIsNone(resp.getheader("Strict-Transport-Security"))
        self.assertNotIn(b"https://192.168.2.20", body)
        self.assertIn(b'href="/app"', body)
        # what the fake device receives
        received = device.last_headers
        self.assertEqual(received.get("Accept-Encoding"), "identity")
        self.assertEqual(received.get("Host"), DEVICE_HOST)
        self.assertEqual(received.get("Origin"), "https://192.168.2.20")
        self.assertEqual(received.get("Referer"), "https://192.168.2.20/setup")

    def test_query_string_never_reaches_the_log(self):
        device = self.start_fake_device()
        bridge = self.start_bridge(device)
        log = io.StringIO()
        with contextlib.redirect_stdout(log):
            resp, _ = get(bridge.port, "/captive.cgi?wpa_key=SUPERSECRET")
        self.assertEqual(resp.status, 200)
        self.assertIn("?<hidden>", log.getvalue())
        self.assertEqual(log.getvalue().count("SUPERSECRET"), 0)

    def test_busy_port_8020_moves_to_next_free_port(self):
        device = self.start_fake_device()
        occupier = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(occupier.close)
        try:
            occupier.bind(("127.0.0.1", 8020))
        except OSError as exc:
            self.skipTest(f"port 8020 cannot be bound here: {exc}")
        occupier.listen(1)
        bridge = self.start_bridge(device, preferred_port=8020)
        self.assertGreater(bridge.port, 8020)
        resp, _ = get(bridge.port, "/")
        self.assertEqual(resp.status, 200)
        occupier.close()

    def test_bridge_listens_only_on_loopback(self):
        device = self.start_fake_device()
        bridge = self.start_bridge(device)
        self.assertEqual(bridge._server.socket.getsockname()[0], "127.0.0.1")
        self.assertEqual(bridge.url, f"http://127.0.0.1:{bridge.port}/")


if __name__ == "__main__":
    unittest.main()
