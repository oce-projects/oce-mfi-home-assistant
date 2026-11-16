"""Offline tests of the mfi-server HTTP API: access rules, login, devices, output and history.

The server runs on 127.0.0.1 with an ephemeral port. Standard library only.
"""
from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

import mfi_server
from mfi_server.api import STATIC_CSP, make_api_server
from mfi_server.auth import LoginLimiter, Sessions, hash_password, save_password_hash
from mfi_server.automation_engine import AutomationEngine
from mfi_server.automation_store import AutomationStore
from mfi_server.commands import CommandQueue
from mfi_server.config import Settings
from mfi_server.control import OutputControl
from mfi_server.history import History
from mfi_server.measurements import Measurements
from mfi_server.states import DeviceStates
from mfi_server.ubnt_discovery import ScanInProgress

PASSWORD = "passw0rd1234"
WRONG_PASSWORD = "not-the-password"
MAC = "02aabbccdd01"
DEVICE = {
    "mac": MAC,
    "model": "m",
    "name": "strip",
    "last_seen_ms": 1000,
    "ports": [{"port": 1, "sensor_id": "sensor-1", "label": "outlet 1", "model": "m"}],
}
OUTPUT_PATH = f"/api/v1/devices/{MAC}/ports/1/output"
ADDON_DEVICES_PATH = "/api/hassio_ingress/abc/api/v1/devices"
AUTOMATIONS_PATH = "/api/v1/automations"
AUTOMATION = {
    "id": "a1",
    "triggers": [{"trigger": "time", "at": "08:00:00"}],
    "actions": [{"action": "switch.turn_on", "target": {"entity_id": "switch.mfi_02aabbccdd01_1"}}],
}


class FakeScanner:
    """Stands in for Scanner: the API only calls scan() and last_results()."""

    def __init__(self, results: list[dict] | None = None, in_progress: bool = False) -> None:
        self._results = results or []
        self._in_progress = in_progress
        self.scanned = 0

    def scan(self, timeout_s: float = 3.0) -> list[dict]:
        if self._in_progress:
            raise ScanInProgress()
        self.scanned += 1
        return self._results

    def last_results(self) -> list[dict]:
        return self._results


class FakeStore:
    """Stands in for DeviceStore: the API and OutputControl only call all() and get()."""

    def __init__(self, records: list[dict]) -> None:
        self._records = {record["mac"]: record for record in records}

    def all(self) -> list[dict]:
        return list(self._records.values())

    def get(self, mac: str) -> dict | None:
        return self._records.get(mac)


class TestApi(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name)
        self.store = FakeStore([DEVICE])
        self.states = DeviceStates()
        self.measurements = Measurements()
        self.measurements.ingest(MAC, {"alarm": [{"sId": "sensor-1", "tag": "active_pwr", "val": 12.5}]}, 1000)
        self.control = OutputControl(self.store, self.states, CommandQueue(), None)
        self.history = History(self.data_dir / "h.sqlite3")
        self.sessions = Sessions(clock=lambda: 0.0)
        self.clock = [0.0]
        self.limiter = LoginLimiter(clock=lambda: self.clock[0])
        self.automations = AutomationStore(self.data_dir)
        self.engine = AutomationEngine(
            entities=lambda e: None,
            set_output=self.control.set_output,
            resolve=lambda e: None,
            clock=lambda: 0.0,
        )
        self.scanner = FakeScanner(
            [
                {"mac": MAC, "ip": "192.168.1.20", "model": "mPower", "seen_ms": 0},
                {"mac": "02aabbccdd02", "ip": "192.168.1.20", "model": "mPort", "seen_ms": 0},
            ]
        )
        self.servers: list = []
        self.server = self._start("standalone")

    def tearDown(self) -> None:
        for server in self.servers:
            server.shutdown()
            server.server_close()
        self._tmp.cleanup()

    def _start(self, mode: str, ingress_peer: str = "172.30.32.2"):
        settings = Settings(
            data_dir=self.data_dir,
            mode=mode,
            bind_address="127.0.0.1",
            web_port=0,
            ingress_peer=ingress_peer,
        )
        server = make_api_server(
            settings,
            self.store,
            self.states,
            self.measurements,
            self.history,
            self.control,
            self.sessions,
            self.limiter,
            self.automations,
            self.engine,
            self.scanner,
        )
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.servers.append(server)
        return server

    def _request(self, method, path, body=None, headers=None, server=None):
        server = self.server if server is None else server
        payload = body if body is None or isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
        try:
            conn.request(method, path, body=payload, headers=headers or {})
            response = conn.getresponse()
            data = response.read()
        finally:
            conn.close()
        return response.status, {key.lower(): value for key, value in response.getheaders()}, data

    def _set_password(self) -> None:
        save_password_hash(self.data_dir, hash_password(PASSWORD, iterations=1000))

    def _cookie(self) -> str:
        self._set_password()
        status, headers, _ = self._request("POST", "/api/v1/login", body={"password": PASSWORD})
        self.assertEqual(status, 204)
        return headers["set-cookie"].split(";")[0]

    def test_health_without_login(self):
        status, _, body = self._request("GET", "/api/v1/health")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["version"], mfi_server.__version__)

    def test_devices_requires_password_set(self):
        status, _, body = self._request("GET", "/api/v1/devices")
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(body), {"error": "password_not_set"})

    def test_login_then_devices(self):
        self._set_password()
        status, headers, _ = self._request("POST", "/api/v1/login", body={"password": PASSWORD})
        self.assertEqual(status, 204)
        self.assertIn("mfi_session=", headers["set-cookie"])
        token = headers["set-cookie"].split(";")[0].split("=", 1)[1]
        status, _, body = self._request("GET", "/api/v1/devices", headers={"Cookie": f"mfi_session={token}"})
        self.assertEqual(status, 200)
        devices = json.loads(body)
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["ports"][0]["values"], {"active_pwr": 12.5})

    def test_devices_without_cookie_is_401(self):
        self._set_password()
        status, _, body = self._request("GET", "/api/v1/devices")
        self.assertEqual(status, 401)
        self.assertEqual(json.loads(body), {"error": "unauthorized"})

    def test_output_and_history_without_cookie_are_401(self):
        self._set_password()
        status, _, _ = self._request("POST", OUTPUT_PATH, body={"value": 1})
        self.assertEqual(status, 401)
        path = f"/api/v1/history?mac={MAC}&sensor_id=sensor-1&tag=active_pwr&from=0&to=5000"
        status, _, _ = self._request("GET", path)
        self.assertEqual(status, 401)

    def test_sixth_wrong_login_is_429(self):
        self._set_password()
        for _ in range(5):
            status, _, _ = self._request("POST", "/api/v1/login", body={"password": WRONG_PASSWORD})
            self.assertEqual(status, 401)
        status, _, body = self._request("POST", "/api/v1/login", body={"password": WRONG_PASSWORD})
        self.assertEqual(status, 429)
        self.assertEqual(json.loads(body), {"error": "too_many_requests"})

    def test_post_with_foreign_origin_is_403(self):
        headers = {"Cookie": self._cookie(), "Origin": "http://evil.example"}
        status, _, body = self._request("POST", OUTPUT_PATH, body={"value": 1}, headers=headers)
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(body), {"error": "forbidden"})

    def test_output_ok_bad_value_unknown_port_and_too_large(self):
        headers = {"Cookie": self._cookie()}
        status, _, _ = self._request("POST", OUTPUT_PATH, body={"value": 1}, headers=headers)
        self.assertEqual(status, 202)
        status, _, _ = self._request("POST", OUTPUT_PATH, body={"value": 5}, headers=headers)
        self.assertEqual(status, 400)
        status, _, _ = self._request(
            "POST", f"/api/v1/devices/{MAC}/ports/99/output", body={"value": 1}, headers=headers
        )
        self.assertEqual(status, 404)
        status, _, body = self._request("POST", OUTPUT_PATH, body=b"x" * 70000, headers=headers)
        self.assertEqual(status, 413)
        self.assertEqual(json.loads(body), {"error": "payload_too_large"})

    def test_history_bad_from_is_400(self):
        headers = {"Cookie": self._cookie()}
        path = f"/api/v1/history?mac={MAC}&sensor_id=sensor-1&tag=active_pwr&from=abc&to=5000"
        status, _, body = self._request("GET", path, headers=headers)
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body), {"error": "bad_request"})

    def test_history_returns_recorded_points(self):
        self.history.record(MAC, "sensor-1", "active_pwr", 12.5, 1000)
        headers = {"Cookie": self._cookie()}
        path = f"/api/v1/history?mac={MAC}&sensor_id=sensor-1&tag=active_pwr&from=0&to=5000"
        status, _, body = self._request("GET", path, headers=headers)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"points": [[1000, 12.5]]})

    def test_addon_mode_serves_ingress_without_login(self):
        server = self._start("addon", ingress_peer="127.0.0.1")
        status, _, body = self._request("GET", ADDON_DEVICES_PATH, server=server)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)[0]["mac"], MAC)

    def test_addon_mode_refuses_other_peers(self):
        server = self._start("addon")
        with self.assertLogs("mfi_server.api", level="WARNING") as cm:
            status, _, body = self._request("GET", ADDON_DEVICES_PATH, server=server)
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(body), {"error": "forbidden"})
        self.assertIn("127.0.0.1", "".join(cm.output))

    def test_root_serves_index_with_csp(self):
        status, headers, body = self._request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["content-type"])
        self.assertEqual(headers["content-security-policy"], STATIC_CSP)
        self.assertEqual(int(headers["content-length"]), len(body))
        self.assertIn(b"<!DOCTYPE html>", body)

    def test_query_string_marker_serves_static(self):
        status, headers, body = self._request("GET", "/?x=api/v1/devices")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["content-type"])
        self.assertIn(b"<!DOCTYPE html>", body)

    def test_ingress_root_serves_index(self):
        status, headers, _ = self._request("GET", "/api/hassio_ingress/abc/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["content-type"])

    def test_app_js_is_javascript(self):
        status, headers, _ = self._request("GET", "/app.js")
        self.assertEqual(status, 200)
        self.assertIn("text/javascript", headers["content-type"])

    def test_automations_html_is_served(self):
        status, headers, _ = self._request("GET", "/automations.html")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["content-type"])

    def test_automations_js_is_served(self):
        status, headers, _ = self._request("GET", "/automations.js")
        self.assertEqual(status, 200)
        self.assertIn("text/javascript", headers["content-type"])

    def test_common_js_is_served(self):
        status, headers, _ = self._request("GET", "/common.js")
        self.assertEqual(status, 200)
        self.assertIn("text/javascript", headers["content-type"])

    def test_automations_html_served_under_ingress_prefix(self):
        status, headers, _ = self._request("GET", "/api/hassio_ingress/abc/automations.html")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["content-type"])

    def test_unlisted_static_file_is_404(self):
        status, _, body = self._request("GET", "/automations.json")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body), {"error": "not_found"})

    def test_traversal_is_404(self):
        for path in ("/../config.py", "/%2e%2e/config.py"):
            status, _, body = self._request("GET", path)
            self.assertEqual(status, 404, path)
            self.assertEqual(json.loads(body), {"error": "not_found"})

    def test_unknown_static_file_is_404(self):
        status, _, body = self._request("GET", "/nonexistent.js")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body), {"error": "not_found"})

    def test_automation_validate_bad_yaml_is_400_with_details(self):
        headers = {"Cookie": self._cookie()}
        status, _, body = self._request(
            "POST", "/api/v1/automations/validate", body={"yaml": "id: [unclosed"}, headers=headers
        )
        self.assertEqual(status, 400)
        self.assertTrue(json.loads(body)["details"])

    def test_automation_create_then_same_id_is_409(self):
        headers = {"Cookie": self._cookie()}
        status, _, body = self._request("POST", AUTOMATIONS_PATH, body=AUTOMATION, headers=headers)
        self.assertEqual(status, 201)
        self.assertEqual(json.loads(body)["id"], "a1")
        status, _, body = self._request("POST", AUTOMATIONS_PATH, body=AUTOMATION, headers=headers)
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(body), {"error": "conflict"})

    def test_automation_trigger_is_202(self):
        headers = {"Cookie": self._cookie()}
        status, _, _ = self._request("POST", AUTOMATIONS_PATH, body=AUTOMATION, headers=headers)
        self.assertEqual(status, 201)
        status, _, _ = self._request("POST", "/api/v1/automations/a1/trigger", headers=headers)
        self.assertEqual(status, 202)

    def test_automations_without_cookie_is_401(self):
        self._set_password()
        status, _, body = self._request("GET", AUTOMATIONS_PATH)
        self.assertEqual(status, 401)
        self.assertEqual(json.loads(body), {"error": "unauthorized"})

    def test_discovery_lists_known_and_unknown(self):
        headers = {"Cookie": self._cookie()}
        status, _, body = self._request("GET", "/api/v1/discovery", headers=headers)
        self.assertEqual(status, 200)
        devices = {device["mac"]: device for device in json.loads(body)["devices"]}
        self.assertIs(devices[MAC]["known"], True)
        self.assertIs(devices["02aabbccdd02"]["known"], False)

    def test_discovery_scan_returns_devices(self):
        headers = {"Cookie": self._cookie()}
        status, _, body = self._request("POST", "/api/v1/discovery/scan", headers=headers)
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(body)["devices"]), 2)
        self.assertEqual(self.scanner.scanned, 1)

    def test_discovery_scan_in_progress_is_409(self):
        self.scanner._in_progress = True
        headers = {"Cookie": self._cookie()}
        status, _, body = self._request("POST", "/api/v1/discovery/scan", headers=headers)
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(body), {"error": "scan_in_progress"})

    def test_discovery_without_cookie_is_401(self):
        self._set_password()
        status, _, body = self._request("GET", "/api/v1/discovery")
        self.assertEqual(status, 401)
        self.assertEqual(json.loads(body), {"error": "unauthorized"})
        status, _, _ = self._request("POST", "/api/v1/discovery/scan")
        self.assertEqual(status, 401)


if __name__ == "__main__":
    unittest.main()
