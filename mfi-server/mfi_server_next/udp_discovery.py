"""UDP discovery of mFi devices on port 10001 (udp_discovery, new server).

A device answers the 4-byte query with a 4-byte header (version, command, length)
and TLV fields (type 1 byte, length 2 bytes big endian, data). Layout from
docs/PROTOCOL.md (Discovery). Standard library only.
"""
from __future__ import annotations

import math
import re
import socket
import struct
import time

DISCOVERY_PORT = 10001
BROADCAST_ADDRESS = "255.255.255.255"
MULTICAST_ADDRESS = "233.89.188.1"
DEFAULT_ADDRESSES = (BROADCAST_ADDRESS, MULTICAST_ADDRESS)
DEFAULT_TIMEOUT_S = 3.0
SOCKET_TIMEOUT_S = 0.5
RECV_SIZE = 2048
QUERY = b"\x01\x00\x00\x00"
HEADER_SIZE = 4
TLV_HEADER_SIZE = 3
MAC_SIZE = 6
IP_SIZE = 4
TYPE_MAC = 1
TYPE_MAC_IP = 2
TYPE_VERSION = 3
TYPE_HOSTNAME = 11
TYPE_PLATFORM = 12
TYPE_ESSID = 13
TYPE_MODEL = 21
TYPE_FIRMWARE = 22
TYPE_DEFAULT = 23
FIRMWARE_RE = re.compile(r"\.v(\d+\.\d+\.\d+(?:\.\d+)?)")


class UdpDiscoveryError(OSError):
    """The query could not be sent or the replies could not be read."""


def build_request() -> bytes:
    """Return the 4-byte discovery query: version 1, command 0, length 0."""
    return QUERY


def parse_reply(data: bytes) -> dict:
    """Split one reply into its header and raw TLV fields; raise ValueError when it is truncated."""
    if len(data) < HEADER_SIZE:
        raise ValueError(f"discovery reply is {len(data)} bytes, the header needs {HEADER_SIZE}")
    version, command = data[0], data[1]
    (length,) = struct.unpack(">H", data[2:4])
    body = data[HEADER_SIZE:]
    if len(body) < length:
        raise ValueError(f"discovery reply declares {length} bytes of fields, {len(body)} are present")
    body = body[:length]
    fields = []
    pos = 0
    while pos < len(body):
        if len(body) - pos < TLV_HEADER_SIZE:
            raise ValueError("discovery reply ends inside a TLV header")
        tlv_type, tlv_len = struct.unpack(">BH", body[pos:pos + TLV_HEADER_SIZE])
        pos += TLV_HEADER_SIZE
        if tlv_len > len(body) - pos:
            raise ValueError(f"TLV type {tlv_type} declares {tlv_len} bytes, {len(body) - pos} are left")
        fields.append({"type": tlv_type, "data": body[pos:pos + tlv_len]})
        pos += tlv_len
    return {"version": version, "command": command, "length": length, "fields": fields}


def _mac(raw: bytes | None) -> str | None:
    """Return the first six bytes as hex without colons, or None when there are too few."""
    if raw is None or len(raw) < MAC_SIZE:
        return None
    return raw[:MAC_SIZE].hex()


def _text(raw: bytes | None) -> str | None:
    """Decode a text field; NUL padding and empty text become None."""
    if raw is None:
        return None
    return raw.decode("utf-8", errors="replace").rstrip("\x00") or None


def device_info(fields: list[dict]) -> dict:
    """Return the device described by the TLV fields of one reply.

    Model and firmware fall back to the platform (12) and the version string (3)
    when fields 21 and 22 are missing; the default flag stays None without field 23.
    Field 14 and uptime (10) are not returned; they stay in the raw fields of parse_reply.
    """
    values: dict[int, bytes] = {}
    for field in fields:
        values.setdefault(field["type"], field["data"])
    mac_ip = values.get(TYPE_MAC_IP)
    mac = _mac(values.get(TYPE_MAC)) or _mac(mac_ip)
    ip = None
    if mac_ip is not None and len(mac_ip) >= MAC_SIZE + IP_SIZE:
        ip = ".".join(str(octet) for octet in mac_ip[MAC_SIZE:MAC_SIZE + IP_SIZE])
    platform = _text(values.get(TYPE_PLATFORM))
    firmware = _text(values.get(TYPE_FIRMWARE))
    if firmware is None:
        match = FIRMWARE_RE.search(_text(values.get(TYPE_VERSION)) or "")
        firmware = match.group(1) if match else None
    default = None
    if values.get(TYPE_DEFAULT):
        default = values[TYPE_DEFAULT][0] != 0
    return {
        "mac": mac,
        "ip": ip,
        "hostname": _text(values.get(TYPE_HOSTNAME)),
        "platform": platform,
        "model": _text(values.get(TYPE_MODEL)) or platform,
        "firmware": firmware,
        "essid": _text(values.get(TYPE_ESSID)),
        "default": default,
    }


def _udp_socket() -> socket.socket:
    """Return a new UDP socket for IPv4."""
    return socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


class UdpDiscovery:
    """Sends the discovery query and collects the devices that answer."""

    def __init__(self, addresses=DEFAULT_ADDRESSES, port=DISCOVERY_PORT, sock_factory=None, clock=time.monotonic) -> None:
        self._addresses = tuple(addresses)
        self._port = port
        self._sock_factory = sock_factory or _udp_socket
        self._clock = clock

    def scan(self, timeout: float = DEFAULT_TIMEOUT_S) -> list[dict]:
        """Return the devices that answered within timeout seconds, one entry per MAC."""
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("discovery timeout must be a finite number of seconds above 0")
        try:
            sock = self._sock_factory()
        except OSError as exc:
            raise UdpDiscoveryError(f"discovery: cannot open a UDP socket: {exc}") from exc
        try:
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                sock.settimeout(SOCKET_TIMEOUT_S)
            except OSError as exc:
                raise UdpDiscoveryError(f"discovery: cannot configure the UDP socket: {exc}") from exc
            self._send_query(sock)
            return self._collect(sock, timeout)
        finally:
            sock.close()

    def _send_query(self, sock) -> None:
        for address in self._addresses:
            try:
                sock.sendto(build_request(), (address, self._port))
            except OSError as exc:
                raise UdpDiscoveryError(f"discovery: the query to {address}:{self._port} failed: {exc}") from exc

    def _collect(self, sock, timeout: float) -> list[dict]:
        deadline = self._clock() + timeout
        devices: dict[str, dict] = {}
        while self._clock() < deadline:
            try:
                data, _ = sock.recvfrom(RECV_SIZE)
            except socket.timeout:
                continue
            except OSError as exc:
                raise UdpDiscoveryError(f"discovery: reading the replies failed: {exc}") from exc
            try:
                info = device_info(parse_reply(data)["fields"])
            except ValueError:
                continue
            if info["mac"] is not None:
                devices[info["mac"]] = info
        return list(devices.values())
