"""CA3 and CA4 checks of the controller-compatible API: no session, read_only, unknown verb, body and JSON limits.

Offline: the server listens on 127.0.0.1 only. Passwords and the MAC are fake test data.
Run from the repository root: python3 -m unittest discover -s mfi-server/tests_next -v
"""
import http.client
import http.server
import json
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
MAX_BODY = 100
OUTPUT_COMMAND = json.dumps({"cmd": "mfi-output", "mac": MAC, "port": 1, "val": 1}).encode("utf-8")


class AbuseTestCase(unittest.TestCase):
    """Serves the compatible API on 127.0.0.1 with a small body limit and a real store in a temporary folder."""

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
            settings={"mode": "standalone", "max_body": MAX_BODY},
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

    def call(self, method, path, *, body=None, cookie=None):
        """Send one request to the local server; return (status, body bytes)."""
        headers = {"Cookie": f"{compat_api.SESSION_COOKIE}={cookie}"} if cookie else {}
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()

    def session(self, username, password):
        """Return the session token of a user; the test fails when the login does not work."""
        token = self.auth.login(username, password, "127.0.0.1")
        self.assertIsNotNone(self.auth.check_session(token))
        return token


class TestSessionAndRole(AbuseTestCase):
    def test_no_session_returns_login_required(self):
        status, data = self.call("POST", "/api/v1.0/cmd/devmgr", body=OUTPUT_COMMAND)
        self.assertEqual(status, 401)
        body = json.loads(data)
        self.assertEqual(body["meta"]["rc"], "error")
        self.assertEqual(body["meta"]["msg"], "api.err.LoginRequired")
        self.assertIsNone(self.context.tasks.pop_for_mac(MAC))

    def test_read_only_cannot_send_command(self):
        token = self.session("viewer", READ_ONLY_PASSWORD)
        status, data = self.call("POST", "/api/v1.0/cmd/devmgr", body=OUTPUT_COMMAND, cookie=token)
        self.assertEqual(status, 403)
        body = json.loads(data)
        self.assertEqual(body["meta"]["rc"], "error")
        self.assertEqual(body["meta"]["msg"], "api.err.NoPermission")
        self.assertIsNone(self.context.tasks.pop_for_mac(MAC))


class TestRequestLimits(AbuseTestCase):
    def test_unknown_verb_object_is_rejected(self):
        token = self.session("boss", ADMIN_PASSWORD)
        status, data = self.call("POST", "/api/v1.0/foo/bar", body=b"{}", cookie=token)
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(data)["meta"]["msg"], "api.err.UnknownMethod")

    def test_oversized_body_is_rejected(self):
        status, data = self.call("POST", "/api/v1.0/cmd/devmgr", body=b"x" * (MAX_BODY * 3))
        self.assertEqual(status, 413)
        body = json.loads(data)
        self.assertEqual(body["meta"]["rc"], "error")
        self.assertEqual(body["meta"]["msg"], "api.err.InvalidPayload")

    def test_malformed_json_is_rejected(self):
        token = self.session("boss", ADMIN_PASSWORD)
        status, data = self.call("POST", "/api/v1.0/cmd/devmgr", body=b'{"cmd": ', cookie=token)
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(data)["meta"]["msg"], "api.err.InvalidPayload")

    def test_wrong_method_is_rejected(self):
        status, data = self.call("GET", "/api/v1.0/cmd/devmgr")
        self.assertEqual(status, 405)
        self.assertEqual(json.loads(data)["meta"]["msg"], "api.err.WrongMethod")


class TestDeeplyNestedJson(unittest.TestCase):
    """A deeply nested JSON body is refused with InvalidPayload, not an uncaught error."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = Store.open(Path(tmp.name))
        self.addCleanup(self.store.close)
        self.auth = auth.AuthManager(self.store)
        self.auth.add_user("boss", ADMIN_PASSWORD, auth.ROLE_ADMIN)
        self.context = SimpleNamespace(
            auth=self.auth,
            tasks=tasks.TaskQueue(),
            sensors=sensors.SensorRegistry(),
            settings={"mode": "standalone", "max_body": 1 << 20},
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

    def test_deeply_nested_json_is_rejected(self):
        token = self.auth.login("boss", ADMIN_PASSWORD, "127.0.0.1")
        depth = 20000
        body = b"[" * depth + b"]" * depth
        headers = {
            "Content-Type": "application/json",
            "Cookie": f"{compat_api.SESSION_COOKIE}={token}",
        }
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request("POST", "/api/v1.0/cmd/devmgr", body=body, headers=headers)
            response = conn.getresponse()
            status, data = response.status, response.read()
        finally:
            conn.close()
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(data)["meta"]["msg"], "api.err.InvalidPayload")


if __name__ == "__main__":
    unittest.main()
