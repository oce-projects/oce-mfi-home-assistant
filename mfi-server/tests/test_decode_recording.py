"""Checks tools/decode_recording.py on recordings built with packet.encode.

Run from the repository root:
    python3 -m unittest discover -s mfi-server/tests -t mfi-server -v

Standard library only; no network. The key used here is a fake 16-byte value:
no real device key appears in this file.
"""
from __future__ import annotations

import base64
import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path

from mfi_server import packet

ROOT = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location("decode_recording", ROOT / "tools" / "decode_recording.py")
decode_recording = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(decode_recording)

MAC_HEX = "0a1b2c3d4e5f"
MAC = bytes.fromhex(MAC_HEX)
FAKE_KEY = bytes(range(1, 17))
IV = bytes(range(16))
EMAIL = "owner" + chr(64) + "example" + chr(46) + "org"
REQUEST = {
    "cmd": "inform",
    "model": "mPower mini",
    "hostname": "lab-host",
    "fw": "2.1.11.1309",
    "authkey": "0" * 32,
    "contact": EMAIL,
    "serial": MAC_HEX,
}
RESPONSE = {"cmd": "noop", "interval": 10}
REQUEST_PACKET = packet.encode(MAC, FAKE_KEY, REQUEST, IV)
RESPONSE_PACKET = packet.encode(MAC, FAKE_KEY, RESPONSE, IV)


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def inform_line(request: bytes, response: bytes, client: str = "203.0.113.7") -> str:
    return json.dumps({
        "t": 1700000000000,
        "port": 6080,
        "client": client,
        "method": "POST",
        "path": "/inform",
        "req_body_b64": b64(request),
        "resp_body_b64": b64(response),
    })


class TestDecodeLines(unittest.TestCase):
    def test_decrypts_request_and_response_with_the_device_key(self):
        result = decode_recording.decode_lines([inform_line(REQUEST_PACKET, RESPONSE_PACKET)], {MAC_HEX: [FAKE_KEY]}, False)
        self.assertEqual(len(result), 1)
        self.assertIsNone(result[0]["error"])
        self.assertEqual(result[0]["mac"], MAC_HEX)
        self.assertEqual(result[0]["request"], REQUEST)
        self.assertEqual(result[0]["response"], RESPONSE)
        self.assertEqual(result[0]["client"], "203.0.113.7")

    def test_anonymize_replaces_mac_ip_email_host_and_redacts_authkey(self):
        result = decode_recording.decode_lines([inform_line(REQUEST_PACKET, RESPONSE_PACKET)], {MAC_HEX: [FAKE_KEY]}, True)
        entry = result[0]
        self.assertIsNone(entry["error"])
        self.assertEqual(entry["mac"], "020000000001")
        self.assertEqual(entry["client"], "192.0.2.1")
        self.assertEqual(entry["request"]["authkey"], "REDACTED")
        self.assertEqual(entry["request"]["contact"], "REDACTED_EMAIL")
        self.assertEqual(entry["request"]["hostname"], "device-1")
        self.assertEqual(entry["request"]["fw"], "2.1.11.1309")
        self.assertEqual(entry["request"]["cmd"], "inform")
        self.assertEqual(entry["response"], RESPONSE)
        self.assertEqual(entry["request"]["serial"], "020000000001")
        text = json.dumps(result)
        self.assertNotIn("203.0.113.7", text)
        self.assertNotIn(MAC_HEX, text)
        self.assertNotIn(EMAIL, text)

    def test_anonymize_is_stable_across_lines(self):
        lines = [
            inform_line(REQUEST_PACKET, RESPONSE_PACKET, "203.0.113.7"),
            inform_line(REQUEST_PACKET, RESPONSE_PACKET, "203.0.113.8"),
            inform_line(REQUEST_PACKET, RESPONSE_PACKET, "203.0.113.7"),
        ]
        result = decode_recording.decode_lines(lines, {MAC_HEX: [FAKE_KEY]}, True)
        self.assertEqual([e["client"] for e in result], ["192.0.2.1", "192.0.2.2", "192.0.2.1"])
        self.assertEqual({e["mac"] for e in result}, {"020000000001"})

    def test_broken_and_unreadable_lines_do_not_stop_the_others(self):
        lines = [
            inform_line(bytes(range(64)), RESPONSE_PACKET),
            "{not json",
            inform_line(REQUEST_PACKET, RESPONSE_PACKET),
        ]
        result = decode_recording.decode_lines(lines, {MAC_HEX: [FAKE_KEY]}, False)
        self.assertEqual(len(result), 3)
        self.assertTrue(result[0]["error"])
        self.assertIsNone(result[0]["mac"])
        self.assertIsNone(result[0]["request"])
        self.assertTrue(result[1]["error"])
        self.assertIsNone(result[2]["error"])
        self.assertEqual(result[2]["request"], REQUEST)

    def test_response_failure_keeps_the_decoded_request(self):
        line = inform_line(REQUEST_PACKET, bytes(range(64)))
        result = decode_recording.decode_lines([line], {MAC_HEX: [FAKE_KEY]}, False)
        self.assertTrue(result[0]["error"])
        self.assertEqual(result[0]["mac"], MAC_HEX)
        self.assertEqual(result[0]["request"], REQUEST)
        self.assertIsNone(result[0]["response"])

    def test_packet_without_a_known_key_gets_an_error(self):
        result = decode_recording.decode_lines([inform_line(REQUEST_PACKET, RESPONSE_PACKET)], {}, False)
        self.assertTrue(result[0]["error"])
        self.assertIsNone(result[0]["request"])

    def test_web_line_decodes_json_bodies(self):
        web = json.dumps({
            "t": 2,
            "port": 6443,
            "client": "203.0.113.7",
            "method": "POST",
            "path": "/api/login",
            "req_headers": [["Content-Type", "application/json"]],
            "req_body_b64": b64(b'{"name":"a","x_password":"REDACTED"}'),
            "resp_headers": [["Content-Type", "application/json"]],
            "resp_body_b64": b64(b'{"meta":{"rc":"ok"}}'),
            "body_omitted": False,
        })
        result = decode_recording.decode_lines([web], {}, False)
        self.assertIsNone(result[0]["error"])
        self.assertEqual(result[0]["request"], {"name": "a", "x_password": "REDACTED"})
        self.assertEqual(result[0]["response"], {"meta": {"rc": "ok"}})
        self.assertEqual(result[0]["client"], "203.0.113.7")
        anonymized = decode_recording.decode_lines([web], {}, True)
        self.assertEqual(anonymized[0]["client"], "192.0.2.1")

    def test_web_body_that_is_not_json_is_left_as_base64(self):
        html = json.dumps({
            "t": 3,
            "port": 6443,
            "client": "203.0.113.7",
            "req_headers": [],
            "req_body_b64": "",
            "resp_headers": [["Content-Type", "text/html"]],
            "resp_body_b64": b64(b"<html></html>"),
            "body_omitted": False,
        })
        result = decode_recording.decode_lines([html], {}, False)
        self.assertIsNone(result[0]["error"])
        self.assertIsNone(result[0]["response"])
        self.assertEqual(result[0]["resp_body_b64"], b64(b"<html></html>"))

    def test_web_json_body_that_is_broken_gets_an_error(self):
        broken = json.dumps({
            "t": 4,
            "port": 6443,
            "client": "203.0.113.7",
            "req_headers": [],
            "req_body_b64": "",
            "resp_headers": [["Content-Type", "application/json"]],
            "resp_body_b64": b64(b"{bad"),
            "body_omitted": False,
        })
        result = decode_recording.decode_lines([broken], {}, False)
        self.assertTrue(result[0]["error"])
        self.assertIsNone(result[0]["response"])

    def test_web_anonymize_redacts_raw_bodies_and_sensitive_headers(self):
        raw_body = b'{"password":"hunter2","peer":"203.0.113.9"}'
        body_b64 = b64(raw_body)
        web = json.dumps({
            "t": 5,
            "port": 6443,
            "client": "203.0.113.7",
            "method": "POST",
            "path": "/api/login",
            "req_headers": [
                ["Cookie", "sessionid=abc123"],
                ["Authorization", "Bearer xyz789"],
                ["Content-Type", "application/json"],
            ],
            "req_body_b64": body_b64,
            "resp_headers": [["Set-Cookie", "sessionid=def456"]],
            "resp_body_b64": "",
            "body_omitted": False,
        })
        result = decode_recording.decode_lines([web], {}, True)
        entry = result[0]
        self.assertIsNone(entry["error"])
        self.assertEqual(entry["client"], "192.0.2.1")
        self.assertEqual(entry["req_body_b64"], "REDACTED")
        self.assertEqual(entry["resp_body_b64"], "REDACTED")
        headers = dict((h[0], h[1]) for h in entry["req_headers"])
        self.assertEqual(headers["Cookie"], "REDACTED")
        self.assertEqual(headers["Authorization"], "REDACTED")
        self.assertEqual(headers["Content-Type"], "application/json")
        resp_headers = dict((h[0], h[1]) for h in entry["resp_headers"])
        self.assertEqual(resp_headers["Set-Cookie"], "REDACTED")
        text = json.dumps(result)
        self.assertNotIn(body_b64, text)
        self.assertNotIn("hunter2", text)
        self.assertNotIn("sessionid=abc123", text)
        self.assertNotIn("Bearer xyz789", text)

    def test_web_line_with_malformed_header_entry_does_not_crash(self):
        web = json.dumps({
            "t": 6,
            "port": 6443,
            "client": "203.0.113.7",
            "req_headers": [42, ["Content-Type", "application/json"]],
            "req_body_b64": b64(b'{"name":"a"}'),
            "resp_headers": [],
            "resp_body_b64": "",
            "body_omitted": False,
        })
        result = decode_recording.decode_lines([web], {}, False)
        self.assertEqual(len(result), 1)
        self.assertIsNone(result[0]["error"])
        self.assertEqual(result[0]["request"], {"name": "a"})

    def test_anonymize_replaces_host_header_and_ip_at_end_of_text(self):
        web = json.dumps({
            "t": 7,
            "port": 6443,
            "client": "203.0.113.7",
            "method": "GET",
            "path": "/api/status",
            "req_headers": [["Host", "myhome.local"], ["Content-Type", "application/json"]],
            "req_body_b64": "",
            "resp_headers": [["Content-Type", "application/json"]],
            "resp_body_b64": b64(b'{"msg":"reach 203.0.113.9."}'),
            "body_omitted": False,
        })
        result = decode_recording.decode_lines([web], {}, True)
        entry = result[0]
        self.assertIsNone(entry["error"])
        headers = dict((h[0], h[1]) for h in entry["req_headers"])
        self.assertEqual(headers["Host"], "device-1")
        self.assertEqual(entry["response"], {"msg": "reach 192.0.2.2."})
        text = json.dumps(result)
        self.assertNotIn("myhome.local", text)
        self.assertNotIn("203.0.113.9", text)
        self.assertNotIn("203.0.113.7", text)

    def test_blank_lines_are_skipped(self):
        self.assertEqual(decode_recording.decode_lines([], {}, False), [])
        self.assertEqual(decode_recording.decode_lines(["", "   \n"], {}, False), [])


class TestMain(unittest.TestCase):
    def test_main_returns_one_when_the_backup_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            recording = Path(tmp) / "rec.jsonl"
            recording.write_text("", encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()):
                code = decode_recording.main([
                    "--recording", str(recording),
                    "--backup", str(Path(tmp) / "missing.unf"),
                    "--out", tmp,
                ])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
