"""Web page API: builds the request handler of the web page (EPIC-11). Standard library only.

make_handler(context) returns a BaseHTTPRequestHandler subclass that captures context in a closure.
Routes are found by the 'api/v1/' part of the path, so the Home Assistant ingress prefix is accepted.
Every route except login and the firmware download needs a session; every write needs the admin role.
Responses are JSON only, and request values are never put into HTML.
"""
from __future__ import annotations

import base64
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from mfi_server_next import auth, editor, network_tools, rules

logger = logging.getLogger(__name__)

SESSION_COOKIE = "mfi_session"
API_MARKER = "api/v1/"
FIRMWARE_PREFIX = "/dl/firmware/"
DEFAULT_MAX_BODY = 65536
DEFAULT_COMET_TIMEOUT_S = 25.0
DEFAULT_REQUEST_TIMEOUT_S = 30.0
# After a refused oversized body, up to this many bytes are read so the client receives the answer.
MAX_DRAIN = 1048576
SIMPLE_ROUTES = {
    "login": ("login", {"POST"}),
    "logout": ("logout", {"POST"}),
    "comet": ("comet", {"GET"}),
    "rules": ("rules", {"GET", "POST"}),
    "events": ("events", {"GET"}),
    "alarms": ("alarms", {"GET"}),
    "maps": ("maps", {"GET", "POST"}),
    "users": ("users_add", {"POST"}),
}
DEVICE_ACTIONS = ("adopt", "forget", "reboot", "locate", "upgrade")
EDITOR_POST = {"save", "validate", "to_yaml", "from_yaml"}
# Fixed web page files served without a session; the request path is only matched against these names.
STATIC_FILES = {
    "index.html": "text/html; charset=utf-8",
    "style.css": "text/css; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
    "editor.js": "text/javascript; charset=utf-8",
    "editor.css": "text/css; charset=utf-8",
    "i18n/en.json": "application/json; charset=utf-8",
    "i18n/it.json": "application/json; charset=utf-8",
}


def _match_route(parts):
    """Return (name, allowed methods, captured parts) for the route shape, or None when no shape matches."""
    count = len(parts)
    if count == 3 and parts[2] in SIMPLE_ROUTES:
        name, methods = SIMPLE_ROUTES[parts[2]]
        return name, methods, ()
    if count == 4 and parts[2] == "stat":
        return "stat", {"GET"}, (parts[3],)
    if count == 4 and parts[2] == "upload" and parts[3] == "backup":
        return "backup", {"POST"}, ()
    if count == 5 and parts[2] == "users" and parts[4] == "password":
        return "users_password", {"POST"}, (parts[3],)
    if count == 5 and parts[2] == "devices" and parts[4] in DEVICE_ACTIONS:
        return parts[4], {"POST"}, (parts[3],)
    if count == 7 and parts[2] == "devices" and parts[4] == "ports" and parts[6] in ("output", "settings"):
        name = "output" if parts[6] == "output" else "port_settings"
        return name, {"POST"}, (parts[3], parts[5])
    if count == 4 and parts[2] == "net" and parts[3] in ("upnp", "guest"):
        return "net_" + parts[3], {"POST"}, ()
    if count == 5 and parts[2] == "net" and parts[3] in ("webshell", "ssh"):
        return "net_" + parts[3], {"POST"}, (parts[4],)
    if count == 4 and parts[2] == "editor" and parts[3] in EDITOR_POST:
        return "editor_" + parts[3], {"POST"}, ()
    if count == 5 and parts[2] == "editor" and parts[3] == "traces":
        return "editor_traces", {"GET"}, (parts[4],)
    return None


def _non_negative_int(text: str) -> int:
    """Return the integer of text, or 0 when it is not an integer or is negative."""
    try:
        return max(0, int(text))
    except ValueError:
        return 0


def make_handler(context):
    """Build the request handler class of the web page; context holds the stores and actions (see the contract)."""

    rules_lock = threading.Lock()

    class PageHandler(BaseHTTPRequestHandler):
        """Answers the web page API and the firmware download."""

        def setup(self) -> None:
            # Bound the time a slow client can hold a worker thread (the body is read before auth).
            self.timeout = context.settings.get("request_timeout_s", DEFAULT_REQUEST_TIMEOUT_S)
            super().setup()

        def log_message(self, format: str, *args: object) -> None:
            logger.debug("page api: %s", format % args)

        def do_GET(self) -> None:
            self._dispatch("GET")

        def do_POST(self) -> None:
            self._dispatch("POST")

        def _dispatch(self, method: str) -> None:
            path = urlparse(self.path).path
            body = b""
            if method == "POST":
                # The body is read before any refusal, so the client always gets the answer.
                read = self._read_body()
                if read is None:
                    return
                body = read
            if path.startswith(FIRMWARE_PREFIX):
                if method != "GET":
                    self._error(405, "method_not_allowed")
                    return
                self._firmware(path[len(FIRMWARE_PREFIX):])
                return
            if method == "GET":
                target = self._static_target(path)
                if target is not None:
                    self._serve_static(*target)
                    return
            idx = path.find(API_MARKER)
            if idx <= 0 or path[idx - 1] != "/":
                self._error(404, "not_found")
                return
            matched = _match_route(path[idx:].split("/"))
            if matched is None:
                self._error(404, "not_found")
                return
            name, methods, params = matched
            if method not in methods:
                self._error(405, "method_not_allowed")
                return
            if not self._authorized(method, name):
                return
            self._route(method, name, params, body)

        def _authorized(self, method, name) -> bool:
            """Check the session and the role; send the refusal and return False when the request may not go on."""
            if name == "login":
                return True
            if context.settings.get("mode", "standalone") == "addon":
                peer = self.client_address[0]
                if peer != context.settings.get("ingress_peer", auth.TRUSTED_INGRESS_PEER):
                    self._error(403, "forbidden")
                    return False
                session = {"username": "ingress", "role": auth.ROLE_ADMIN}
            else:
                session = context.auth.check_session(self._session_token())
                if session is None:
                    self._error(401, "unauthorized")
                    return False
            if method == "POST" and name not in ("login", "logout") and session["role"] != auth.ROLE_ADMIN:
                self._error(403, "forbidden")
                return False
            return True

        def _route(self, method, name, params, body) -> None:
            if name == "login":
                self._login(body)
            elif name == "logout":
                context.auth.logout(self._session_token())
                self._send_empty(204)
            elif name == "comet":
                self._comet()
            elif name == "stat":
                self._stat(params[0])
            elif name == "rules":
                if method == "GET":
                    self._send_json(200, {"automations": context.automations.load()})
                else:
                    self._rule_add(body)
            elif name == "events":
                self._send_json(200, {"events": context.events.list_events()})
            elif name == "alarms":
                self._send_json(200, {"alarms": context.alarms.list_alarms()})
            elif name == "maps":
                self._maps(method, body)
            elif name == "users_add":
                self._user_add(body)
            elif name == "users_password":
                self._user_password(params[0], body)
            elif name == "backup":
                self._backup(body)
            elif name == "net_webshell":
                self._net_webshell(params[0], body)
            elif name == "net_ssh":
                self._net_ssh(params[0], body)
            elif name == "net_upnp":
                self._run_net(lambda: network_tools.upnp_announce(context.settings))
            elif name == "net_guest":
                self._run_net(lambda: network_tools.guest_portal(
                    context.settings,
                    getattr(context, "net_guest_limiter", None),
                    self.client_address[0],
                ))
            elif name == "editor_save":
                self._editor_save(body)
            elif name == "editor_validate":
                self._editor_validate(body)
            elif name == "editor_to_yaml":
                self._editor_to_yaml(body)
            elif name == "editor_from_yaml":
                self._editor_from_yaml(body)
            elif name == "editor_traces":
                self._editor_traces(params[0])
            else:
                self._device_action(name, params, body)

        def _login(self, body: bytes) -> None:
            data = self._json_object(body)
            if data is None:
                return
            username = data.get("username")
            password = data.get("password")
            if not isinstance(username, str) or not isinstance(password, str):
                self._error(400, "bad_request")
                return
            try:
                token = context.auth.login(username, password, self.client_address[0])
            except auth.TooManyAttempts:
                self._error(429, "too_many_attempts")
            except auth.LoginFailed:
                self._error(401, "login_failed")
            else:
                cookie = f"{SESSION_COOKIE}={token}; HttpOnly; SameSite=Strict; Path=/"
                self._send_json(
                    200,
                    {"username": username, "role": context.auth.role(username)},
                    [("Set-Cookie", cookie)],
                )

        def _comet(self) -> None:
            cursor = _non_negative_int(self._query("cursor", "0"))
            timeout = context.settings.get("comet_timeout_s", DEFAULT_COMET_TIMEOUT_S)
            new_cursor, messages = context.comet.read_after(cursor, timeout=timeout)
            self._send_json(200, {"cursor": new_cursor, "messages": messages})

        def _maps(self, method, body: bytes) -> None:
            if method == "GET":
                self._send_json(200, {"maps": context.maps.list_maps()})
                return
            data = self._json_object(body)
            if data is None:
                return
            name = data.get("name")
            scale = data.get("scale")
            scale_unit = data.get("scale_unit", "metres")
            icons = data.get("icons")
            image = None
            value = data.get("image_base64")
            if value is not None:
                try:
                    image = base64.b64decode(value, validate=True)
                except (ValueError, TypeError):
                    self._error(400, "bad_request")
                    return
            try:
                created = context.maps.create_map(name, scale=scale, scale_unit=scale_unit, image=image, icons=icons)
            except ValueError as exc:
                code = str(exc)
                self._send_json(413 if code == "image_too_large" else 400, {"error": code})
                return
            self._send_json(201, {"map": created})

        def _stat(self, interval: str) -> None:
            try:
                aggregates = context.stats.read(interval)
            except ValueError:
                self._error(400, "bad_request")
                return
            self._send_json(200, {"interval": interval, "aggregates": aggregates})

        def _rule_add(self, body: bytes) -> None:
            obj = self._json_object(body)
            if obj is None:
                return
            problems = rules.validate(obj)
            if problems:
                self._send_json(400, {"error": "invalid", "details": problems})
                return
            normalized = rules.normalize(obj)
            with rules_lock:
                automations = context.automations.load()
                automations.append(normalized)
                context.automations.save(automations)
            self._send_json(200, {"automation": normalized})

        def _editor_problems(self, automation: dict) -> list[str]:
            """Problems of an editor automation, checked with the script settings of this server."""
            return rules.validate(
                automation,
                allow_script_action=context.settings.get("allow_script_action", False),
                script_max_length=context.settings.get("script_max_length", rules.DEFAULT_SCRIPT_MAX_LENGTH),
            )

        def _editor_save(self, body: bytes) -> None:
            data = self._json_object(body)
            if data is None:
                return
            automation = data.get("automation")
            if not isinstance(automation, dict):
                self._error(400, "bad_request")
                return
            problems = self._editor_problems(automation)
            if problems:
                self._send_json(400, {"error": "invalid", "details": problems})
                return
            normalized = rules.normalize(automation)
            with rules_lock:
                automations = context.automations.load()
                for index, item in enumerate(automations):
                    if item.get("id") == normalized["id"]:
                        automations[index] = normalized
                        break
                else:
                    automations.append(normalized)
                context.automations.save(automations)
            self._send_json(200, {"automation": normalized})

        def _editor_validate(self, body: bytes) -> None:
            data = self._json_object(body)
            if data is None:
                return
            automation = data.get("automation")
            if not isinstance(automation, dict):
                self._error(400, "bad_request")
                return
            problems = self._editor_problems(automation)
            if problems:
                self._send_json(200, {"valid": False, "details": problems})
            else:
                self._send_json(200, {"valid": True, "details": []})

        def _editor_to_yaml(self, body: bytes) -> None:
            data = self._json_object(body)
            if data is None:
                return
            automation = data.get("automation")
            if not isinstance(automation, dict):
                self._error(400, "bad_request")
                return
            try:
                text = editor.to_yaml(automation)
            except (TypeError, ValueError):
                self._send_json(400, {"error": "invalid"})
                return
            self._send_json(200, {"yaml": text})

        def _editor_from_yaml(self, body: bytes) -> None:
            data = self._json_object(body)
            if data is None:
                return
            text = data.get("yaml")
            if not isinstance(text, str):
                self._error(400, "bad_request")
                return
            try:
                obj = editor.from_yaml(text)
            except editor.YamlError as exc:
                self._send_json(400, {"error": "invalid_yaml", "line": exc.line, "detail": str(exc)})
                return
            if not isinstance(obj, dict):
                self._send_json(400, {"error": "invalid_yaml", "line": 1, "detail": "not a mapping"})
                return
            self._send_json(200, {"automation": obj})

        def _editor_traces(self, automation_id: str) -> None:
            try:
                traces = context.rules_engine.traces(automation_id)
            except KeyError:
                self._error(404, "not_found")
                return
            self._send_json(200, {"traces": traces})

        def _user_add(self, body: bytes) -> None:
            data = self._json_object(body)
            if data is None:
                return
            username = data.get("username")
            role = data.get("role")
            try:
                context.auth.add_user(username, data.get("password"), role)
            except ValueError as exc:
                self._send_json(400, {"error": "invalid", "details": [str(exc)]})
                return
            self._send_json(201, {"username": username, "role": role})

        def _user_password(self, username: str, body: bytes) -> None:
            data = self._json_object(body)
            if data is None:
                return
            try:
                context.auth.set_password(username, data.get("password"))
            except KeyError:
                self._error(404, "not_found")
            except ValueError as exc:
                self._send_json(400, {"error": "invalid", "details": [str(exc)]})
            else:
                self._send_empty(204)

        def _backup(self, body: bytes) -> None:
            try:
                imported = context.import_backup(body)
            except ValueError:
                self._send_json(400, {"error": "invalid"})
                return
            self._send_json(200, {"imported": imported})

        def _device_action(self, name: str, params, body: bytes) -> None:
            actions = context.actions
            mac = params[0]
            if name == "output":
                data = self._json_object(body)
                if data is None:
                    return
                if "value" not in data:
                    self._error(400, "bad_request")
                    return
                port, value = params[1], data["value"]
                self._run_action(lambda: actions.set_output(mac, int(port), value))
            elif name == "port_settings":
                data = self._json_object(body)
                if data is None:
                    return
                port = params[1]
                self._run_action(lambda: actions.set_port(mac, int(port), data))
            elif name == "locate":
                data = self._json_object(body)
                if data is None:
                    return
                self._run_action(lambda: actions.locate(mac, data))
            else:
                by_name = {
                    "adopt": actions.adopt,
                    "forget": actions.forget,
                    "reboot": actions.reboot,
                    "upgrade": actions.upgrade,
                }
                action = by_name[name]
                self._run_action(lambda: action(mac))

        def _run_action(self, action) -> None:
            """Run one device command and map its exceptions to the API answers."""
            try:
                action()
            except LookupError:
                self._error(404, "not_found")
            except ValueError:
                self._error(400, "bad_request")
            except PermissionError as exc:
                self._send_json(409, {"error": str(exc)})
            except Exception:  # noqa: BLE001 - never leak the connection on an unexpected failure
                logger.exception("page api: device action failed")
                self._error(500, "internal_error")
            else:
                self._send_json(202, {"result": "accepted"})

        def _net_target_ok(self, body: bytes) -> bool:
            """Reject a body that tries to set its own host or port; the address is server-side only."""
            data = self._json_object(body) if body else {}
            if data is None:
                return False
            if "host" in data or "port" in data:
                self._error(400, "bad_request")
                return False
            return True

        def _net_webshell(self, mac: str, body: bytes) -> None:
            if not self._net_target_ok(body):
                return
            self._run_net(lambda: network_tools.open_webshell(
                context.settings, context.devices, mac,
                connect=getattr(context, "net_connect", None)))

        def _net_ssh(self, mac: str, body: bytes) -> None:
            if not self._net_target_ok(body):
                return
            self._run_net(lambda: network_tools.start_browser_ssh(
                context.settings, context.devices, mac,
                connect=getattr(context, "net_connect", None)))

        def _run_net(self, action) -> None:
            """Run one network tool and map its result or its refusal to the API answer."""
            try:
                result = action()
            except network_tools.NetworkToolError as exc:
                self._error(exc.status, exc.code)
            except ValueError:
                self._error(400, "bad_request")
            except OSError:
                self._error(502, "connect_failed")
            except Exception:  # noqa: BLE001 - map any unexpected failure to a 500 without leaking internals
                logger.exception("page api: network tool failed")
                self._error(500, "internal_error")
            else:
                self._send_json(200, {"result": "ok", **result})

        def _static_target(self, path):
            """Map a GET path to one fixed web file, or None; the request path never becomes a filesystem path."""
            if getattr(context, "web_dir", None) is None or ".." in path:
                return None
            if path.endswith("/"):
                return "index.html", STATIC_FILES["index.html"]
            for rel, content_type in STATIC_FILES.items():
                if path.endswith("/" + rel):
                    return rel, content_type
            return None

        def _serve_static(self, rel, content_type):
            """Send one fixed web file from context.web_dir; 404 when it cannot be read."""
            try:
                data = (Path(context.web_dir) / rel).read_bytes()
            except OSError:
                self._error(404, "not_found")
                return
            self._send_bytes(200, data, content_type)

        def _firmware(self, rel: str) -> None:
            """Send one firmware file; only the exact names of context.firmware_paths are ever read."""
            folder = context.firmware_dir
            if rel not in context.firmware_paths or folder is None:
                self._error(404, "not_found")
                return
            try:
                data = (Path(folder) / rel).read_bytes()
            except OSError:
                self._error(404, "not_found")
                return
            self._send_bytes(200, data, "application/octet-stream")

        def _query(self, key: str, default: str) -> str:
            values = parse_qs(urlparse(self.path).query).get(key)
            return values[0] if values else default

        def _session_token(self) -> str:
            """Return the value of the mfi_session cookie, or an empty string when it is missing."""
            for item in self.headers.get("Cookie", "").split(";"):
                name, _, value = item.strip().partition("=")
                if name == SESSION_COOKIE:
                    return value
            return ""

        def _read_body(self):
            """Read the request body; over max_body bytes answer 413 and return None."""
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._error(400, "bad_request")
                return None
            if length < 0:
                self._error(400, "bad_request")
                return None
            max_body = context.settings.get("max_body", DEFAULT_MAX_BODY)
            if length > max_body:
                self.close_connection = True
                self._error(413, "payload_too_large")
                self.rfile.read(min(length, MAX_DRAIN))
                return None
            return self.rfile.read(length)

        def _json_object(self, body: bytes):
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

        def _send_json(self, status: int, obj, extra_headers=None) -> None:
            body = json.dumps(obj).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            for name, value in extra_headers or []:
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_empty(self, status: int) -> None:
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _send_bytes(self, status: int, data: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _error(self, status: int, code: str) -> None:
            self._send_json(status, {"error": code})

    return PageHandler
