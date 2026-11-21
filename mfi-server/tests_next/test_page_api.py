"""CA1 checks of the page API: login cookie, 401 without a session, 200 with it, comet (standard library only).

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
FIRMWARE_PATH = "M2M/2.1.11.1309/firmware.bin"


class FakeEvents:
    """Returns no events; the real EventLog uses a sqlite3 connection that belongs to the test thread."""

    def list_events(self, *, device=None, since=None, until=None, limit=1000):
        return []


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

    def repoint(self, mac):
        self._record("repoint", mac)

    def set_port(self, mac, port, data):
        self._record("set_port", mac, port, data)

    def set_output(self, mac, port, value):
        self._record("set_output", mac, port, value)


class PageApiTestCase(unittest.TestCase):
    """Serves the page API on 127.0.0.1 with real stores in a temporary data folder."""

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
            settings={"mode": "standalone", "comet_timeout_s": 0.05, "max_body": 65536},
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

    def login(self, username, password):
        body = json.dumps({"username": username, "password": password}).encode("utf-8")
        return self.call("POST", "/api/v1/login", body=body)

    @staticmethod
    def token_of(set_cookie):
        """Return the session token of a Set-Cookie header value."""
        return set_cookie.split(";", 1)[0].split("=", 1)[1]


class TestLogin(PageApiTestCase):
    def test_login_with_right_password_sets_session_cookie(self):
        status, set_cookie, data = self.login("boss", ADMIN_PASSWORD)
        self.assertEqual(status, 200)
        self.assertIsNotNone(set_cookie)
        self.assertIn("mfi_session=", set_cookie)
        self.assertIn("HttpOnly", set_cookie)
        self.assertEqual(json.loads(data)["role"], "admin")

    def test_login_with_wrong_password_is_401(self):
        status, set_cookie, data = self.login("boss", "Wrong-pass1!x")
        self.assertEqual(status, 401)
        self.assertIsNone(set_cookie)
        self.assertEqual(json.loads(data), {"error": "login_failed"})


class TestSessionRoutes(PageApiTestCase):
    def test_protected_route_without_session_is_401(self):
        status, _, data = self.call("GET", "/api/v1/events")
        self.assertEqual(status, 401)
        self.assertEqual(json.loads(data), {"error": "unauthorized"})

    def test_protected_route_with_session_is_200(self):
        # The server thread must not use the sqlite3 connection of the test thread, so events is faked here.
        self.context.events = FakeEvents()
        _, set_cookie, _ = self.login("boss", ADMIN_PASSWORD)
        status, _, data = self.call("GET", "/api/v1/events", cookie=self.token_of(set_cookie))
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data), {"events": []})

    def test_comet_with_session_returns_cursor_and_messages(self):
        self.context.comet.append({"kind": "test"})
        _, set_cookie, _ = self.login("boss", ADMIN_PASSWORD)
        status, _, data = self.call("GET", "/api/v1/comet?cursor=0", cookie=self.token_of(set_cookie))
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data), {"cursor": 1, "messages": [{"kind": "test"}]})


class TestRepoint(PageApiTestCase):
    def test_admin_repoint_calls_actions_repoint(self):
        _, set_cookie, _ = self.login("boss", ADMIN_PASSWORD)
        status, _, data = self.call(
            "POST", "/api/v1/devices/001122334455/repoint", cookie=self.token_of(set_cookie)
        )
        self.assertEqual(status, 202)
        self.assertEqual(json.loads(data), {"result": "accepted"})
        self.assertEqual(self.context.actions.calls, [("repoint", "001122334455")])

    def test_repoint_without_session_is_401(self):
        status, _, data = self.call("POST", "/api/v1/devices/001122334455/repoint")
        self.assertEqual(status, 401)
        self.assertEqual(json.loads(data), {"error": "unauthorized"})
        self.assertEqual(self.context.actions.calls, [])


class TestAdoptMissingCredential(PageApiTestCase):
    def test_adopt_without_ssh_username_is_409_naming_the_setting(self):
        class FailingAdoptActions(FakeActions):
            def adopt(self, mac):
                raise PermissionError("device_ssh_username is not set")

        self.context.actions = FailingAdoptActions()
        _, set_cookie, _ = self.login("boss", ADMIN_PASSWORD)
        status, _, data = self.call(
            "POST", "/api/v1/devices/001122334455/adopt", cookie=self.token_of(set_cookie)
        )
        self.assertEqual(status, 409)
        self.assertIn("device_ssh_username", data.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
