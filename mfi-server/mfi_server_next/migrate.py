"""Migration of the data of the previous controller into the new store. Implemented in EPIC-10."""
import re
import gzip
import io
import os
import shutil
import sqlite3
import struct
import time
import zlib
from pathlib import Path

from mfi_server_next import bson, config, crypto, store

UNF_KEY = b"bcyangkmluohmars"
UNF_IV = b"ubntenterpriseap"
BACKUP_SUFFIX = ".bak"
DEVICE_DEFAULTS = {"x_prev_authkey": None, "cfgversion": None, "portversion": None, "version": None}
DEVICES_FILE = "devices.json"
AUTOMATIONS_FILE = "automations.json"
RAW_TABLE_DDL = (
    "CREATE TABLE IF NOT EXISTS raw("
    "mac TEXT NOT NULL, sensor_id TEXT NOT NULL, tag TEXT NOT NULL, "
    "time_ms INTEGER NOT NULL, value REAL NOT NULL)"
)
RAW_INDEX_DDL = "CREATE INDEX IF NOT EXISTS raw_series ON raw(mac, sensor_id, tag, time_ms)"
SECRET_WORDS = ("password", "authkey", "key", "secret", "token")
LOG_TAIL_LINES = 200
SCRUB_RE = re.compile(
    r"[0-9a-fA-F]{32}"
    r"|(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}"
    r"|[0-9a-fA-F]{12}"
)
MAC_HEX_RE = re.compile(r"[0-9a-f]{12}")
AUTHKEY_RE = re.compile(r"[0-9a-f]{32}")
_LOCAL_SIG = 0x04034B50
_DESCRIPTOR_SIG = 0x08074B50
_LOCAL_HEADER = struct.Struct("<IHHHHHIIIHH")
_FLAG_DATA_DESCRIPTOR = 0x08
_METHOD_STORED = 0
_METHOD_DEFLATED = 8


class MigrateError(Exception):
    """A migration step that failed; path names the file involved."""

    def __init__(self, message, path=None):
        super().__init__(message)
        self.path = path


def _timestamp(clock=time.time):
    """Sortable stamp of the clock: UTC date and time, then microseconds."""
    now = clock()
    micros = int((now - int(now)) * 1_000_000)
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime(now)) + "-%06d" % micros


def _prune_copies(path, keep):
    """Delete the oldest backup copies of path, keeping the newest `keep`."""
    copies = sorted(
        (p for p in path.parent.glob(f"{path.name}.*{BACKUP_SUFFIX}") if p.is_file()),
        key=lambda p: p.name,
    )
    for old in copies[:max(len(copies) - keep, 0)]:
        old.unlink()


def backup_copy(path, keep, *, stamp=None):
    """Copy path next to itself as a 0600 backup, keep only the newest `keep` copies, return the copy."""
    path = Path(path)
    copy = path.parent / f"{path.name}.{stamp or _timestamp()}{BACKUP_SUFFIX}"
    data = path.read_bytes()
    fd = os.open(copy, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(copy, 0o600)
    _prune_copies(path, keep)
    return copy


def protected_write(path, writer, keep, *, stamp=None):
    """Run writer() after a backup copy of path; on failure restore path and raise MigrateError."""
    path = Path(path)
    backup = backup_copy(path, keep, stamp=stamp) if path.exists() else None
    try:
        writer()
    except Exception as exc:
        if backup is not None and backup.exists():
            shutil.copyfile(backup, path)
        raise MigrateError(f"migration failed for {path}", path=str(path)) from exc


def _protected_step(path, writer, keep, clock):
    """protected_write with a clock stamp; return the name of the copy made, or None."""
    stamp = _timestamp(clock)
    protected_write(path, writer, keep, stamp=stamp)
    copy = path.parent / f"{path.name}.{stamp}{BACKUP_SUFFIX}"
    return copy.name if copy.exists() else None


def _migrate_devices(db, folder, keep, clock):
    """Add the missing DEVICE_DEFAULTS keys to every device record; return the copy names."""
    records = db.read_json(DEVICES_FILE, default=None)
    if records is None:
        return []
    if not isinstance(records, list):
        raise MigrateError(f"{DEVICES_FILE} is not a list", path=str(folder / DEVICES_FILE))
    changed = False
    for record in records:
        if not isinstance(record, dict):
            continue
        for key, default in DEVICE_DEFAULTS.items():
            if key not in record:
                record[key] = default
                changed = True
    if not changed:
        return []
    copy = _protected_step(
        folder / DEVICES_FILE,
        lambda: db.write_json(DEVICES_FILE, records, private=True),
        keep,
        clock,
    )
    return [copy] if copy else []


def _migrate_history(folder, existed, keep, clock):
    """Ensure the raw table of history.sqlite3; copy the file first only when it existed before this run."""
    path = folder / store.HISTORY_DB
    conn = sqlite3.connect(path)
    try:
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='raw'"
        ).fetchone()
        if table is not None:
            return []
        created = []
        if existed:
            copy = backup_copy(path, keep, stamp=_timestamp(clock))
            if copy.exists():
                created.append(copy.name)
        conn.execute(RAW_TABLE_DDL)
        conn.execute(RAW_INDEX_DDL)
        conn.commit()
        return created
    finally:
        conn.close()


def _migrate_automations(db, folder, keep, clock):
    """Ensure the key 'enabled' (default True) on every automation record; return the copy names."""
    records = db.read_json(AUTOMATIONS_FILE, default=None)
    if not isinstance(records, list) or not all(isinstance(r, dict) for r in records):
        return []
    changed = False
    for record in records:
        if "enabled" not in record:
            record["enabled"] = True
            changed = True
    if not changed:
        return []
    copy = _protected_step(
        folder / AUTOMATIONS_FILE,
        lambda: db.write_json(AUTOMATIONS_FILE, records, private=True),
        keep,
        clock,
    )
    return [copy] if copy else []


def migrate_all(data_dir=None, *, clock=time.time):
    """Migrate the data files of the previous controller once; return the names of the copies made."""
    settings = config.load_settings(data_dir)
    keep = settings["backup_copies"]
    folder = Path(settings["data_dir"])
    history_existed = (folder / store.HISTORY_DB).exists()
    db = store.Store.open(folder)
    try:
        created = _migrate_devices(db, folder, keep, clock)
        created += _migrate_history(folder, history_existed, keep, clock)
        created += _migrate_automations(db, folder, keep, clock)
    finally:
        db.close()
    return created


# ---------------------------------------------------------------- .unf reading (logic of mfi_server/unf.py)


def _read_zip_entries(data):
    """Return {name: content} of the local entries, stopping at the first other signature."""
    entries = {}
    offset = 0
    while offset + 4 <= len(data) and struct.unpack_from("<I", data, offset)[0] == _LOCAL_SIG:
        if offset + _LOCAL_HEADER.size > len(data):
            raise ValueError("truncated local file header")
        _sig, _version, flags, method, _time, _date, _crc, comp_size, _uncomp, name_len, extra_len = (
            _LOCAL_HEADER.unpack_from(data, offset)
        )
        name_start = offset + _LOCAL_HEADER.size
        start = name_start + name_len + extra_len
        if start > len(data):
            raise ValueError("truncated local file header")
        name = data[name_start:name_start + name_len].decode("utf-8", errors="replace")
        if flags & _FLAG_DATA_DESCRIPTOR:
            content, offset = _read_with_descriptor(data, start, method, name)
        else:
            content = _read_plain(data, start, comp_size, method, name)
            offset = start + comp_size
        entries[name] = content
    return entries


def _read_plain(data, start, comp_size, method, name):
    """Return the content of an entry whose size is in its local header."""
    comp = data[start:start + comp_size]
    if len(comp) != comp_size:
        raise ValueError(f"truncated entry {name!r}")
    if method == _METHOD_STORED:
        return comp
    if method == _METHOD_DEFLATED:
        try:
            return zlib.decompress(comp, -15)
        except zlib.error as exc:
            raise ValueError(f"bad deflate data in {name!r}") from exc
    raise ValueError(f"unsupported compression method {method} in {name!r}")


def _read_with_descriptor(data, start, method, name):
    """Inflate an entry whose size is in the data descriptor after it; return (content, next offset)."""
    if method != _METHOD_DEFLATED:
        raise ValueError(f"entry {name!r} has a data descriptor but method {method}")
    decoder = zlib.decompressobj(-15)
    try:
        content = decoder.decompress(data[start:])
    except zlib.error as exc:
        raise ValueError(f"bad deflate data in {name!r}") from exc
    if not decoder.eof:
        raise ValueError(f"truncated entry {name!r}")
    end = len(data) - len(decoder.unused_data)
    if data[end:end + 4] == struct.pack("<I", _DESCRIPTOR_SIG):
        return content, end + 16
    return content, end + 12


def _normalize_mac(value):
    """Return the MAC as 12 lower-case hex digits; colons are removed. Raise ValueError otherwise."""
    if not isinstance(value, str):
        raise ValueError("MAC must be a string")
    mac = value.replace(":", "").lower()
    if not MAC_HEX_RE.fullmatch(mac):
        raise ValueError("MAC must be 12 hex digits")
    return mac


def _device_record(mac, doc):
    """Build the device record of one device document, with DEVICE_DEFAULTS applied."""
    authkey = str(doc.get("x_authkey", "")).lower()
    if not AUTHKEY_RE.fullmatch(authkey):
        authkey = ""
    record = {
        "mac": mac,
        "model": str(doc.get("model", "")),
        "name": str(doc.get("name", "")),
        "x_authkey": authkey,
        "ports": [],
        "state": "unknown",
    }
    record.update(DEVICE_DEFAULTS)
    return record


def _add_device(devices, doc):
    """Store one device document; a document without a valid MAC is skipped."""
    try:
        mac = _normalize_mac(doc.get("mac"))
    except ValueError:
        return
    devices[mac] = _device_record(mac, doc)


def _attach_sensor(devices, doc):
    """Add one sensor document as a port of its device; incomplete or orphan sensors are skipped."""
    try:
        mac = _normalize_mac(doc.get("mac"))
    except ValueError:
        return
    port = doc.get("port")
    sensor_id = doc.get("_id")
    device = devices.get(mac)
    if type(port) is not int or port < 1 or sensor_id in (None, ""):
        return
    if device is None:
        return
    device["ports"].append({
        "port": port,
        "sensor_id": str(sensor_id),
        "label": str(doc.get("label", "")),
        "model": str(doc.get("model", "")),
    })


def _store_devices(data_dir, imported):
    """Merge the imported devices into devices.json (mode 0600), keeping the other records."""
    settings = config.load_settings(data_dir)
    folder = Path(settings["data_dir"])
    db = store.Store.open(folder)
    try:
        existing = db.read_json(DEVICES_FILE, default=[])
        if not isinstance(existing, list):
            raise MigrateError(f"{DEVICES_FILE} is not a list", path=str(folder / DEVICES_FILE))
        kept = []
        by_mac = {}
        for record in existing:
            mac = record.get("mac") if isinstance(record, dict) else None
            if isinstance(mac, str):
                by_mac[mac] = record
            else:
                kept.append(record)
        for record in imported:
            by_mac[record["mac"]] = {**by_mac.get(record["mac"], {}), **record}
        merged = kept + [by_mac[mac] for mac in sorted(by_mac)]
        protected_write(
            folder / DEVICES_FILE,
            lambda: db.write_json(DEVICES_FILE, merged, private=True),
            settings["backup_copies"],
        )
    finally:
        db.close()


def import_backup(path, data_dir=None):
    """Read a .unf backup (never written) and return its devices sorted by MAC; store them when data_dir is given."""
    path = Path(path)
    with open(path, "rb") as handle:
        data = handle.read()
    usable = len(data) - len(data) % 16
    try:
        if usable == 0:
            raise ValueError("backup is too short")
        plain = crypto.aes128_decrypt(UNF_KEY, UNF_IV, data[:usable], unpad=False)
        entries = _read_zip_entries(plain)
        if "db.gz" not in entries:
            raise ValueError("db.gz not found in backup")
        raw = gzip.decompress(entries["db.gz"])
        docs = bson.read_bson_stream(io.BytesIO(raw))
    except (ValueError, OSError, EOFError, zlib.error) as exc:
        raise MigrateError(f"cannot read backup {path}: {exc}", path=str(path)) from exc
    devices = {}
    sensors = []
    collection = None
    for doc in docs:
        if doc.get("__cmd") == "select":
            collection = doc.get("collection")
        elif collection == "device":
            _add_device(devices, doc)
        elif collection == "sensor":
            sensors.append(doc)
    for doc in sensors:
        _attach_sensor(devices, doc)
    for device in devices.values():
        device["ports"].sort(key=lambda port: port["port"])
    imported = [devices[mac] for mac in sorted(devices)]
    if data_dir is not None:
        _store_devices(data_dir, imported)
    return imported


def build_support_info(*, version="", settings=None, log_lines=()):
    """Plain-text support report: version, settings without secret names, recent log; keys and MACs scrubbed."""
    parts = ["## Version", str(version), "", "## Settings"]
    for name in sorted(settings or {}):
        if any(word in name.lower() for word in SECRET_WORDS):
            continue
        parts.append(f"{name}={settings[name]}")
    parts += ["", "## Recent log"]
    parts += [str(line) for line in list(log_lines)[-LOG_TAIL_LINES:]]
    return SCRUB_RE.sub("***", "\n".join(parts) + "\n")
