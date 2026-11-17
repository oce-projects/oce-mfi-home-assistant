"""Offline tests of mfi_server.ssh_adopt: no ssh, no network.

A fake runner records the arguments and the environment it receives.
"""
from __future__ import annotations

import os
import stat
import subprocess
import unittest

from mfi_server import ssh_adopt
from mfi_server.ssh_adopt import SshError

DEVICE_IP = "192.168.1.20"
USERNAME = "ubnt"
PASSWORD = "test-password"
AUTHKEY = "0123456789abcdef0123456789abcdef"
URL = "http://mfi-server:6080/inform"
DEFAULT_OPTIONS = (
    "KexAlgorithms=+diffie-hellman-group1-sha1,diffie-hellman-group14-sha1;"
    "HostKeyAlgorithms=+ssh-rsa,ssh-dss;Ciphers=+aes128-cbc,3des-cbc"
)


class FakeRunner:
    """Records each call; raises the given error or returns the given result."""

    def __init__(self, result=None, error=None, inspect=None):
        self.result = result
        self.error = error
        self.inspect = inspect
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((list(command), kwargs))
        if self.inspect is not None:
            self.inspect(kwargs["env"])
        if self.error is not None:
            raise self.error
        return self.result


def completed(returncode, stderr=b""):
    return subprocess.CompletedProcess(["ssh"], returncode, stdout=b"", stderr=stderr)


def sample_command():
    options = ssh_adopt.parse_extra_options(DEFAULT_OPTIONS)
    remote = ssh_adopt.set_adopt_remote(URL, AUTHKEY)
    return ssh_adopt.build_ssh_command(DEVICE_IP, USERNAME, options, remote)


class TestBuildSshCommand(unittest.TestCase):
    def test_exact_command(self):
        command = sample_command()
        expected = [
            "ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ConnectTimeout=5",
            "-o", "NumberOfPasswordPrompts=1",
            "-o", "PubkeyAuthentication=no",
            "-o", "PreferredAuthentications=password,keyboard-interactive",
            "-o", "KexAlgorithms=+diffie-hellman-group1-sha1,diffie-hellman-group14-sha1",
            "-o", "HostKeyAlgorithms=+ssh-rsa,ssh-dss",
            "-o", "Ciphers=+aes128-cbc,3des-cbc",
            "-l", "ubnt", "192.168.1.20",
            "/usr/bin/syswrapper.sh", "set-adopt", URL, AUTHKEY,
        ]
        self.assertEqual(command, expected)

    def test_host_with_option_prefix_is_rejected(self):
        options = ssh_adopt.parse_extra_options(DEFAULT_OPTIONS)
        remote = ssh_adopt.set_adopt_remote(URL, AUTHKEY)
        with self.assertRaises(SshError) as cm:
            ssh_adopt.build_ssh_command("-oProxyCommand=x", USERNAME, options, remote)
        self.assertEqual(cm.exception.code, "invalid_input")

    def test_host_name_is_rejected(self):
        options = ssh_adopt.parse_extra_options(DEFAULT_OPTIONS)
        remote = ssh_adopt.set_adopt_remote(URL, AUTHKEY)
        with self.assertRaises(SshError) as cm:
            ssh_adopt.build_ssh_command("example.com", USERNAME, options, remote)
        self.assertEqual(cm.exception.code, "invalid_input")

    def test_bad_username_is_rejected(self):
        remote = ssh_adopt.set_adopt_remote(URL, AUTHKEY)
        with self.assertRaises(SshError) as cm:
            ssh_adopt.build_ssh_command(DEVICE_IP, "ubnt;id", [], remote)
        self.assertEqual(cm.exception.code, "invalid_input")

    def test_option_not_from_parser_is_rejected(self):
        remote = ssh_adopt.set_adopt_remote(URL, AUTHKEY)
        with self.assertRaises(SshError) as cm:
            ssh_adopt.build_ssh_command(DEVICE_IP, USERNAME, ["ProxyCommand=x"], remote)
        self.assertEqual(cm.exception.code, "invalid_input")


class TestParseExtraOptions(unittest.TestCase):
    def test_rejects_proxy_command(self):
        with self.assertRaises(ValueError):
            ssh_adopt.parse_extra_options("ProxyCommand=nc x 22")

    def test_rejects_local_command(self):
        with self.assertRaises(ValueError):
            ssh_adopt.parse_extra_options("LocalCommand=id")

    def test_accepts_default_with_three_entries(self):
        options = ssh_adopt.parse_extra_options(DEFAULT_OPTIONS)
        self.assertEqual(len(options), 3)
        self.assertEqual(options[2], "Ciphers=+aes128-cbc,3des-cbc")

    def test_skips_empty_entries(self):
        self.assertEqual(ssh_adopt.parse_extra_options("Ciphers=3des-cbc; ;"), ["Ciphers=3des-cbc"])

    def test_empty_text_gives_no_options(self):
        self.assertEqual(ssh_adopt.parse_extra_options(""), [])


class TestSetAdoptRemote(unittest.TestCase):
    def test_uppercase_authkey_is_rejected(self):
        with self.assertRaises(SshError) as cm:
            ssh_adopt.set_adopt_remote(URL, "0123456789ABCDEF0123456789ABCDEF")
        self.assertEqual(cm.exception.code, "invalid_input")

    def test_non_hex_authkey_is_rejected(self):
        with self.assertRaises(SshError) as cm:
            ssh_adopt.set_adopt_remote(URL, "g" * 32)
        self.assertEqual(cm.exception.code, "invalid_input")

    def test_url_without_inform_is_rejected(self):
        with self.assertRaises(SshError) as cm:
            ssh_adopt.set_adopt_remote("http://mfi-server:6080/", AUTHKEY)
        self.assertEqual(cm.exception.code, "invalid_input")

    def test_valid_input_gives_remote_list(self):
        self.assertEqual(
            ssh_adopt.set_adopt_remote(URL, AUTHKEY),
            ["/usr/bin/syswrapper.sh", "set-adopt", URL, AUTHKEY],
        )


class TestRunSsh(unittest.TestCase):
    def test_password_is_only_in_environment(self):
        runner = FakeRunner(result=completed(0))
        ssh_adopt.run_ssh(sample_command(), PASSWORD, runner=runner)
        command, kwargs = runner.calls[0]
        for item in command:
            self.assertNotIn(PASSWORD, item)
        env = kwargs["env"]
        self.assertEqual(env["MFI_SSH_PASSWORD"], PASSWORD)
        self.assertEqual(env["SSH_ASKPASS_REQUIRE"], "force")
        self.assertIs(kwargs["capture_output"], True)
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)

    def test_askpass_script_is_private_while_running(self):
        seen = {}

        def inspect(env):
            seen["mode"] = stat.S_IMODE(os.stat(env["SSH_ASKPASS"]).st_mode)
            with open(env["SSH_ASKPASS"], encoding="utf-8") as handle:
                seen["body"] = handle.read()

        runner = FakeRunner(result=completed(0), inspect=inspect)
        ssh_adopt.run_ssh(sample_command(), PASSWORD, runner=runner)
        self.assertEqual(seen["mode"], 0o700)
        self.assertIn("MFI_SSH_PASSWORD", seen["body"])
        self.assertNotIn(PASSWORD, seen["body"])

    def test_script_folder_is_removed_after_success(self):
        runner = FakeRunner(result=completed(0))
        ssh_adopt.run_ssh(sample_command(), PASSWORD, runner=runner)
        script = runner.calls[0][1]["env"]["SSH_ASKPASS"]
        self.assertFalse(os.path.exists(os.path.dirname(script)))

    def test_script_folder_is_removed_after_timeout(self):
        runner = FakeRunner(error=subprocess.TimeoutExpired(sample_command(), 20))
        with self.assertRaises(SshError) as cm:
            ssh_adopt.run_ssh(sample_command(), PASSWORD, runner=runner)
        self.assertEqual(cm.exception.code, "timeout")
        script = runner.calls[0][1]["env"]["SSH_ASKPASS"]
        self.assertFalse(os.path.exists(os.path.dirname(script)))

    def test_script_folder_is_removed_after_other_exception(self):
        runner = FakeRunner(error=RuntimeError("boom"))
        with self.assertRaises(RuntimeError):
            ssh_adopt.run_ssh(sample_command(), PASSWORD, runner=runner)
        script = runner.calls[0][1]["env"]["SSH_ASKPASS"]
        self.assertFalse(os.path.exists(os.path.dirname(script)))

    def test_errors_are_mapped(self):
        cases = [
            ("ssh_not_installed", FakeRunner(error=FileNotFoundError("ssh"))),
            ("timeout", FakeRunner(error=subprocess.TimeoutExpired(["ssh"], 20))),
            ("connection_failed", FakeRunner(result=completed(255))),
            ("command_failed", FakeRunner(result=completed(1))),
        ]
        for code, runner in cases:
            with self.subTest(code=code):
                with self.assertRaises(SshError) as cm:
                    ssh_adopt.run_ssh(sample_command(), PASSWORD, runner=runner)
                self.assertEqual(cm.exception.code, code)

    def test_permission_denied_is_auth_failed(self):
        runner = FakeRunner(result=completed(255, stderr=b"ubnt@192.168.1.20: Permission denied (password)."))
        with self.assertRaises(SshError) as cm:
            ssh_adopt.run_ssh(sample_command(), PASSWORD, runner=runner)
        self.assertEqual(cm.exception.code, "auth_failed")

    def test_other_255_stderr_is_connection_failed(self):
        runner = FakeRunner(result=completed(255, stderr=b"ssh: connect to host port 22: Connection refused"))
        with self.assertRaises(SshError) as cm:
            ssh_adopt.run_ssh(sample_command(), PASSWORD, runner=runner)
        self.assertEqual(cm.exception.code, "connection_failed")

    def test_success_returns_none(self):
        runner = FakeRunner(result=completed(0))
        self.assertIsNone(ssh_adopt.run_ssh(sample_command(), PASSWORD, runner=runner))

    def test_log_hides_password_and_authkey(self):
        stderr = b"Warning: test-password accepted\nkey aabbccddeeff00112233445566778899 seen\n"
        runner = FakeRunner(result=completed(0, stderr=stderr))
        with self.assertLogs("mfi_server.ssh_adopt", level="DEBUG") as logs:
            ssh_adopt.run_ssh(sample_command(), PASSWORD, runner=runner)
        text = "\n".join(logs.output)
        self.assertNotIn(PASSWORD, text)
        self.assertNotIn("aabbccddeeff00112233445566778899", text)
        self.assertIn("***", text)

    def test_log_keeps_only_last_300_lines(self):
        stderr = "\n".join(f"row-{i:03d}" for i in range(305)).encode("utf-8")
        runner = FakeRunner(result=completed(0, stderr=stderr))
        with self.assertLogs("mfi_server.ssh_adopt", level="DEBUG") as logs:
            ssh_adopt.run_ssh(sample_command(), PASSWORD, runner=runner)
        text = "\n".join(logs.output)
        self.assertNotIn("row-004", text)
        self.assertIn("row-005", text)
        self.assertIn("row-304", text)


if __name__ == "__main__":
    unittest.main()
