"""Inform protocol: decrypt a device packet and build the answer. Clean room, standard library only.

Packet layout (docs/PROTOCOL.md, "Packet format"): a 40-byte header, then the payload.
The payload is AES-128-CBC with the IV of the header and PKCS#7 padding, and it is
zlib-compressed when FLAG_COMPRESSED is set. The answer reuses the magic, version, MAC,
IV and data version of the request. The answer choice follows the observed subset of
docs/PROTOCOL.md, "Controller responses". Lines marked UNVERIFIED need a recording from a device.
"""
from __future__ import annotations

import http.server
import json
import logging
import re
import struct
import time
import zlib
from typing import NamedTuple

from mfi_server_next import crypto, devices, firmware, tasks as task_queue

logger = logging.getLogger(__name__)

FACTORY_KEY_HEX = "ba86f2bbe107c7c57eb5f2690775c712"
FACTORY_KEY = bytes.fromhex(FACTORY_KEY_HEX)
MAGIC = 1414414933
HEADER_LEN = 40
HEADER_STRUCT = struct.Struct(">II6sH16sII")
FLAG_ENCRYPTED = 0x1
FLAG_COMPRESSED = 0x2
MAX_DATA_VERSION = 1
MAX_JSON_BYTES = 262144
MAX_REQUEST_BYTES = 262144
AUTHKEY_RE = re.compile(r"[0-9a-f]{32}")
INFORM_PORT = 6080
INFORM_PATH = "/inform"
NOOP_INTERVAL_S = 10
RESPONSE_CONTENT_TYPE = "application/x-binary"


class InformError(Exception):
    """A packet the server does not accept; status is the HTTP status to answer with."""

    def __init__(self, reason: str, status: int = 400) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status = status


class InformHeader(NamedTuple):
    """Fixed 40-byte header of an inform packet."""

    version: int
    mac: bytes
    flags: int
    iv: bytes
    data_version: int
    data_length: int


def parse_header(data: bytes) -> InformHeader:
    """Read and check the 40-byte header; the payload is not touched."""
    if len(data) < HEADER_LEN:
        raise InformError("header is too short")
    magic, version, mac, flags, iv, data_version, data_length = HEADER_STRUCT.unpack_from(data, 0)
    if magic != MAGIC:
        raise InformError("bad packet magic")
    if data_version > MAX_DATA_VERSION:
        raise InformError("unsupported data version")
    return InformHeader(version, mac, flags, iv, data_version, data_length)


def candidate_keys(record: dict | None) -> list[bytes]:
    """Return the keys to try for a device, in order: previous key, current key, factory key."""
    if record is None:
        return [FACTORY_KEY]
    keys = []
    for name in ("x_prev_authkey", "x_authkey"):
        value = record.get(name)
        if value is None:
            continue
        if not isinstance(value, str) or AUTHKEY_RE.fullmatch(value) is None:
            raise ValueError(f"{name} must be 32 lowercase hex characters")
        keys.append(bytes.fromhex(value))
    keys.append(FACTORY_KEY)
    return keys


def _try_key(key: bytes, header: InformHeader, payload: bytes) -> dict | None:
    """Decrypt with one key; return the JSON object, or None when this key is wrong."""
    try:
        body = crypto.aes128_decrypt(key, header.iv, payload)
    except ValueError:
        # Bad padding: keep the raw blocks, as the controller does; a wrong key fails the JSON check below.
        body = crypto.aes128_decrypt(key, header.iv, payload, unpad=False).rstrip(b"\x00")
    if header.flags & FLAG_COMPRESSED:
        inflater = zlib.decompressobj()
        try:
            body = inflater.decompress(body, MAX_JSON_BYTES)
        except zlib.error:
            return None
        if inflater.unconsumed_tail:
            return None
    try:
        message = json.loads(body.decode("utf-8"))
    except (ValueError, RecursionError):
        return None
    if not isinstance(message, dict):
        return None
    return message


def decode(data: bytes, keys: list[bytes]) -> tuple[InformHeader, dict, bytes]:
    """Return (header, payload, key) for the first key that decrypts the packet; InformError otherwise."""
    header = parse_header(data)
    if not (header.flags & FLAG_ENCRYPTED):
        raise InformError("unencrypted packet not accepted")
    payload = data[HEADER_LEN:HEADER_LEN + header.data_length]
    if len(payload) < header.data_length:
        raise InformError("truncated payload")
    if not payload or len(payload) % crypto.BLOCK_SIZE:
        raise InformError("bad payload length")
    for key in keys:
        message = _try_key(key, header, payload)
        if message is not None:
            return header, message, key
    logger.warning("inform decrypt error (tried all %d keys)", len(keys))
    raise InformError("inform decrypt error")


def encode_response(header: InformHeader, key: bytes, payload: dict) -> bytes:
    """Build the answer: same magic, version, MAC, IV and data version as the request, encrypted with key."""
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    cipher = crypto.aes128_encrypt(key, header.iv, body)
    head = HEADER_STRUCT.pack(
        MAGIC,
        header.version,
        header.mac,
        FLAG_ENCRYPTED,
        header.iv,
        header.data_version,
        len(cipher),
    )
    return head + cipher


def _device_of(registry: devices.DeviceRegistry | None, mac) -> dict | None:
    """Return the record of mac, or None when there is no registry or the MAC is not valid."""
    if registry is None or not isinstance(mac, str):
        return None
    try:
        return registry.get(mac)
    except ValueError:
        return None


def _noop() -> dict:
    # UNVERIFIED (needs device test R-POWER): the 10 s interval is the value the controller
    # bytecode always sends (docs/PROTOCOL.md, "Controller responses"); the heartbeat timing is not seen on a device.
    return {"_type": "noop", "interval": NOOP_INTERVAL_S}


def handle_inform(payload=None, registry=None, tasks: task_queue.TaskQueue | None = None) -> dict:
    """Choose the answer to one inform payload. Always returns a dict whose "_type" is a str.

    Rules in the order of docs/PROTOCOL.md, "Controller responses": a payload that is not an
    object gets a noop; a device that is not adopted gets setdefault unless it declares default;
    then upgrade, setparam, a queued command, and noop.
    """
    if not isinstance(payload, dict):
        return _noop()
    mac = payload.get("mac")
    device = _device_of(registry, mac)
    adopted = bool(device and device.get("adopted"))
    if not adopted and payload.get("default") is not True:
        return {"_type": "setdefault"}
    if adopted and device.get("auto_upgrade"):
        upgrade = firmware.build_upgrade(payload.get("model"))
        # UNVERIFIED (needs device test R-UPDATE): the version is compared as a plain string with
        # FIRMWARE_VERSION; the controller reads the version as numbers (docs/PROTOCOL.md, "Firmware archive").
        if upgrade is not None and payload.get("version") != firmware.FIRMWARE_VERSION:
            return upgrade
    if adopted and payload.get("cfgversion") != device.get("cfgversion"):
        return {"_type": "setparam", "cfgversion": device.get("cfgversion")}
    if adopted and tasks is not None:
        task = tasks.pop_for_mac(mac)
        if task is not None:
            # A queued task is delivered once; it is a cmd unless it says otherwise.
            return {"_type": "cmd", **task}
    return _noop()


def build_inform_response(raw: bytes, registry, tasks: task_queue.TaskQueue | None = None, *, host="mfi-server", port=INFORM_PORT) -> tuple[int, bytes]:
    """Decrypt one inform packet and return (status, body) for the HTTP answer.

    A packet that cannot be decrypted, or whose payload MAC differs from the header MAC,
    gets (400, b""). The reason is logged and never sent back.
    """
    try:
        mac = parse_header(raw).mac.hex()
        header, payload, key = decode(raw, candidate_keys(_device_of(registry, mac)))
        if payload.get("mac") != mac:
            raise InformError("payload mac differs from the header mac")
    except InformError as exc:
        logger.warning("inform rejected: %s", exc.reason)
        return exc.status, b""
    reply = handle_inform(payload, registry, tasks)
    if reply.get("_type") == "upgrade":
        upgrade = firmware.build_upgrade(payload.get("model"), host=host, port=port)
        if upgrade is not None:
            reply = upgrade
    reply["server_time_in_utc"] = str(int(time.time() * 1000))
    return 200, encode_response(header, key, reply)


def make_server(registry, tasks: task_queue.TaskQueue | None = None, host="127.0.0.1", port=0) -> http.server.ThreadingHTTPServer:
    """Return a server that is not started yet; it answers POST /inform through build_inform_response."""

    class InformHandler(http.server.BaseHTTPRequestHandler):
        server_version = "mfi-server"
        sys_version = ""

        def do_POST(self) -> None:
            if self.path != INFORM_PATH:
                self.send_error(404)
                return
            length_text = self.headers.get("Content-Length", "")
            if not length_text.isdigit():
                self.send_error(400)
                return
            length = int(length_text)
            if length > MAX_REQUEST_BYTES:
                self.send_error(413)
                return
            status, body = build_inform_response(self.rfile.read(length), registry, tasks)
            self.send_response(status)
            self.send_header("Content-Type", RESPONSE_CONTENT_TYPE)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args) -> None:
            logger.debug(fmt, *args)

    return http.server.ThreadingHTTPServer((host, port), InformHandler)
