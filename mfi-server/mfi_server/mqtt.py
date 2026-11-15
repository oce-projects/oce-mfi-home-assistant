"""MQTT 3.1.1 (protocol level 4) client in pure Python: sockets and the standard library only.

The Home Assistant bridge uses it to publish device states and to receive output
commands. QoS 0 and QoS 1 are supported; TLS and QoS 2 are out of scope.
The password is never written to a log line.
"""
from __future__ import annotations

import logging
import socket
import threading
import time
from collections import deque
from collections.abc import Callable

logger = logging.getLogger(__name__)

PROTOCOL_NAME = b"\x00\x04MQTT"
PROTOCOL_LEVEL = 4
MAX_REMAINING_LENGTH = 268435455
MAX_STRING_BYTES = 65535

CONNECT = 1
CONNACK = 2
PUBLISH = 3
PUBACK = 4
SUBSCRIBE = 8
PINGREQ = 12
DISCONNECT = 14

FLAG_CLEAN_SESSION = 0x02
FLAG_WILL = 0x04
FLAG_WILL_RETAIN = 0x20
FLAG_PASSWORD = 0x40
FLAG_USERNAME = 0x80

CONNECT_TIMEOUT_S = 10.0
PUBACK_TIMEOUT_S = 10.0
POLL_INTERVAL_S = 1.0
RECONNECT_FIRST_S = 1
RECONNECT_MAX_S = 60


class MqttError(Exception):
    """The broker refused the connection; .code is the CONNACK return code."""

    def __init__(self, code: int) -> None:
        super().__init__(f"MQTT connection refused with code {code}")
        self.code = code


def encode_remaining_length(n: int) -> bytes:
    """Encode a packet length in the MQTT variable-length form (1 to 4 bytes)."""
    if n < 0 or n > MAX_REMAINING_LENGTH:
        raise ValueError("remaining length must be 0 to 268435455")
    out = bytearray()
    while True:
        digit = n % 128
        n //= 128
        if n > 0:
            digit |= 0x80
        out.append(digit)
        if n == 0:
            return bytes(out)


def _read_remaining_length(data: bytes, offset: int) -> tuple[int, int] | None:
    """Return (value, bytes_read), or None if the length bytes are not all there yet."""
    value = 0
    multiplier = 1
    for index in range(4):
        position = offset + index
        if position >= len(data):
            return None
        byte = data[position]
        value += (byte & 0x7F) * multiplier
        multiplier *= 128
        if not byte & 0x80:
            return value, index + 1
    raise ValueError("remaining length uses more than 4 bytes")


def decode_remaining_length(data: bytes, offset: int) -> tuple[int, int]:
    """Decode a variable-length packet length; return (value, bytes_read)."""
    decoded = _read_remaining_length(data, offset)
    if decoded is None:
        raise ValueError("remaining length is incomplete")
    return decoded


def _string(text: str) -> bytes:
    """Encode a UTF-8 string with its 2-byte length prefix."""
    raw = text.encode("utf-8")
    if len(raw) > MAX_STRING_BYTES:
        raise ValueError("MQTT string is longer than 65535 bytes")
    return len(raw).to_bytes(2, "big") + raw


def _binary(data: bytes) -> bytes:
    """Encode binary data with its 2-byte length prefix."""
    if len(data) > MAX_STRING_BYTES:
        raise ValueError("MQTT binary field is longer than 65535 bytes")
    return len(data).to_bytes(2, "big") + data


def _packet(packet_type: int, flags: int, body: bytes) -> bytes:
    """Frame a packet: fixed header byte, remaining length, body."""
    return bytes([(packet_type << 4) | flags]) + encode_remaining_length(len(body)) + body


def build_connect(
    client_id: str,
    username: str,
    password: str,
    keepalive: int,
    will_topic: str,
    will_payload: bytes,
) -> bytes:
    """Build a CONNECT packet: clean session, optional retained will, username and password."""
    if not 0 <= keepalive <= 65535:
        raise ValueError("keepalive must be 0 to 65535 seconds")
    flags = FLAG_CLEAN_SESSION
    payload = _string(client_id)
    if will_topic:
        flags |= FLAG_WILL | FLAG_WILL_RETAIN
        payload += _string(will_topic) + _binary(will_payload)
    if username:
        flags |= FLAG_USERNAME
        payload += _string(username)
    if password:
        flags |= FLAG_PASSWORD
        payload += _string(password)
    variable = PROTOCOL_NAME + bytes([PROTOCOL_LEVEL, flags]) + keepalive.to_bytes(2, "big")
    return _packet(CONNECT, 0, variable + payload)


def build_publish(
    topic: str,
    payload: bytes,
    qos: int = 0,
    retain: bool = False,
    packet_id: int | None = None,
) -> bytes:
    """Build a PUBLISH packet; QoS 1 needs a packet identifier from 1 to 65535."""
    if qos not in (0, 1):
        raise ValueError("qos must be 0 or 1")
    variable = _string(topic)
    if qos == 1:
        if packet_id is None or not 1 <= packet_id <= 65535:
            raise ValueError("QoS 1 needs a packet id from 1 to 65535")
        variable += packet_id.to_bytes(2, "big")
    flags = (qos << 1) | (1 if retain else 0)
    return _packet(PUBLISH, flags, variable + payload)


def build_subscribe(packet_id: int, topics: list[str]) -> bytes:
    """Build a SUBSCRIBE packet asking for QoS 0 on every topic."""
    if not topics:
        raise ValueError("SUBSCRIBE needs at least one topic")
    if not 1 <= packet_id <= 65535:
        raise ValueError("packet id must be 1 to 65535")
    body = packet_id.to_bytes(2, "big") + b"".join(_string(topic) + b"\x00" for topic in topics)
    return _packet(SUBSCRIBE, 0x02, body)


def build_pingreq() -> bytes:
    """Build a PINGREQ packet."""
    return _packet(PINGREQ, 0, b"")


def build_disconnect() -> bytes:
    """Build a DISCONNECT packet."""
    return _packet(DISCONNECT, 0, b"")


def parse_packet(data: bytes) -> tuple[int, int, bytes, int] | None:
    """Split the first packet of data into (packet_type, flags, body, consumed).

    Returns None while the packet is not complete.
    """
    if len(data) < 2:
        return None
    decoded = _read_remaining_length(data, 1)
    if decoded is None:
        return None
    length, used = decoded
    start = 1 + used
    end = start + length
    if len(data) < end:
        return None
    return data[0] >> 4, data[0] & 0x0F, data[start:end], end


class MqttClient:
    """One connection to a broker; use it from a single thread (the bridge thread)."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        client_id: str,
        on_message: Callable[[str, bytes], None],
        keepalive: int = 60,
        will_topic: str = "",
        will_payload: bytes = b"",
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.client_id = client_id
        self.on_message = on_message
        self.keepalive = keepalive
        self.will_topic = will_topic
        self.will_payload = will_payload
        self._sock: socket.socket | None = None
        self._buffer = b""
        self._inbox: deque[tuple[str, bytes]] = deque()
        self._subscriptions: list[str] = []
        self._last_packet_id = 0

    def connect(self) -> None:
        """Open the TCP connection and log in; raise MqttError(code) if the broker refuses."""
        self._close()
        sock = socket.create_connection((self.host, self.port), timeout=CONNECT_TIMEOUT_S)
        sock.settimeout(POLL_INTERVAL_S)
        self._sock = sock
        try:
            self._send(
                build_connect(
                    self.client_id,
                    self.username,
                    self.password,
                    self.keepalive,
                    self.will_topic,
                    self.will_payload,
                )
            )
            body = self._wait_for(CONNACK, CONNECT_TIMEOUT_S)
            if len(body) != 2:
                raise ConnectionError("malformed CONNACK from the broker")
            if body[1] != 0:
                raise MqttError(body[1])
        except Exception:
            self._close()
            raise
        logger.info("connected to the MQTT broker at %s:%d", self.host, self.port)

    def disconnect(self) -> None:
        """Send DISCONNECT if connected, then close the socket."""
        if self._sock is None:
            return
        try:
            self._send(build_disconnect())
        except OSError as exc:
            logger.debug("DISCONNECT not sent: %s", exc)
        self._close()

    def publish(self, topic: str, payload: bytes, qos: int = 0, retain: bool = False) -> None:
        """Publish one message; for QoS 1 wait for the PUBACK with the same packet id."""
        packet_id = self._next_packet_id() if qos == 1 else None
        self._send(build_publish(topic, payload, qos, retain, packet_id))
        if packet_id is not None:
            self._wait_for(PUBACK, PUBACK_TIMEOUT_S, packet_id)

    def subscribe(self, topics: list[str]) -> None:
        """Subscribe to topics with QoS 0; the subscriptions are renewed after a reconnect."""
        packet = build_subscribe(self._next_packet_id(), list(topics))
        self._send(packet)
        self._subscriptions = list(topics)

    def loop_forever(self, stop_event: threading.Event) -> None:
        """Deliver incoming messages until stop_event is set; reconnect with a growing delay."""
        delay = RECONNECT_FIRST_S
        while not stop_event.is_set():
            try:
                if self._sock is None:
                    self.connect()
                    delay = RECONNECT_FIRST_S
                    if self._subscriptions:
                        self._send(build_subscribe(self._next_packet_id(), self._subscriptions))
                self._pump(stop_event)
            except (OSError, MqttError, ValueError) as exc:
                self._close()
                logger.warning(
                    "MQTT connection lost (%s: %s), retry in %d s",
                    type(exc).__name__,
                    exc,
                    delay,
                )
                stop_event.wait(delay)
                delay = min(delay * 2, RECONNECT_MAX_S)
        self.disconnect()

    def _pump(self, stop_event: threading.Event) -> None:
        """Read and deliver packets, sending PINGREQ every keepalive seconds."""
        last_ping = time.monotonic()
        while not stop_event.is_set():
            packet = self._read_once()
            if packet is not None:
                self._dispatch(*packet)
            self._deliver_inbox()
            if self.keepalive > 0 and time.monotonic() - last_ping >= self.keepalive:
                self._send(build_pingreq())
                last_ping = time.monotonic()

    def _deliver_inbox(self) -> None:
        """Call on_message for every queued QoS 0 message; a failing handler is logged."""
        while self._inbox:
            topic, payload = self._inbox.popleft()
            try:
                self.on_message(topic, payload)
            except Exception as exc:
                logger.error("message handler failed: %s", type(exc).__name__)

    def _wait_for(self, packet_type: int, timeout_s: float, packet_id: int | None = None) -> bytes:
        """Read until the wanted packet arrives; other packets are queued or ignored."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            packet = self._read_once()
            if packet is None:
                continue
            ptype, flags, body = packet
            if ptype == packet_type and (packet_id is None or body[:2] == packet_id.to_bytes(2, "big")):
                return body
            self._dispatch(ptype, flags, body)
        raise TimeoutError(f"no answer from the broker for packet type {packet_type}")

    def _read_once(self) -> tuple[int, int, bytes] | None:
        """Return the next complete packet, or None if the socket timed out first."""
        packet = parse_packet(self._buffer)
        if packet is None:
            if self._sock is None:
                raise ConnectionError("not connected to the broker")
            try:
                chunk = self._sock.recv(4096)
            except socket.timeout:
                return None
            if not chunk:
                raise ConnectionError("the broker closed the connection")
            self._buffer += chunk
            packet = parse_packet(self._buffer)
            if packet is None:
                return None
        ptype, flags, body, consumed = packet
        self._buffer = self._buffer[consumed:]
        return ptype, flags, body

    def _dispatch(self, ptype: int, flags: int, body: bytes) -> None:
        """Queue an inbound QoS 0 PUBLISH; other packets need no action here."""
        if ptype != PUBLISH:
            return
        qos = (flags >> 1) & 0x03
        if qos != 0:
            logger.debug("ignored an inbound message with QoS %d", qos)
            return
        topic_length = int.from_bytes(body[:2], "big")
        topic = body[2 : 2 + topic_length].decode("utf-8")
        self._inbox.append((topic, body[2 + topic_length :]))

    def _send(self, data: bytes) -> None:
        """Send bytes on the open socket."""
        if self._sock is None:
            raise ConnectionError("not connected to the broker")
        self._sock.sendall(data)

    def _next_packet_id(self) -> int:
        """Return the next packet identifier, 1 to 65535 and then 1 again."""
        self._last_packet_id = self._last_packet_id % 65535 + 1
        return self._last_packet_id

    def _close(self) -> None:
        """Close the socket and forget any partial packet."""
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError as exc:
                logger.debug("closing the MQTT socket failed: %s", exc)
            self._sock = None
        self._buffer = b""
