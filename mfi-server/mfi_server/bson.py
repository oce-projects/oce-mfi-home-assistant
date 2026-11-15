"""Minimal BSON reader and writer for the .unf backup import.

The reader decodes the types used by mFi backups (0x01 to 0x12) and raises
BsonError on anything else or on any read outside the document. Integers are
little-endian, as in the BSON specification. The writer covers the types used
by tests and fixtures. Standard library only.
"""
from __future__ import annotations

import logging
import struct
from collections.abc import Iterator
from typing import Any

logger = logging.getLogger(__name__)

INT32_MIN = -(2**31)
INT32_MAX = 2**31 - 1
INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1
MAX_DEPTH = 100


class BsonError(ValueError):
    """Malformed, truncated or unsupported BSON data."""


class _Reader:
    """Cursor over one BSON buffer; every read stays below `end`."""

    def __init__(self, data: bytes, pos: int, end: int) -> None:
        self.data = data
        self.pos = pos
        self.end = end

    def take(self, size: int) -> bytes:
        if size < 0 or self.pos + size > self.end:
            raise BsonError(f"read of {size} bytes at offset {self.pos} is outside the document")
        chunk = self.data[self.pos:self.pos + size]
        self.pos += size
        return chunk

    def unpack(self, fmt: str) -> Any:
        raw = self.take(struct.calcsize(fmt))
        try:
            return struct.unpack(fmt, raw)[0]
        except struct.error as exc:
            raise BsonError(f"bad value at offset {self.pos}") from exc

    def cstring(self) -> str:
        start = self.pos
        nul = self.data.find(b"\x00", self.pos, self.end)
        if nul < 0:
            raise BsonError(f"unterminated name at offset {start}")
        raw = self.data[start:nul]
        self.pos = nul + 1
        return _decode_text(raw, start)


def _decode_text(raw: bytes, offset: int) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BsonError(f"invalid UTF-8 at offset {offset}") from exc


def _read_string(r: _Reader) -> str:
    start = r.pos
    length = r.unpack("<i")
    if length < 1:
        raise BsonError(f"string length {length} at offset {start} is below 1")
    raw = r.take(length)
    if raw[-1] != 0:
        raise BsonError(f"string at offset {start} is not 0x00 terminated")
    return _decode_text(raw[:-1], start)


def _read_container(r: _Reader, depth: int = 0) -> list[tuple[str, Any]]:
    if depth > MAX_DEPTH:
        raise BsonError(f"document nested deeper than {MAX_DEPTH}")
    start = r.pos
    length = r.unpack("<i")
    end = start + length
    if length < 5 or end > r.end:
        raise BsonError(f"document length {length} at offset {start} does not fit the data")
    if r.data[end - 1] != 0:
        raise BsonError(f"document at offset {start} does not end with 0x00")
    inner = _Reader(r.data, r.pos, end - 1)
    pairs: list[tuple[str, Any]] = []
    while inner.pos < inner.end:
        type_pos = inner.pos
        type_byte = inner.take(1)[0]
        name = inner.cstring()
        pairs.append((name, _read_value(inner, type_byte, type_pos, depth)))
    r.pos = end
    return pairs


def _read_value(r: _Reader, type_byte: int, type_pos: int, depth: int = 0) -> Any:
    if type_byte == 0x01:
        return r.unpack("<d")
    if type_byte == 0x02:
        return _read_string(r)
    if type_byte == 0x03:
        return dict(_read_container(r, depth + 1))
    if type_byte == 0x04:
        return [value for _, value in _read_container(r, depth + 1)]
    if type_byte == 0x05:
        size = r.unpack("<i")
        r.take(1)  # binary subtype, not kept
        return r.take(size)
    if type_byte == 0x07:
        return r.take(12).hex()
    if type_byte == 0x08:
        return r.take(1)[0] != 0
    if type_byte == 0x09:
        return r.unpack("<q")
    if type_byte == 0x0A:
        return None
    if type_byte == 0x10:
        return r.unpack("<i")
    if type_byte == 0x11:
        return r.unpack("<Q")
    if type_byte == 0x12:
        return r.unpack("<q")
    raise BsonError(f"unknown BSON type 0x{type_byte:02x} at offset {type_pos}")


def iter_documents(data: bytes) -> Iterator[dict]:
    """Yield each document stored back to back in `data`."""
    offset = 0
    while offset < len(data):
        reader = _Reader(data, offset, len(data))
        yield dict(_read_container(reader))
        offset = reader.pos


def encode_document(doc: dict) -> bytes:
    """Encode a dict as one BSON document."""
    body = bytearray()
    for key, value in doc.items():
        body += _encode_element(key, value)
    body += b"\x00"
    return struct.pack("<i", len(body) + 4) + bytes(body)


def _cstring(name: Any) -> bytes:
    if not isinstance(name, str):
        raise BsonError(f"document key must be str, got {type(name).__name__}")
    try:
        raw = name.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise BsonError(f"key {name!r} is not valid UTF-8") from exc
    if b"\x00" in raw:
        raise BsonError(f"key {name!r} contains a 0x00 byte")
    return raw + b"\x00"


def _encode_string(value: str) -> bytes:
    try:
        raw = value.encode("utf-8") + b"\x00"
    except UnicodeEncodeError as exc:
        raise BsonError("string is not valid UTF-8") from exc
    return struct.pack("<i", len(raw)) + raw


def _encode_element(name: Any, value: Any) -> bytes:
    key = _cstring(name)
    if value is None:
        return b"\x0a" + key
    if isinstance(value, bool):
        return b"\x08" + key + (b"\x01" if value else b"\x00")
    if isinstance(value, int):
        if INT32_MIN <= value <= INT32_MAX:
            return b"\x10" + key + struct.pack("<i", value)
        if INT64_MIN <= value <= INT64_MAX:
            return b"\x12" + key + struct.pack("<q", value)
        raise BsonError(f"integer {value} does not fit in int64")
    if isinstance(value, float):
        return b"\x01" + key + struct.pack("<d", value)
    if isinstance(value, str):
        return b"\x02" + key + _encode_string(value)
    if isinstance(value, dict):
        return b"\x03" + key + encode_document(value)
    if isinstance(value, (list, tuple)):
        return b"\x04" + key + encode_document({str(i): item for i, item in enumerate(value)})
    if isinstance(value, bytes):
        return b"\x05" + key + struct.pack("<i", len(value)) + b"\x00" + value
    raise BsonError(f"unsupported value type {type(value).__name__} for key {name!r}")
