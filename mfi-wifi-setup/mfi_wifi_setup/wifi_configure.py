"""Guided configuration of a Wi-Fi device: the states of status.cgi and the leaveap step.

configure() sends the captive.cgi query built by wifi_survey, polls status.cgi
every POLL_INTERVAL_S seconds and asks the device to close its access point
(POST /leaveap.cgi) only when the Wi-Fi is connected and the address is obtained.
Standard library only; no tkinter.
"""
from __future__ import annotations

import http.client
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from .bridge import hide_query
from .wifi_survey import build_captive_query

STATUS_PATH = "/status.cgi"
LEAVEAP_PATH = "/leaveap.cgi"
POLL_INTERVAL_S = 1.0
ERROR_CP_STATES = {"wifitimeout", "iptimeout"}

STEP_PENDING = "pending"
STEP_WIFI_CONNECTED = "wifi_connected"
STEP_ADDRESS_OBTAINED = "address_obtained"
STEP_ERROR = "error"

log = logging.getLogger("mfi_wifi_setup.wifi_configure")


@dataclass
class SetupStep:
    step: str
    ip: str = ""
    cp_state: str = ""


@dataclass
class ConfigureResult:
    ok: bool
    step: str
    ip: str = ""
    error: str = ""


def _section(payload: dict, name: str) -> dict:
    """A section of the status payload (host, wireless, wlan); anything else is an empty section."""
    value = payload.get(name)
    return value if isinstance(value, dict) else {}


def classify_status(payload: dict) -> SetupStep:
    """Map a status.cgi payload to one step; an error state of cp_state wins over the rest."""
    host = _section(payload, "host")
    cp = str(host.get("cp_state") or "")
    if cp in ERROR_CP_STATES:
        return SetupStep(STEP_ERROR, cp_state=cp)
    wireless = _section(payload, "wireless")
    wlan = _section(payload, "wlan")
    essid = str(wireless.get("essid") or "")
    apmac = str(wireless.get("apmac") or "")
    ip = str(wlan.get("ip") or "")
    wifi_ok = bool(essid) and any(c not in "0:-" for c in apmac)
    ip_ok = ip not in ("", "0.0.0.0")
    if wifi_ok and ip_ok:
        return SetupStep(STEP_ADDRESS_OBTAINED, ip=ip, cp_state=cp)
    if wifi_ok:
        return SetupStep(STEP_WIFI_CONNECTED, cp_state=cp)
    return SetupStep(STEP_PENDING, cp_state=cp)


def _request(connect: Callable[[], http.client.HTTPConnection], method: str, path: str, timeout: int = 5) -> bytes:
    """One request through connect(); returns the body. Raises OSError or HTTPException on failure."""
    conn = connect()
    conn.timeout = timeout
    try:
        conn.request(method, path)
        return conn.getresponse().read()
    finally:
        conn.close()


def read_setup_status(
    connect: Callable[[], http.client.HTTPConnection],
    path: str = STATUS_PATH,
    timeout: int = 5,
) -> SetupStep:
    """Ask the device for its status; a request or body failure counts as pending."""
    try:
        data = _request(connect, "GET", path, timeout)
        payload = json.loads(data)
    except (OSError, ValueError, http.client.HTTPException):
        return SetupStep(STEP_PENDING)
    if not isinstance(payload, dict):
        return SetupStep(STEP_PENDING)
    return classify_status(payload)


def _close_access_point(connect: Callable[[], http.client.HTTPConnection], ip: str) -> ConfigureResult:
    """Ask the device to close its access point; the address is already obtained."""
    try:
        _request(connect, "POST", LEAVEAP_PATH)
    except (OSError, http.client.HTTPException):
        log.warning("address obtained but the access point did not close")
        return ConfigureResult(False, STEP_ADDRESS_OBTAINED, ip=ip, error="leaveap failed")
    log.info("access point closed, address obtained")
    return ConfigureResult(True, STEP_ADDRESS_OBTAINED, ip=ip)


def configure(
    connect: Callable[[], http.client.HTTPConnection],
    *,
    essid: str,
    security: str,
    wpa_key: str = "",
    on_progress: Callable[[SetupStep], None] | None = None,
    poll_interval_s: float = POLL_INTERVAL_S,
    max_polls: int = 600,
) -> ConfigureResult:
    """Send the setup form, then poll status.cgi until the address is obtained, an error comes, or max_polls ends.

    POST /leaveap.cgi is sent only after the address is obtained. The password is never logged
    and never put in an error message.
    """
    query = build_captive_query(essid, security, wpa_key)
    log.info("configuring essid=%s security=%s", essid, security)
    try:
        _request(connect, "GET", query)
    except (OSError, http.client.HTTPException):
        log.warning("device not reachable while sending the setup form")
        return ConfigureResult(False, STEP_ERROR, error="device not reachable")
    log.info("setup form sent: %s", hide_query(query))
    for _ in range(max_polls):
        time.sleep(poll_interval_s)
        status = read_setup_status(connect)
        log.info("step=%s cp_state=%s", status.step, status.cp_state)
        if on_progress is not None:
            on_progress(status)
        if status.step == STEP_ERROR:
            log.warning("configuration failed")
            return ConfigureResult(False, STEP_ERROR, error="configuration failed")
        if status.step == STEP_ADDRESS_OBTAINED:
            return _close_access_point(connect, status.ip)
    log.warning("configuration timed out")
    return ConfigureResult(False, STEP_ERROR, error="timeout")
