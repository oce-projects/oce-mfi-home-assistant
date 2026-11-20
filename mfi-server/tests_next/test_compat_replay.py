"""Replay bench tests: the synthetic compatibility fixtures of EPIC-01b.

Run with the suite of mfi-server, so that tests_next is importable:
    python3 -m unittest discover -s mfi-server/tests_next -t mfi-server -v

Offline and standard library only. The fixtures are read, never written.
"""
from __future__ import annotations

import pathlib
import re
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from compat_replay import load_fixtures, validate_fixture, resolve_handler, is_pending, KNOWN_EPICS
from mfi_server_next import devices, firmware, inform, sensors, serial

REQUIRED_CODES = frozenset({"R-ADOPT", "R-POWER", "R-FORGET", "R-RESET", "R-UPDATE", "R-MPORT", "R-SERIAL", "R-MPOWER", "R-DISC"})
ALLOWED_IP = "192.168.1.20"
MAC_RE = re.compile(r"(?i)\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b")
PRIVATE_IP_RE = re.compile(r"(?<![\d.])(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3})(?!\d|\.\d)")


def good_fixture() -> dict:
    """A valid in-memory fixture; the tests break a copy of it."""
    return {
        "code": "R-POWER",
        "source": "synthetic",
        "owner_epic": "EPIC-02",
        "handler": "mfi_server_next.inform.handle_inform",
        "request": {"mac": "002722000001", "ip": ALLOWED_IP},
        "expected": {"status": 200, "keys": {"_type": "str"}},
    }


class TestFixtureFormat(unittest.TestCase):
    """CA1: every fixture follows the format of the README."""

    def test_fixtures_are_present(self):
        self.assertGreater(len(load_fixtures()), 0)

    def test_every_fixture_is_valid(self):
        for path, data in load_fixtures():
            with self.subTest(file=path.name):
                self.assertEqual(validate_fixture(data), [])

    def test_every_handler_resolves(self):
        for path, data in load_fixtures():
            with self.subTest(file=path.name):
                resolve_handler(data["handler"])


class TestPendingFixtures(unittest.TestCase):
    """CA2: a fixture whose handler is still a stub is PENDING, with its epic printed."""

    def test_pending_fixtures_name_their_epic(self):
        for path, data in load_fixtures():
            owner = data["owner_epic"]
            pending = is_pending(resolve_handler(data["handler"]))
            with self.subTest(file=path.name):
                if pending:
                    print(f"PENDING {path.name} -> {owner}")
                    self.assertIn(owner, KNOWN_EPICS)
                else:
                    print(f"IMPLEMENTED {path.name} -> {owner}")


class TestBrokenFixtures(unittest.TestCase):
    """CA3: a fixture without owner_epic or with a missing handler fails the checks."""

    def test_good_fixture_has_no_problems(self):
        self.assertEqual(validate_fixture(good_fixture()), [])

    def test_missing_owner_epic_is_rejected(self):
        broken = good_fixture()
        del broken["owner_epic"]
        problems = validate_fixture(broken)
        self.assertTrue(problems)
        self.assertIn("owner_epic", " ".join(problems))

    def test_unknown_owner_epic_is_rejected(self):
        broken = good_fixture()
        broken["owner_epic"] = "EPIC-99"
        self.assertTrue(validate_fixture(broken))

    def test_handler_without_module_is_rejected(self):
        broken = good_fixture()
        broken["handler"] = "handle_inform"
        self.assertTrue(validate_fixture(broken))

    def test_missing_handler_does_not_resolve(self):
        with self.assertRaises((ModuleNotFoundError, AttributeError)):
            resolve_handler("mfi_server_next.nope.nope")

    def test_handler_outside_package_is_rejected(self):
        broken = good_fixture()
        broken["handler"] = "os.system"
        problems = validate_fixture(broken)
        self.assertTrue(problems)
        self.assertIn("mfi_server_next", " ".join(problems))
        with self.assertRaises(ValueError):
            resolve_handler("os.system")

    def test_unknown_code_and_source_are_both_reported(self):
        broken = good_fixture()
        broken["code"] = "R-NOPE"
        broken["source"] = "live"
        self.assertEqual(len(validate_fixture(broken)), 2)

    def test_expected_must_be_an_object(self):
        for value in (None, [], "200"):
            with self.subTest(expected=value):
                broken = good_fixture()
                broken["expected"] = value
                self.assertTrue(validate_fixture(broken))


class TestNoPrivateData(unittest.TestCase):
    """CA4: the raw text of the fixtures has no MAC with colons and no foreign private IPv4."""

    def test_no_mac_with_colons(self):
        for path, _ in load_fixtures():
            text = path.read_text(encoding="utf-8")
            with self.subTest(file=path.name):
                self.assertEqual(MAC_RE.findall(text), [])

    def test_no_private_ip_other_than_factory_default(self):
        for path, _ in load_fixtures():
            text = path.read_text(encoding="utf-8")
            found = [m.group(0) for m in PRIVATE_IP_RE.finditer(text) if m.group(0) != ALLOWED_IP]
            with self.subTest(file=path.name):
                self.assertEqual(found, [])


class TestCoverage(unittest.TestCase):
    """The fixtures cover the recorded routes that the owner epics implement."""

    def test_codes_cover_the_required_routes(self):
        codes = {data["code"] for _, data in load_fixtures()}
        self.assertEqual(REQUIRED_CODES - codes, set())


class TestEpic02Replay(unittest.TestCase):
    """CA7: the EPIC-01b fixtures owned by EPIC-02 are implemented and replay with the expected answer."""

    TYPES = {"str": str, "dict": dict, "int": int}

    @staticmethod
    def _replay(data):
        handler = data["handler"]
        request = data["request"]
        if handler.endswith(".build_upgrade"):
            return firmware.build_upgrade(request.get("model"))
        if handler.endswith(".handle_inform"):
            return inform.handle_inform(request, devices.DeviceRegistry())
        raise AssertionError(f"no replay for handler {handler!r}")

    def test_epic02_fixtures_are_not_pending_and_replay(self):
        replayed = 0
        for path, data in load_fixtures():
            if data["owner_epic"] != "EPIC-02":
                continue
            replayed += 1
            with self.subTest(file=path.name):
                self.assertFalse(is_pending(resolve_handler(data["handler"])))
                result = self._replay(data)
                self.assertIsInstance(result, dict)
                for name, kind in data["expected"].get("keys", {}).items():
                    self.assertIn(name, result)
                    self.assertIsInstance(result[name], self.TYPES[kind])
                for name, value in data["expected"].get("values", {}).items():
                    self.assertEqual(result[name], value)
        self.assertGreater(replayed, 0)


class TestEpic04Replay(unittest.TestCase):
    """CA6: the EPIC-01b fixtures owned by EPIC-04 are implemented and replay with the expected answer."""

    TYPES = {"str": str, "dict": dict, "int": int}

    @staticmethod
    def _replay(data):
        handler = data["handler"]
        request = data["request"]
        if handler.endswith(".build_ser2net_cfg"):
            return serial.build_ser2net_cfg(request)
        if handler.endswith(".build_port_config"):
            return sensors.build_port_config(request)
        raise AssertionError(f"no replay for handler {handler!r}")

    def test_epic04_fixtures_are_not_pending_and_replay(self):
        replayed = 0
        for path, data in load_fixtures():
            if data["owner_epic"] != "EPIC-04":
                continue
            replayed += 1
            with self.subTest(file=path.name):
                self.assertFalse(is_pending(resolve_handler(data["handler"])))
                result = self._replay(data)
                self.assertIsInstance(result, dict)
                for name, kind in data["expected"].get("keys", {}).items():
                    self.assertIn(name, result)
                    self.assertIsInstance(result[name], self.TYPES[kind])
                for name, value in data["expected"].get("values", {}).items():
                    self.assertEqual(result[name], value)
        self.assertGreater(replayed, 0)


if __name__ == "__main__":
    unittest.main()
