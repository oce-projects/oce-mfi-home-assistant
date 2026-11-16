#!/usr/bin/env python3
"""
legacy_tls_proxy.py - open the setup page of an mFi Wi-Fi device in setup mode
from a current browser.

Version: 0.1.0

An mFi Wi-Fi device (mPower, mPower mini) without a Wi-Fi configuration runs
its own access point and serves its setup page at https://192.168.2.20 over
TLS 1.0 only. Current browsers removed TLS 1.0 (Chrome shows
ERR_SSL_VERSION_OR_CIPHER_MISMATCH). This prototype bridges them:

    browser --http--> 127.0.0.1:PORT --TLS 1.0--> device:443

It rewrites redirects, absolute links to the device, Origin/Referer and
"Secure" cookies, so the browser stays on the proxy.
Device facts: docs/PROTOCOL.md, section "Wi-Fi setup mode".
Design of the real program: docs/WIFI-SETUP.md.

Usage (the PC must be joined to the device access point):
    python legacy_tls_proxy.py --open
    python legacy_tls_proxy.py --map 8020=192.168.2.20 --map 8021=HOST
then open http://127.0.0.1:8020/ in the browser.

Security:
    - listens on 127.0.0.1 only, unless --bind says otherwise;
    - TLS 1.0 and weak ciphers are enabled only towards the device;
    - the device certificate is not verified: it is self-signed and expired;
    - query strings never reach the log: the setup form sends the Wi-Fi
      password in the query string of /captive.cgi.

Standard library only. Verified 2026-11-17 with Python 3.13.14 (OpenSSL 3.0.21)
against an mPower mini with firmware v2.1.11 (see docs/WIFI-SETUP.md).

Changelog:
0.1.0 - 2026-11-17 - prototype: TLS 1.0 with ALL:@SECLEVEL=0 towards the
        device, several devices with --map, default 192.168.2.20, rewrite of
        Location, absolute links, Origin, Referer and Secure cookies, HSTS
        dropped, query strings hidden in the log, --open.
"""
from __future__ import annotations

import argparse
import http.client
import re
import ssl
import sys
import threading
import time
import warnings
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

__version__ = "0.1.0"

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


def device_tls_context(ciphers: str) -> ssl.SSLContext:
    """TLS towards the device: TLS 1.0 allowed, certificate not verified."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.set_ciphers(ciphers)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        ctx.minimum_version = ssl.TLSVersion.TLSv1
    return ctx


def make_handler(host: str, device_port: int, ctx: ssl.SSLContext):
    """HTTP handler that forwards every request to https://host:device_port."""
    pattern = device_url_pattern(host, device_port)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "legacy_tls_proxy/" + __version__

        def log_message(self, fmt, *args):  # stdlib name
            sys.stdout.write(f"[{host}] " + hide_query(fmt % args) + "\n")
            sys.stdout.flush()

        def _forward(self):
            length = self.headers.get("Content-Length")
            body = self.rfile.read(int(length)) if length else None

            headers = {}
            for name, value in self.headers.items():
                low = name.lower()
                if low in HOP_BY_HOP:
                    continue
                if low in ("origin", "referer"):
                    value = rewrite_request_origin(value, host)
                headers[name] = value
            headers["Host"] = host
            headers["Accept-Encoding"] = "identity"

            try:
                conn = http.client.HTTPSConnection(host, device_port, context=ctx, timeout=TIMEOUT_S)
                conn.request(self.command, self.path, body=body, headers=headers)
                resp = conn.getresponse()
                data = resp.read()
                conn.close()
            except Exception as exc:  # device off, access point lost, TLS failure
                self.send_error(502, "Bad Gateway", f"device {host}:{device_port} not reachable: {exc}")
                return

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


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(
        description=f"legacy_tls_proxy {__version__}: open the TLS 1.0 setup page of mFi Wi-Fi devices")
    ap.add_argument("--map", action="append", type=parse_map, metavar="PORT=HOST[:PORT]",
                    help=f"local port = device, repeatable (default {DEFAULT_MAP})")
    ap.add_argument("--bind", default="127.0.0.1",
                    help="listen address (default 127.0.0.1 = this PC only)")
    ap.add_argument("--ciphers", default=DEFAULT_CIPHERS,
                    help=f"OpenSSL cipher list towards the device (default {DEFAULT_CIPHERS})")
    ap.add_argument("--open", action="store_true",
                    help="open the default browser on the first page")
    args = ap.parse_args(argv)

    maps = args.map or [parse_map(DEFAULT_MAP)]
    ctx = device_tls_context(args.ciphers)

    servers = []
    for local_port, host, device_port in maps:
        try:
            srv = ThreadingHTTPServer((args.bind, local_port), make_handler(host, device_port, ctx))
        except OSError as exc:
            print(f"ERROR: port {local_port} is busy or not available ({exc})", file=sys.stderr)
            return 1
        srv.daemon_threads = True
        servers.append((srv, local_port, host, device_port))

    print(f"legacy_tls_proxy {__version__} running.")
    for srv, local_port, host, device_port in servers:
        print(f"  open http://{args.bind}:{local_port}/  ->  https://{host}:{device_port} (TLS 1.0)")
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    print("Stop: close this window or press Ctrl+C.", flush=True)

    if args.open:
        webbrowser.open(f"http://{args.bind}:{servers[0][1]}/")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
