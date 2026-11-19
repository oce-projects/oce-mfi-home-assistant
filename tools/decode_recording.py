"""Offline decoder of the compatibility recordings of mfi-controller (recorder).

A recording is one JSON object per line (see mfi-controller/recorder.py).
Lines of port 6080 hold inform packets: they are decrypted with the device keys
of a controller backup (.unf) and with the default key. Lines of port 6443 hold
web API bodies: the JSON bodies are decoded. Lines of UDP ports 10001 (discovery)
and 3478 (wake-up) hold the decoded TLV fields and the connection flag, never the payload.

With --anonymize, MACs and IPv4 addresses are replaced by stable placeholders
in order of appearance, e-mail addresses and host names are replaced, and keys
and passwords are redacted. Standard library only; no network; device keys are
never printed.

Run from the repository root:
    python3 tools/decode_recording.py --recording FILE.jsonl --backup FILE.unf --out DIR [--anonymize]
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "mfi-server"))

from mfi_server import packet, unf

INFORM_PORT = 6080
WEB_PORT = 6443
REDACTED = "REDACTED"
REDACTED_EMAIL = "REDACTED_EMAIL"
DEFAULT_KEY = bytes.fromhex(packet.DEFAULT_KEY_HEX)
SENSITIVE_KEY_PARTS = ("authkey", "password", "passwd", "passphrase", "secret", "token", "psk", "cookie")
SENSITIVE_HEADER_NAMES = ("cookie", "set-cookie", "authorization")
RAW_BODY_KEYS = ("req_body_b64", "resp_body_b64")
HEADER_KEYS = ("req_headers", "resp_headers")
# \x40 is the '@' sign, written as an escape so no literal e-mail address appears in this source
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+\x40[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
IPV4_RE = re.compile(r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?!\d)(?!\.\d)")
MAC_RE = re.compile(r"(?i)(?<![0-9a-f])(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}(?![0-9a-f])")
MAC_KEY_RE = re.compile(r"(?i)[0-9a-f]{12}|(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}")
# Discovery TLV types of the controller (docs/PROTOCOL.md, section Discovery).
DISCOVERY_TLV_TYPES = {
    1: "mac",
    2: "mac_ipv4",
    3: "version",
    10: "uptime",
    11: "hostname",
    12: "platform",
    13: "essid",
    14: "field14",
    21: "model",
    22: "firmware",
    23: "default_flag",
}


class _Anonymizer:
    """Replaces identifiers with stable placeholders, numbered in order of appearance."""

    def __init__(self) -> None:
        self.macs: dict[str, str] = {}
        self.ips: dict[str, str] = {}
        self.hosts: dict[str, str] = {}

    def mac(self, value: str) -> str:
        """Return the placeholder of a MAC, with or without separators."""
        key = value.lower().replace(":", "").replace("-", "")
        if key not in self.macs:
            self.macs[key] = f"02{len(self.macs) + 1:010d}"
        return self.macs[key]

    def ip(self, value: str) -> str:
        """Return the placeholder of an IPv4 address."""
        if value not in self.ips:
            self.ips[value] = f"192.0.2.{len(self.ips) + 1}"
        return self.ips[value]

    def host(self, value: str) -> str:
        """Return the placeholder of a host name."""
        if value not in self.hosts:
            self.hosts[value] = f"device-{len(self.hosts) + 1}"
        return self.hosts[value]

    def value(self, obj, key: str = ""):
        """Return a copy of obj with every identifier replaced."""
        if isinstance(obj, dict):
            return {self._text(str(k), ""): self._entry(str(k), v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.value(item, key) for item in obj]
        if isinstance(obj, str):
            return self._text(obj, key)
        return obj

    def _entry(self, key: str, value):
        """Redact a sensitive value or raw body, anonymize any other."""
        if _is_sensitive(key):
            return REDACTED
        if key in RAW_BODY_KEYS:
            return REDACTED
        if key in HEADER_KEYS:
            return self._redact_headers(value)
        return self.value(value, key)

    def _redact_headers(self, headers):
        """Redact sensitive header values; anonymize identifiers in the others."""
        result = []
        for pair in headers or []:
            if isinstance(pair, (list, tuple)) and len(pair) == 2:
                name = str(pair[0])
                if name.lower() in SENSITIVE_HEADER_NAMES or _is_sensitive(name):
                    result.append([name, REDACTED])
                else:
                    result.append([name, self._text(str(pair[1]), name)])
            else:
                result.append(self.value(pair))
        return result

    def _text(self, text: str, key: str) -> str:
        """Anonymize one string; key is the name of the field that holds it."""
        lowered = key.lower()
        if lowered in ("hostname", "host", "fqdn", "alias", "essid"):
            return self.host(text)
        if ("mac" in lowered or "serial" in lowered) and MAC_KEY_RE.fullmatch(text):
            return self.mac(text)
        text = EMAIL_RE.sub(REDACTED_EMAIL, text)
        text = MAC_RE.sub(lambda m: self.mac(m.group(0)), text)
        return IPV4_RE.sub(lambda m: self.ip(m.group(0)), text)


def _is_sensitive(key: str) -> bool:
    """True when a field name is a key, a password or a similar secret."""
    lowered = key.lower()
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)


def _new_entry(record: dict) -> dict:
    """Return an output entry with every field set to None."""
    return {
        "t": record.get("t"),
        "port": record.get("port"),
        "client": record.get("client"),
        "mac": None,
        "request": None,
        "response": None,
        "error": None,
    }


def _b64(text: str) -> bytes:
    """Decode base64 text, rejecting bad characters."""
    return base64.b64decode(text, validate=True)


def _content_type(headers) -> str:
    """Return the Content-Type header value in lower case, or an empty string."""
    for pair in headers or []:
        if isinstance(pair, (list, tuple)) and len(pair) == 2 and str(pair[0]).lower() == "content-type":
            return str(pair[1]).lower()
    return ""


def _web_json(encoded: str, content_type: str):
    """Decode a JSON body; other bodies and empty bodies give None."""
    if "json" not in content_type or not encoded:
        return None
    return json.loads(_b64(encoded).decode("utf-8"))


def _decode_inform(record: dict, keys: dict[str, list[bytes]]) -> dict:
    """Decrypt the request and the response of one inform line."""
    entry = _new_entry(record)
    try:
        request_raw = _b64(record["req_body_b64"])
        mac = packet.parse_header(request_raw).mac.hex()
        candidates = keys.get(mac, []) + [DEFAULT_KEY]
        request = packet.decode(request_raw, candidates)[1]
    except (KeyError, TypeError, ValueError, packet.PacketError) as exc:
        entry["error"] = str(exc) or type(exc).__name__
        return entry
    entry["mac"] = mac
    entry["request"] = request
    try:
        response_raw = _b64(record["resp_body_b64"])
        entry["response"] = packet.decode(response_raw, candidates)[1] if response_raw else None
    except (KeyError, TypeError, ValueError, packet.PacketError) as exc:
        entry["error"] = str(exc) or type(exc).__name__
    return entry


def _decode_web(record: dict) -> dict:
    """Copy one web API line and decode its JSON bodies."""
    entry = dict(record, mac=None, request=None, response=None, error=None)
    try:
        entry["request"] = _web_json(record.get("req_body_b64", ""), _content_type(record.get("req_headers")))
        entry["response"] = _web_json(record.get("resp_body_b64", ""), _content_type(record.get("resp_headers")))
    except (ValueError, TypeError) as exc:
        entry["error"] = f"json body not decodable: {exc}"
    return entry


def parse_discovery_tlv(payload: bytes) -> list[dict]:
    """Return the TLV fields of a discovery reply; the 4-byte header is skipped."""
    fields = []
    pos = 4
    while len(payload) - pos >= 3:
        field_type = payload[pos]
        length = int.from_bytes(payload[pos + 1:pos + 3], "big")
        start = pos + 3
        if length > len(payload) - start:
            break
        fields.append(_decode_tlv_field(field_type, payload[start:start + length]))
        pos = start + length
    return fields


def _decode_tlv_field(field_type: int, data: bytes) -> dict:
    """Decode one TLV field; unknown, short or non-ASCII data is kept as hex."""
    field = {"type": field_type, "name": DISCOVERY_TLV_TYPES.get(field_type)}
    if field_type == 1 and len(data) == 6:
        field["mac"] = data.hex()
    elif field_type == 2 and len(data) == 10:
        field["mac"] = data[0:6].hex()
        field["ipv4"] = ".".join(str(octet) for octet in data[6:10])
    elif field_type == 10 and data:
        field["uptime"] = int.from_bytes(data, "big")
    elif field_type in (3, 11, 12, 13) and data.isascii():
        field[DISCOVERY_TLV_TYPES[field_type]] = data.decode("ascii")
    else:
        field["hex"] = data.hex()
    return field


def _decode_udp(record: dict) -> dict:
    """Decode a UDP line: TLV fields for discovery (10001), a connection flag for wake-up (3478)."""
    entry = {
        "time": record.get("time"),
        "port": record.get("port"),
        "src": record.get("src"),
        "dst": record.get("dst"),
    }
    try:
        payload = _b64(record["payload_b64"])
    except (KeyError, TypeError, ValueError) as exc:
        entry["error"] = f"payload not decodable: {exc}"
        return entry
    if record.get("port") == "udp10001":
        entry["fields"] = parse_discovery_tlv(payload)
    else:
        entry["length"] = len(payload)
        entry["connection_request"] = payload[:2] == b"\x88\x88"
    return entry


def _decode_record(line: str, keys: dict[str, list[bytes]]) -> dict:
    """Decode one recording line; an unreadable line gives an entry with an error."""
    try:
        record = json.loads(line)
    except ValueError:
        return dict(_new_entry({}), error="line is not valid JSON")
    if not isinstance(record, dict):
        return dict(_new_entry({}), error="line is not a JSON object")
    port = record.get("port")
    if port == INFORM_PORT:
        return _decode_inform(record, keys)
    if port == WEB_PORT:
        return _decode_web(record)
    if port in ("udp10001", "udp3478"):
        return _decode_udp(record)
    return dict(_new_entry(record), error=f"unknown port {port!r}")


def decode_lines(lines: list[str], keys: dict[str, list[bytes]], anonymize: bool) -> list[dict]:
    """Decode each recording line; a line that fails gets an error and does not stop the others."""
    anonymizer = _Anonymizer() if anonymize else None
    results = []
    for line in lines:
        if not line.strip():
            continue
        entry = _decode_record(line, keys)
        if anonymizer is not None:
            entry = anonymizer.value(entry)
        results.append(entry)
    return results


def main(argv: list[str] | None = None) -> int:
    """Read the recording and the backup keys, write the decoded lines to DIR."""
    parser = argparse.ArgumentParser(description="Decode a compatibility recording offline.")
    parser.add_argument("--recording", required=True, help="recording file (.jsonl) written by the add-on")
    parser.add_argument("--backup", required=True, help="controller backup (.unf) with the device keys")
    parser.add_argument("--out", required=True, help="folder for the decoded file")
    parser.add_argument("--anonymize", action="store_true", help="replace MACs, IPs, e-mails, host names and keys")
    args = parser.parse_args(argv)
    if not args.anonymize:
        print("warning: without --anonymize the output keeps real MACs, IPs and keys; do not commit it.",
              file=sys.stderr)
    try:
        with open(args.backup, "rb") as handle:
            devices = unf.import_backup(handle.read())
        with open(args.recording, encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    keys: dict[str, list[bytes]] = {}
    for device in devices:
        authkey = device.get("authkey")
        mac = device.get("mac")
        if not authkey or not mac:
            continue
        try:
            key_bytes = bytes.fromhex(authkey)
        except ValueError:
            continue
        keys.setdefault(mac, []).append(key_bytes)
    results = decode_lines(lines, keys, args.anonymize)
    os.makedirs(args.out, exist_ok=True)
    name = os.path.splitext(os.path.basename(args.recording))[0]
    out_path = os.path.join(args.out, f"{name}.decoded.jsonl")
    with open(out_path, "w", encoding="utf-8") as handle:
        for entry in results:
            handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"{len(results)} lines written to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
