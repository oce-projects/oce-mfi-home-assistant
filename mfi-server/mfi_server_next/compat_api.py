"""Controller-compatible HTTP API, so that existing mFi clients keep working. Implemented in EPIC-17.

Standard library only, clean room. Only the routes OBSERVED in docs/controller/web-api.md
are served. Success answers use {"data": [...], "meta": {"rc": "ok"}}; error answers use
{"meta": {"rc": "error", "msg": "api.err.<Name>"}}. The api.err.* names are the server's own
choice: the real controller error codes are UNVERIFIED.
"""
import json
import logging
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse

from mfi_server_next import auth, tasks, serial, sensors

logger = logging.getLogger(__name__)

SESSION_COOKIE = "mfi_session"
API_MARKER = "api/v1.0/"
DEFAULT_MAX_BODY = 65536
# After a refused oversized body, up to this many bytes are read so the client receives the answer.
MAX_DRAIN = 1048576
IMPLEMENTED_ROUTES = frozenset({"cmd/devmgr", "upd/sensor"})

ERR_LOGIN_REQUIRED = "api.err.LoginRequired"
ERR_NO_PERMISSION = "api.err.NoPermission"
ERR_UNKNOWN_METHOD = "api.err.UnknownMethod"
ERR_WRONG_METHOD = "api.err.WrongMethod"
ERR_INVALID_PAYLOAD = "api.err.InvalidPayload"
ERR_SERVER_ERROR = "api.err.ServerError"


def ok_envelope(data=None):
    """Return the success envelope: a list of data items, None gives an empty list."""
    if data is None:
        items = []
    elif isinstance(data, list):
        items = list(data)
    else:
        items = [data]
    return {"data": items, "meta": {"rc": "ok"}}


def error_envelope(msg=ERR_INVALID_PAYLOAD):
    """Return the error envelope with the api.err.* name msg."""
    return {"meta": {"rc": "error", "msg": msg}}


def unverified_route():
    """Marker for UNVERIFIED routes: the replay bench marks their fixtures PENDING."""
    raise NotImplementedError("UNVERIFIED route: needs an R-WEB capture")


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_text(value):
    return isinstance(value, str) and value != ""


def make_compat_handler(context):
    """Build the request handler class of the controller-compatible API.

    context holds auth, tasks, sensors and settings (see the contract of the epic).
    """

    class CompatHandler(BaseHTTPRequestHandler):
        """Answers the controller-compatible API."""

        # Socket timeout for a single read or write, not a deadline for the whole
        # request: BaseHTTPRequestHandler applies it to the socket in setup(). It
        # bounds an idle connection, not a client that trickles bytes just under it.
        timeout = 10

        def log_message(self, format, *args):
            logger.debug("compat api: %s", format % args)

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def _dispatch(self, method):
            path = urlparse(self.path).path
            body = b""
            if method == "POST":
                # The body is read before any refusal, so the client always gets the answer.
                read = self._read_body()
                if read is None:
                    return
                body = read
            idx = path.find(API_MARKER)
            if idx <= 0 or path[idx - 1] != "/":
                self._send_error(404, ERR_UNKNOWN_METHOD)
                return
            route = path[idx + len(API_MARKER):].strip("/")
            if route not in IMPLEMENTED_ROUTES:
                self._send_error(404, ERR_UNKNOWN_METHOD)
                return
            if method != "POST":
                self._send_error(405, ERR_WRONG_METHOD)
                return
            if not self._authorized():
                return
            if not self._json_content_type():
                return
            data = self._json_object(body)
            if data is None:
                return
            if route == "cmd/devmgr":
                self._guarded(self._cmd_devmgr, data)
            else:
                self._guarded(self._upd_sensor, data)

        def _authorized(self):
            """Check the caller and its role; send the refusal and return False when the request may not go on."""
            if context.settings.get("mode", "standalone") == "addon":
                peer = self.client_address[0]
                if peer != context.settings.get("ingress_peer", auth.TRUSTED_INGRESS_PEER):
                    self._send_error(401, ERR_LOGIN_REQUIRED)
                    return False
                session = {"username": "ingress", "role": auth.ROLE_ADMIN}
            else:
                session = context.auth.check_session(self._session_token())
                if session is None:
                    self._send_error(401, ERR_LOGIN_REQUIRED)
                    return False
            if session["role"] != auth.ROLE_ADMIN:
                self._send_error(403, ERR_NO_PERMISSION)
                return False
            return True

        def _guarded(self, handler, data):
            """Run one route handler; an unexpected failure is logged and answered with a plain 500."""
            try:
                handler(data)
            except Exception:  # noqa: BLE001 - never leak internals to the client
                logger.exception("compat api: request failed")
                self._send_error(500, ERR_SERVER_ERROR)

        def _cmd_devmgr(self, data):
            cmd = data.get("cmd")
            if cmd == "mfi-output":
                mac = data.get("mac")
                port = data.get("port")
                val = data.get("val")
                if (
                    not (isinstance(mac, str) and serial.MAC_PATTERN.fullmatch(mac))
                    or not _is_int(port)
                    or port < 1
                    or not _is_int(val)
                    or val not in (0, 1)
                ):
                    self._send_error(400, ERR_INVALID_PAYLOAD)
                    return
                try:
                    context.tasks.enqueue(tasks.build_output_command(mac, port, val))
                except ValueError:
                    self._send_error(400, ERR_INVALID_PAYLOAD)
                    return
                self._send_json(200, ok_envelope())
            elif cmd == "kick-serial":
                mac = data.get("mac")
                if not _is_text(mac):
                    self._send_error(400, ERR_INVALID_PAYLOAD)
                    return
                try:
                    task = serial.kick_serial(mac)
                    context.tasks.enqueue(task)
                except ValueError:
                    self._send_error(400, ERR_INVALID_PAYLOAD)
                    return
                self._send_json(200, ok_envelope())
            else:
                self._send_error(400, ERR_INVALID_PAYLOAD)

        def _upd_sensor(self, data):
            s_id = data.get("sId")
            calibration = data.get("calibration")
            if not _is_int(s_id) or not isinstance(calibration, str):
                self._send_error(400, ERR_INVALID_PAYLOAD)
                return
            try:
                sensor = context.sensors.set_calibration(s_id, calibration)
            except ValueError:
                self._send_error(400, ERR_INVALID_PAYLOAD)
                return
            self._send_json(200, ok_envelope(sensor))

        def _read_body(self):
            """Read the request body; over max_body bytes answer 413 and return None."""
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._send_error(400, ERR_INVALID_PAYLOAD)
                return None
            if length < 0:
                self._send_error(400, ERR_INVALID_PAYLOAD)
                return None
            max_body = context.settings.get("max_body", DEFAULT_MAX_BODY)
            if length > max_body:
                self.close_connection = True
                self._send_error(413, ERR_INVALID_PAYLOAD)
                self.rfile.read(min(length, MAX_DRAIN))
                return None
            return self.rfile.read(length)

        def _json_content_type(self):
            """Require Content-Type application/json so a cross-site HTML form cannot send a command (CSRF). Send 400 and return False otherwise."""
            media = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if media != "application/json":
                self._send_error(400, ERR_INVALID_PAYLOAD)
                return False
            return True

        def _json_object(self, body):
            """Parse a JSON object; answer 400 and return None when the body is not one."""
            try:
                data = json.loads(body.decode("utf-8"))
            except (ValueError, RecursionError):
                self._send_error(400, ERR_INVALID_PAYLOAD)
                return None
            if not isinstance(data, dict):
                self._send_error(400, ERR_INVALID_PAYLOAD)
                return None
            return data

        def _session_token(self):
            """Return the value of the mfi_session cookie, or an empty string when it is missing."""
            for item in self.headers.get("Cookie", "").split(";"):
                name, _, value = item.strip().partition("=")
                if name == SESSION_COOKIE:
                    return value
            return ""

        def _send_json(self, status, obj):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_error(self, status, name):
            self._send_json(status, error_envelope(name))

    return CompatHandler
