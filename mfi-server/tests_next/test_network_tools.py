"""CA5 and the risky network functions: Wi-Fi with RADIUS, web shell, browser SSH, UPnP and guest page.

Offline, standard library only. Addresses are documentation addresses (203.0.113.0/24) and MACs are 12 hex digits.
Run from the repository root: python3 -m unittest discover -s mfi-server/tests_next -v
"""
import unittest

from mfi_server_next import network_tools, sensors
from mfi_server_next.devices import DeviceRegistry

MAC = "aabbccddeeff"
OTHER_MAC = "001122334455"
HOST = "203.0.113.5"
RADIUS_HOST = "203.0.113.9"
RADIUS_SECRET = "s3cr3t-radius-key"
ENTERPRISE_REQUEST = {
    "essid": "corp",
    "security": "wpa2eap",
    "radius_server": RADIUS_HOST,
    "radius_port": 1812,
    "radius_secret": RADIUS_SECRET,
}


class FakeSocket:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class FakeConnect:
    def __init__(self):
        self.calls = []
        self.sockets = []

    def __call__(self, host, port):
        self.calls.append((host, port))
        sock = FakeSocket()
        self.sockets.append(sock)
        return sock


class FakeLimiter:
    def __init__(self, blocked=False):
        self._blocked = blocked
        self.hits = []

    def blocked(self, ip):
        return self._blocked

    def failure(self, ip):
        self.hits.append(ip)


def serial_registry():
    reg = DeviceRegistry()
    reg.adopt(MAC, x_authkey="0" * 32, cfgversion=1, portversion=1, model="M2S", ip=HOST)
    return reg


def other_registry(model):
    reg = DeviceRegistry()
    reg.adopt(OTHER_MAC, x_authkey="0" * 32, cfgversion=1, portversion=1, model=model, ip=HOST)
    return reg


def no_address_registry():
    reg = DeviceRegistry()
    reg.adopt(MAC, x_authkey="0" * 32, cfgversion=1, portversion=1, model="M2S")
    return reg


class TestWifiConfig(unittest.TestCase):
    def test_personal(self):
        msg = sensors.build_wifi_config({"essid": "home", "security": "wpa2aes", "passphrase": "pass-phrase-1"})
        text = msg["mgmt"]["wireless_cfg"]
        self.assertIn("wireless.1.ssid=home", text)
        self.assertIn("wireless.1.security=wpa2aes", text)
        self.assertIn("wireless.1.passphrase=pass-phrase-1", text)

    def test_enterprise_radius(self):
        msg = sensors.build_wifi_config(ENTERPRISE_REQUEST)
        text = msg["mgmt"]["wireless_cfg"]
        self.assertIn(f"wireless.1.radius.ip={RADIUS_HOST}", text)
        self.assertIn("wireless.1.radius.port=1812", text)
        self.assertIn(f"wireless.1.radius.secret={RADIUS_SECRET}", text)

    def test_secret_not_logged(self):
        with self.assertNoLogs("mfi_server_next"):
            sensors.build_wifi_config(ENTERPRISE_REQUEST)

    def test_bad_security(self):
        self.assertRaises(ValueError, sensors.build_wifi_config, {"essid": "x", "security": "bad"})

    def test_rejects_line_injection_and_bad_port(self):
        cases = {
            "radius_port=0": dict(ENTERPRISE_REQUEST, radius_port=0),
            "radius_port=65536": dict(ENTERPRISE_REQUEST, radius_port=65536),
            "radius_port as string": dict(ENTERPRISE_REQUEST, radius_port="1812"),
            "radius_server with newline": dict(ENTERPRISE_REQUEST, radius_server="203.0.113.9\nwireless.1.extra=1"),
            "radius_secret with newline": dict(ENTERPRISE_REQUEST, radius_secret="secret\nwireless.1.x=1"),
            "personal essid with newline": {"essid": "home\nwireless.1.x=1", "security": "wpa2aes"},
            "personal passphrase with newline": {
                "essid": "home",
                "security": "wpa2aes",
                "passphrase": "pass\nwireless.1.x=1",
            },
        }
        for name, request in cases.items():
            with self.subTest(case=name):
                self.assertRaises(ValueError, sensors.build_wifi_config, request)

    def test_secret_absent_from_error_message(self):
        with self.assertRaises(ValueError) as cm:
            sensors.build_wifi_config(dict(ENTERPRISE_REQUEST, radius_port=0))
        self.assertNotIn(RADIUS_SECRET, str(cm.exception))


class TestWebshell(unittest.TestCase):
    def test_disabled(self):
        with self.assertRaises(network_tools.NetworkToolError) as cm:
            network_tools.open_webshell({}, serial_registry(), MAC)
        self.assertEqual(cm.exception.status, 403)
        self.assertEqual(cm.exception.code, "disabled")

    def test_connects_to_stored_address(self):
        fc = FakeConnect()
        result = network_tools.open_webshell({"allow_webshell": True}, serial_registry(), MAC, connect=fc)
        self.assertEqual(fc.calls, [(HOST, network_tools.WEBSHELL_PORT)])
        self.assertTrue(fc.sockets[0].closed)
        self.assertEqual(result, {"host": HOST, "port": network_tools.WEBSHELL_PORT, "protocol": "telnet"})

    def test_not_adopted(self):
        with self.assertRaises(network_tools.NetworkToolError) as cm:
            network_tools.open_webshell({"allow_webshell": True}, DeviceRegistry(), MAC)
        self.assertEqual(cm.exception.status, 404)
        self.assertEqual(cm.exception.code, "not_adopted")

    def test_not_serial(self):
        with self.assertRaises(network_tools.NetworkToolError) as cm:
            network_tools.open_webshell({"allow_webshell": True}, other_registry("M2M"), OTHER_MAC)
        self.assertEqual(cm.exception.status, 409)
        self.assertEqual(cm.exception.code, "not_serial")

    def test_no_address(self):
        with self.assertRaises(network_tools.NetworkToolError) as cm:
            network_tools.open_webshell({"allow_webshell": True}, no_address_registry(), MAC)
        self.assertEqual(cm.exception.status, 409)
        self.assertEqual(cm.exception.code, "no_address")

    def test_connect_failure_propagates(self):
        def unreachable(host, port):
            raise OSError("unreachable")

        with self.assertRaises(OSError):
            network_tools.open_webshell({"allow_webshell": True}, serial_registry(), MAC, connect=unreachable)


class TestBrowserSsh(unittest.TestCase):
    def test_disabled(self):
        with self.assertRaises(network_tools.NetworkToolError) as cm:
            network_tools.start_browser_ssh({}, serial_registry(), MAC)
        self.assertEqual(cm.exception.status, 403)
        self.assertEqual(cm.exception.code, "disabled")

    def test_connects(self):
        fc = FakeConnect()
        result = network_tools.start_browser_ssh({"allow_browser_ssh": True}, serial_registry(), MAC, connect=fc)
        self.assertEqual(fc.calls, [(HOST, 22)])
        self.assertTrue(fc.sockets[0].closed)
        self.assertEqual(result, {"host": HOST, "port": 22})

    def test_connect_failure_propagates(self):
        def unreachable(host, port):
            raise OSError("unreachable")

        with self.assertRaises(OSError):
            network_tools.start_browser_ssh({"allow_browser_ssh": True}, serial_registry(), MAC, connect=unreachable)


class TestUpnp(unittest.TestCase):
    def test_disabled(self):
        with self.assertRaises(network_tools.NetworkToolError) as cm:
            network_tools.upnp_announce({})
        self.assertEqual(cm.exception.status, 403)
        self.assertEqual(cm.exception.code, "disabled")

    def test_product_has_no_version(self):
        result = network_tools.upnp_announce({"allow_upnp": True})
        self.assertEqual(result, {"product": "mFi Server"})
        self.assertFalse(any(ch.isdigit() for ch in result["product"]))


class TestGuest(unittest.TestCase):
    def test_disabled(self):
        with self.assertRaises(network_tools.NetworkToolError) as cm:
            network_tools.guest_portal({})
        self.assertEqual(cm.exception.status, 403)
        self.assertEqual(cm.exception.code, "disabled")

    def test_rate_limited(self):
        lim = FakeLimiter(blocked=True)
        with self.assertRaises(network_tools.NetworkToolError) as cm:
            network_tools.guest_portal({"allow_guest_page": True}, lim, "c1")
        self.assertEqual(cm.exception.status, 429)
        self.assertEqual(cm.exception.code, "rate_limited")
        self.assertEqual(lim.hits, [])

    def test_enabled_counts(self):
        lim = FakeLimiter()
        res = network_tools.guest_portal({"allow_guest_page": True}, lim, "c1")
        self.assertEqual(res, {"product": "mFi Server", "page": "guest"})
        self.assertEqual(lim.hits, ["c1"])


if __name__ == "__main__":
    unittest.main()
