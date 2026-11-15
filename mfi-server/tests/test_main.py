"""Tests of the command line entry point: import-backup, decode and argument errors.

Backups are built in memory with the layout of a real .unf file, using this
file's own helpers; the .unf file is written only into a temporary folder.
The server is never started here.
"""
from __future__ import annotations

import contextlib
import gzip
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from mfi_server import aes, bson, packet, unf
from mfi_server.__main__ import main
from mfi_server.store import DeviceStore

MAC = "02aabbccdd01"


def device_doc(mac: str, authkey: str) -> dict:
    return {"mac": mac, "model": "test-model", "name": "test device", "x_authkey": authkey}


def sensor_doc(mac: str, port: int, sensor_id: str) -> dict:
    return {"mac": mac, "port": port, "_id": sensor_id, "label": f"outlet {port}", "model": "test-model"}


def build_backup(devices: list[dict], sensors: list[dict]) -> bytes:
    """Build a .unf backup in memory: BSON in db.gz, db.gz in a ZIP, padded and AES-CBC encrypted."""
    docs = [
        {"__cmd": "select", "collection": "device"},
        *devices,
        {"__cmd": "select", "collection": "sensor"},
        *sensors,
    ]
    db = b"".join(bson.encode_document(doc) for doc in docs)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("db.gz", gzip.compress(db))
    raw = buffer.getvalue()
    raw += b"\x00" * (-len(raw) % aes.BLOCK_SIZE)
    return aes.encrypt_cbc(unf.UNF_KEY, unf.UNF_IV, raw)


def run_main(argv: list[str]) -> tuple[int, str, str]:
    """Run main() with an empty environment override; return (code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv, {})
    return code, out.getvalue(), err.getvalue()


class ImportBackupTest(unittest.TestCase):
    def test_counts_are_printed_and_the_key_is_stored_not_printed(self):
        key = os.urandom(16).hex()
        sensors = [sensor_doc(MAC, 1, "sensor-1"), sensor_doc(MAC, 2, "sensor-2")]
        with tempfile.TemporaryDirectory() as tmp:
            backup = Path(tmp) / "backup.unf"
            backup.write_bytes(build_backup([device_doc(MAC, key)], sensors))
            data_dir = Path(tmp) / "data"
            code, out, err = run_main(["import-backup", str(backup), "--data", str(data_dir)])
            record = DeviceStore(data_dir).get(MAC)
        self.assertEqual(code, 0)
        self.assertEqual(out, "imported 1 devices, 2 ports\n")
        self.assertNotIn(key, out)
        self.assertNotIn(key, err)
        self.assertEqual(record["authkey"], key)
        self.assertEqual([port["label"] for port in record["ports"]], ["outlet 1", "outlet 2"])

    def test_backup_without_devices_imports_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            backup = Path(tmp) / "empty.unf"
            backup.write_bytes(build_backup([], []))
            code, out, err = run_main(["import-backup", str(backup), "--data", str(Path(tmp) / "data")])
        self.assertEqual(code, 0)
        self.assertEqual(out, "imported 0 devices, 0 ports\n")
        self.assertEqual(err, "")

    def test_short_and_missing_files_are_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            short = Path(tmp) / "short.unf"
            short.write_bytes(b"0123456789")
            code, out, err = run_main(["import-backup", str(short), "--data", tmp])
            self.assertEqual(code, 2)
            self.assertEqual(out, "")
            self.assertTrue(err.startswith("error:"), err)
            missing = Path(tmp) / "missing.unf"
            code, out, err = run_main(["import-backup", str(missing), "--data", tmp])
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertTrue(err.startswith("error:"), err)


class DecodeTest(unittest.TestCase):
    def test_decodes_a_packet_and_never_prints_the_key(self):
        key = os.urandom(16)
        raw = packet.encode(bytes.fromhex(MAC), key, {"mac": MAC}, os.urandom(16))
        with tempfile.TemporaryDirectory() as tmp:
            inform = Path(tmp) / "inform.packet"
            inform.write_bytes(raw)
            key_file = Path(tmp) / "key.txt"
            key_file.write_text(key.hex() + "\n", encoding="utf-8")
            code, out, err = run_main(["decode", str(inform), "--key-file", str(key_file)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["mac"], MAC)
        self.assertNotIn(key.hex(), out)
        self.assertNotIn(key.hex(), err)

    def test_wrong_key_is_an_error_naming_the_attempts(self):
        raw = packet.encode(bytes.fromhex(MAC), os.urandom(16), {"mac": MAC}, os.urandom(16))
        with tempfile.TemporaryDirectory() as tmp:
            inform = Path(tmp) / "inform.packet"
            inform.write_bytes(raw)
            key_file = Path(tmp) / "key.txt"
            key_file.write_text(os.urandom(16).hex(), encoding="utf-8")
            code, out, err = run_main(["decode", str(inform), "--key-file", str(key_file)])
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("tried all", err)

    def test_key_file_must_hold_32_hex_characters(self):
        raw = packet.encode(bytes.fromhex(MAC), os.urandom(16), {"mac": MAC}, os.urandom(16))
        with tempfile.TemporaryDirectory() as tmp:
            inform = Path(tmp) / "inform.packet"
            inform.write_bytes(raw)
            key_file = Path(tmp) / "key.txt"
            key_file.write_text("abc\n", encoding="utf-8")
            code, out, err = run_main(["decode", str(inform), "--key-file", str(key_file)])
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("error: key file must contain 32 hex characters", err)

    def test_missing_file_argument_is_an_argument_error(self):
        code, out, err = run_main(["decode"])
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("error:", err)


class ServerModeTest(unittest.TestCase):
    def test_bad_port_in_environment_is_rejected_before_serving(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main(["--data", tmp], {"MFI_INFORM_PORT": "70000"})
        self.assertEqual(code, 2)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("inform_port must be 1-65535", err.getvalue())


if __name__ == "__main__":
    unittest.main()
