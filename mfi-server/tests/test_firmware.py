"""Tests of the firmware archive: bundle table, file check, read and version comparison.

Offline: temporary folders and the standard library only. The real firmware
file is never needed; the archive is built on a 2-byte test file whose size and
sha256 match the bundle given to it.
"""
from __future__ import annotations

import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path

from mfi_server.firmware import BUNDLES_PATH, FirmwareArchive, compare_versions, load_bundles, parse_version

MODELS = {"IWD1U", "P1E", "IWO2U", "P8U", "M2S", "M2M", "P6E", "P1U", "P3E", "P3U"}
EXCLUDED_MODELS = ("EM3", "EM24", "THERM", "IWS1U")
EXPECTED_PATH = "M2M/2.1.11.1309/firmware.bin"
EXPECTED_VERSION = "2.1.11.1309"
EXPECTED_SIZE = 7418034
EXPECTED_SHA256 = "7dc6fb4bd67c6352b940d8b65dd0d99325199e8dc4052c20139aaf861fec2a79"
TEST_MODEL = "P3E"
TEST_PATH = "M2M/x/firmware.bin"
TEST_BYTES = b"FW"


class BundleTableTest(unittest.TestCase):
    def setUp(self) -> None:
        with BUNDLES_PATH.open(encoding="utf-8") as handle:
            self.table = json.load(handle)

    def test_table_has_exactly_the_ten_models(self):
        self.assertEqual(set(self.table), MODELS)

    def test_excluded_models_are_absent(self):
        for model in EXCLUDED_MODELS:
            with self.subTest(model=model):
                self.assertNotIn(model, self.table)

    def test_every_entry_has_the_release_fields(self):
        for model, entry in self.table.items():
            with self.subTest(model=model):
                self.assertEqual(set(entry), {"path", "version", "sha256", "size"})
                self.assertEqual(entry["path"], EXPECTED_PATH)
                self.assertEqual(entry["version"], EXPECTED_VERSION)
                self.assertEqual(entry["size"], EXPECTED_SIZE)
                self.assertRegex(entry["sha256"], r"^[0-9a-f]{64}$")
                self.assertEqual(entry["sha256"], EXPECTED_SHA256)

    def test_load_bundles_reads_the_same_table(self):
        self.assertEqual(load_bundles(BUNDLES_PATH), self.table)
        self.assertIsNotNone(re.fullmatch(r"[0-9a-f]{64}", EXPECTED_SHA256))


class ArchiveFileTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, data: bytes) -> None:
        target = self.root / TEST_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def _bundles(self) -> dict[str, dict]:
        return {
            TEST_MODEL: {
                "path": TEST_PATH,
                "version": EXPECTED_VERSION,
                "sha256": hashlib.sha256(TEST_BYTES).hexdigest(),
                "size": len(TEST_BYTES),
            }
        }

    def test_matching_file_is_available(self):
        self._write(TEST_BYTES)
        archive = FirmwareArchive(self.root, bundles=self._bundles())
        self.assertTrue(archive.available)
        self.assertIsNone(archive.error)

    def test_changed_byte_is_rejected(self):
        self._write(b"FX")
        archive = FirmwareArchive(self.root, bundles=self._bundles())
        self.assertFalse(archive.available)
        self.assertEqual(archive.error, "sha256")

    def test_truncated_file_is_rejected(self):
        self._write(b"F")
        archive = FirmwareArchive(self.root, bundles=self._bundles())
        self.assertFalse(archive.available)
        self.assertEqual(archive.error, "size")

    def test_longer_file_is_rejected(self):
        self._write(b"FWX")
        archive = FirmwareArchive(self.root, bundles=self._bundles())
        self.assertFalse(archive.available)
        self.assertEqual(archive.error, "size")

    def test_missing_file_is_rejected(self):
        archive = FirmwareArchive(self.root, bundles=self._bundles())
        self.assertFalse(archive.available)
        self.assertEqual(archive.error, "missing")

    def test_verify_again_after_repair_makes_archive_available(self):
        self._write(b"FX")
        archive = FirmwareArchive(self.root, bundles=self._bundles())
        self.assertFalse(archive.available)
        self._write(TEST_BYTES)
        archive.verify()
        self.assertTrue(archive.available)
        self.assertIsNone(archive.error)

    def test_archive_version_and_paths_come_from_the_table(self):
        self._write(TEST_BYTES)
        archive = FirmwareArchive(self.root, bundles=self._bundles())
        self.assertEqual(archive.archive_version(), EXPECTED_VERSION)
        self.assertEqual(archive.paths(), {TEST_PATH})
        self.assertIsNone(archive.bundle_for("M2M"))
        self.assertEqual(archive.bundle_for(TEST_MODEL)["path"], TEST_PATH)


class ArchiveReadTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, data: bytes) -> None:
        target = self.root / TEST_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def _archive(self) -> FirmwareArchive:
        bundles = {
            TEST_MODEL: {
                "path": TEST_PATH,
                "version": EXPECTED_VERSION,
                "sha256": hashlib.sha256(TEST_BYTES).hexdigest(),
                "size": len(TEST_BYTES),
            }
        }
        return FirmwareArchive(self.root, bundles=bundles)

    def test_known_path_is_served(self):
        self._write(TEST_BYTES)
        self.assertEqual(self._archive().read(TEST_PATH), b"FW")

    def test_unknown_path_is_refused(self):
        self._write(TEST_BYTES)
        self.assertIsNone(self._archive().read("M2M/other/firmware.bin"))

    def test_parent_directory_path_is_refused(self):
        self._write(TEST_BYTES)
        archive = self._archive()
        self.assertIsNone(archive.read("../x"))
        self.assertIsNone(archive.read("M2M/x/../../firmware.bin"))

    def test_encoded_path_is_refused(self):
        self._write(TEST_BYTES)
        self.assertIsNone(self._archive().read("%2e%2e%2ffirmware.bin"))

    def test_unavailable_archive_serves_nothing(self):
        self._write(b"FX")
        archive = self._archive()
        self.assertFalse(archive.available)
        self.assertIsNone(archive.read(TEST_PATH))


class VersionTest(unittest.TestCase):
    def test_compare_versions_cases(self):
        cases = [
            ("2.1.8.1309", "2.1.11.1309", "older"),
            ("MF.ar933x.v2.1.11.1309.150406.1423", "2.1.11.1309", "same_or_newer"),
            ("2.1.11.1309", "2.1.11.1309", "same_or_newer"),
            ("2.1.12.0", "2.1.11.1309", "same_or_newer"),
            ("2.1.9", "2.1.11.1309", "older"),
            ("2.1.11", "2.1.11.1309", "older"),
            ("", "2.1.11.1309", "unreadable"),
            (None, "2.1.11.1309", "unreadable"),
            ("MF.ar933x.v2.1.8.1309.150406.1423", "2.1.11.1309", "older"),
        ]
        for device, archive, expected in cases:
            with self.subTest(device=device, archive=archive):
                self.assertEqual(compare_versions(device, archive), expected)

    def test_parse_version_short_and_long_forms(self):
        self.assertEqual(parse_version("2.1.11.1309"), (2, 1, 11, 1309))
        self.assertEqual(parse_version("MF.ar933x.v2.1.11.1309.150406.1423"), (2, 1, 11, 1309))
        self.assertEqual(parse_version("2.1.9"), (2, 1, 9))

    def test_parse_version_unreadable_text(self):
        self.assertIsNone(parse_version(""))
        self.assertIsNone(parse_version(None))
        self.assertIsNone(parse_version("no numbers here"))


if __name__ == "__main__":
    unittest.main()
