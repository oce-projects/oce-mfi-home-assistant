"""Tests of the inform HTTP server: real sockets on 127.0.0.1, port chosen by the OS.

Each test starts a server on a free port with a temporary data folder, sends
inform packets built in memory with mfi_server.packet, and stops the server in
tearDown. No network beyond 127.0.0.1.
"""
from __future__ import annotations

import http.client
import os
import tempfile
import threading
import unittest
from pathlib import Path

import mfi_server
from mfi_server import packet
from mfi_server.commands import CommandQueue
from mfi_server.config import Settings
from mfi_server.measurements import Measurements
from mfi_server.server import make_server
from mfi_server.states import DeviceStates
from mfi_server.store import DeviceStore

MAC = "02aabbccdd01"
MAC_UNKNOWN = "02aabbccdd02"
MAC_FACTORY = "02aabbccdd03"
TIMEOUT_S = 5


class _BrokenMeasurements:
    """Measurements whose ingest always fails, to test the 503 answer."""

    def ingest(self, mac: str, payload: dict, now_ms: int) -> None:
        raise RuntimeError("measurement store is broken")

    def latest(self, mac: str) -> dict:
        return {}


class InformServerTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        data_dir = Path(self._tmp.name)
        self.settings = Settings(data_dir=data_dir, inform_port=0, bind_address="127.0.0.1")
        self.store = DeviceStore(data_dir)
        self.states = DeviceStates()
        self.queue = CommandQueue()
        self.measurements = Measurements()
        self.server = make_server(self.settings, self.store, self.states, self.queue, self.measurements)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(TIMEOUT_S)
        self._tmp.cleanup()

    def _add_device(self, mac: str, authkey: str) -> None:
        self.store.upsert(
            {
                "mac": mac,
                "model": "P3E",
                "name": "",
                "authkey": authkey,
                "ports": [],
                "state": "unknown",
                "last_seen_ms": 0,
            }
        )

    def _request(self, method: str, path: str, body: bytes | None = None) -> tuple[int, dict, bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=TIMEOUT_S)
        try:
            conn.request(method, path, body=body)
            response = conn.getresponse()
            data = response.read()
            headers = {name.lower(): value for name, value in response.getheaders()}
            return response.status, headers, data
        finally:
            conn.close()

    def _inform(self, key: bytes, payload: dict) -> dict:
        """Send one inform from MAC with a fresh IV and return the decrypted answer."""
        request = packet.encode(bytes.fromhex(MAC), key, payload, os.urandom(16))
        status, _, body = self._request("POST", "/inform", request)
        self.assertEqual(status, 200)
        _, message, _ = packet.decode(body, [key])
        return message

    def test_known_device_gets_encrypted_noop(self):
        key = os.urandom(16)
        self._add_device(MAC, key.hex())
        iv = os.urandom(16)
        request = packet.encode(bytes.fromhex(MAC), key, {"mac": MAC, "model": "P3E"}, iv)
        status, headers, body = self._request("POST", "/inform", request)
        self.assertEqual(status, 200)
        self.assertEqual(headers["content-type"], "application/x-binary")
        self.assertEqual(headers["content-length"], str(len(body)))
        header, message, used_key = packet.decode(body, [key])
        self.assertEqual(used_key, key)
        self.assertEqual(header.iv, iv)
        self.assertEqual(message["_type"], "noop")
        self.assertEqual(message["interval"], 10)
        self.assertIsInstance(message["server_time_in_utc"], str)
        self.assertTrue(message["server_time_in_utc"].isdigit())

    def test_unknown_mac_and_other_paths_get_404(self):
        key = os.urandom(16)
        self._add_device(MAC, key.hex())
        request = packet.encode(bytes.fromhex(MAC_UNKNOWN), key, {"mac": MAC_UNKNOWN}, os.urandom(16))
        status, headers, body = self._request("POST", "/inform", request)
        self.assertEqual((status, body), (404, b""))
        self.assertEqual(headers["content-length"], "0")
        status, _, _ = self._request("POST", "/other", b"")
        self.assertEqual(status, 404)
        status, _, _ = self._request("GET", "/inform")
        self.assertEqual(status, 404)

    def test_bad_packets_get_400(self):
        key = os.urandom(16)
        self._add_device(MAC, key.hex())
        status, _, body = self._request("POST", "/inform", b"12345")
        self.assertEqual((status, body), (400, b""))
        mismatch = packet.encode(bytes.fromhex(MAC), key, {"mac": MAC_FACTORY}, os.urandom(16))
        status, _, _ = self._request("POST", "/inform", mismatch)
        self.assertEqual(status, 400)
        valid = packet.encode(bytes.fromhex(MAC), key, {"mac": MAC}, os.urandom(16))
        wrong_magic = b"\x00\x00\x00\x00" + valid[4:]
        status, _, _ = self._request("POST", "/inform", wrong_magic)
        self.assertEqual(status, 400)

    def test_queued_command_is_sent_once_to_a_connected_device(self):
        key = os.urandom(16)
        self._add_device(MAC, key.hex())
        self.queue.put(MAC, 1, "sensor1", 1)
        first = self._inform(key, {"mac": MAC})
        second = self._inform(key, {"mac": MAC})
        third = self._inform(key, {"mac": MAC})
        self.assertEqual(first["_type"], "noop")
        self.assertEqual(second["_type"], "cmd")
        self.assertEqual(second["cmd"], "mfi-output")
        self.assertEqual(second["port"], 1)
        self.assertEqual(second["sId"], "sensor1")
        self.assertEqual(second["val"], 1)
        self.assertEqual(third["_type"], "noop")
        self.assertEqual(self.queue.pending(MAC), 0)

    def test_device_with_empty_authkey_gets_noop_not_reset(self):
        self._add_device(MAC_FACTORY, "")
        factory = bytes.fromhex(packet.DEFAULT_KEY_HEX)
        request = packet.encode(bytes.fromhex(MAC_FACTORY), factory, {"mac": MAC_FACTORY}, os.urandom(16))
        status, _, body = self._request("POST", "/inform", request)
        self.assertEqual(status, 200)
        _, message, _ = packet.decode(body, [factory])
        self.assertEqual(message["_type"], "noop")

    def test_package_sources_never_quote_the_reset_word(self):
        package_dir = Path(mfi_server.__file__).parent
        needles = ['"' + "setdefault" + '"', "'" + "setdefault" + "'"]
        sources = sorted(package_dir.glob("*.py"))
        self.assertTrue(sources)
        for path in sources:
            text = path.read_text(encoding="utf-8")
            for needle in needles:
                self.assertNotIn(needle, text, path.name)

    def test_internal_error_gets_503_and_no_key_in_log(self):
        key = os.urandom(16)
        self._add_device(MAC, key.hex())
        self.server.measurements = _BrokenMeasurements()
        request = packet.encode(bytes.fromhex(MAC), key, {"mac": MAC}, os.urandom(16))
        with self.assertLogs("mfi_server.server", "ERROR") as logs:
            status, _, body = self._request("POST", "/inform", request)
        self.assertEqual((status, body), (503, b""))
        self.assertNotIn(key.hex(), "\n".join(logs.output))

    def test_measurements_are_stored_and_device_is_connected(self):
        key = os.urandom(16)
        self._add_device(MAC, key.hex())
        payload = {"mac": MAC, "alarm": [{"sId": "sensor1", "tag": "output", "val": 1}]}
        message = self._inform(key, payload)
        self.assertEqual(message["_type"], "noop")
        self.assertEqual(self.measurements.latest(MAC), {"sensor1": {"output": 1}})
        self.assertEqual(self.states.state(MAC), "connected")

    def test_valid_inform_records_the_wakeup_target(self):
        key = os.urandom(16)
        self._add_device(MAC, key.hex())
        self._inform(key, {"mac": MAC, "connect_request_ip": "127.0.0.1", "connect_request_port": 40000})
        self.assertEqual(self.states.wakeup_target(MAC), ("127.0.0.1", 40000))
        other_key = os.urandom(16)
        self._add_device("02aabbccdd09", other_key.hex())
        request = packet.encode(bytes.fromhex("02aabbccdd09"), other_key, {"mac": "02aabbccdd09"}, os.urandom(16))
        status, _, _ = self._request("POST", "/inform", request)
        self.assertEqual(status, 200)
        self.assertIsNone(self.states.wakeup_target("02aabbccdd09"))
