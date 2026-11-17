"""Firmware archive of mfi-server: the files that device upgrades are served from.

firmware_bundles.json has one entry per device model: the path under the
firmware folder, the version, the sha256 and the size of the file. The archive
is available only when every file of the table is present and matches its
size and sha256. Standard library only.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

BUNDLES_PATH = Path(__file__).resolve().parent / "firmware_bundles.json"
DEFAULT_FIRMWARE_DIR = Path("/opt/mfi-server/firmware")
BUNDLE_KEYS = frozenset({"path", "version", "sha256", "size"})
HASH_BLOCK_BYTES = 1024 * 1024
_NUMBERS_RE = re.compile(r"[0-9]+(?:\.[0-9]+)+")
VERSION_PARTS = 4


def load_bundles(path: Path = BUNDLES_PATH) -> dict[str, dict]:
    """Read the bundle table: strict JSON, one object per model with path, version, sha256 and size."""
    with path.open(encoding="utf-8") as handle:
        bundles = json.load(handle)
    if not isinstance(bundles, dict):
        raise ValueError(f"{path.name}: the top level must be a JSON object")
    for model, bundle in bundles.items():
        if not isinstance(bundle, dict) or set(bundle) != BUNDLE_KEYS:
            raise ValueError(f"{path.name}: bad entry for {model}")
    return bundles


def parse_version(text: str) -> tuple[int, ...] | None:
    """Return the numbers of a version: '2.1.11.1309' or 'MF.ar933x.v2.1.11.1309.150406.1423' give (2, 1, 11, 1309)."""
    if not isinstance(text, str):
        return None
    _, sep, tail = text.partition("v")
    body = tail if sep else text
    match = _NUMBERS_RE.search(body)
    if match is None:
        return None
    return tuple(int(part) for part in match.group(0).split(".")[:VERSION_PARTS])


def compare_versions(device: str | None, archive: str) -> str:
    """Compare the device version with the archive version: 'older', 'same_or_newer' or 'unreadable'."""
    device_numbers = parse_version(device)
    archive_numbers = parse_version(archive)
    if device_numbers is None or archive_numbers is None:
        return "unreadable"
    width = max(len(device_numbers), len(archive_numbers))
    device_padded = device_numbers + (0,) * (width - len(device_numbers))
    archive_padded = archive_numbers + (0,) * (width - len(archive_numbers))
    return "older" if device_padded < archive_padded else "same_or_newer"


class FirmwareArchive:
    """The firmware files of the bundle table, checked when the archive is built."""

    def __init__(self, firmware_dir: Path, bundles: dict[str, dict] | None = None) -> None:
        self.firmware_dir = Path(firmware_dir)
        self.bundles = load_bundles() if bundles is None else bundles
        self.available = False
        self.error: str | None = None
        self.verify()

    def verify(self) -> None:
        """Check every distinct file of the table; the first problem makes the archive unavailable."""
        self.available = False
        self.error = None
        checked: set[str] = set()
        for bundle in self.bundles.values():
            if bundle["path"] in checked:
                continue
            checked.add(bundle["path"])
            error = self._check_file(bundle)
            if error is not None:
                self.error = error
                logger.warning("firmware file %s rejected: %s", bundle["path"], error)
                return
        self.available = True

    def _check_file(self, bundle: dict) -> str | None:
        """Return None when the file matches the bundle, else 'missing', 'size' or 'sha256'."""
        target = self.firmware_dir / bundle["path"]
        try:
            if not target.is_file():
                return "missing"
            if target.stat().st_size != bundle["size"]:
                return "size"
            digest = hashlib.sha256()
            with target.open("rb") as handle:
                for block in iter(lambda: handle.read(HASH_BLOCK_BYTES), b""):
                    digest.update(block)
        except OSError as exc:
            logger.warning("firmware file %s unreadable: %s", bundle["path"], type(exc).__name__)
            return "missing"
        if digest.hexdigest() != bundle["sha256"]:
            return "sha256"
        return None

    def paths(self) -> set[str]:
        """Return the file paths of the table, as they are written in the table."""
        return {bundle["path"] for bundle in self.bundles.values()}

    def bundle_for(self, model: str) -> dict | None:
        """Return the bundle of a device model, or None when the model is not in the table."""
        return self.bundles.get(model)

    def archive_version(self) -> str:
        """Return the version of the table ('' when the table is empty)."""
        return next((bundle["version"] for bundle in self.bundles.values()), "")

    def read(self, path: str) -> bytes | None:
        """Return the bytes of a file of the table; None when unavailable, unknown or unreadable. The path is never decoded."""
        if not self.available or path not in self.paths():
            return None
        try:
            return (self.firmware_dir / path).read_bytes()
        except OSError:
            logger.warning("firmware file %s could not be read", path)
            return None
