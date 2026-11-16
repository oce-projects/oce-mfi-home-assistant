"""Tests of adoption.py: adoption of factory devices and re-pointing, with fake ssh runner, store, scanner and settings.

No real ssh, no network: the runner is a fake that records the command.
"""
from __future__ import annotations

import re
import subprocess
import unittest

from mfi_server.adoption import Adoption, FACTORY_PASSWORD, FACTORY_USERNAME
from mfi_server.ssh_adopt import SshError

FACTORY_MAC = "02aabbccdd02"
ADOPTED_MAC = "02aabbccdd01"
UNKNOWN_MAC = "02aabbccdd09"
DEVICE_IP = "192.168.1.20"
DEVICE_AUTHKEY = "0123456789abcdef0123456789abcdef"
SSH_PASSWORD = "test-password"
AUTHKEY_RE = re.compile(r"[0-9a-f]{32}")


class FakeScanner:
    """Discovery stand-in: last_results() returns the prepared list."""

    def __init__(self, results):
        self.results = results

    def last_results(self):
        return [dict(item) for item in self.results]


class FakeStore:
    """Device store stand-in: keeps the records and every upsert, in order."""

    def __init__(self, records=None):
        self.records = {mac: dict(rec) for mac, rec in (records or {}).items()}
        self.saved = []

    def get(self, mac):
        rec = self.records.get(mac)
        return None if rec is None else dict(rec)

    def upsert(self, rec):
        self.records[rec["mac"]] = dict(rec)
        self.saved.append(dict(rec))


class FakeSettings:
    """Settings stand-in with the fields adoption.py reads."""

    def __init__(self, server_address="", device_ssh_username="", device_ssh_password="", ssh_extra_options=""):
        self.server_address = server_address
        self.inform_port = 6080
        self.device_ssh_username = device_ssh_username
        self.device_ssh_password = device_ssh_password
        self.ssh_extra_options = ssh_extra_options


class FakeRunner:
    """Replaces subprocess.run: records the command and the environment, returns a fixed return code."""

    def __init__(self, returncode=0, store=None):
        self.returncode = returncode
        self.store = store
        self.command = None
        self.env = None
        self.calls = 0
        self.saved_before_call = None

    def __call__(self, command, **kwargs):
        self.calls += 1
        self.command = list(command)
        self.env = kwargs.get("env")
        if self.store is not None:
            self.saved_before_call = len(self.store.saved)
        return subprocess.CompletedProcess(command, self.returncode)


class TestAdopt(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.runner = FakeRunner(store=self.store)
        self.scanner = FakeScanner(
            [{"mac": FACTORY_MAC, "ip": DEVICE_IP, "model": "M2M", "is_default": True}]
        )
        self.adoption = Adoption(
            FakeSettings(),
            self.store,
            self.scanner,
            runner=self.runner,
            address_for=lambda ip: DEVICE_IP,
        )

    def test_adopt_saves_adopting_record_before_ssh(self):
        self.adoption.adopt(FACTORY_MAC)
        first = self.store.saved[0]
        self.assertEqual(first["mac"], FACTORY_MAC)
        self.assertEqual(first["state"], "adopting")
        self.assertIsNotNone(AUTHKEY_RE.fullmatch(first["authkey"]))
        self.assertEqual(self.runner.saved_before_call, 1)

    def test_adopt_sends_set_adopt_with_factory_user(self):
        self.adoption.adopt(FACTORY_MAC)
        command = self.runner.command
        authkey = self.store.saved[0]["authkey"]
        self.assertIn("/usr/bin/syswrapper.sh", command)
        self.assertIn("set-adopt", command)
        self.assertIn("http://192.168.1.20:6080/inform", command)
        self.assertIn(authkey, command)
        self.assertEqual(command[-4:], ["/usr/bin/syswrapper.sh", "set-adopt", "http://192.168.1.20:6080/inform", authkey])
        index = command.index("-l")
        self.assertEqual(command[index : index + 2], ["-l", FACTORY_USERNAME])
        # "ubnt" is also the factory user name, so it appears once: as the user, never as an argument of the password.
        self.assertEqual(command.count(FACTORY_PASSWORD), 1)
        self.assertEqual(self.runner.env["MFI_SSH_PASSWORD"], FACTORY_PASSWORD)

    def test_adopt_unknown_mac_is_lookup_error(self):
        with self.assertRaises(LookupError):
            self.adoption.adopt(UNKNOWN_MAC)
        self.assertEqual(self.store.saved, [])
        self.assertEqual(self.runner.calls, 0)

    def test_adopt_device_without_ip_is_lookup_error(self):
        self.scanner.results = [{"mac": FACTORY_MAC, "model": "M2M", "is_default": True}]
        with self.assertRaises(LookupError):
            self.adoption.adopt(FACTORY_MAC)
        self.assertEqual(self.store.saved, [])

    def test_adopt_not_factory_default_is_permission_error(self):
        self.scanner.results = [{"mac": FACTORY_MAC, "ip": DEVICE_IP, "model": "M2M", "is_default": False}]
        with self.assertRaises(PermissionError):
            self.adoption.adopt(FACTORY_MAC)
        self.assertEqual(self.store.saved, [])
        self.assertEqual(self.runner.calls, 0)

    def test_ssh_failure_marks_adopt_failed_and_raises(self):
        self.runner.returncode = 255
        with self.assertRaises(SshError) as ctx:
            self.adoption.adopt(FACTORY_MAC)
        self.assertEqual(ctx.exception.code, "connection_failed")
        self.assertEqual(len(self.store.saved), 2)
        self.assertEqual(self.store.saved[-1]["state"], "adopt_failed")
        self.assertEqual(self.store.records[FACTORY_MAC]["state"], "adopt_failed")


class TestRepoint(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore(
            {
                ADOPTED_MAC: {
                    "mac": ADOPTED_MAC,
                    "model": "M2S",
                    "name": "M2S ff01",
                    "authkey": DEVICE_AUTHKEY,
                    "ports": [],
                    "state": "connected",
                    "last_seen_ms": 0,
                }
            }
        )
        self.scanner = FakeScanner([{"mac": ADOPTED_MAC, "ip": DEVICE_IP, "model": "M2S", "is_default": False}])
        self.runner = FakeRunner()
        self.settings = FakeSettings(
            server_address=DEVICE_IP,
            device_ssh_username="test-user",
            device_ssh_password=SSH_PASSWORD,
        )
        self.adoption = Adoption(
            self.settings,
            self.store,
            self.scanner,
            runner=self.runner,
            address_for=self._address_must_not_be_used,
        )

    @staticmethod
    def _address_must_not_be_used(ip):
        raise AssertionError("server_address is set: address_for must not be called")

    def test_repoint_uses_stored_authkey_and_credentials(self):
        self.adoption.repoint(ADOPTED_MAC)
        command = self.runner.command
        self.assertIn(DEVICE_AUTHKEY, command)
        self.assertIn("http://192.168.1.20:6080/inform", command)
        index = command.index("-l")
        self.assertEqual(command[index : index + 2], ["-l", "test-user"])
        self.assertNotIn(SSH_PASSWORD, command)
        self.assertEqual(self.runner.env["MFI_SSH_PASSWORD"], SSH_PASSWORD)
        self.assertEqual(self.store.saved, [])

    def test_repoint_without_ssh_credentials_is_permission_error(self):
        for username, password in (("", SSH_PASSWORD), ("test-user", "")):
            with self.subTest(username=username, password=password):
                self.settings.device_ssh_username = username
                self.settings.device_ssh_password = password
                with self.assertRaises(PermissionError) as ctx:
                    self.adoption.repoint(ADOPTED_MAC)
                self.assertEqual(str(ctx.exception), "ssh_credentials_not_set")
        self.assertEqual(self.runner.calls, 0)

    def test_repoint_unknown_mac_is_lookup_error(self):
        with self.assertRaises(LookupError):
            self.adoption.repoint(UNKNOWN_MAC)
        self.assertEqual(self.runner.calls, 0)


if __name__ == "__main__":
    unittest.main()
