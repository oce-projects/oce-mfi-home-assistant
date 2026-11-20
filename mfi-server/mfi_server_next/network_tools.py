"""Risky network tools, all OFF by default (EPIC-13): web shell to an adopted
mPort Serial, SSH from the browser, UPnP announcements and the guest page.

Each tool has its own setting (default False). The admin role is enforced by the
page API (every POST route needs the admin role). The host and port of the web
shell and the browser SSH are never taken from the request: only the stored
address of an adopted device is used. No password or secret is logged.
Standard library only, clean room.
"""
from __future__ import annotations

import socket

SETTING_WEBSHELL = "allow_webshell"
SETTING_BROWSER_SSH = "allow_browser_ssh"
SETTING_UPNP = "allow_upnp"
SETTING_GUEST_PAGE = "allow_guest_page"

MPORT_SERIAL_MODEL = "M2S"
# UG-V11 p. 13/28: the web shell reaches the serial line of an mPort Serial over
# TCP 2323. UNVERIFIED on a device; the exact port is not confirmed by a document.
WEBSHELL_PORT = 2323
WEBSHELL_PROTOCOL = "telnet"
SSH_PORT = 22
UPNP_PRODUCT = "mFi Server"
CONNECT_TIMEOUT_S = 5.0


class NetworkToolError(Exception):
    """A risky network tool refused the request.

    `code` is the API error key, `status` the HTTP status the page API sends.
    """

    def __init__(self, code: str, status: int = 403) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


def _require_enabled(settings, key) -> None:
    if settings.get(key) is not True:
        raise NetworkToolError("disabled", 403)


def _default_connect(host, port):
    return socket.create_connection((host, port), timeout=CONNECT_TIMEOUT_S)


def _adopted_record(devices, mac):
    record = devices.get(mac)
    if record is None or not record.get("adopted"):
        raise NetworkToolError("not_adopted", 404)
    return record


def _probe(connect, host, port) -> None:
    conn = (connect or _default_connect)(host, port)
    close = getattr(conn, "close", None)
    if callable(close):
        try:
            close()
        except OSError:
            # The probe already succeeded; a failed close changes nothing.
            pass


def open_webshell(settings, devices, mac, *, connect=None) -> dict:
    """Open a web shell toward the serial line of an adopted mPort Serial.

    The host and port come only from the stored device record. Raises
    NetworkToolError when the setting is off, the device is unknown or not
    adopted, not an mPort Serial, or has no stored address.
    """
    _require_enabled(settings, SETTING_WEBSHELL)
    record = _adopted_record(devices, mac)
    if record.get("model") != MPORT_SERIAL_MODEL:
        raise NetworkToolError("not_serial", 409)
    host = record.get("ip")
    if not host:
        raise NetworkToolError("no_address", 409)
    _probe(connect, host, WEBSHELL_PORT)
    return {"host": host, "port": WEBSHELL_PORT, "protocol": WEBSHELL_PROTOCOL}


def start_browser_ssh(settings, devices, mac, *, connect=None) -> dict:
    """Open an SSH session from the browser toward an adopted device.

    Separate from the adoption SSH call. The host comes only from the stored
    device record. Raises NetworkToolError when the setting is off, the device
    is unknown or not adopted, or has no stored address.
    """
    _require_enabled(settings, SETTING_BROWSER_SSH)
    record = _adopted_record(devices, mac)
    host = record.get("ip")
    if not host:
        raise NetworkToolError("no_address", 409)
    _probe(connect, host, SSH_PORT)
    return {"host": host, "port": SSH_PORT}


def upnp_announce(settings) -> dict:
    """Return the UPnP announcement content: only the product name, no version."""
    _require_enabled(settings, SETTING_UPNP)
    return {"product": UPNP_PRODUCT}


def guest_portal(settings, limiter=None, client_ip="") -> dict:
    """Return the guest access page content; rate limited when a limiter is given."""
    _require_enabled(settings, SETTING_GUEST_PAGE)
    if limiter is not None:
        if limiter.blocked(client_ip):
            raise NetworkToolError("rate_limited", 429)
        # Count every request against the public-page rate budget (not only auth failures).
        limiter.failure(client_ip)
    return {"product": UPNP_PRODUCT, "page": "guest"}
