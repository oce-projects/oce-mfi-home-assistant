"""Core bridge of mfi-wifi-setup: the browser talks plain HTTP to 127.0.0.1,
the bridge talks TLS 1.0 to the setup page of the device.

Pure functions and the request handler come from prototype/legacy_tls_proxy.py
0.1.0 and keep its behaviour. The upstream connection is injectable, so the
tests run against a plain-HTTP fake device on 127.0.0.1. Standard library only,
no tkinter.
"""
from __future__ import annotations

import argparse
import functools
import http.client
import re
import socket
import ssl
import sys
import threading
import warnings
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_MAP = "8020=192.168.2.20"
DEFAULT_CIPHERS = "ALL:@SECLEVEL=0"
TIMEOUT_S = 20

HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
}
DROPPED_RESPONSE_HEADERS = HOP_BY_HOP | {"content-length", "strict-transport-security"}
TEXT_TYPES = ("text/", "application/javascript", "application/x-javascript", "application/json")
RE_SECURE = re.compile(r";\s*secure\b", re.IGNORECASE)
RE_PROXY_ORIGIN = re.compile(r"^https?://[^/]+")
RE_QUERY = re.compile(r"\?[^\s\"']*")


def hide_query(text: str) -> str:
    """Replace every query string with '?<hidden>' (the Wi-Fi password travels there)."""
    return RE_QUERY.sub("?<hidden>", text)


def device_url_pattern(host: str, port: int) -> re.Pattern[str]:
    """Absolute URL of the device (http or https, optional port), ending at a URL boundary."""
    return re.compile(r"https?://" + re.escape(host) + r"(?::" + str(port) + r")?(?=[/?#\"'\s<>)]|$)")


def rewrite_location(value: str, pattern: re.Pattern[str]) -> str:
    """Absolute redirect to the device -> path on the proxy."""
    m = pattern.match(value)
    if not m:
        return value
    return value[m.end():] or "/"


def rewrite_body(data: bytes, content_type: str, pattern: re.Pattern[str]) -> bytes:
    """Remove the device origin from absolute links in text responses."""
    if not data or not (content_type or "").lower().startswith(TEXT_TYPES):
        return data
    return re.compile(pattern.pattern.encode("ascii")).sub(b"", data)


def rewrite_cookie(value: str) -> str:
    """Drop the Secure flag: the browser talks plain http to 127.0.0.1."""
    return RE_SECURE.sub("", value)


def rewrite_request_origin(value: str, host: str) -> str:
    """Origin and Referer point to the proxy; the device expects its own origin."""
    return RE_PROXY_ORIGIN.sub(f"https://{host}", value, count=1)


def device_tls_context(ciphers: str = DEFAULT_CIPHERS) -> ssl.SSLContext:
    """TLS towards the device: TLS 1.0 allowed, certificate not verified."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.set_ciphers(ciphers)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        ctx.minimum_version = ssl.TLSVersion.TLSv1
    return ctx


def parse_map(text: str) -> tuple[int, str, int]:
    """'8020=192.168.2.20' or '8020=192.168.2.20:443' -> (8020, '192.168.2.20', 443)."""
    port_s, sep, device = text.partition("=")
    if not sep or not device:
        raise argparse.ArgumentTypeError(f"bad map {text!r}: use PORT=HOST or PORT=HOST:PORT")
    host, _, device_port = device.partition(":")
    try:
        return int(port_s), host, int(device_port) if device_port else 443
    except ValueError:
        raise argparse.ArgumentTypeError(f"port is not a number in {text!r}") from None


def make_handler(host: str, device_port: int, connect: Callable[[], http.client.HTTPConnection]):
    """HTTP handler that forwards every request through connect() to the device."""
    pattern = device_url_pattern(host, device_port)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "mfi-wifi-setup"

        def log_message(self, fmt, *args):  # stdlib name
            sys.stdout.write(f"[{host}] " + hide_query(fmt % args) + "\n")
            sys.stdout.flush()

        def _forward(self):
            length = self.headers.get("Content-Length")
            try:
                size = int(length) if length else 0
            except ValueError:
                self.send_error(400, "Bad Request", "Content-Length is not a number")
                return
            body = self.rfile.read(size) if size else None

            headers = {}
            for name, value in self.headers.items():
                low = name.lower()
                if low in HOP_BY_HOP or low in ("host", "accept-encoding"):
                    continue
                if low in ("origin", "referer"):
                    value = rewrite_request_origin(value, host)
                headers[name] = value
            headers["Host"] = host
            headers["Accept-Encoding"] = "identity"

            conn = None
            try:
                conn = connect()
                conn.request(self.command, self.path, body=body, headers=headers)
                resp = conn.getresponse()
                data = resp.read()
            except Exception as exc:  # device off, access point lost, TLS failure
                self.send_error(502, "Bad Gateway", f"device {host}:{device_port} not reachable: {exc}")
                return
            finally:
                if conn is not None:
                    conn.close()

            data = rewrite_body(data, resp.getheader("Content-Type", ""), pattern)
            self.send_response(resp.status, resp.reason)
            for name, value in resp.getheaders():
                low = name.lower()
                if low in DROPPED_RESPONSE_HEADERS:
                    continue
                if low == "location":
                    value = rewrite_location(value, pattern)
                elif low == "set-cookie":
                    value = rewrite_cookie(value)
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Connection", "close")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)
            self.close_connection = True

        do_GET = do_POST = do_PUT = do_DELETE = _forward
        do_HEAD = do_OPTIONS = do_PATCH = _forward

    return Handler


def _device_connection(host: str, device_port: int, ciphers: str) -> http.client.HTTPSConnection:
    """Default upstream connection: HTTPS to the device with the TLS 1.0 context."""
    return http.client.HTTPSConnection(
        host, device_port, context=device_tls_context(ciphers), timeout=TIMEOUT_S
    )


def find_free_port(preferred: int, bind: str = "127.0.0.1") -> int:
    """Return `preferred` if it can be bound, else the first free port above it."""
    for port in range(preferred, 65536):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind((bind, port))
            except OSError:
                continue
        return port
    raise OSError(f"no free port from {preferred} on {bind}")


class Bridge:
    """Local HTTP server that forwards to the device; binds only to `bind` (127.0.0.1 by default)."""

    def __init__(
        self,
        host: str = "192.168.2.20",
        device_port: int = 443,
        preferred_port: int = 8020,
        bind: str = "127.0.0.1",
        connect: Callable[[], http.client.HTTPConnection] | None = None,
        ciphers: str = DEFAULT_CIPHERS,
    ) -> None:
        self.host = host
        self.device_port = device_port
        self.preferred_port = preferred_port
        self.bind = bind
        if connect is None:
            connect = functools.partial(_device_connection, host, device_port, ciphers)
        self.connect = connect
        self.port = 0
        self._server = None
        self._thread = None

    def start(self) -> int:
        """Start serving in a daemon thread and return the port actually used."""
        if self._server is not None:
            raise RuntimeError("bridge already running")
        port = find_free_port(self.preferred_port, self.bind)
        handler = make_handler(self.host, self.device_port, self.connect)
        server = ThreadingHTTPServer((self.bind, port), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self._server = server
        self._thread = thread
        self.port = server.server_address[1]
        return self.port

    def stop(self) -> None:
        """Stop the server; safe to call more than once."""
        server, self._server = self._server, None
        if server is None:
            return
        server.shutdown()
        server.server_close()
        self._thread = None

    @property
    def url(self) -> str:
        return f"http://{self.bind}:{self.port}/"
