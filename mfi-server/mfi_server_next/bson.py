"""BSON reader for the .unf backup import. Standard library only."""
from __future__ import annotations

import struct
from typing import Any

MAX_DEPTH = 100


class BsonError(ValueError):
    """Truncated or malformed BSON data."""


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
        return struct.unpack(fmt, raw)[0]

    def cstring(self) -> str:
        start = self.pos
        nul = self.data.find(b"\x00", self.pos, self.end)
        if nul < 0:
            raise BsonError(f"unterminated name at offset {start}")
        self.pos = nul + 1
        return _decode_text(self.data[start:nul], start)


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


def _read_pairs(r: _Reader, depth: int) -> list[tuple[str, Any]]:
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


def _read_value(r: _Reader, type_byte: int, type_pos: int, depth: int) -> Any:
    if type_byte == 0x01:
        return r.unpack("<d")
    if type_byte == 0x02:
        return _read_string(r)
    if type_byte == 0x03:
        return dict(_read_pairs(r, depth + 1))
    if type_byte == 0x04:
        return [value for _, value in _read_pairs(r, depth + 1)]
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
    if type_byte == 0x12:
        return r.unpack("<q")
    raise BsonError(f"unknown BSON type 0x{type_byte:02x} at offset {type_pos}")


def read_bson_stream(fileobj) -> list[dict]:
    """Read every BSON document stored back to back in a binary file object."""
    data = fileobj.read()
    documents: list[dict] = []
    offset = 0
    while offset < len(data):
        reader = _Reader(data, offset, len(data))
        documents.append(dict(_read_pairs(reader, 0)))
        offset = reader.pos
    return documents
