"""Inform packets of mFi devices (TNBU format): parse, decrypt and encrypt.

Layout (docs/PROTOCOL.md, "Packet format"): a 40-byte header, then the payload.
The payload is AES-128-CBC with the IV from the header and PKCS#7 padding, and
it is zlib-compressed when FLAG_COMPRESSED is set. A response reuses the magic,
version, MAC, flags, IV and data version of the request.
Standard library only.
"""
from __future__ import annotations

import json
import logging
import re
import struct
import zlib
from dataclasses import dataclass

from mfi_server.aes import decrypt_cbc, encrypt_cbc, pkcs7_pad, pkcs7_unpad

logger = logging.getLogger(__name__)

MAGIC = 1414414933
HEADER_LEN = 40
FLAG_ENCRYPTED = 0x1
FLAG_COMPRESSED = 0x2
DEFAULT_KEY_HEX = "ba86f2bbe107c7c57eb5f2690775c712"
HEADER_STRUCT = struct.Struct(">II6sH16sII")
BLOCK_SIZE = 16
MAC_LEN = 6
IV_LEN = 16
MAX_DATA_VERSION = 1
MAX_JSON_BYTES = 262144
_MAC_RE = re.compile(r"[0-9a-f]{12}")


class PacketError(Exception):
    """A packet the server does not accept; status is the HTTP status to answer with."""

    def __init__(self, reason: str, status: int = 400) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status = status


@dataclass(frozen=True)
class InformHeader:
    """Fixed 40-byte header of an inform packet."""

    version: int
    mac: bytes
    flags: int
    iv: bytes
    data_version: int
    data_length: int


def normalize_mac(value: str) -> str:
    """Return a MAC as 12 lower-case hex digits, without ':' or '-'."""
    if not isinstance(value, str):
        raise ValueError("mac must be a string")
    text = value.lower().replace(":", "").replace("-", "")
    if not _MAC_RE.fullmatch(text):
        raise ValueError("mac must be 12 hex digits")
    return text


def parse_header(data: bytes) -> InformHeader:
    """Read and check the header; the payload is not touched."""
    if len(data) < HEADER_LEN:
        raise PacketError("header is too short")
    magic, version, mac, flags, iv, data_version, data_length = HEADER_STRUCT.unpack_from(data, 0)
    if magic != MAGIC:
        raise PacketError("bad packet magic")
    if data_version > MAX_DATA_VERSION:
        raise PacketError("unsupported data version")
    return InformHeader(
        version=version,
        mac=mac,
        flags=flags,
        iv=iv,
        data_version=data_version,
        data_length=data_length,
    )


def decode(data: bytes, keys: list[bytes]) -> tuple[InformHeader, dict, bytes]:
    """Return (header, payload, key) for the first key that decrypts the packet."""
    header = parse_header(data)
    payload = data[HEADER_LEN:HEADER_LEN + header.data_length]
    if len(payload) < header.data_length:
        raise PacketError("truncated payload")
    if not (header.flags & FLAG_ENCRYPTED):
        raise PacketError("unencrypted packet not accepted")
    if not payload or len(payload) % BLOCK_SIZE:
        raise PacketError("bad payload length")
    for key in keys:
        message = _try_key(key, header, payload)
        if message is not None:
            return header, message, key
    raise PacketError(f"inform decrypt error (tried all {len(keys)} keys)")


def _try_key(key: bytes, header: InformHeader, payload: bytes) -> dict | None:
    """Decrypt with one key; return the JSON object, or None if this key is wrong."""
    plain = decrypt_cbc(key, header.iv, payload)
    try:
        body = pkcs7_unpad(plain)
    except ValueError:
        logger.debug("bad padding, trying to recover")
        body = plain.rstrip(b"\x00")
    if header.flags & FLAG_COMPRESSED:
        decompressor = zlib.decompressobj()
        try:
            body = decompressor.decompress(body, MAX_JSON_BYTES)
        except zlib.error:
            logger.debug("inflate failed for one key")
            return None
        if decompressor.unconsumed_tail:
            logger.debug("compressed payload above the size limit, rejecting")
            return None
    try:
        message = json.loads(body.decode("utf-8"))
    except ValueError:
        logger.debug("one key did not give valid JSON")
        return None
    if not isinstance(message, dict):
        logger.debug("one key did not give a JSON object")
        return None
    return message


def encode(
    mac: bytes,
    key: bytes,
    payload: dict,
    iv: bytes,
    flags: int = FLAG_ENCRYPTED,
    version: int = 0,
    data_version: int = 1,
) -> bytes:
    """Build one packet: header, then the encrypted (and optionally compressed) JSON."""
    if not isinstance(mac, bytes) or len(mac) != MAC_LEN:
        raise ValueError("mac must be 6 bytes")
    if not isinstance(iv, bytes) or len(iv) != IV_LEN:
        raise ValueError("iv must be 16 bytes")
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    if flags & FLAG_COMPRESSED:
        body = zlib.compress(body)
    cipher = encrypt_cbc(key, iv, pkcs7_pad(body))
    header = HEADER_STRUCT.pack(MAGIC, version, mac, flags, iv, data_version, len(cipher))
    return header + cipher


def encode_response(header: InformHeader, key: bytes, payload: dict) -> bytes:
    """Answer a request: same MAC, version, IV and data version, encrypted with key."""
    return encode(
        header.mac,
        key,
        payload,
        header.iv,
        flags=FLAG_ENCRYPTED,
        version=header.version,
        data_version=header.data_version,
    )
