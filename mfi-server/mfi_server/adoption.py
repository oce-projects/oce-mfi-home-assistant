"""Adoption of factory-default mFi devices and re-pointing of adopted ones.

Both actions send set-adopt to the device through the system ssh program
(see ssh_adopt.py). The factory password is used only for that ssh call and is
never stored, logged or returned. Standard library only.
"""
from __future__ import annotations

import secrets
import subprocess

from mfi_server import ssh_adopt

FACTORY_USERNAME = "ubnt"
FACTORY_PASSWORD = "ubnt"
AUTHKEY_BYTES = 16
ADOPTING_STATE = "adopting"
ADOPT_FAILED_STATE = "adopt_failed"
# Models accepted as mFi when discovery gives no factory-default flag (firmware 2.1.11).
# Same 14 values as web/app.js. Source: docs/PROTOCOL.md (section Devices,
# "Models accepted as mFi"). INFERRED from device names in real backups; UNVERIFIED
# on a live device.
MFI_MODELS = frozenset({
    "M2M", "M2S", "P1U", "P3U", "P8U", "P1E", "P3E", "P6E",
    "IWO2U", "IWS1U", "IWD1U", "EM3", "EM24", "THERM",
})


class Adoption:
    """Adopts new devices and re-points adopted devices to this server."""

    def __init__(
        self,
        settings,
        store,
        scanner,
        runner=subprocess.run,
        address_for=ssh_adopt.local_address_for,
    ) -> None:
        self.settings = settings
        self.store = store
        self.scanner = scanner
        self.runner = runner
        self.address_for = address_for

    def inform_url(self, device_ip) -> str:
        """Return the inform URL for the device: server_address, or the local address toward the device."""
        host = self.settings.server_address or self.address_for(device_ip)
        return f"http://{host}:{self.settings.inform_port}/inform"

    def adopt(self, mac) -> None:
        """Adopt a factory-default device found by discovery; the record is saved as adopting before ssh runs."""
        devices = {d["mac"]: d for d in self.scanner.last_results()}
        dev = devices.get(mac)
        if dev is None or not dev.get("ip"):
            raise LookupError(mac)
        is_default = dev.get("is_default")
        if is_default is not None and not is_default:
            raise PermissionError("not_factory_default")
        if is_default is None:
            model = str(dev.get("model") or "").upper()
            platform = str(dev.get("platform") or "").upper()
            if model not in MFI_MODELS and platform not in MFI_MODELS:
                raise PermissionError("not_factory_default")
            existing = self.store.get(mac)
            if existing is not None and existing.get("state") not in (ADOPTING_STATE, ADOPT_FAILED_STATE):
                raise PermissionError("not_factory_default")
        authkey = secrets.token_hex(AUTHKEY_BYTES)
        name = f"{dev.get('model', '')} {mac[-4:]}"
        self.store.upsert(
            {
                "mac": mac,
                "model": dev.get("model", ""),
                "name": name,
                "authkey": authkey,
                "ports": [],
                "state": ADOPTING_STATE,
            }
        )
        try:
            remote = ssh_adopt.set_adopt_remote(self.inform_url(dev["ip"]), authkey)
            options = ssh_adopt.parse_extra_options(self.settings.ssh_extra_options)
            command = ssh_adopt.build_ssh_command(dev["ip"], FACTORY_USERNAME, options, remote)
            ssh_adopt.run_ssh(command, FACTORY_PASSWORD, runner=self.runner)
        except (ssh_adopt.SshError, ValueError, OSError):
            self._mark_failed(mac)
            raise

    def repoint(self, mac, ip: str | None = None) -> None:
        """Send set-adopt with the authkey already stored, so the device informs this server again."""
        rec = self.store.get(mac)
        if rec is None or not rec.get("authkey"):
            raise LookupError(mac)
        device_ip = ip or self._discovered_ip(mac)
        if not device_ip:
            raise LookupError(mac)
        username = self.settings.device_ssh_username
        password = self.settings.device_ssh_password
        if not username or not password:
            raise PermissionError("ssh_credentials_not_set")
        remote = ssh_adopt.set_adopt_remote(self.inform_url(device_ip), rec["authkey"])
        options = ssh_adopt.parse_extra_options(self.settings.ssh_extra_options)
        command = ssh_adopt.build_ssh_command(device_ip, username, options, remote)
        ssh_adopt.run_ssh(command, password, runner=self.runner)

    def _mark_failed(self, mac) -> None:
        """Set the saved record of mac to adopt_failed."""
        record = self.store.get(mac)
        record["state"] = ADOPT_FAILED_STATE
        self.store.upsert(record)

    def _discovered_ip(self, mac):
        """Return the IP that discovery last saw for mac, or None."""
        for dev in self.scanner.last_results():
            if dev.get("mac") == mac:
                return dev.get("ip")
        return None
