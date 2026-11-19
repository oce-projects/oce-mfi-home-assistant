"""Registry of the devices: their keys, states and SSH adoption. Standard library only.

The SSH call is always made through an injected runner (subprocess.run by default).
The device password reaches ssh only through an SSH_ASKPASS helper that prints the
MFI_SSH_PASSWORD variable. The helper folder is removed when each call ends, also on error.
"""
from __future__ import annotations

import ipaddress
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Callable

FACTORY_SSH_USER = "ubnt"
FACTORY_SSH_PASSWORD = "ubnt"
ADOPT_COMMAND = "/usr/bin/syswrapper.sh"
LOST_AFTER_S = 120
DEVICES_FILE = "devices.json"
PENDING_STATE = 2
ADOPTING_STATE = 7

MAC_RE = re.compile(r"[0-9a-f]{12}")
AUTHKEY_RE = re.compile(r"[0-9a-f]{32}")
URL_RE = re.compile(r"http://([A-Za-z0-9.-]+):([0-9]{1,5})/inform")
USERNAME_RE = re.compile(r"[A-Za-z0-9._-]{1,32}")
EXTRA_OPTION_RE = re.compile(
    r"(?:KexAlgorithms|HostKeyAlgorithms|Ciphers|MACs|PubkeyAcceptedAlgorithms|PubkeyAcceptedKeyTypes)"
    r"=[A-Za-z0-9+,@.-]+"
)
BASE_SSH_COMMAND = [
    "ssh",
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=/dev/null",
    "-o", "ConnectTimeout=5",
    "-o", "NumberOfPasswordPrompts=1",
    "-o", "PubkeyAuthentication=no",
    "-o", "PreferredAuthentications=password,keyboard-interactive",
]
ASKPASS_SCRIPT = "#!/bin/sh\nprintf '%s\\n' \"$MFI_SSH_PASSWORD\"\n"
LOGIN_REFUSED_CODE = 255
LOGIN_REFUSED_TEXT = "Permission denied"


class AdoptionError(Exception):
    """An SSH adoption failed, or its arguments are not valid."""


def _valid_authkey(value) -> bool:
    """Return True when value is 32 lowercase hex characters."""
    return isinstance(value, str) and AUTHKEY_RE.fullmatch(value) is not None


def _valid_username(value) -> bool:
    """Return True when value is a plain user name that cannot be read as an ssh option."""
    return (
        isinstance(value, str)
        and USERNAME_RE.fullmatch(value) is not None
        and not value.startswith("-")
    )


def _check_mac(mac) -> None:
    """Raise ValueError unless mac is 12 lowercase hex digits without colons."""
    if not isinstance(mac, str) or MAC_RE.fullmatch(mac) is None:
        raise ValueError("mac must be 12 lowercase hex digits without colons")


def _as_text(value) -> str:
    """Return subprocess output as text: bytes are decoded, anything else gives an empty string."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value
    return ""


def _is_login_refused(result) -> bool:
    """Return True when ssh exited because the login was refused."""
    return result.returncode == LOGIN_REFUSED_CODE and LOGIN_REFUSED_TEXT in _as_text(result.stderr)


def _validate_adopt_input(ip, inform_url, authkey, admin_user, admin_password, extra_options) -> None:
    """Raise AdoptionError on the first argument of set_adopt that is not valid."""
    if not isinstance(ip, str):
        raise AdoptionError("ip must be an IPv4 address")
    try:
        ipaddress.IPv4Address(ip)
    except ValueError as exc:
        raise AdoptionError("ip must be an IPv4 address") from exc
    match = URL_RE.fullmatch(inform_url) if isinstance(inform_url, str) else None
    if match is None or not 1 <= int(match.group(2)) <= 65535:
        raise AdoptionError("inform_url must be http://<host>:<port>/inform")
    if not _valid_authkey(authkey):
        raise AdoptionError("authkey must be 32 lowercase hex characters")
    if not _valid_username(admin_user):
        raise AdoptionError("admin_user is not a valid user name")
    if not isinstance(admin_password, str) or admin_password == "":
        raise AdoptionError("admin_password must not be empty")
    if "\x00" in admin_password:
        raise AdoptionError("admin_password must not contain a NUL byte")
    for option in extra_options:
        if not isinstance(option, str) or EXTRA_OPTION_RE.fullmatch(option) is None:
            raise AdoptionError("ssh_extra_options: option not allowed")


def _ssh_command(ip, username, extra_options, inform_url, authkey) -> list[str]:
    """Return the ssh argument list of one set-adopt call; never a shell string."""
    command = list(BASE_SSH_COMMAND)
    for option in extra_options:
        command += ["-o", option]
    command += ["-l", username, ip, ADOPT_COMMAND, "set-adopt", inform_url, authkey]
    return command


def _run_ssh(ip, username, password, inform_url, authkey, extra_options, runner, timeout_s):
    """Run one set-adopt call with the password only in SSH_ASKPASS and MFI_SSH_PASSWORD."""
    command = _ssh_command(ip, username, extra_options, inform_url, authkey)
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
            return runner(
                command,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=timeout_s,
                check=False,
                env=env,
            )
        except FileNotFoundError as exc:
            raise AdoptionError("ssh is not installed") from exc
        except subprocess.TimeoutExpired as exc:
            raise AdoptionError("ssh timed out") from exc
        except OSError as exc:
            raise AdoptionError("ssh could not be started") from exc
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def set_adopt(
    ip,
    inform_url,
    authkey,
    *,
    admin_user,
    admin_password,
    runner=subprocess.run,
    timeout_s=20,
    ssh_extra_options=(),
) -> str:
    """Point a device to inform_url with authkey over SSH.

    Tries the administrator credentials first. Only on a refused login retries once
    with the factory credentials. Returns "admin" or "factory" for the credentials
    that worked; raises AdoptionError otherwise.
    """
    if isinstance(ssh_extra_options, str):
        raise AdoptionError("ssh_extra_options must be a sequence of options")
    extra_options = tuple(ssh_extra_options)
    _validate_adopt_input(ip, inform_url, authkey, admin_user, admin_password, extra_options)

    result = _run_ssh(ip, admin_user, admin_password, inform_url, authkey, extra_options, runner, timeout_s)
    if result.returncode == 0:
        return "admin"
    if not _is_login_refused(result):
        raise AdoptionError(f"set-adopt failed with exit code {result.returncode}")

    result = _run_ssh(
        ip, FACTORY_SSH_USER, FACTORY_SSH_PASSWORD, inform_url, authkey, extra_options, runner, timeout_s
    )
    if result.returncode == 0:
        return "factory"
    if _is_login_refused(result):
        raise AdoptionError("login refused with the administrator and the factory credentials")
    raise AdoptionError(f"set-adopt failed with exit code {result.returncode}")


def _new_record(
    mac,
    *,
    model,
    ip,
    adopted,
    state,
    x_authkey=None,
    x_prev_authkey=None,
    cfgversion=None,
    portversion=None,
    version=None,
) -> dict:
    """Return one device record with every key of the contract."""
    return {
        "mac": mac,
        "model": model,
        "ip": ip,
        "adopted": adopted,
        "x_authkey": x_authkey,
        "x_prev_authkey": x_prev_authkey,
        "cfgversion": cfgversion,
        "portversion": portversion,
        "state": state,
        "version": version,
    }


class DeviceRegistry:
    """Devices known to the server, by MAC address. Records are copied in and out, never shared."""

    def __init__(self, store=None, clock: Callable[[], float] = time.monotonic) -> None:
        self._store = store
        self._clock = clock
        self._lock = threading.Lock()
        self._records: dict[str, dict] = {}
        self._last_seen: dict[str, float] = {}

    def get(self, mac) -> dict | None:
        """Return a copy of the record of mac, or None."""
        _check_mac(mac)
        with self._lock:
            record = self._records.get(mac)
            return None if record is None else dict(record)

    def add(self, mac, *, model=None, ip=None) -> dict:
        """Create a pending record (state 2). An adopted record is kept and returned unchanged."""
        _check_mac(mac)
        with self._lock:
            current = self._records.get(mac)
            if current is not None and current["adopted"]:
                return dict(current)
            keep = current or {}
            record = _new_record(
                mac,
                model=model if model is not None else keep.get("model"),
                ip=ip if ip is not None else keep.get("ip"),
                adopted=False,
                state=PENDING_STATE,
            )
            self._records[mac] = record
            return dict(record)

    def adopt(self, mac, *, x_authkey, cfgversion, portversion, model=None, ip=None) -> dict:
        """Create or replace an adopted record (state 7). The previous key is kept as x_prev_authkey."""
        _check_mac(mac)
        if not _valid_authkey(x_authkey):
            raise ValueError("x_authkey must be 32 lowercase hex characters")
        with self._lock:
            current = self._records.get(mac)
            keep = current or {}
            previous = keep.get("x_prev_authkey")
            if keep.get("x_authkey") and keep["x_authkey"] != x_authkey:
                previous = keep["x_authkey"]
            record = _new_record(
                mac,
                model=model if model is not None else keep.get("model"),
                ip=ip if ip is not None else keep.get("ip"),
                adopted=True,
                state=ADOPTING_STATE,
                x_authkey=x_authkey,
                x_prev_authkey=previous,
                cfgversion=cfgversion,
                portversion=portversion,
                version=keep.get("version"),
            )
            self._records[mac] = record
            return dict(record)

    def forget(self, mac) -> None:
        """Remove the record of mac, if any."""
        _check_mac(mac)
        with self._lock:
            self._records.pop(mac, None)
            self._last_seen.pop(mac, None)

    def factory_reset(self, mac) -> None:
        """Remove the record of mac after a factory reset."""
        self.forget(mac)

    def seen(self, mac) -> None:
        """Record that mac informed now."""
        _check_mac(mac)
        with self._lock:
            self._last_seen[mac] = self._clock()

    def state(self, mac) -> str:
        """Return 'connected' (seen within LOST_AFTER_S), 'lost' (seen earlier) or 'unknown' (never seen)."""
        _check_mac(mac)
        with self._lock:
            last = self._last_seen.get(mac)
            if last is None:
                return "unknown"
            if self._clock() - last <= LOST_AFTER_S:
                return "connected"
            return "lost"

    def save(self) -> None:
        """Write every record to devices.json (mode 0600) when a store is set; otherwise do nothing."""
        if self._store is None:
            return
        with self._lock:
            rows = [dict(self._records[mac]) for mac in sorted(self._records)]
        self._store.write_json(DEVICES_FILE, rows, private=True)
