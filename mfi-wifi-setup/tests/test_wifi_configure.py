"""Offline tests of mfi_wifi_setup.wifi_configure: status.cgi states, guided configuration, leaveap.

Run from the mfi-wifi-setup folder:
    python3 -m unittest discover -s tests -t . -v

Standard library only; no tkinter, no device: the fake device listens on 127.0.0.1.
"""
from __future__ import annotations

import http.client
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from mfi_wifi_setup import wifi_configure

SECRET = "MARK-SECRET-123"
LOGGER = "mfi_wifi_setup.wifi_configure"
ADDRESS_IP = "203.0.113.42"
NO_ADDRESS = "0.0.0.0"
CONNECTED_APMAC = "aabbcc"
NOT_CONNECTED_APMAC = "000000"


def _status(cp_state, essid="", apmac=NOT_CONNECTED_APMAC, ip=NO_ADDRESS):
    return {
        "host": {"cp_state": cp_state},
        "wireless": {"essid": essid, "apmac": apmac},
        "wlan": {"ip": ip},
    }


class _DeviceHandler(BaseHTTPRequestHandler):
    statuses = []  # status.cgi answers in order; the last one repeats
    calls = {}  # what the device received: "captive", "status", "leaveap"
    drop_leaveap = False  # True: POST /leaveap.cgi gets no answer

    def do_GET(self):
        if self.path.startswith("/captive.cgi"):
            self.calls["captive"].append(self.path)
            self._reply(b"{}")
        elif self.path.startswith("/status.cgi"):
            index = min(len(self.calls["status"]), len(self.statuses) - 1)
            self.calls["status"].append(self.path)
            self._reply(json.dumps(self.statuses[index]).encode("utf-8"))
        else:
            self._reply(b"", code=404)

    def do_POST(self):
        if self.path.startswith("/leaveap.cgi"):
            self.calls["leaveap"].append(self.path)
            if not self.drop_leaveap:
                self._reply(b"{}")
            return
        self._reply(b"", code=404)

    def _reply(self, body, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        """Silent: the fake device writes nothing, so the tests see only the module logging."""


def _fake_device(statuses, drop_leaveap=False):
    """Fake device on 127.0.0.1 on a free port; returns the server and the record of its calls."""
    calls = {"captive": [], "status": [], "leaveap": []}
    handler = type(
        "Handler",
        (_DeviceHandler,),
        {"statuses": list(statuses), "calls": calls, "drop_leaveap": drop_leaveap},
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, calls


def _stop(server):
    server.shutdown()
    server.server_close()


def _http_to(server):
    """Connect factory for the fake device: a plain HTTP connection to 127.0.0.1."""
    port = server.server_address[1]
    return lambda: http.client.HTTPConnection("127.0.0.1", port, timeout=5)


def _raising(exc):
    """Connect factory that fails with exc, as an unreachable device does."""

    def connect():
        raise exc

    return connect


class TestConstants(unittest.TestCase):
    def test_paths_and_interval(self):
        self.assertEqual(wifi_configure.STATUS_PATH, "/status.cgi")
        self.assertEqual(wifi_configure.LEAVEAP_PATH, "/leaveap.cgi")
        self.assertEqual(wifi_configure.POLL_INTERVAL_S, 1.0)
        self.assertEqual(wifi_configure.ERROR_CP_STATES, {"wifitimeout", "iptimeout"})

    def test_step_values(self):
        self.assertEqual(wifi_configure.STEP_PENDING, "pending")
        self.assertEqual(wifi_configure.STEP_WIFI_CONNECTED, "wifi_connected")
        self.assertEqual(wifi_configure.STEP_ADDRESS_OBTAINED, "address_obtained")
        self.assertEqual(wifi_configure.STEP_ERROR, "error")


class TestClassifyStatus(unittest.TestCase):
    def test_sequence_up_to_connected(self):
        pending = {
            "host": {"cp_state": "wifipending"},
            "wireless": {"essid": "", "apmac": "000000"},
            "wlan": {"ip": "0.0.0.0"},
        }
        wifi = {
            "host": {"cp_state": "wifipending"},
            "wireless": {"essid": "CasaWPA2", "apmac": "aabbcc"},
            "wlan": {"ip": "0.0.0.0"},
        }
        address = {
            "host": {"cp_state": "ctrlconnected"},
            "wireless": {"essid": "CasaWPA2", "apmac": "aabbcc"},
            "wlan": {"ip": "203.0.113.42"},
        }
        self.assertEqual(wifi_configure.classify_status(pending).step, wifi_configure.STEP_PENDING)
        self.assertEqual(wifi_configure.classify_status(wifi).step, wifi_configure.STEP_WIFI_CONNECTED)
        step = wifi_configure.classify_status(address)
        self.assertEqual(step.step, wifi_configure.STEP_ADDRESS_OBTAINED)
        self.assertEqual(step.ip, "203.0.113.42")
        self.assertEqual(step.cp_state, "ctrlconnected")

    def test_error_states_give_error_step(self):
        for cp in ("wifitimeout", "iptimeout"):
            with self.subTest(cp_state=cp):
                step = wifi_configure.classify_status(_status(cp, "CasaWPA2", CONNECTED_APMAC, ADDRESS_IP))
                self.assertEqual(step.step, wifi_configure.STEP_ERROR)
                self.assertEqual(step.cp_state, cp)

    def test_all_zero_apmac_is_not_connected(self):
        step = wifi_configure.classify_status(_status("wifipending", "CasaWPA2", "000000", ADDRESS_IP))
        self.assertEqual(step.step, wifi_configure.STEP_PENDING)

    def test_missing_essid_is_not_connected(self):
        step = wifi_configure.classify_status(_status("wifipending", "", CONNECTED_APMAC, ADDRESS_IP))
        self.assertEqual(step.step, wifi_configure.STEP_PENDING)

    def test_no_address_is_wifi_connected(self):
        step = wifi_configure.classify_status(_status("wifipending", "CasaWPA2", CONNECTED_APMAC, NO_ADDRESS))
        self.assertEqual(step.step, wifi_configure.STEP_WIFI_CONNECTED)

    def test_missing_wlan_ip_is_not_an_address(self):
        payload = {
            "host": {"cp_state": "wifipending"},
            "wireless": {"essid": "CasaWPA2", "apmac": "aabbcc"},
            "wlan": {},
        }
        self.assertEqual(wifi_configure.classify_status(payload).step, wifi_configure.STEP_WIFI_CONNECTED)

    def test_non_ascii_essid_counts_as_connected(self):
        step = wifi_configure.classify_status(_status("wifipending", "Caffè Ü", CONNECTED_APMAC, NO_ADDRESS))
        self.assertEqual(step.step, wifi_configure.STEP_WIFI_CONNECTED)

    def test_non_error_states_are_never_errors(self):
        for cp in ("none", "wifipending", "ctrlconnected", "ctrltimeout", "ctrlerror", "byebye"):
            with self.subTest(cp_state=cp):
                step = wifi_configure.classify_status({"host": {"cp_state": cp}})
                self.assertNotEqual(step.step, wifi_configure.STEP_ERROR)
                self.assertEqual(step.step, wifi_configure.STEP_PENDING)

    def test_empty_or_malformed_payload_is_pending(self):
        self.assertEqual(wifi_configure.classify_status({}).step, wifi_configure.STEP_PENDING)
        self.assertEqual(wifi_configure.classify_status({"host": "x"}).step, wifi_configure.STEP_PENDING)


class TestReadSetupStatus(unittest.TestCase):
    def test_reads_address_from_device(self):
        server, _ = _fake_device([_status("ctrlconnected", "CasaWPA2", CONNECTED_APMAC, ADDRESS_IP)])
        self.addCleanup(_stop, server)
        step = wifi_configure.read_setup_status(_http_to(server))
        self.assertEqual(step.step, wifi_configure.STEP_ADDRESS_OBTAINED)
        self.assertEqual(step.ip, ADDRESS_IP)

    def test_unreachable_device_is_pending(self):
        step = wifi_configure.read_setup_status(_raising(OSError("refused")))
        self.assertEqual(step.step, wifi_configure.STEP_PENDING)


class TestConfigure(unittest.TestCase):
    def test_success_polls_then_leaves_access_point(self):
        server, calls = _fake_device(
            [
                _status("wifipending"),
                _status("wifipending", "CasaWPA2", CONNECTED_APMAC),
                _status("ctrlconnected", "CasaWPA2", CONNECTED_APMAC, ADDRESS_IP),
            ]
        )
        self.addCleanup(_stop, server)
        seen = []
        result = wifi_configure.configure(
            _http_to(server),
            essid="CasaWPA2",
            security="wpa2",
            wpa_key=SECRET,
            on_progress=seen.append,
            poll_interval_s=0,
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.step, wifi_configure.STEP_ADDRESS_OBTAINED)
        self.assertEqual(result.ip, ADDRESS_IP)
        self.assertEqual(
            [s.step for s in seen],
            [wifi_configure.STEP_PENDING, wifi_configure.STEP_WIFI_CONNECTED, wifi_configure.STEP_ADDRESS_OBTAINED],
        )
        self.assertEqual(len(calls["captive"]), 1)
        self.assertTrue(calls["captive"][0].startswith("/captive.cgi?"))
        self.assertEqual(len(calls["status"]), 3)
        self.assertEqual(len(calls["leaveap"]), 1)

    def test_error_state_stops_without_leaveap(self):
        server, calls = _fake_device([_status("wifipending"), _status("wifitimeout")])
        self.addCleanup(_stop, server)
        result = wifi_configure.configure(
            _http_to(server), essid="CasaWPA2", security="wpa2", wpa_key=SECRET, poll_interval_s=0
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.step, wifi_configure.STEP_ERROR)
        self.assertEqual(result.error, "configuration failed")
        self.assertEqual(calls["leaveap"], [])

    def test_iptimeout_also_stops_without_leaveap(self):
        server, calls = _fake_device([_status("iptimeout", "CasaWPA2", CONNECTED_APMAC)])
        self.addCleanup(_stop, server)
        result = wifi_configure.configure(
            _http_to(server), essid="CasaWPA2", security="wpa2", wpa_key=SECRET, poll_interval_s=0
        )
        self.assertEqual(result.step, wifi_configure.STEP_ERROR)
        self.assertEqual(calls["leaveap"], [])

    def test_timeout_without_address(self):
        server, calls = _fake_device([_status("wifipending")])
        self.addCleanup(_stop, server)
        result = wifi_configure.configure(
            _http_to(server), essid="CasaWPA2", security="wpa2", wpa_key=SECRET, poll_interval_s=0, max_polls=3
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.step, wifi_configure.STEP_ERROR)
        self.assertEqual(result.error, "timeout")
        self.assertEqual(len(calls["status"]), 3)
        self.assertEqual(calls["leaveap"], [])

    def test_zero_max_polls_times_out_at_once(self):
        server, calls = _fake_device([_status("wifipending")])
        self.addCleanup(_stop, server)
        result = wifi_configure.configure(
            _http_to(server), essid="CasaWPA2", security="wpa2", wpa_key=SECRET, poll_interval_s=0, max_polls=0
        )
        self.assertEqual(result.error, "timeout")
        self.assertEqual(calls["status"], [])

    def test_unreachable_device_when_sending_form(self):
        result = wifi_configure.configure(
            _raising(OSError("refused")),
            essid="CasaWPA2",
            security="wpa2",
            wpa_key=SECRET,
            poll_interval_s=0,
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.step, wifi_configure.STEP_ERROR)
        self.assertEqual(result.error, "device not reachable")
        self.assertNotIn(SECRET, result.error)

    def test_failed_leaveap_is_reported(self):
        server, calls = _fake_device(
            [_status("ctrlconnected", "CasaWPA2", CONNECTED_APMAC, ADDRESS_IP)], drop_leaveap=True
        )
        self.addCleanup(_stop, server)
        result = wifi_configure.configure(
            _http_to(server), essid="CasaWPA2", security="wpa2", wpa_key=SECRET, poll_interval_s=0
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.step, wifi_configure.STEP_ADDRESS_OBTAINED)
        self.assertEqual(result.ip, ADDRESS_IP)
        self.assertEqual(result.error, "leaveap failed")
        self.assertEqual(len(calls["leaveap"]), 1)

    def test_password_never_reaches_the_log(self):
        server, _ = _fake_device(
            [
                _status("wifipending"),
                _status("ctrlconnected", "CasaWPA2", CONNECTED_APMAC, ADDRESS_IP),
            ]
        )
        self.addCleanup(_stop, server)
        with self.assertLogs(LOGGER, level="DEBUG") as captured:
            result = wifi_configure.configure(
                _http_to(server), essid="CasaWPA2", security="wpa2", wpa_key=SECRET, poll_interval_s=0
            )
        self.assertTrue(result.ok)
        self.assertTrue(captured.output)
        self.assertEqual("\n".join(captured.output).count(SECRET), 0)

    def test_password_absent_from_error_and_log(self):
        server, _ = _fake_device([_status("wifitimeout")])
        self.addCleanup(_stop, server)
        with self.assertLogs(LOGGER, level="DEBUG") as captured:
            result = wifi_configure.configure(
                _http_to(server), essid="CasaWPA2", security="wpa2", wpa_key=SECRET, poll_interval_s=0
            )
        self.assertEqual(result.error.count(SECRET), 0)
        self.assertTrue(captured.output)
        self.assertEqual("\n".join(captured.output).count(SECRET), 0)


if __name__ == "__main__":
    unittest.main()
