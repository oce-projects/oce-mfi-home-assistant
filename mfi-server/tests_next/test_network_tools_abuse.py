"""CA1 to CA4 and the size limit of the risky network routes: off by default, web shell target only from
the stored record, admin role only, body limit.

Offline: the server listens on 127.0.0.1 only. Passwords are fake test data; addresses are documentation addresses.
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

from mfi_server_next import alarms, auth, comet, events, page_api, rules, stats
from mfi_server_next.devices import DeviceRegistry
from mfi_server_next.store import Store

ADMIN_PASSWORD = "Abcdefghij1!"
READ_ONLY_PASSWORD = "Bcdefghijk2@"
MAC_SERIAL = "aabbccddeeff"
MAC_OTHER = "001122334455"
HOST = "203.0.113.5"
WEBSHELL_PORT = 2323
MAX_BODY = 65536
NET_ROUTES = (
    f"/api/v1/net/webshell/{MAC_SERIAL}",
    f"/api/v1/net/ssh/{MAC_SERIAL}",
    "/api/v1/net/upnp",
    "/api/v1/net/guest",
)
ALLOW_KEYS = ("allow_webshell", "allow_browser_ssh", "allow_upnp", "allow_guest_page")


class FakeSocket:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class FakeConnect:
    def __init__(self):
        self.calls = []

    def __call__(self, host, port):
        self.calls.append((host, port))
        return FakeSocket()


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


def enable_all(settings):
    for key in ALLOW_KEYS:
        settings[key] = True


class AbuseTestCase(unittest.TestCase):
    """Serves the page API on 127.0.0.1 with real stores in a temporary folder; network tools are off by default."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = Store.open(Path(tmp.name))
        self.addCleanup(self.store.close)
        self.auth = auth.AuthManager(self.store)
        self.auth.add_user("boss", ADMIN_PASSWORD, auth.ROLE_ADMIN)
        self.auth.add_user("viewer", READ_ONLY_PASSWORD, auth.ROLE_READ_ONLY)
        devices = DeviceRegistry()
        devices.adopt(MAC_SERIAL, x_authkey="0" * 32, cfgversion=1, portversion=1, model="M2S", ip=HOST)
        devices.adopt(MAC_OTHER, x_authkey="0" * 32, cfgversion=1, portversion=1, model="M2M", ip=HOST)
        self.fake_connect = FakeConnect()
        self.context = SimpleNamespace(
            auth=self.auth,
            devices=devices,
            events=events.EventLog(self.store),
            alarms=alarms.AlarmStore(self.store),
            stats=stats.Aggregator(sqlite3.connect(":memory:")),
            automations=rules.AutomationStore(self.store),
            comet=comet.CometBuffer(),
            actions=FakeActions(),
            import_backup=lambda data: 0,
            firmware_paths=set(),
            firmware_dir=None,
            net_connect=self.fake_connect,
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


class TestDefaultsOff(AbuseTestCase):
    def test_every_tool_answers_403_and_opens_nothing(self):
        token = self.session("boss", ADMIN_PASSWORD)
        for path in NET_ROUTES:
            with self.subTest(path=path):
                status, _, data = self.call("POST", path, cookie=token)
                self.assertEqual(status, 403)
                self.assertEqual(json.loads(data), {"error": "disabled"})
        self.assertEqual(self.fake_connect.calls, [])


class TestWebshellTarget(AbuseTestCase):
    def test_webshell_connects_only_to_the_stored_address(self):
        self.context.settings["allow_webshell"] = True
        token = self.session("boss", ADMIN_PASSWORD)
        status, _, data = self.call("POST", f"/api/v1/net/webshell/{MAC_SERIAL}", cookie=token)
        self.assertEqual(status, 200)
        self.assertEqual(
            json.loads(data),
            {"result": "ok", "host": HOST, "port": WEBSHELL_PORT, "protocol": "telnet"},
        )
        self.assertEqual(self.fake_connect.calls, [(HOST, WEBSHELL_PORT)])

    def test_host_and_port_in_the_request_are_refused(self):
        self.context.settings["allow_webshell"] = True
        token = self.session("boss", ADMIN_PASSWORD)
        self.call("POST", f"/api/v1/net/webshell/{MAC_SERIAL}", cookie=token)
        before = list(self.fake_connect.calls)
        body = json.dumps({"host": "evil.example", "port": 1}).encode("utf-8")
        status, _, data = self.call("POST", f"/api/v1/net/webshell/{MAC_SERIAL}", body=body, cookie=token)
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(data), {"error": "bad_request"})
        self.assertEqual(self.fake_connect.calls, before)
        self.assertNotIn(("evil.example", 1), self.fake_connect.calls)


class TestWebshellNonSerial(AbuseTestCase):
    def test_webshell_on_a_non_serial_device_is_refused(self):
        self.context.settings["allow_webshell"] = True
        token = self.session("boss", ADMIN_PASSWORD)
        status, _, data = self.call("POST", f"/api/v1/net/webshell/{MAC_OTHER}", cookie=token)
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(data), {"error": "not_serial"})
        self.assertEqual(self.fake_connect.calls, [])


class TestRoles(AbuseTestCase):
    def test_read_only_is_refused_on_every_tool(self):
        enable_all(self.context.settings)
        token = self.session("viewer", READ_ONLY_PASSWORD)
        for path in NET_ROUTES:
            with self.subTest(path=path):
                status, _, data = self.call("POST", path, cookie=token)
                self.assertEqual(status, 403)
                self.assertEqual(json.loads(data), {"error": "forbidden"})
        self.assertEqual(self.fake_connect.calls, [])

    def test_no_session_is_refused_on_every_tool(self):
        enable_all(self.context.settings)
        for path in NET_ROUTES:
            with self.subTest(path=path):
                status, _, data = self.call("POST", path)
                self.assertEqual(status, 401)
                self.assertEqual(json.loads(data), {"error": "unauthorized"})
        self.assertEqual(self.fake_connect.calls, [])


class TestOversized(AbuseTestCase):
    def test_oversized_body_is_413(self):
        self.context.settings["max_body"] = 100
        self.context.settings["allow_webshell"] = True
        token = self.session("boss", ADMIN_PASSWORD)
        status, _, data = self.call(
            "POST", f"/api/v1/net/webshell/{MAC_SERIAL}", body=b"x" * 300, cookie=token
        )
        self.assertEqual(status, 413)
        self.assertEqual(json.loads(data), {"error": "payload_too_large"})
        self.assertEqual(self.fake_connect.calls, [])


if __name__ == "__main__":
    unittest.main()
