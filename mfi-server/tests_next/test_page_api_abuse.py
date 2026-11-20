"""CA2, CA3 and CA4 checks of the page API: read_only refusals, body and JSON limits, 404/405, firmware path.

Offline: the server listens on 127.0.0.1 only. Passwords and the firmware path are fake test data.
Run from the repository root: python3 -m unittest discover -s mfi-server/tests_next -v
"""
import http.client
import http.server
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

from mfi_server_next import alarms, auth, comet, devices, events, page_api, rules, stats
from mfi_server_next.store import Store

ADMIN_PASSWORD = "Abcdefghij1!"
READ_ONLY_PASSWORD = "Bcdefghijk2@"
NEW_USER_PASSWORD = "Cdefghijkl3#"
FIRMWARE_PATH = "M2M/2.1.11.1309/firmware.bin"
MAC = "aabbccddeeff"
MAX_BODY = 100


class FakeActions:
    """Records every device command; each call succeeds like the real action does."""

    def __init__(self):
        self.calls = []

    def _record(self, *call):
        self.calls.append(call)

    def adopt(self, mac):
        self._record("adopt", mac)

    def forget(self, mac):
        self._record("forget", mac)

    def reboot(self, mac):
        self._record("reboot", mac)

    def locate(self, mac, data):
        self._record("locate", mac, data)

    def upgrade(self, mac):
        self._record("upgrade", mac)

    def set_port(self, mac, port, data):
        self._record("set_port", mac, port, data)

    def set_output(self, mac, port, value):
        self._record("set_output", mac, port, value)


class AbuseTestCase(unittest.TestCase):
    """Serves the page API on 127.0.0.1 with a small body limit and real stores in a temporary folder."""

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
            devices=devices.DeviceRegistry(self.store),
            events=events.EventLog(self.store),
            alarms=alarms.AlarmStore(self.store),
            stats=stats.Aggregator(sqlite3.connect(":memory:")),
            automations=rules.AutomationStore(self.store),
            comet=comet.CometBuffer(),
            actions=FakeActions(),
            import_backup=lambda data: 0,
            firmware_paths={FIRMWARE_PATH},
            firmware_dir=None,
            settings={"mode": "standalone", "comet_timeout_s": 0.05, "max_body": MAX_BODY},
        )
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), page_api.make_handler(self.context))
        self.addCleanup(self.server.server_close)
        self.port = self.server.server_address[1]
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(self.server.shutdown)

    def call(self, method, path, *, body=None, cookie=None):
        """Send one request to the local server; return (status, Set-Cookie header, body bytes)."""
        headers = {"Cookie": f"{page_api.SESSION_COOKIE}={cookie}"} if cookie else {}
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            return response.status, response.getheader("Set-Cookie"), response.read()
        finally:
            conn.close()

    def session(self, username, password):
        """Log in and return the session token; the test fails when the login does not work."""
        body = json.dumps({"username": username, "password": password}).encode("utf-8")
        status, set_cookie, _ = self.call("POST", "/api/v1/login", body=body)
        self.assertEqual(status, 200)
        return set_cookie.split(";", 1)[0].split("=", 1)[1]


class TestReadOnlyRole(AbuseTestCase):
    def test_read_only_cannot_adopt(self):
        token = self.session("viewer", READ_ONLY_PASSWORD)
        status, _, data = self.call("POST", f"/api/v1/devices/{MAC}/adopt", cookie=token)
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(data), {"error": "forbidden"})
        self.assertEqual(self.context.actions.calls, [])

    def test_read_only_cannot_forget(self):
        token = self.session("viewer", READ_ONLY_PASSWORD)
        status, _, data = self.call("POST", f"/api/v1/devices/{MAC}/forget", cookie=token)
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(data), {"error": "forbidden"})
        self.assertEqual(self.context.actions.calls, [])

    def test_read_only_cannot_add_user(self):
        token = self.session("viewer", READ_ONLY_PASSWORD)
        body = json.dumps({"username": "newbie", "password": NEW_USER_PASSWORD, "role": "admin"}).encode("utf-8")
        status, _, data = self.call("POST", "/api/v1/users", body=body, cookie=token)
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(data), {"error": "forbidden"})
        self.assertIsNone(self.auth.role("newbie"))

    def test_admin_adopt_is_accepted_so_the_refusal_is_the_role(self):
        token = self.session("boss", ADMIN_PASSWORD)
        status, _, data = self.call("POST", f"/api/v1/devices/{MAC}/adopt", cookie=token)
        self.assertEqual(status, 202)
        self.assertEqual(json.loads(data), {"result": "accepted"})
        self.assertEqual(self.context.actions.calls, [("adopt", MAC)])


class TestRequestLimits(AbuseTestCase):
    def test_body_over_max_body_is_413(self):
        status, _, data = self.call("POST", "/api/v1/login", body=b"x" * (MAX_BODY * 3))
        self.assertEqual(status, 413)
        self.assertEqual(json.loads(data), {"error": "payload_too_large"})

    def test_broken_json_on_login_is_400(self):
        status, _, data = self.call("POST", "/api/v1/login", body=b'{"username": ')
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(data), {"error": "bad_request"})

    def test_unknown_route_is_404(self):
        status, _, data = self.call("GET", "/api/v1/nonexistent")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(data), {"error": "not_found"})

    def test_wrong_method_on_known_route_is_405(self):
        status, _, data = self.call("GET", "/api/v1/login")
        self.assertEqual(status, 405)
        self.assertEqual(json.loads(data), {"error": "method_not_allowed"})


class TestFirmwareAllowlist(AbuseTestCase):
    def test_path_traversal_in_firmware_is_404(self):
        status, _, data = self.call("GET", "/dl/firmware/../secret")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(data), {"error": "not_found"})

    def test_file_outside_the_table_is_404(self):
        status, _, data = self.call("GET", "/dl/firmware/unknown.bin")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(data), {"error": "not_found"})


if __name__ == "__main__":
    unittest.main()
