"""Tests of mfi_server_next.inform: packet decryption, the answer choice and the HTTP server.

EPIC-02, CA1 and CA2. Offline, standard library only. Packets are built here with
crypto.aes128_encrypt and struct; mfi_server/packet.py is not imported.
Run with: python3 -m unittest discover -s mfi-server/tests_next -t mfi-server -v
"""
from __future__ import annotations

import http.client
import json
import struct
import threading
import unittest
import zlib

from mfi_server_next import crypto, devices, firmware, inform, tasks

TNBU_MAGIC = 1414414933
HEADER_FORMAT = ">II6sH16sII"
MAC = "002722000001"
OTHER_MAC = "002722000002"
AUTHKEY = "0123456789abcdef0123456789abcdef"
PREV_AUTHKEY = "fedcba9876543210fedcba9876543210"
CFGVERSION = "0123456701234567"
OTHER_CFGVERSION = "fedcba9876543210"
PORTVERSION = "7654321076543210"
IV = bytes(range(16, 32))
WRONG_KEY = bytes([0x11] * 16)


def build_packet(key, payload, *, mac=MAC, iv=IV, compress=False, data_version=1):
    """Return one TNBU packet: a 40-byte header, then the payload encrypted with key (AES-128-CBC, PKCS#7)."""
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    flags = inform.FLAG_ENCRYPTED
    if compress:
        body = zlib.compress(body)
        flags |= inform.FLAG_COMPRESSED
    cipher = crypto.aes128_encrypt(key, iv, body)
    header = struct.pack(HEADER_FORMAT, TNBU_MAGIC, 0, bytes.fromhex(mac), flags, iv, data_version, len(cipher))
    return header + cipher


def adopted_registry(authkey=AUTHKEY):
    """Return a registry with MAC adopted under authkey."""
    registry = devices.DeviceRegistry()
    registry.adopt(MAC, x_authkey=authkey, cfgversion=CFGVERSION, portversion=PORTVERSION, model="M2M")
    return registry


class RecordRegistry:
    """A registry with one fixed record: DeviceRegistry does not store the auto_upgrade flag."""

    def __init__(self, record):
        self._record = record

    def get(self, mac):
        return dict(self._record) if mac == self._record["mac"] else None


class TestDecode(unittest.TestCase):
    def test_first_key_that_decrypts_wins(self):
        packet = build_packet(bytes.fromhex(AUTHKEY), {"mac": MAC, "model": "M2M"})
        keys = [WRONG_KEY, bytes.fromhex(AUTHKEY), inform.FACTORY_KEY]
        header, payload, key = inform.decode(packet, keys)
        self.assertEqual(header.mac, bytes.fromhex(MAC))
        self.assertEqual(payload, {"mac": MAC, "model": "M2M"})
        self.assertEqual(key, bytes.fromhex(AUTHKEY))

    def test_key_not_in_the_list_raises_with_status_400(self):
        packet = build_packet(WRONG_KEY, {"mac": MAC})
        with self.assertRaises(inform.InformError) as ctx:
            inform.decode(packet, [bytes.fromhex(AUTHKEY), inform.FACTORY_KEY])
        self.assertEqual(ctx.exception.status, 400)

    def test_empty_key_list_raises(self):
        packet = build_packet(bytes.fromhex(AUTHKEY), {"mac": MAC})
        with self.assertRaises(inform.InformError):
            inform.decode(packet, [])

    def test_compressed_payload_is_inflated(self):
        packet = build_packet(bytes.fromhex(AUTHKEY), {"mac": MAC, "model": "P3U"}, compress=True)
        _, payload, _ = inform.decode(packet, [bytes.fromhex(AUTHKEY)])
        self.assertEqual(payload, {"mac": MAC, "model": "P3U"})

    def test_payload_that_is_not_an_object_is_rejected(self):
        packet = build_packet(bytes.fromhex(AUTHKEY), ["not", "an", "object"])
        with self.assertRaises(inform.InformError):
            inform.decode(packet, [bytes.fromhex(AUTHKEY)])

    def test_bad_magic_is_rejected(self):
        packet = build_packet(bytes.fromhex(AUTHKEY), {"mac": MAC})
        broken = struct.pack(">I", 1) + packet[4:]
        with self.assertRaises(inform.InformError):
            inform.parse_header(broken)

    def test_short_header_is_rejected(self):
        with self.assertRaises(inform.InformError):
            inform.parse_header(b"\x00" * (inform.HEADER_LEN - 1))

    def test_unsupported_data_version_is_rejected(self):
        packet = build_packet(bytes.fromhex(AUTHKEY), {"mac": MAC}, data_version=2)
        with self.assertRaises(inform.InformError):
            inform.parse_header(packet)


class TestCandidateKeys(unittest.TestCase):
    def test_order_is_previous_then_current_then_factory(self):
        record = {"x_prev_authkey": PREV_AUTHKEY, "x_authkey": AUTHKEY}
        self.assertEqual(
            inform.candidate_keys(record),
            [bytes.fromhex(PREV_AUTHKEY), bytes.fromhex(AUTHKEY), inform.FACTORY_KEY],
        )

    def test_missing_previous_key_is_skipped(self):
        record = {"x_prev_authkey": None, "x_authkey": AUTHKEY}
        self.assertEqual(inform.candidate_keys(record), [bytes.fromhex(AUTHKEY), inform.FACTORY_KEY])

    def test_unknown_device_gets_only_the_factory_key(self):
        self.assertEqual(inform.candidate_keys(None), [inform.FACTORY_KEY])

    def test_factory_key_is_the_public_constant(self):
        self.assertEqual(inform.FACTORY_KEY.hex(), "ba86f2bbe107c7c57eb5f2690775c712")
        self.assertEqual(len(inform.FACTORY_KEY), 16)


class TestBuildInformResponse(unittest.TestCase):
    def test_known_key_gets_an_encrypted_answer(self):
        raw = build_packet(bytes.fromhex(AUTHKEY), {"mac": MAC, "cfgversion": CFGVERSION, "model": "M2M"})
        status, body = inform.build_inform_response(raw, adopted_registry())
        self.assertEqual(status, 200)
        header, reply, _ = inform.decode(body, [bytes.fromhex(AUTHKEY)])
        self.assertEqual(header.mac, bytes.fromhex(MAC))
        self.assertEqual(reply["_type"], "noop")
        self.assertIsInstance(reply["server_time_in_utc"], str)

    def test_unknown_key_gives_400_and_no_crash(self):
        raw = build_packet(WRONG_KEY, {"mac": MAC, "cfgversion": CFGVERSION})
        self.assertEqual(inform.build_inform_response(raw, adopted_registry()), (400, b""))

    def test_unknown_device_with_factory_key_gets_setdefault(self):
        raw = build_packet(inform.FACTORY_KEY, {"mac": OTHER_MAC, "model": "M2M"}, mac=OTHER_MAC)
        status, body = inform.build_inform_response(raw, devices.DeviceRegistry())
        self.assertEqual(status, 200)
        _, reply, _ = inform.decode(body, [inform.FACTORY_KEY])
        self.assertEqual(reply["_type"], "setdefault")

    def test_payload_mac_must_match_the_header(self):
        raw = build_packet(bytes.fromhex(AUTHKEY), {"mac": OTHER_MAC, "cfgversion": CFGVERSION})
        self.assertEqual(inform.build_inform_response(raw, adopted_registry()), (400, b""))

    def test_previous_key_is_accepted_after_a_key_change(self):
        registry = devices.DeviceRegistry()
        registry.adopt(MAC, x_authkey=PREV_AUTHKEY, cfgversion=CFGVERSION, portversion=PORTVERSION)
        registry.adopt(MAC, x_authkey=AUTHKEY, cfgversion=CFGVERSION, portversion=PORTVERSION)
        raw = build_packet(bytes.fromhex(PREV_AUTHKEY), {"mac": MAC, "cfgversion": CFGVERSION})
        status, body = inform.build_inform_response(raw, registry)
        self.assertEqual(status, 200)
        _, reply, _ = inform.decode(body, [bytes.fromhex(PREV_AUTHKEY)])
        self.assertEqual(reply["_type"], "noop")


class TestHandleInform(unittest.TestCase):
    def test_adopted_device_without_changes_gets_noop(self):
        reply = inform.handle_inform({"mac": MAC, "cfgversion": CFGVERSION}, adopted_registry())
        self.assertEqual(reply, {"_type": "noop", "interval": 10})

    def test_different_cfgversion_gets_setparam(self):
        reply = inform.handle_inform({"mac": MAC, "cfgversion": OTHER_CFGVERSION}, adopted_registry())
        self.assertEqual(reply, {"_type": "setparam", "cfgversion": CFGVERSION})

    def test_auto_upgrade_gets_the_upgrade_message(self):
        registry = RecordRegistry(
            {"mac": MAC, "adopted": True, "cfgversion": CFGVERSION, "auto_upgrade": True}
        )
        payload = {"mac": MAC, "model": "M2M", "version": "2.1.1.0", "cfgversion": CFGVERSION}
        reply = inform.handle_inform(payload, registry)
        self.assertEqual(reply, firmware.build_upgrade("M2M"))
        self.assertEqual(reply["_type"], "upgrade")
        self.assertEqual(reply["version"], firmware.FIRMWARE_VERSION)

    def test_upgrade_needs_auto_upgrade_on(self):
        payload = {"mac": MAC, "model": "M2M", "version": "2.1.1.0", "cfgversion": CFGVERSION}
        reply = inform.handle_inform(payload, adopted_registry())
        self.assertEqual(reply, {"_type": "noop", "interval": 10})

    def test_model_without_firmware_gets_no_upgrade(self):
        registry = RecordRegistry(
            {"mac": MAC, "adopted": True, "cfgversion": CFGVERSION, "auto_upgrade": True}
        )
        payload = {"mac": MAC, "model": "IWS1U", "version": "2.1.1.0", "cfgversion": CFGVERSION}
        reply = inform.handle_inform(payload, registry)
        self.assertEqual(reply, {"_type": "noop", "interval": 10})

    def test_queued_command_is_delivered_once(self):
        queue = tasks.TaskQueue()
        queue.enqueue(tasks.build_output_command(MAC, 1, 1))
        registry = adopted_registry()
        payload = {"mac": MAC, "cfgversion": CFGVERSION}
        reply = inform.handle_inform(payload, registry, queue)
        self.assertEqual(reply["_type"], "cmd")
        self.assertEqual(reply, tasks.build_output_command(MAC, 1, 1))
        self.assertEqual(inform.handle_inform(payload, registry, queue), {"_type": "noop", "interval": 10})

    def test_device_not_adopted_gets_setdefault(self):
        registry = devices.DeviceRegistry()
        registry.add(MAC, model="M2M")
        reply = inform.handle_inform({"mac": MAC, "cfgversion": CFGVERSION}, registry)
        self.assertEqual(reply, {"_type": "setdefault"})

    def test_unknown_device_declaring_default_gets_noop(self):
        reply = inform.handle_inform({"mac": MAC, "default": True}, devices.DeviceRegistry())
        self.assertEqual(reply, {"_type": "noop", "interval": 10})

    def test_no_payload_gives_noop_and_does_not_raise(self):
        self.assertEqual(inform.handle_inform(), {"_type": "noop", "interval": 10})
        self.assertEqual(inform.handle_inform(None, devices.DeviceRegistry(), tasks.TaskQueue()), {"_type": "noop", "interval": 10})

    def test_payload_that_is_not_an_object_gives_noop(self):
        self.assertEqual(inform.handle_inform(["x"], devices.DeviceRegistry()), {"_type": "noop", "interval": 10})

    def test_invalid_mac_gives_a_typed_answer_and_does_not_raise(self):
        reply = inform.handle_inform({"mac": "0027220000zz"}, devices.DeviceRegistry())
        self.assertIsInstance(reply["_type"], str)


class TestHttpServer(unittest.TestCase):
    """make_server answers real POST /inform requests on 127.0.0.1."""

    def setUp(self):
        self.server = inform.make_server(adopted_registry(), tasks.TaskQueue(), host="127.0.0.1", port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def post(self, packet):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=10)
        try:
            conn.request("POST", "/inform", body=packet, headers={"Content-Type": "application/x-binary"})
            response = conn.getresponse()
            return response.status, response.getheader("Content-Type"), response.read()
        finally:
            conn.close()

    def test_valid_packet_gets_a_decryptable_answer(self):
        packet = build_packet(bytes.fromhex(AUTHKEY), {"mac": MAC, "cfgversion": CFGVERSION})
        status, content_type, body = self.post(packet)
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/x-binary")
        _, reply, _ = inform.decode(body, [bytes.fromhex(AUTHKEY)])
        self.assertEqual(reply["_type"], "noop")
        self.assertIn("server_time_in_utc", reply)

    def test_packet_with_unknown_key_gets_400_over_http(self):
        packet = build_packet(WRONG_KEY, {"mac": MAC, "cfgversion": CFGVERSION})
        status, _, body = self.post(packet)
        self.assertEqual(status, 400)
        self.assertEqual(body, b"")
