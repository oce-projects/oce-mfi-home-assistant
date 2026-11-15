"""HTTP server of the inform protocol: POST /inform on the inform port.

One request is one inform. The packet is checked, decrypted with the device key
from the store, and the measurements are recorded. The answer is encrypted with
the same key and IV: a connected device gets its queued command, any other
device gets a heartbeat (noop). Rejected packets get an empty answer with the
HTTP status of the reason. Standard library only.
"""
from __future__ import annotations

import logging
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from mfi_server.commands import CommandQueue
from mfi_server.config import Settings
from mfi_server.measurements import Measurements
from mfi_server.messages import noop, output_command
from mfi_server.packet import PacketError, decode, encode_response, normalize_mac, parse_header
from mfi_server.states import DeviceStates
from mfi_server.store import DeviceStore

logger = logging.getLogger(__name__)

INFORM_PATH = "/inform"
CONTENT_TYPE = "application/x-binary"
MIN_BODY_BYTES = 8


class InformServer(ThreadingHTTPServer):
    """HTTP server that answers inform requests with the shared state objects."""

    daemon_threads = True

    def __init__(
        self,
        settings: Settings,
        store: DeviceStore,
        states: DeviceStates,
        queue: CommandQueue,
        measurements: Measurements,
    ) -> None:
        self.settings = settings
        self.store = store
        self.states = states
        self.queue = queue
        self.measurements = measurements
        super().__init__((settings.bind_address, settings.inform_port), InformHandler)


class InformHandler(BaseHTTPRequestHandler):
    """Answers GET and POST requests; only POST /inform does any work."""

    def setup(self) -> None:
        self.timeout = self.server.settings.request_timeout_s
        super().setup()

    def log_message(self, format: str, *args: object) -> None:
        logger.debug("http: %s", format % args)

    def do_GET(self) -> None:
        self._send_empty(404)

    def do_POST(self) -> None:
        if self.path.split("?")[0] != INFORM_PATH:
            self._send_empty(404)
            return
        mac = "?"
        try:
            body = self.rfile.read(self._content_length())
            if len(body) < MIN_BODY_BYTES:
                raise PacketError("body is too short")
            header = parse_header(body)
            mac = header.mac.hex()
            if self.server.store.get(mac) is None:
                raise PacketError("unknown device", 404)
            _, payload, key = decode(body, self.server.store.keys_for(mac))
            try:
                payload_mac = normalize_mac(str(payload.get("mac", "")))
            except ValueError as exc:
                raise PacketError("payload mac is not valid") from exc
            if payload_mac != mac:
                raise PacketError("payload mac differs from the header")
            now_ms = int(time.time() * 1000)
            was_connected = self.server.states.state(mac) == "connected"
            self.server.states.seen(mac)
            self.server.measurements.ingest(mac, payload, now_ms)
            cmd = self.server.queue.pop(mac) if was_connected else None
            if cmd is None:
                message = noop(now_ms)
            else:
                message = output_command(mac, cmd["port"], cmd["sensor_id"], cmd["value"], now_ms)
            response = encode_response(header, key, message)
        except PacketError as exc:
            logger.debug("inform rejected with %d: %s", exc.status, exc.reason)
            self._send_empty(exc.status)
        except Exception as exc:
            logger.error("inform handler error for %s: %s", mac, type(exc).__name__)
            self._send_empty(503)
        else:
            self._send_bytes(200, response)

    def _content_length(self) -> int:
        raw = self.headers.get("Content-Length")
        if raw is None:
            raise PacketError("Content-Length is missing")
        try:
            length = int(raw)
        except ValueError as exc:
            raise PacketError("Content-Length is not an integer") from exc
        if length < 0 or length > self.server.settings.max_body_bytes:
            raise PacketError("Content-Length is out of range")
        return length

    def _send_empty(self, status: int) -> None:
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send_bytes(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", CONTENT_TYPE)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def make_server(
    settings: Settings,
    store: DeviceStore,
    states: DeviceStates,
    queue: CommandQueue,
    measurements: Measurements,
) -> InformServer:
    """Build the server bound to settings.bind_address and settings.inform_port."""
    return InformServer(settings, store, states, queue, measurements)
