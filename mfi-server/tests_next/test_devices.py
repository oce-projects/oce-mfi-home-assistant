"""Tests for mfi_server_next.devices: the device registry and the SSH adoption.

The SSH runner is always a fake: no network, no real ssh. Each test works in its own
temporary folder. Standard library only.
"""
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from mfi_server_next import devices
from mfi_server_next.store import Store

MAC = "002722000001"
OTHER_AUTHKEY = "fedcba9876543210fedcba9876543210"
IP = "192.168.1.20"
INFORM_URL = "http://mfi-server:6080/inform"
AUTHKEY = "0123456789abcdef0123456789abcdef"
ADMIN_USER = "mfiadmin"
ADMIN_PASSWORD = "Adm1n-Secret-pw"
PERMISSION_DENIED = b"Permission denied, please try again.\n"


class FakeResult:
    """What subprocess.run returns: the exit code and the stderr bytes."""

    def __init__(self, returncode, stderr=b""):
        self.returncode = returncode
        self.stderr = stderr


class FakeRunner:
    """Stand-in for subprocess.run: records each call and answers with the scripted results in order."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((list(command), kwargs))
        if not self.answers:
            raise AssertionError("unexpected ssh call")
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer


class FakeClock:
    """A monotonic clock that the test moves by hand."""

    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


class TestSetAdopt(unittest.TestCase):
    def adopt(self, runner, **overrides):
        options = {
            "admin_user": ADMIN_USER,
            "admin_password": ADMIN_PASSWORD,
            "runner": runner,
        }
        options.update(overrides)
        return devices.set_adopt(IP, INFORM_URL, AUTHKEY, **options)

    def test_login_retried_once_with_factory_credentials(self):
        runner = FakeRunner(FakeResult(255, PERMISSION_DENIED), FakeResult(0))
        self.assertEqual(self.adopt(runner), "factory")
        self.assertEqual(len(runner.calls), 2)
        first, second = runner.calls[0][0], runner.calls[1][0]
        self.assertEqual(first[first.index("-l") + 1], ADMIN_USER)
        self.assertEqual(second[second.index("-l") + 1], "ubnt")

    def test_admin_credentials_accepted_without_retry(self):
        runner = FakeRunner(FakeResult(0))
        self.assertEqual(self.adopt(runner), "admin")
        self.assertEqual(len(runner.calls), 1)
        command = runner.calls[0][0]
        self.assertEqual(command[command.index("-l") + 1], ADMIN_USER)

    def test_both_logins_refused_raises(self):
        runner = FakeRunner(FakeResult(255, PERMISSION_DENIED), FakeResult(255, PERMISSION_DENIED))
        with self.assertRaises(devices.AdoptionError):
            self.adopt(runner)
        self.assertEqual(len(runner.calls), 2)

    def test_other_failure_is_not_retried(self):
        runner = FakeRunner(FakeResult(1, b"syswrapper failed\n"))
        with self.assertRaises(devices.AdoptionError):
            self.adopt(runner)
        self.assertEqual(len(runner.calls), 1)

    def test_password_never_in_arguments(self):
        runner = FakeRunner(FakeResult(255, PERMISSION_DENIED), FakeResult(0))
        self.adopt(runner)
        for command, kwargs in runner.calls:
            for argument in command:
                self.assertNotIn(ADMIN_PASSWORD, argument)
        self.assertEqual(runner.calls[0][1]["env"]["MFI_SSH_PASSWORD"], ADMIN_PASSWORD)

    def test_invalid_authkey_does_not_call_runner(self):
        runner = FakeRunner()
        with self.assertRaises(devices.AdoptionError):
            devices.set_adopt(IP, INFORM_URL, "xyz", admin_user=ADMIN_USER, admin_password=ADMIN_PASSWORD, runner=runner)
        self.assertEqual(runner.calls, [])

    def test_invalid_ip_and_url_are_rejected_before_ssh(self):
        bad_ips = ["10.0.0", "mfi-server", "1.2.3.400", 3232235796]
        bad_urls = [
            "https://mfi-server:6080/inform",
            "http://mfi-server/inform",
            "http://mfi-server:70000/inform",
            "http://mfi-server:6080/inform;rm",
        ]
        for ip in bad_ips:
            with self.subTest(ip=ip):
                runner = FakeRunner()
                with self.assertRaises(devices.AdoptionError):
                    devices.set_adopt(ip, INFORM_URL, AUTHKEY, admin_user=ADMIN_USER, admin_password=ADMIN_PASSWORD, runner=runner)
                self.assertEqual(runner.calls, [])
        for url in bad_urls:
            with self.subTest(url=url):
                runner = FakeRunner()
                with self.assertRaises(devices.AdoptionError):
                    devices.set_adopt(IP, url, AUTHKEY, admin_user=ADMIN_USER, admin_password=ADMIN_PASSWORD, runner=runner)
                self.assertEqual(runner.calls, [])

    def test_option_like_username_is_rejected(self):
        runner = FakeRunner()
        with self.assertRaises(devices.AdoptionError):
            self.adopt(runner, admin_user="-oProxyCommand=x")
        self.assertEqual(runner.calls, [])

    def test_empty_admin_password_is_rejected(self):
        runner = FakeRunner()
        with self.assertRaises(devices.AdoptionError):
            self.adopt(runner, admin_password="")
        self.assertEqual(runner.calls, [])

    def test_base_options_and_timeout_are_set(self):
        runner = FakeRunner(FakeResult(0))
        self.adopt(runner)
        command, kwargs = runner.calls[0]
        for option in ("StrictHostKeyChecking=no", "UserKnownHostsFile=/dev/null", "ConnectTimeout=5", "NumberOfPasswordPrompts=1"):
            self.assertIn(option, command)
        self.assertEqual(kwargs["timeout"], 20)

    def test_extra_options_pass_through_unchanged(self):
        extra = ("KexAlgorithms=+diffie-hellman-group1-sha1", "Ciphers=+aes128-cbc")
        runner = FakeRunner(FakeResult(0))
        self.adopt(runner, ssh_extra_options=extra)
        command = runner.calls[0][0]
        for option in extra:
            self.assertEqual(command[command.index(option) - 1], "-o")

    def test_timeout_becomes_adoption_error_and_helper_is_removed(self):
        runner = FakeRunner(subprocess.TimeoutExpired(cmd="ssh", timeout=20))
        with self.assertRaises(devices.AdoptionError):
            self.adopt(runner)
        script = runner.calls[0][1]["env"]["SSH_ASKPASS"]
        self.assertFalse(os.path.exists(script))
        self.assertFalse(os.path.exists(os.path.dirname(script)))

    def test_missing_ssh_becomes_adoption_error(self):
        runner = FakeRunner(FileNotFoundError("ssh"))
        with self.assertRaises(devices.AdoptionError):
            self.adopt(runner)
        self.assertEqual(len(runner.calls), 1)

    def test_helper_is_removed_after_success(self):
        runner = FakeRunner(FakeResult(0))
        self.adopt(runner)
        script = runner.calls[0][1]["env"]["SSH_ASKPASS"]
        self.assertFalse(os.path.exists(os.path.dirname(script)))


class TestDeviceRegistry(unittest.TestCase):
    def test_adopt_then_get_returns_adopted_record(self):
        registry = devices.DeviceRegistry()
        registry.adopt(MAC, x_authkey=AUTHKEY, cfgversion="c" * 16, portversion="d" * 16, model="M2M", ip=IP)
        record = registry.get(MAC)
        self.assertTrue(record["adopted"])
        self.assertEqual(record["state"], 7)
        self.assertEqual(record["x_authkey"], AUTHKEY)

    def test_add_creates_pending_record(self):
        registry = devices.DeviceRegistry()
        registry.add(MAC, model="P1E")
        record = registry.get(MAC)
        self.assertFalse(record["adopted"])
        self.assertEqual(record["state"], 2)
        self.assertIsNone(record["x_authkey"])

    def test_forget_removes_record(self):
        registry = devices.DeviceRegistry()
        registry.adopt(MAC, x_authkey=AUTHKEY, cfgversion="c" * 16, portversion="d" * 16)
        registry.forget(MAC)
        self.assertIsNone(registry.get(MAC))

    def test_factory_reset_removes_record(self):
        registry = devices.DeviceRegistry()
        registry.adopt(MAC, x_authkey=AUTHKEY, cfgversion="c" * 16, portversion="d" * 16)
        registry.factory_reset(MAC)
        self.assertIsNone(registry.get(MAC))

    def test_readopt_with_new_key_keeps_old_key_as_previous(self):
        registry = devices.DeviceRegistry()
        registry.adopt(MAC, x_authkey=AUTHKEY, cfgversion="c" * 16, portversion="d" * 16)
        registry.adopt(MAC, x_authkey=OTHER_AUTHKEY, cfgversion="e" * 16, portversion="f" * 16)
        record = registry.get(MAC)
        self.assertEqual(record["x_authkey"], OTHER_AUTHKEY)
        self.assertEqual(record["x_prev_authkey"], AUTHKEY)

    def test_invalid_mac_is_rejected(self):
        registry = devices.DeviceRegistry()
        with self.assertRaises(ValueError):
            registry.add("00272200000G")

    def test_get_returns_a_copy(self):
        registry = devices.DeviceRegistry()
        registry.adopt(MAC, x_authkey=AUTHKEY, cfgversion="c" * 16, portversion="d" * 16)
        copy = registry.get(MAC)
        copy["adopted"] = False
        self.assertTrue(registry.get(MAC)["adopted"])

    def test_state_unknown_connected_lost(self):
        clock = FakeClock(1000.0)
        registry = devices.DeviceRegistry(clock=clock)
        self.assertEqual(registry.state(MAC), "unknown")
        registry.seen(MAC)
        clock.now = 1000.0 + 120
        self.assertEqual(registry.state(MAC), "connected")
        clock.now = 1000.0 + 121
        self.assertEqual(registry.state(MAC), "lost")


class TestSave(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.store = Store.open(self.folder)
        self.addCleanup(self.store.close)

    def test_save_writes_devices_json_with_mode_0600(self):
        registry = devices.DeviceRegistry(store=self.store)
        registry.adopt(MAC, x_authkey=AUTHKEY, cfgversion="c" * 16, portversion="d" * 16)
        registry.save()
        path = self.folder / "devices.json"
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        rows = self.store.read_json("devices.json")
        self.assertEqual([row["mac"] for row in rows], [MAC])
        self.assertTrue(rows[0]["adopted"])

    def test_save_without_store_writes_nothing(self):
        registry = devices.DeviceRegistry()
        registry.adopt(MAC, x_authkey=AUTHKEY, cfgversion="c" * 16, portversion="d" * 16)
        registry.save()
        self.assertFalse((self.folder / "devices.json").exists())


if __name__ == "__main__":
    unittest.main()
