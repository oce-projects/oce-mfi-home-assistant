"""Wi-Fi survey of the setup window: the networks the device can see, and the query for /captive.cgi.

Reads GET /survey.json.cgi through a connection supplied by the caller (the same
factory as device_check) and builds the query that the device setup page sends
to /captive.cgi. The query never carries inform_addr, cloud_name or cloud_pass.
Standard library only; no tkinter.
"""
from __future__ import annotations

import http.client
import json
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlencode

SURVEY_PATH = "/survey.json.cgi"
CAPTIVE_PATH = "/captive.cgi"

SEC_NONE = "none"
SEC_WPA = "wpa"
SEC_WPA2 = "wpa2"

WPA_AUTH_PSK = "WPA-PSK"


@dataclass
class Network:
    essid: str
    signal_level: int
    encryption: str
    security: str


def security_for(encryption: str) -> str:
    """Map the encryption name of the survey to SEC_WPA2, SEC_WPA or SEC_NONE."""
    e = encryption.lower()
    if "wpa2" in e:
        return SEC_WPA2
    if "wpa" in e:
        return SEC_WPA
    return SEC_NONE


def is_supported(obj: dict) -> bool:
    """True for open networks and WPA/WPA2 personal networks; False for WEP and EAP."""
    enc = str(obj.get("encryption") or "").lower()
    auth = obj.get("auth_suites")
    auth_s = (" ".join(str(a) for a in auth) if isinstance(auth, list) else str(auth or "")).lower()
    if "wep" in enc:
        return False
    if "eap" in auth_s or "802.1x" in auth_s:
        return False
    return True


def read_survey(
    connect: Callable[[], http.client.HTTPConnection],
    path: str = SURVEY_PATH,
    timeout: int = 5,
) -> list[Network]:
    """Networks the device can see, strongest first; WEP and EAP networks are left out.

    The body is a JSON array even when the device serves it as text/html. Any
    failure of the request or of the body gives an empty list.
    """
    try:
        conn = connect()
        conn.timeout = timeout
        try:
            conn.request("GET", path)
            data = conn.getresponse().read()
        finally:
            conn.close()
        items = json.loads(data)
    except (OSError, ValueError):
        return []
    if not isinstance(items, list):
        return []
    networks = []
    for obj in items:
        if not isinstance(obj, dict) or not is_supported(obj):
            continue
        try:
            level = int(obj.get("signal_level"))
        except (TypeError, ValueError):
            continue
        encryption = str(obj.get("encryption") or "")
        networks.append(
            Network(
                essid=str(obj.get("essid") or ""),
                signal_level=level,
                encryption=encryption,
                security=security_for(encryption),
            )
        )
    networks.sort(key=lambda net: net.signal_level, reverse=True)
    return networks


def build_captive_query(essid: str, security: str, wpa_key: str = "", path: str = CAPTIVE_PATH) -> str:
    """Path and query of GET /captive.cgi, with the field names of the device setup form."""
    fields = [("type", "POST"), ("essid", essid), ("security", security)]
    if security != SEC_NONE:
        fields += [("wpa_auth", WPA_AUTH_PSK), ("wpa_key", wpa_key)]
    return f"{path}?{urlencode(fields)}"
