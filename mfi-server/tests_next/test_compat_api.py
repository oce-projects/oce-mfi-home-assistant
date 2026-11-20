"""CA1 and CA2 checks of the controller-compatible API: observed routes, cmd/devmgr and upd/sensor (standard library only).

Offline: the server listens on 127.0.0.1 only. Passwords and MAC addresses are fake test data.
Run from the repository root: python3 -m unittest discover -s mfi-server/tests_next -v
"""
import http.client
import http.server
import json
import re
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

from mfi_server_next import auth, compat_api, sensors, tasks
from mfi_server_next.store import Store

ADMIN_PASSWORD = "Abcdefghij1!"
READ_ONLY_PASSWORD = "Bcdefghijk2@"
MAC = "002722000001"
WEB_API_DOC = Path(__file__).resolve().parents[2] / "docs" / "controller" / "web-api.md"
OBSERVED_ROUTE_RE = re.compile(r"`/api/v1\.0/([a-z]+/[a-z]+)`")


class CompatApiTestCase(unittest.TestCase):
    """Serves the compatible API on 127.0.0.1 with a real store and auth in a temporary data folder."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = Store.open(Path(tmp.name))
        self.addCleanup(self.store.close)
        self.auth = auth.AuthManager(self.store)
        self.auth.add_user("boss", ADMIN_PASSWORD, auth.ROLE_ADMIN)
        self.auth.add_user("viewer", READ_ONLY_PASSWORD, auth.ROLE_READ_ONLY)
        self.context = SimpleNamespace(
            auth=self.auth,
            tasks=tasks.TaskQueue(),
            sensors=sensors.SensorRegistry(),
            settings={"mode": "standalone", "max_body": 65536},
        )
        self.server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), compat_api.make_compat_handler(self.context)
        )
        self.addCleanup(self.server.server_close)
        self.port = self.server.server_address[1]
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(self.server.shutdown)

    def session(self, username, password):
        """Return a session token from the auth store; the compatible API has no login route."""
        return self.auth.login(username, password, "127.0.0.1")

    def call(self, method, path, body=None, cookie=None):
        """Send one request to the local server; return (status, body bytes)."""
        headers = {"Content-Type": "application/json"} if body is not None else {}
        if cookie:
            headers["Cookie"] = f"{compat_api.SESSION_COOKIE}={cookie}"
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()


class TestImplementedRoutes(unittest.TestCase):
    """CA1: every implemented route is marked OBSERVED in docs/controller/web-api.md."""

    def test_implemented_routes_are_observed_in_web_api(self):
        observed = set()
        with WEB_API_DOC.open(encoding="utf-8") as doc:
            for line in doc:
                if "OBSERVED" not in line:
                    continue
                for match in OBSERVED_ROUTE_RE.finditer(line):
                    observed.add(match.group(1))
        self.assertTrue(
            compat_api.IMPLEMENTED_ROUTES.issubset(observed),
            f"not OBSERVED in web-api.md: {sorted(compat_api.IMPLEMENTED_ROUTES - observed)}",
        )
        self.assertIn("cmd/devmgr", compat_api.IMPLEMENTED_ROUTES)
        self.assertIn("upd/sensor", compat_api.IMPLEMENTED_ROUTES)


class TestCmdDevmgr(CompatApiTestCase):
    """CA2: cmd/devmgr queues the device command and answers meta.rc 'ok'."""

    def test_cmd_devmgr_mfi_output_queues_and_returns_ok(self):
        token = self.session("boss", ADMIN_PASSWORD)
        body = json.dumps({"cmd": "mfi-output", "mac": MAC, "port": 1, "val": 1}).encode("utf-8")
        status, data = self.call("POST", "/api/v1.0/cmd/devmgr", body=body, cookie=token)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data), {"data": [], "meta": {"rc": "ok"}})
        task = self.context.tasks.pop_for_mac(MAC)
        self.assertIsInstance(task, dict)
        self.assertEqual(task["cmd"], "mfi-output")
        self.assertEqual(task["port"], 1)
        self.assertEqual(task["val"], 1)
        self.assertEqual(task["mac"], MAC)

    def test_cmd_devmgr_kick_serial_queues_and_returns_ok(self):
        token = self.session("boss", ADMIN_PASSWORD)
        body = json.dumps({"cmd": "kick-serial", "mac": MAC}).encode("utf-8")
        status, data = self.call("POST", "/api/v1.0/cmd/devmgr", body=body, cookie=token)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data)["meta"], {"rc": "ok"})
        task = self.context.tasks.pop_for_mac(MAC)
        self.assertIsInstance(task, dict)
        self.assertEqual(task["cmd"], "kick-serial")


class TestUpdSensor(CompatApiTestCase):
    """upd/sensor stores the new calibration of the sensor and answers meta.rc 'ok'."""

    def test_upd_sensor_updates_calibration_and_returns_ok(self):
        created = self.context.sensors.add(MAC, 1, "THS", "")
        sid = created["sId"]
        token = self.session("boss", ADMIN_PASSWORD)
        body = json.dumps({"sId": sid, "calibration": "abc123"}).encode("utf-8")
        status, data = self.call("POST", "/api/v1.0/upd/sensor", body=body, cookie=token)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data)["meta"], {"rc": "ok"})
        self.assertEqual(self.context.sensors.get(sid)["calibration"], "abc123")


if __name__ == "__main__":
    unittest.main()
