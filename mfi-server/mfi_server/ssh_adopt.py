"""Adoption of mFi devices through the system ssh program.

Standard library only. ssh is an external program: it is always started with
an argument list, never through a shell. The device password reaches ssh only
through an SSH_ASKPASS helper that prints the MFI_SSH_PASSWORD variable. The
helper folder is removed when the call ends, also on error.
"""
from __future__ import annotations

import ipaddress
import logging
import os
import re
import shutil
import socket
import subprocess
import tempfile

logger = logging.getLogger(__name__)

ALLOWED_OPTION_KEYS = (
    "KexAlgorithms",
    "HostKeyAlgorithms",
    "Ciphers",
    "MACs",
    "PubkeyAcceptedAlgorithms",
    "PubkeyAcceptedKeyTypes",
)
OPTION_RE = re.compile(r"(?:" + "|".join(ALLOWED_OPTION_KEYS) + r")=[A-Za-z0-9+,@.-]+")
USERNAME_RE = re.compile(r"[A-Za-z0-9._-]{1,32}")
URL_RE = re.compile(r"http://[A-Za-z0-9.-]+:[0-9]{1,5}/inform")
AUTHKEY_RE = re.compile(r"[0-9a-f]{32}")
ADOPT_COMMAND = "/usr/bin/syswrapper.sh"
DISCOVERY_PORT = 10001
STDERR_LOG_LINES = 300
BASE_COMMAND = [
    "ssh",
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=/dev/null",
    "-o", "ConnectTimeout=5",
    "-o", "NumberOfPasswordPrompts=1",
    "-o", "PubkeyAuthentication=no",
    "-o", "PreferredAuthentications=password,keyboard-interactive",
]
ASKPASS_SCRIPT = "#!/bin/sh\nprintf '%s\\n' \"$MFI_SSH_PASSWORD\"\n"


class SshError(Exception):
    """Failure of an ssh call; code is one of the fixed codes of the API."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def parse_extra_options(text: str) -> list[str]:
    """Split the ';' separated ssh options and keep only the allowed ones; ValueError otherwise."""
    options = []
    for raw in text.split(";"):
        entry = raw.strip()
        if not entry:
            continue
        if OPTION_RE.fullmatch(entry) is None:
            # The entry is not echoed: it may contain a secret typed by mistake.
            raise ValueError(f"ssh option not allowed (allowed keys: {', '.join(ALLOWED_OPTION_KEYS)})")
        options.append(entry)
    return options


def build_ssh_command(host: str, username: str, extra_options: list[str], remote: list[str]) -> list[str]:
    """Return the ssh argument list for one device; SshError invalid_input for a bad host, user or option."""
    if not isinstance(host, str):
        raise SshError("invalid_input")
    try:
        ipaddress.IPv4Address(host)
    except ValueError as exc:
        raise SshError("invalid_input") from exc
    if not isinstance(username, str) or USERNAME_RE.fullmatch(username) is None:
        raise SshError("invalid_input")
    command = list(BASE_COMMAND)
    for option in extra_options:
        if not isinstance(option, str) or OPTION_RE.fullmatch(option) is None:
            raise SshError("invalid_input")
        command += ["-o", option]
    command += ["-l", username, host]
    command += list(remote)
    return command


def set_adopt_remote(url: str, authkey: str) -> list[str]:
    """Return the remote command that points the device to url with authkey; invalid_input otherwise."""
    if not isinstance(url, str) or URL_RE.fullmatch(url) is None:
        raise SshError("invalid_input")
    if not isinstance(authkey, str) or AUTHKEY_RE.fullmatch(authkey) is None:
        raise SshError("invalid_input")
    return [ADOPT_COMMAND, "set-adopt", url, authkey]


def run_ssh(command: list[str], password: str, timeout_s: float = 20.0, runner=subprocess.run) -> None:
    """Run the ssh command with the password given through SSH_ASKPASS; map the failures to SshError."""
    folder = tempfile.mkdtemp(prefix="mfi-askpass-")
    try:
        script = os.path.join(folder, "askpass.sh")
        fd = os.open(script, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o700)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(ASKPASS_SCRIPT)
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "SSH_ASKPASS": script,
            "SSH_ASKPASS_REQUIRE": "force",
            "DISPLAY": "none",
            "MFI_SSH_PASSWORD": password,
        }
        try:
            result = runner(command, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout_s, env=env)
        except FileNotFoundError as exc:
            raise SshError("ssh_not_installed") from exc
        except subprocess.TimeoutExpired as exc:
            raise SshError("timeout") from exc
        _log_stderr(result.stderr, password)
        if result.returncode == 255:
            stderr = result.stderr
            if isinstance(stderr, bytes):
                stderr_text = stderr.decode("utf-8", errors="replace")
            else:
                stderr_text = stderr or ""
            if "Permission denied" in stderr_text:
                raise SshError("auth_failed")
            raise SshError("connection_failed")
        if result.returncode != 0:
            raise SshError("command_failed")
    finally:
        shutil.rmtree(folder)


def _log_stderr(stderr, password: str) -> None:
    """Log the last lines of ssh stderr at DEBUG, with the password and the authkeys hidden."""
    if isinstance(stderr, bytes):
        text = stderr.decode("utf-8", errors="replace")
    elif isinstance(stderr, str):
        text = stderr
    else:
        text = ""
    tail = "\n".join(text.splitlines()[-STDERR_LOG_LINES:])
    if password:
        tail = tail.replace(password, "***")
    tail = AUTHKEY_RE.sub("***", tail)
    logger.debug("ssh stderr, last %d lines:\n%s", STDERR_LOG_LINES, tail)


def local_address_for(ip: str) -> str:
    """Return the local address the system uses to reach ip; no packet is sent."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect((ip, DISCOVERY_PORT))
        return sock.getsockname()[0]
    finally:
        sock.close()
