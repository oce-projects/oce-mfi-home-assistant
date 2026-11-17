"""Offline tests of mfi_wifi_setup.wifi_survey: the network list and the captive.cgi query.

Run from the mfi-wifi-setup folder:
    python3 -m unittest discover -s tests -t . -v

Standard library only; no tkinter, no device: the fake survey.json.cgi listens on 127.0.0.1.
"""
from __future__ import annotations

import errno
import http.client
import json
import socket
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from mfi_wifi_setup import wifi_survey

SURVEY = [
    {"essid": "CasaWPA2", "signal_level": -40, "encryption": "WPA2", "auth_suites": "PSK"},
    {"essid": "Open Net", "signal_level": -55, "encryption": "none", "auth_suites": ""},
    {"essid": "OldWEP", "signal_level": -30, "encryption": "WEP", "auth_suites": ""},
    {"essid": "OfficeEAP", "signal_level": -35, "encryption": "WPA2", "auth_suites": "802.1x"},
    {"essid": "WeakWPA", "signal_level": -70, "encryption": "WPA", "auth_suites": "PSK"},
]

FORBIDDEN_FIELDS = ("inform_addr", "cloud_name", "cloud_pass")


class _SurveyHandler(BaseHTTPRequestHandler):
    body = b""

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, fmt, *args):
        pass


def _fake_survey(body: bytes) -> ThreadingHTTPServer:
    """Start a fake survey.json.cgi on 127.0.0.1 on a free port; stop it with _stop."""
    handler = type("Handler", (_SurveyHandler,), {"body": body})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _stop(server: ThreadingHTTPServer) -> None:
    server.shutdown()
    server.server_close()


def _http_to(server: ThreadingHTTPServer):
    """Connect factory for the fake server: a plain HTTP connection to 127.0.0.1."""
    port = server.server_address[1]
    return lambda: http.client.HTTPConnection("127.0.0.1", port, timeout=5)


def _raising(exc: BaseException):
    """Connect factory that fails with exc, as a closed or unreachable device does."""

    def connect():
        raise exc

    return connect


class TestReadSurvey(unittest.TestCase):
    def test_sorted_strongest_first_without_wep_and_eap(self):
        server = _fake_survey(json.dumps(SURVEY).encode("utf-8"))
        self.addCleanup(_stop, server)
        networks = wifi_survey.read_survey(_http_to(server))
        self.assertEqual(len(networks), 3)
        self.assertEqual([n.essid for n in networks], ["CasaWPA2", "Open Net", "WeakWPA"])
        self.assertEqual([n.signal_level for n in networks], [-40, -55, -70])
        self.assertEqual([n.encryption for n in networks], ["WPA2", "none", "WPA"])
        self.assertEqual([n.security for n in networks], ["wpa2", "none", "wpa"])

    def test_signal_level_is_an_int(self):
        server = _fake_survey(json.dumps(SURVEY).encode("utf-8"))
        self.addCleanup(_stop, server)
        networks = wifi_survey.read_survey(_http_to(server))
        for net in networks:
            with self.subTest(essid=net.essid):
                self.assertIsInstance(net.signal_level, int)

    def test_empty_survey_gives_empty_list(self):
        server = _fake_survey(b"[]")
        self.addCleanup(_stop, server)
        self.assertEqual(wifi_survey.read_survey(_http_to(server)), [])

    def test_item_without_signal_level_is_skipped(self):
        survey = SURVEY + [{"essid": "NoLevel", "encryption": "WPA2", "auth_suites": "PSK"}]
        server = _fake_survey(json.dumps(survey).encode("utf-8"))
        self.addCleanup(_stop, server)
        networks = wifi_survey.read_survey(_http_to(server))
        self.assertEqual([n.essid for n in networks], ["CasaWPA2", "Open Net", "WeakWPA"])

    def test_non_json_or_non_list_body_gives_empty_list(self):
        for body in (b"<html>not json</html>", b"", b"{}", b'"text"'):
            with self.subTest(body=body):
                server = _fake_survey(body)
                try:
                    networks = wifi_survey.read_survey(_http_to(server))
                finally:
                    _stop(server)
                self.assertEqual(networks, [])

    def test_request_error_gives_empty_list(self):
        for exc in (
            OSError(errno.ECONNREFUSED, "refused"),
            OSError(errno.ENETUNREACH, "net"),
            socket.timeout("timed out"),
        ):
            with self.subTest(exc=type(exc).__name__):
                self.assertEqual(wifi_survey.read_survey(_raising(exc)), [])


class TestSecurityFor(unittest.TestCase):
    def test_security_for_values(self):
        self.assertEqual(wifi_survey.security_for("WPA2"), "wpa2")
        self.assertEqual(wifi_survey.security_for("WPA"), "wpa")
        self.assertEqual(wifi_survey.security_for("none"), "none")
        self.assertEqual(wifi_survey.security_for(""), "none")


class TestIsSupported(unittest.TestCase):
    def test_open_and_psk_networks_are_supported(self):
        self.assertTrue(wifi_survey.is_supported({"encryption": "none", "auth_suites": ""}))
        self.assertTrue(wifi_survey.is_supported({"encryption": "WPA2", "auth_suites": "PSK"}))
        self.assertTrue(wifi_survey.is_supported({"encryption": "WPA", "auth_suites": "PSK"}))

    def test_wep_is_not_supported(self):
        self.assertFalse(wifi_survey.is_supported({"encryption": "WEP", "auth_suites": ""}))

    def test_eap_is_not_supported(self):
        self.assertFalse(wifi_survey.is_supported({"encryption": "WPA2", "auth_suites": "802.1x"}))
        self.assertFalse(wifi_survey.is_supported({"encryption": "WPA2", "auth_suites": "EAP"}))
        self.assertFalse(wifi_survey.is_supported({"encryption": "WPA2", "auth_suites": ["PSK", "eap"]}))


class TestBuildCaptiveQuery(unittest.TestCase):
    def test_open_network_query(self):
        path = wifi_survey.build_captive_query("Open Net", "none")
        self.assertTrue(path.startswith(wifi_survey.CAPTIVE_PATH + "?"))
        fields = parse_qs(urlsplit(path).query)
        self.assertEqual(fields["type"], ["POST"])
        self.assertEqual(fields["essid"], ["Open Net"])
        self.assertEqual(fields["security"], ["none"])
        self.assertEqual(set(fields), {"type", "essid", "security"})

    def test_wpa2_query_encodes_special_characters(self):
        path = wifi_survey.build_captive_query("Caffe & Te", "wpa2", "p@ss word!")
        query = urlsplit(path).query
        self.assertNotIn(" ", query)
        fields = parse_qs(query)
        self.assertEqual(
            fields,
            {
                "type": ["POST"],
                "essid": ["Caffe & Te"],
                "security": ["wpa2"],
                "wpa_auth": ["WPA-PSK"],
                "wpa_key": ["p@ss word!"],
            },
        )

    def test_query_never_carries_controller_or_cloud_fields(self):
        for path in (
            wifi_survey.build_captive_query("Open Net", "none"),
            wifi_survey.build_captive_query("Caffe & Te", "wpa2", "p@ss word!"),
        ):
            fields = parse_qs(urlsplit(path).query)
            for name in FORBIDDEN_FIELDS:
                with self.subTest(field=name):
                    self.assertNotIn(name, fields)


class TestSettings(unittest.TestCase):
    def test_security_values(self):
        self.assertEqual(wifi_survey.SEC_NONE, "none")
        self.assertEqual(wifi_survey.SEC_WPA, "wpa")
        self.assertEqual(wifi_survey.SEC_WPA2, "wpa2")

    def test_paths(self):
        self.assertEqual(wifi_survey.SURVEY_PATH, "/survey.json.cgi")
        self.assertEqual(wifi_survey.CAPTIVE_PATH, "/captive.cgi")


if __name__ == "__main__":
    unittest.main()
