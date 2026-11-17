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
# Names each option key accepts, as listed by 'ssh -Q <query>'. HostKeyAlgorithms and
# the public key options also take signature names, so both lists are read.
KEY_QUERIES = {
    "KexAlgorithms": ("kex",),
    "HostKeyAlgorithms": ("key", "sig"),
    "PubkeyAcceptedAlgorithms": ("key", "sig"),
    "PubkeyAcceptedKeyTypes": ("key", "sig"),
    "Ciphers": ("cipher",),
    "MACs": ("mac",),
}
ALGORITHM_QUERIES = ("cipher", "key", "kex", "mac", "sig")
QUERY_TIMEOUT_S = 10
PROBE_ADDRESS = "192.0.2.1"  # documentation address (RFC 5737): ssh -G never connects to it
PROBE_TIMEOUT_S = 10
OPTION_REJECTED_MARKERS = ("Bad key types", "Bad SSH2", "Unable to negotiate")
# Names read from the local ssh, once per process. Empty until the first read.
_LOCAL_CACHE: dict = {}


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


def _query_local_algorithms() -> dict[str, frozenset[str]] | None:
    """Read the names the local ssh accepts, one 'ssh -Q' per query; None when ssh is missing or fails."""
    names: dict[str, frozenset[str]] = {}
    for query in ALGORITHM_QUERIES:
        try:
            result = subprocess.run(
                ["ssh", "-Q", query],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=QUERY_TIMEOUT_S,
                check=False,
            )
        except FileNotFoundError:
            logger.info("ssh not found: ssh_extra_options are not checked against it")
            return None
        except subprocess.TimeoutExpired:
            logger.warning("ssh -Q %s timed out: ssh_extra_options are not checked", query)
            return None
        if result.returncode != 0:
            logger.warning(
                "ssh -Q %s exited with %d: ssh_extra_options are not checked", query, result.returncode
            )
            return None
        names[query] = frozenset(_as_text(result.stdout).split())
    return names


def local_algorithms() -> dict[str, frozenset[str]] | None:
    """Return the algorithm names of the local ssh, read once per process; None when they cannot be read."""
    if "names" not in _LOCAL_CACHE:
        _LOCAL_CACHE["names"] = _query_local_algorithms()
    return _LOCAL_CACHE["names"]


def usable_options(extra_options: list[str]) -> list[str]:
    """Remove from the '+' lists the names the local ssh does not know; an option left with no name is dropped.

    Installations keep the options saved by Home Assistant, so this check is what
    keeps them working after a default change. Lists without '+' are kept as they are.
    """
    known = local_algorithms()
    if known is None:
        return list(extra_options)
    usable = []
    for option in extra_options:
        key, _, value = option.partition("=")
        if key not in KEY_QUERIES or not value.startswith("+"):
            usable.append(option)
            continue
        accepted = frozenset().union(*(known[query] for query in KEY_QUERIES[key]))
        names = [name for name in value[1:].split(",") if name]
        kept = [name for name in names if name in accepted]
        dropped = [name for name in names if name not in accepted]
        if dropped:
            logger.warning("the local ssh does not know %s: removed from %s", ", ".join(dropped), key)
        if kept:
            usable.append(f"{key}=+{','.join(kept)}")
    return usable


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
    for option in extra_options:
        if not isinstance(option, str) or OPTION_RE.fullmatch(option) is None:
            raise SshError("invalid_input")
    command = list(BASE_COMMAND)
    for option in usable_options(extra_options):
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


def check_ssh_options(extra_options: str, runner=subprocess.run) -> None:
    """Ask the local ssh to parse the options for a documentation address (ssh -G, no connection).

    Logs a WARNING when ssh refuses them. The options are the ones that adoption
    uses, after usable_options.
    """
    options = usable_options(parse_extra_options(extra_options))
    command = ["ssh", "-G"]
    for option in options:
        command += ["-o", option]
    command.append(PROBE_ADDRESS)
    try:
        result = runner(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=PROBE_TIMEOUT_S,
            check=False,
        )
    except FileNotFoundError:
        logger.warning("ssh is not installed: adoption and re-pointing will fail")
        return
    except subprocess.TimeoutExpired:
        logger.warning("ssh -G timed out: check ssh_extra_options")
        return
    if result.returncode != 0:
        logger.warning(
            "ssh refuses the ssh_extra_options (exit code %d): %s",
            result.returncode,
            _first_line(_as_text(result.stderr), ""),
        )


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
            stderr_text = _as_text(result.stderr)
            code = _failure_code(stderr_text)
            logger.warning("ssh exited with 255 (%s): %s", code, _first_line(stderr_text, password))
            raise SshError(code)
        if result.returncode != 0:
            raise SshError("command_failed")
    finally:
        shutil.rmtree(folder)


def _failure_code(stderr_text: str) -> str:
    """Map the stderr of an ssh call that exited with 255 to one code of the API."""
    if "Permission denied" in stderr_text:
        return "auth_failed"
    if any(marker in stderr_text for marker in OPTION_REJECTED_MARKERS):
        return "ssh_options_rejected"
    return "connection_failed"


def _as_text(value) -> str:
    """Return subprocess output as text: bytes are decoded, anything else gives an empty string."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value
    return ""


def _mask(text: str, password: str) -> str:
    """Hide the password and every authkey in a text."""
    if password:
        text = text.replace(password, "***")
    return AUTHKEY_RE.sub("***", text)


def _first_line(text: str, password: str) -> str:
    """Return the first non-empty line of ssh stderr, masked; a placeholder when there is none."""
    line = next((item for item in text.splitlines() if item.strip()), "(no stderr)")
    return _mask(line, password)


def _log_stderr(stderr, password: str) -> None:
    """Log the last lines of ssh stderr at DEBUG, with the password and the authkeys hidden."""
    tail = "\n".join(_as_text(stderr).splitlines()[-STDERR_LOG_LINES:])
    logger.debug("ssh stderr, last %d lines:\n%s", STDERR_LOG_LINES, _mask(tail, password))


def local_address_for(ip: str) -> str:
    """Return the local address the system uses to reach ip; no packet is sent."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect((ip, DISCOVERY_PORT))
        return sock.getsockname()[0]
    finally:
        sock.close()
