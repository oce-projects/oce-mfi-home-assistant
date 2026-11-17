"""Offline tests of mfi_server.ssh_adopt: no ssh filter, no network.

A fake runner records the arguments and the environment it receives. The names
of the local ssh are patched to None (no filter) for every test, except the
tests that set them. The one test that runs the real ssh only parses options (ssh -G).
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import unittest
from unittest import mock

from mfi_server import ssh_adopt
from mfi_server.ssh_adopt import SshError

DEVICE_IP = "192.168.1.20"
USERNAME = "ubnt"
PASSWORD = "test-password"
AUTHKEY = "0123456789abcdef0123456789abcdef"
URL = "http://mfi-server:6080/inform"
DEFAULT_OPTIONS = (
    "KexAlgorithms=+diffie-hellman-group1-sha1,diffie-hellman-group14-sha1;"
    "HostKeyAlgorithms=+ssh-rsa;Ciphers=+aes128-cbc,3des-cbc"
)
OLD_OPTIONS = (
    "KexAlgorithms=+diffie-hellman-group1-sha1,diffie-hellman-group14-sha1;"
    "HostKeyAlgorithms=+ssh-rsa,ssh-dss;Ciphers=+aes128-cbc,3des-cbc"
)
# Names a fake local ssh accepts ('ssh -Q' output, already split into sets).
FAKE_NAMES = {
    "kex": frozenset({"diffie-hellman-group14-sha1", "diffie-hellman-group14-sha256"}),
    "key": frozenset({"ssh-rsa", "ssh-ed25519"}),
    "sig": frozenset({"rsa-sha2-256"}),
    "cipher": frozenset({"aes128-cbc", "3des-cbc"}),
    "mac": frozenset({"hmac-sha1"}),
}
# Text printed by a fake 'ssh -Q <query>', one name per line.
QUERY_OUTPUT = {
    "cipher": "aes128-cbc\n3des-cbc\n",
    "key": "ssh-rsa\nssh-ed25519\n",
    "kex": "diffie-hellman-group14-sha1\n",
    "mac": "hmac-sha1\n",
    "sig": "rsa-sha2-256\n",
}
# The real reader, kept before setUpModule replaces it.
REAL_QUERY = ssh_adopt._query_local_algorithms


def setUpModule():
    """No test reads the real local ssh unless it says so: the names are None (no filter)."""
    patchers = [
        mock.patch.object(ssh_adopt, "_query_local_algorithms", return_value=None),
        mock.patch.dict(ssh_adopt._LOCAL_CACHE, clear=True),
    ]
    for patcher in patchers:
        patcher.start()
        unittest.addModuleCleanup(patcher.stop)


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
            "-o", "HostKeyAlgorithms=+ssh-rsa",
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

    def test_allowed_keys_have_a_query(self):
        self.assertEqual(set(ssh_adopt.KEY_QUERIES), set(ssh_adopt.ALLOWED_OPTION_KEYS))


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


class TestLocalAlgorithms(unittest.TestCase):
    def test_names_are_read_once(self):
        with mock.patch.object(ssh_adopt, "_query_local_algorithms", return_value=FAKE_NAMES) as query:
            with mock.patch.dict(ssh_adopt._LOCAL_CACHE, clear=True):
                first = ssh_adopt.local_algorithms()
                second = ssh_adopt.local_algorithms()
        self.assertEqual(query.call_count, 1)
        self.assertEqual(first, FAKE_NAMES)
        self.assertEqual(second, FAKE_NAMES)

    def test_every_query_is_run_and_split_into_names(self):
        def fake_ssh_query(command, **kwargs):
            self.assertEqual(command[:2], ["ssh", "-Q"])
            return subprocess.CompletedProcess(command, 0, stdout=QUERY_OUTPUT[command[2]].encode("utf-8"), stderr=b"")

        with mock.patch.object(ssh_adopt.subprocess, "run", side_effect=fake_ssh_query) as run:
            names = REAL_QUERY()
        self.assertEqual(run.call_count, len(ssh_adopt.ALGORITHM_QUERIES))
        self.assertEqual(names["key"], frozenset({"ssh-rsa", "ssh-ed25519"}))
        self.assertEqual(names["cipher"], frozenset({"aes128-cbc", "3des-cbc"}))

    def test_missing_ssh_gives_none_and_no_filter(self):
        with mock.patch.object(ssh_adopt.subprocess, "run", side_effect=FileNotFoundError("ssh")):
            self.assertIsNone(REAL_QUERY())

    def test_failed_query_gives_none_with_warning(self):
        failed = subprocess.CompletedProcess(["ssh"], 1, stdout=b"", stderr=b"")
        with mock.patch.object(ssh_adopt.subprocess, "run", return_value=failed):
            with self.assertLogs("mfi_server.ssh_adopt", level="WARNING"):
                self.assertIsNone(REAL_QUERY())

    def test_timed_out_query_gives_none_with_warning(self):
        with mock.patch.object(ssh_adopt.subprocess, "run", side_effect=subprocess.TimeoutExpired(["ssh"], 10)):
            with self.assertLogs("mfi_server.ssh_adopt", level="WARNING"):
                self.assertIsNone(REAL_QUERY())


class TestUsableOptions(unittest.TestCase):
    def test_default_options_lose_only_unknown_names(self):
        with mock.patch.object(ssh_adopt, "local_algorithms", return_value=FAKE_NAMES):
            usable = ssh_adopt.usable_options(ssh_adopt.parse_extra_options(DEFAULT_OPTIONS))
        self.assertEqual(
            usable,
            [
                "KexAlgorithms=+diffie-hellman-group14-sha1",
                "HostKeyAlgorithms=+ssh-rsa",
                "Ciphers=+aes128-cbc,3des-cbc",
            ],
        )

    def test_saved_old_options_lose_ssh_dss_in_the_command(self):
        remote = ssh_adopt.set_adopt_remote(URL, AUTHKEY)
        with mock.patch.object(ssh_adopt, "local_algorithms", return_value=FAKE_NAMES):
            command = ssh_adopt.build_ssh_command(
                DEVICE_IP, USERNAME, ssh_adopt.parse_extra_options(OLD_OPTIONS), remote
            )
        self.assertIn("HostKeyAlgorithms=+ssh-rsa", command)
        for item in command:
            self.assertNotIn("ssh-dss", item)

    def test_option_without_any_known_name_is_dropped(self):
        with mock.patch.object(ssh_adopt, "local_algorithms", return_value=FAKE_NAMES):
            self.assertEqual(ssh_adopt.usable_options(["HostKeyAlgorithms=+ssh-dss"]), [])

    def test_list_without_plus_is_kept_as_it_is(self):
        with mock.patch.object(ssh_adopt, "local_algorithms", return_value=FAKE_NAMES):
            self.assertEqual(ssh_adopt.usable_options(["HostKeyAlgorithms=ssh-dss"]), ["HostKeyAlgorithms=ssh-dss"])

    def test_no_local_names_means_no_filter(self):
        options = ssh_adopt.parse_extra_options(OLD_OPTIONS)
        with mock.patch.object(ssh_adopt, "local_algorithms", return_value=None):
            self.assertEqual(ssh_adopt.usable_options(options), options)


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

    def test_bad_key_types_is_ssh_options_rejected(self):
        stderr = b"command-line line 0: Bad key types '+ssh-rsa,ssh-dss'."
        runner = FakeRunner(result=completed(255, stderr=stderr))
        with self.assertLogs("mfi_server.ssh_adopt", level="WARNING") as logs:
            with self.assertRaises(SshError) as cm:
                ssh_adopt.run_ssh(sample_command(), PASSWORD, runner=runner)
        self.assertEqual(cm.exception.code, "ssh_options_rejected")
        text = "\n".join(logs.output)
        self.assertIn("ssh_options_rejected", text)
        self.assertIn("Bad key types", text)

    def test_unable_to_negotiate_is_ssh_options_rejected(self):
        stderr = b"Unable to negotiate with 192.168.1.20 port 22: no matching key exchange method found."
        runner = FakeRunner(result=completed(255, stderr=stderr))
        with self.assertRaises(SshError) as cm:
            ssh_adopt.run_ssh(sample_command(), PASSWORD, runner=runner)
        self.assertEqual(cm.exception.code, "ssh_options_rejected")

    def test_warning_line_hides_password(self):
        stderr = b"ubnt@192.168.1.20: test-password refused by the device"
        runner = FakeRunner(result=completed(255, stderr=stderr))
        with self.assertLogs("mfi_server.ssh_adopt", level="WARNING") as logs:
            with self.assertRaises(SshError):
                ssh_adopt.run_ssh(sample_command(), PASSWORD, runner=runner)
        text = "\n".join(logs.output)
        self.assertNotIn(PASSWORD, text)
        self.assertIn("***", text)

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


class TestCheckSshOptions(unittest.TestCase):
    def test_refusal_is_logged_as_warning_with_first_line(self):
        stderr = b"command-line line 0: Bad key types '+ssh-rsa,ssh-dss'."
        runner = FakeRunner(result=completed(255, stderr=stderr))
        with self.assertLogs("mfi_server.ssh_adopt", level="WARNING") as logs:
            ssh_adopt.check_ssh_options(OLD_OPTIONS, runner=runner)
        text = "\n".join(logs.output)
        self.assertIn("exit code 255", text)
        self.assertIn("Bad key types", text)

    def test_probe_uses_documentation_address_and_no_password(self):
        runner = FakeRunner(result=completed(0))
        ssh_adopt.check_ssh_options(DEFAULT_OPTIONS, runner=runner)
        command, kwargs = runner.calls[0]
        self.assertEqual(command[:2], ["ssh", "-G"])
        self.assertEqual(command[-1], "192.0.2.1")
        self.assertNotIn("MFI_SSH_PASSWORD", kwargs.get("env", {}))

    def test_accepted_options_log_nothing(self):
        runner = FakeRunner(result=completed(0))
        with self.assertNoLogs("mfi_server.ssh_adopt", level="WARNING"):
            ssh_adopt.check_ssh_options(DEFAULT_OPTIONS, runner=runner)

    def test_missing_ssh_is_logged_as_warning(self):
        runner = FakeRunner(error=FileNotFoundError("ssh"))
        with self.assertLogs("mfi_server.ssh_adopt", level="WARNING"):
            ssh_adopt.check_ssh_options(DEFAULT_OPTIONS, runner=runner)


@unittest.skipUnless(shutil.which("ssh"), "ssh is not installed")
class TestRealSsh(unittest.TestCase):
    def test_default_options_are_parsed_by_real_ssh(self):
        command = ["ssh", "-G"]
        for option in ssh_adopt.parse_extra_options(DEFAULT_OPTIONS):
            command += ["-o", option]
        command.append(ssh_adopt.PROBE_ADDRESS)
        result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, timeout=10, check=False)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))


if __name__ == "__main__":
    unittest.main()
