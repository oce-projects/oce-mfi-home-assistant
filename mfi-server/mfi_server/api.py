"""HTTP JSON API of mfi-server: health, login, devices, output commands and history.

Standard library only. Routes are found by the 'api/v1/' part of the path, so
the Home Assistant ingress prefix ('/api/hassio_ingress/<token>/') is accepted.
Standalone mode needs a session cookie and answers 503 until a password is set
with 'python3 -m mfi_server set-password'. Add-on mode serves only the requests
that come from the Home Assistant ingress address.
"""
from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import mfi_server
from mfi_server.auth import load_password_hash, verify_password

logger = logging.getLogger(__name__)

# Home Assistant Supervisor ingress address, see developers.home-assistant.io (add-on ingress).
INGRESS_PEER = "172.30.32.2"
MAX_BODY = 65536
# After a refused oversized body, up to this many bytes are read so the client receives the answer.
MAX_DRAIN = 1048576
DEFAULT_WEB_PORT = 8099
API_MARKER = "api/v1/"
HEALTH_ROUTE = "api/v1/health"
LOGIN_ROUTE = "api/v1/login"
LOGOUT_ROUTE = "api/v1/logout"
HISTORY_ROUTE = "api/v1/history"
DEVICES_ROUTE = "api/v1/devices"
SESSION_COOKIE = "mfi_session"
WEB_DIR = Path(__file__).resolve().parent / "web"
STATIC_FILES = {
    "index.html": "text/html; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
    "style.css": "text/css; charset=utf-8",
    "i18n/en.json": "application/json; charset=utf-8",
    "i18n/it.json": "application/json; charset=utf-8",
}
STATIC_CSP = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:"


class ApiServer(ThreadingHTTPServer):
    """HTTP server that answers API requests with the shared state objects."""

    daemon_threads = True

    def __init__(self, settings, store, states, measurements, history, control, sessions, limiter) -> None:
        self.settings = settings
        self.store = store
        self.states = states
        self.measurements = measurements
        self.history = history
        self.control = control
        self.sessions = sessions
        self.limiter = limiter
        super().__init__((settings.bind_address, getattr(settings, "web_port", DEFAULT_WEB_PORT)), ApiHandler)


def make_api_server(settings, store, states, measurements, history, control, sessions, limiter) -> ThreadingHTTPServer:
    """Build the API server bound to settings.bind_address and the web port."""
    return ApiServer(settings, store, states, measurements, history, control, sessions, limiter)


class ApiHandler(BaseHTTPRequestHandler):
    """Answers GET and POST requests of the JSON API."""

    def setup(self) -> None:
        # Bound the time a slow client can hold a worker thread (body is read before auth).
        self.timeout = self.server.settings.request_timeout_s
        super().setup()

    def log_message(self, format: str, *args: object) -> None:
        logger.debug("api: %s", format % args)

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def _dispatch(self, method: str) -> None:
        idx = self.path.find(API_MARKER)
        if idx == -1:
            if method == "GET":
                self._serve_static()
            else:
                self._error(404, "not_found")
            return
        route = self.path[idx:].split("?")[0]
        body = b""
        if method == "POST":
            # The body is read before any refusal, so the client always gets the answer.
            read = self._read_body()
            if read is None:
                return
            body = read
        if not self._allowed(method, route):
            return
        parts = route.split("/")
        if method == "GET":
            self._get(route, parts)
        else:
            self._post(route, parts, body)

    def _allowed(self, method: str, route: str) -> bool:
        """Apply the access rules of the route; send the refusal and return False when it is not allowed."""
        if route == HEALTH_ROUTE:
            return True
        if self.server.settings.mode == "addon":
            if self.client_address[0] != INGRESS_PEER:
                self._error(403, "forbidden")
                return False
            return True
        if method == "POST" and not self._origin_allowed():
            self._error(403, "forbidden")
            return False
        if method == "POST" and route == LOGIN_ROUTE:
            return True
        if load_password_hash(self.server.settings.data_dir) is None:
            self._error(503, "password_not_set")
            return False
        if not self.server.sessions.valid(self._session_token()):
            self._error(401, "unauthorized")
            return False
        return True

    def _get(self, route: str, parts: list[str]) -> None:
        if route == HEALTH_ROUTE:
            self._send_json(200, {"status": "ok", "version": mfi_server.__version__})
        elif route == DEVICES_ROUTE:
            self._send_json(200, [self._device_view(record) for record in self.server.store.all()])
        elif len(parts) == 4 and parts[2] == "devices":
            record = self.server.store.get(parts[3])
            if record is None:
                self._error(404, "not_found")
                return
            self._send_json(200, self._device_view(record))
        elif route == HISTORY_ROUTE:
            self._history()
        else:
            self._error(404, "not_found")

    def _post(self, route: str, parts: list[str], body: bytes) -> None:
        if route == LOGIN_ROUTE:
            self._login(body)
        elif route == LOGOUT_ROUTE:
            self.server.sessions.drop(self._session_token())
            self._send_empty(204)
        elif len(parts) == 7 and parts[2] == "devices" and parts[4] == "ports" and parts[6] == "output":
            self._set_output(parts[3], parts[5], body)
        else:
            self._error(404, "not_found")

    def _login(self, body: bytes) -> None:
        ip = self.client_address[0]
        if self.server.limiter.blocked(ip):
            self._error(429, "too_many_requests")
            return
        data = self._json_object(body)
        if data is None:
            return
        stored = load_password_hash(self.server.settings.data_dir)
        if stored is None:
            self._error(503, "password_not_set")
            return
        password = data.get("password")
        if not isinstance(password, str):
            self._error(400, "bad_request")
            return
        if not verify_password(password, stored):
            self.server.limiter.failure(ip)
            self._error(401, "unauthorized")
            return
        token = self.server.sessions.create()
        self._send_empty(204, [("Set-Cookie", f"{SESSION_COOKIE}={token}; HttpOnly; SameSite=Strict; Path=/")])

    def _set_output(self, mac: str, port_text: str, body: bytes) -> None:
        data = self._json_object(body)
        if data is None:
            return
        if "value" not in data:
            self._error(400, "bad_request")
            return
        try:
            self.server.control.set_output(mac, int(port_text), data["value"])
        except ValueError:
            self._error(400, "bad_request")
        except KeyError:
            self._error(404, "not_found")
        else:
            self._send_empty(202)

    def _history(self) -> None:
        params = {key: values[0] for key, values in parse_qs(urlparse(self.path).query).items()}
        mac = params.get("mac", "")
        sensor_id = params.get("sensor_id", "")
        tag = params.get("tag", "")
        if not (mac and sensor_id and tag):
            self._error(400, "bad_request")
            return
        try:
            from_ms = int(params.get("from", ""))
            to_ms = int(params.get("to", ""))
        except ValueError:
            self._error(400, "bad_request")
            return
        points = self.server.history.query(mac, sensor_id, tag, from_ms, to_ms)
        self._send_json(200, {"points": [[t, v] for t, v in points]})

    def _device_view(self, record: dict) -> dict:
        mac = record["mac"]
        latest = self.server.measurements.latest(mac)
        return {
            "mac": mac,
            "model": record["model"],
            "name": record["name"],
            "state": self.server.states.state(mac),
            "last_seen_ms": record["last_seen_ms"],
            "ports": [
                {
                    "port": port["port"],
                    "sensor_id": port["sensor_id"],
                    "label": port["label"],
                    "model": port["model"],
                    "values": latest.get(port["sensor_id"], {}),
                }
                for port in record["ports"]
            ],
        }

    def _session_token(self) -> str:
        """Return the value of the mfi_session cookie, or an empty string when it is missing."""
        for item in self.headers.get("Cookie", "").split(";"):
            name, _, value = item.strip().partition("=")
            if name == SESSION_COOKIE:
                return value
        return ""

    def _origin_allowed(self) -> bool:
        """Return False only when an Origin header is present and is not this server's own address."""
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        host = self.headers.get("Host", "")
        return origin in (f"http://{host}", f"https://{host}")

    def _read_body(self) -> bytes | None:
        """Read the request body; over MAX_BODY bytes answer 413 and return None."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._error(400, "bad_request")
            return None
        if length < 0:
            self._error(400, "bad_request")
            return None
        if length > MAX_BODY:
            self.close_connection = True
            self._error(413, "payload_too_large")
            self.rfile.read(min(length, MAX_DRAIN))
            return None
        return self.rfile.read(length)

    def _json_object(self, body: bytes) -> dict | None:
        """Parse a JSON object; answer 400 and return None when the body is not one."""
        try:
            data = json.loads(body.decode("utf-8"))
        except ValueError:
            self._error(400, "bad_request")
            return None
        if not isinstance(data, dict):
            self._error(400, "bad_request")
            return None
        return data

    def _serve_static(self) -> None:
        """Send a file of the web page; only the names listed in STATIC_FILES are ever read."""
        path = urlparse(self.path).path
        name = self._static_name(path)
        if name is None:
            self._error(404, "not_found")
            return
        try:
            body = (WEB_DIR / name).read_bytes()
        except OSError:
            self._error(404, "not_found")
            return
        self.send_response(200)
        self.send_header("Content-Type", STATIC_FILES[name])
        self.send_header("Content-Security-Policy", STATIC_CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    @staticmethod
    def _static_name(path: str) -> str | None:
        """Return the STATIC_FILES key that ends the path, or None. The path is never decoded or joined to a directory."""
        if path == "" or path.endswith("/"):
            return "index.html"
        segments = path.strip("/").split("/")
        for start in range(len(segments)):
            candidate = "/".join(segments[start:])
            if candidate in STATIC_FILES:
                return candidate
        return None

    def _send_json(self, status: int, obj: object) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_empty(self, status: int, extra_headers: list[tuple[str, str]] | None = None) -> None:
        self.send_response(status)
        for name, value in extra_headers or []:
            self.send_header(name, value)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _error(self, status: int, code: str) -> None:
        self._send_json(status, {"error": code})
