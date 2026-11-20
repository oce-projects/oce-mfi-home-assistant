"""Abuse tests of the maps (EPIC-12): a non-image file, an oversized image, a '../' name and the read_only refusal.

Offline, standard library only. Each test works in its own temporary folder. The image bytes are a tiny
synthetic PNG built in code; no real image is stored in the repository.
Run from the repository root: python3 -m unittest discover -s mfi-server/tests_next -v
"""
import base64
import http.client
import http.server
import json
import re
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

from mfi_server_next import alarms, auth, comet, devices, events, maps, page_api, rules, stats
from mfi_server_next.store import Store

ADMIN_PASSWORD = "Abcdefghij1!"
READ_ONLY_PASSWORD = "Bcdefghijk2@"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
IMAGE_NAME = re.compile(r"^map_[0-9a-f]+\.png$")
MAX_BODY = 65536


class FakeActions:
    """Records every device command; the maps tests never call it."""

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


class MapsTestCase(unittest.TestCase):
    """Serves the page API on 127.0.0.1 with a real MapStore in a temporary folder."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store.open(Path(self.tmp.name) / "data")
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
            firmware_paths={"M2M/2.1.11.1309/firmware.bin"},
            firmware_dir=None,
            maps=maps.MapStore(self.store),
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


class TestMapStoreRefusals(MapsTestCase):
    def test_non_image_file_is_refused(self):
        with self.assertRaises(ValueError):
            maps.MapStore(self.store).create_map("x", image=b"this is not an image")
        self.assertEqual(maps.MapStore(self.store).list_maps(), [])

    def test_image_over_the_limit_is_refused(self):
        with self.assertRaises(ValueError):
            maps.MapStore(self.store, max_image_bytes=10).create_map("x", image=PNG)
        self.assertEqual(maps.MapStore(self.store).list_maps(), [])


class TestNameFromServer(MapsTestCase):
    def test_image_name_is_made_by_the_server(self):
        record = self.context.maps.create_map("x", image=PNG)
        self.assertRegex(record["image"], IMAGE_NAME)

    def test_traversal_name_creates_no_file_outside_the_data_folder(self):
        record = self.context.maps.create_map("../evil", image=PNG)
        self.assertRegex(record["image"], IMAGE_NAME)
        self.assertFalse((Path(self.tmp.name) / "evil.png").exists())
        names = sorted(p.name for p in (self.store.data_dir / "maps").iterdir())
        self.assertEqual(names, [record["image"]])

    def test_traversal_name_is_not_a_stored_key(self):
        self.context.maps.create_map("../evil", image=PNG)
        self.assertIsNone(self.context.maps.get_map("../evil"))
        self.assertFalse(self.context.maps.delete_map("../evil"))


class TestReadOnlyHttp(MapsTestCase):
    def test_read_only_cannot_create_a_map(self):
        token = self.session("viewer", READ_ONLY_PASSWORD)
        body = json.dumps({"name": "x"}).encode("utf-8")
        status, _, data = self.call("POST", "/api/v1/maps", body=body, cookie=token)
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(data), {"error": "forbidden"})
        self.assertEqual(self.context.maps.list_maps(), [])


class TestAdminHttp(MapsTestCase):
    def test_admin_creates_a_map_and_lists_it(self):
        token = self.session("boss", ADMIN_PASSWORD)
        body = json.dumps({"name": "Ground", "image_base64": base64.b64encode(PNG).decode()}).encode("utf-8")
        status, _, data = self.call("POST", "/api/v1/maps", body=body, cookie=token)
        self.assertEqual(status, 201)
        self.assertRegex(json.loads(data)["map"]["image"], IMAGE_NAME)

        status, _, data = self.call("GET", "/api/v1/maps", cookie=token)
        self.assertEqual(status, 200)
        self.assertEqual(len(json.loads(data)["maps"]), 1)


if __name__ == "__main__":
    unittest.main()
