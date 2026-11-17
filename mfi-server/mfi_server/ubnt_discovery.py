"""UDP discovery of mFi devices on port 10001 (ubnt_discovery).

Not the same as discovery.py, which builds the Home Assistant MQTT discovery messages.
A device answers the 4-byte QUERY with a header and TLV fields. Standard library only.
"""
from __future__ import annotations

import logging
import re
import socket
import struct
import threading
import time

logger = logging.getLogger(__name__)

DISCOVERY_PORT = 10001
BROADCAST_ADDRESS = "255.255.255.255"
MULTICAST_ADDRESS = "233.89.188.1"
QUERY = b"\x01\x00\x00\x00"
HEADER_SIZE = 4
TLV_HEADER_SIZE = 3
MAC_SIZE = 6
IP_SIZE = 4
UPTIME_SIZE = 4
RECV_SIZE = 2048
SOCKET_TIMEOUT_S = 0.5
TYPE_MAC = 1
TYPE_MAC_IP = 2
TYPE_VERSION = 3
TYPE_UPTIME = 10
TYPE_DEFAULT = 23
TYPE_ESSID = 13
TYPE_WMODE = 14
TEXT_FIELDS = {11: "hostname", 12: "platform", 21: "model", 22: "firmware"}


class DiscoveryError(ValueError):
    """A discovery reply that is not valid."""


class ScanInProgress(RuntimeError):
    """A discovery scan is already running."""


def parse_reply(data: bytes) -> dict:
    """Return the device described by one discovery reply; raise DiscoveryError when the reply is not valid."""
    if len(data) < HEADER_SIZE:
        raise DiscoveryError(f"reply is {len(data)} bytes, the header is {HEADER_SIZE}")
    (declared,) = struct.unpack(">H", data[2:4])
    if declared != len(data) - HEADER_SIZE:
        raise DiscoveryError(f"length field is {declared}, the fields are {len(data) - HEADER_SIZE} bytes")
    fields = data[HEADER_SIZE:]
    device = {
        "mac": None,
        "ip": None,
        "model": None,
        "firmware": None,
        "hostname": None,
        "platform": None,
        "uptime_s": None,
        "is_default": None,
        "essid": None,
        "wmode": None,
        "version": None,
        "unknown": {},
    }
    pos = 0
    while pos < len(fields):
        if len(fields) - pos < TLV_HEADER_SIZE:
            raise DiscoveryError("truncated TLV header")
        tlv_type, tlv_len = struct.unpack(">BH", fields[pos:pos + TLV_HEADER_SIZE])
        pos += TLV_HEADER_SIZE
        if tlv_len > len(fields) - pos:
            raise DiscoveryError(f"TLV type {tlv_type} declares {tlv_len} bytes, {len(fields) - pos} are left")
        value = fields[pos:pos + tlv_len]
        pos += tlv_len
        _apply_tlv(device, tlv_type, value)
    if device["mac"] is None:
        raise DiscoveryError("reply has no MAC field")
    if device["firmware"] is None and device["version"]:
        match = re.search(r"\.v(\d+\.\d+\.\d+(?:\.\d+)?)", device["version"])
        device["firmware"] = match.group(1) if match else device["version"]
    if device["model"] is None and device["platform"]:
        device["model"] = device["platform"]
    return device


def _apply_tlv(device: dict, tlv_type: int, value: bytes) -> None:
    """Store the value of one TLV field in the device dict."""
    if tlv_type in (TYPE_MAC, TYPE_MAC_IP):
        if len(value) < MAC_SIZE:
            raise DiscoveryError(f"TLV type {tlv_type} is {len(value)} bytes, the MAC needs {MAC_SIZE}")
        device["mac"] = value[:MAC_SIZE].hex()
        if tlv_type == TYPE_MAC_IP and len(value) >= MAC_SIZE + IP_SIZE:
            device["ip"] = ".".join(str(octet) for octet in value[MAC_SIZE:MAC_SIZE + IP_SIZE])
    elif tlv_type in TEXT_FIELDS:
        device[TEXT_FIELDS[tlv_type]] = value.decode("utf-8", errors="replace")
    elif tlv_type == TYPE_UPTIME:
        if len(value) != UPTIME_SIZE:
            raise DiscoveryError(f"TLV type {tlv_type} is {len(value)} bytes, the uptime needs {UPTIME_SIZE}")
        device["uptime_s"] = struct.unpack(">I", value)[0]
    elif tlv_type == TYPE_DEFAULT:
        device["is_default"] = len(value) > 0 and value[0] != 0
    elif tlv_type == TYPE_ESSID:
        device["essid"] = value.decode("utf-8", errors="replace")
    elif tlv_type == TYPE_WMODE:
        device["wmode"] = value[0] if len(value) > 0 else None
    elif tlv_type == TYPE_VERSION:
        device["version"] = value.decode("utf-8", errors="replace")
    else:
        device["unknown"][str(tlv_type)] = value.hex()


def _udp_socket() -> socket.socket:
    """Return a new UDP socket for IPv4."""
    return socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


class Scanner:
    """Runs one discovery scan at a time and keeps the devices of the last scan."""

    def __init__(self, sock_factory=None, clock=time.monotonic) -> None:
        self._sock_factory = sock_factory or _udp_socket
        self._clock = clock
        self._lock = threading.Lock()
        self._results: list[dict] = []

    def scan(self, timeout_s: float = 3.0) -> list[dict]:
        """Send the query and collect the replies until timeout_s has passed; one scan at a time."""
        if not self._lock.acquire(blocking=False):
            raise ScanInProgress("a discovery scan is already running")
        try:
            self._results = self._collect(timeout_s)
            return self._results
        finally:
            self._lock.release()

    def last_results(self) -> list[dict]:
        """Return a copy of the devices of the last scan."""
        return [dict(device) for device in self._results]

    def _collect(self, timeout_s: float) -> list[dict]:
        sock = self._sock_factory()
        try:
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                sock.settimeout(SOCKET_TIMEOUT_S)
                for address in (BROADCAST_ADDRESS, MULTICAST_ADDRESS):
                    sock.sendto(QUERY, (address, DISCOVERY_PORT))
            except OSError as exc:
                logger.warning("discovery: the query could not be sent: %s", exc)
                return []
            return self._listen(sock, timeout_s)
        finally:
            sock.close()

    def _listen(self, sock, timeout_s: float) -> list[dict]:
        deadline = self._clock() + timeout_s
        devices: dict[str, dict] = {}
        while self._clock() < deadline:
            try:
                data, _ = sock.recvfrom(RECV_SIZE)
            except socket.timeout:
                continue
            except OSError as exc:
                logger.debug("discovery: receive stopped: %s", exc)
                break
            try:
                device = parse_reply(data)
            except DiscoveryError as exc:
                logger.debug("discovery: invalid reply ignored: %s", exc)
                continue
            device["seen_ms"] = int(self._clock() * 1000)
            devices[device["mac"]] = device
        return list(devices.values())
