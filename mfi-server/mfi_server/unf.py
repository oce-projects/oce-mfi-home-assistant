"""Import of mFi controller backups (.unf): device keys and sensor ports.

A backup is AES-128-CBC with the public UniFi backup key and IV, wrapping a
ZIP that holds db.gz: gzip-compressed MongoDB BSON documents, one collection
after another. Real backups cannot be read with zipfile (docs/PROTOCOL.md),
so the local file headers are read one by one and inflated with zlib.
The backup contains device keys: they are returned in the records of
import_backup and never logged. Standard library only.
"""
from __future__ import annotations

import gzip
import logging
import re
import struct
import zlib

from mfi_server.aes import BLOCK_SIZE, decrypt_cbc
from mfi_server.bson import BsonError, iter_documents
from mfi_server.packet import normalize_mac

logger = logging.getLogger(__name__)

UNF_KEY = b"bcyangkmluohmars"
UNF_IV = b"ubntenterpriseap"
LOCAL_SIG = 0x04034B50
DESCRIPTOR_SIG = 0x08074B50
LOCAL_HEADER = struct.Struct("<IHHHHHIIIHH")
FLAG_DATA_DESCRIPTOR = 0x08
METHOD_STORED = 0
METHOD_DEFLATED = 8
_AUTHKEY_RE = re.compile(r"[0-9a-f]{32}")


class UnfError(ValueError):
    """A backup that cannot be decrypted, unpacked or read."""


def decrypt_unf(data: bytes) -> bytes:
    """Decrypt the whole blocks of a backup; the padding is not removed."""
    usable = len(data) - len(data) % BLOCK_SIZE
    if usable == 0:
        raise UnfError("backup is too short")
    return decrypt_cbc(UNF_KEY, UNF_IV, data[:usable])


def read_zip_entries(data: bytes) -> dict[str, bytes]:
    """Return {name: content} of the local entries, stopping at the first other signature."""
    entries: dict[str, bytes] = {}
    offset = 0
    while offset + 4 <= len(data) and struct.unpack_from("<I", data, offset)[0] == LOCAL_SIG:
        if offset + LOCAL_HEADER.size > len(data):
            raise UnfError("truncated local file header")
        _, _, flags, method, _, _, _, comp_size, _, name_len, extra_len = LOCAL_HEADER.unpack_from(data, offset)
        name_start = offset + LOCAL_HEADER.size
        start = name_start + name_len + extra_len
        if start > len(data):
            raise UnfError("truncated local file header")
        name = data[name_start:name_start + name_len].decode("utf-8", errors="replace")
        if flags & FLAG_DATA_DESCRIPTOR:
            content, offset = _read_with_descriptor(data, start, method, name)
        else:
            content = _read_plain(data, start, comp_size, method, name)
            offset = start + comp_size
        entries[name] = content
    return entries


def _read_plain(data: bytes, start: int, comp_size: int, method: int, name: str) -> bytes:
    """Return the content of an entry whose size is in its local header."""
    comp = data[start:start + comp_size]
    if len(comp) != comp_size:
        raise UnfError(f"truncated entry {name!r}")
    if method == METHOD_STORED:
        return comp
    if method == METHOD_DEFLATED:
        try:
            return zlib.decompress(comp, -15)
        except zlib.error as exc:
            raise UnfError(f"bad deflate data in {name!r}") from exc
    raise UnfError(f"unsupported compression method {method} in {name!r}")


def _read_with_descriptor(data: bytes, start: int, method: int, name: str) -> tuple[bytes, int]:
    """Inflate an entry whose size is in the data descriptor after it; return (content, next offset)."""
    if method != METHOD_DEFLATED:
        raise UnfError(f"entry {name!r} has a data descriptor but method {method}")
    decoder = zlib.decompressobj(-15)
    try:
        content = decoder.decompress(data[start:])
    except zlib.error as exc:
        raise UnfError(f"bad deflate data in {name!r}") from exc
    if not decoder.eof:
        raise UnfError(f"truncated entry {name!r}")
    end = len(data) - len(decoder.unused_data)
    if data[end:end + 4] == struct.pack("<I", DESCRIPTOR_SIG):
        return content, end + 16
    return content, end + 12


def import_backup(data: bytes) -> list[dict]:
    """Return the devices of a backup, each with its authkey and its sensor ports sorted by port."""
    entries = read_zip_entries(decrypt_unf(data))
    if "db.gz" not in entries:
        raise UnfError("db.gz not found in backup")
    try:
        raw = gzip.decompress(entries["db.gz"])
    except (OSError, EOFError, zlib.error) as exc:
        raise UnfError("db.gz is not valid gzip") from exc
    devices: dict[str, dict] = {}
    sensors: list[dict] = []
    collection = None
    try:
        for doc in iter_documents(raw):
            if doc.get("__cmd") == "select":
                collection = doc.get("collection")
            elif collection == "device":
                _add_device(devices, doc)
            elif collection == "sensor":
                sensors.append(doc)
    except BsonError as exc:
        raise UnfError(f"db.gz is not valid BSON: {exc}") from exc
    for doc in sensors:
        _attach_sensor(devices, doc)
    for device in devices.values():
        device["ports"].sort(key=lambda port: port["port"])
    return [devices[mac] for mac in sorted(devices)]


def _add_device(devices: dict[str, dict], doc: dict) -> None:
    """Store one device document; a device without a valid MAC is skipped."""
    try:
        mac = normalize_mac(doc.get("mac"))
    except ValueError:
        logger.warning("skipped device without a valid MAC")
        return
    authkey = str(doc.get("x_authkey", "")).lower()
    if not _AUTHKEY_RE.fullmatch(authkey):
        logger.debug("device without a valid authkey is stored with an empty key")
        authkey = ""
    devices[mac] = {
        "mac": mac,
        "model": str(doc.get("model", "")),
        "name": str(doc.get("name", "")),
        "authkey": authkey,
        "ports": [],
        "state": "unknown",
        "last_seen_ms": 0,
    }


def _attach_sensor(devices: dict[str, dict], doc: dict) -> None:
    """Add one sensor document as a port of its device; orphan or incomplete sensors are skipped."""
    try:
        mac = normalize_mac(doc.get("mac"))
        port = int(doc["port"])
        sensor_id = str(doc["_id"])
    except (KeyError, TypeError, ValueError):
        logger.debug("skipped sensor without a valid MAC, port or id")
        return
    device = devices.get(mac)
    if device is None:
        logger.debug("skipped sensor of a device not in the backup")
        return
    device["ports"].append({
        "port": port,
        "sensor_id": sensor_id,
        "label": str(doc.get("label", "")),
        "model": str(doc.get("model", "")),
    })
