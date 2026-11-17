"""Tests of upgrade.py: request rules, one upgrade at a time, confirmation within 180 s."""
import hashlib
import tempfile
import unittest
from pathlib import Path

from mfi_server.commands import CommandQueue
from mfi_server.firmware import FirmwareArchive
from mfi_server.states import DeviceStates
from mfi_server.upgrade import UPGRADE_TIMEOUT_S, UpgradeError, UpgradeManager

MAC = "aa0000000001"
OTHER_MAC = "aa0000000002"
FIRMWARE = b"FW"
FIRMWARE_PATH = "M2M/x/firmware.bin"
ARCHIVE_VERSION = "2.1.11.1309"
OLDER_VERSION = "2.1.8.1309"
BUNDLE = {
    "path": FIRMWARE_PATH,
    "version": ARCHIVE_VERSION,
    "sha256": hashlib.sha256(FIRMWARE).hexdigest(),
    "size": len(FIRMWARE),
}


class UpgradeTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "M2M" / "x").mkdir(parents=True)
        (self.root / FIRMWARE_PATH).write_bytes(FIRMWARE)
        self.t = [0.0]
        self.archive = FirmwareArchive(self.root, bundles={"P3E": dict(BUNDLE)})
        self.states = DeviceStates(clock=lambda: self.t[0])
        self.queue = CommandQueue()
        self.mgr = self._manager(self.archive)
        self.record = self._record(MAC)

    def _manager(self, archive: FirmwareArchive) -> UpgradeManager:
        return UpgradeManager(archive, self.states, self.queue, clock=lambda: self.t[0])

    def _record(self, mac: str, model: str = "P3E") -> dict:
        return {"mac": mac, "model": model, "ports": []}

    def _connect(self, mac: str, version: str | None) -> None:
        self.states.seen(mac)
        if version is not None:
            self.states.set_version(mac, version)

    def _rejected(self, code: str, record: dict) -> None:
        with self.assertRaises(UpgradeError) as ctx:
            self.mgr.request(record)
        self.assertEqual(ctx.exception.code, code)

    def test_request_queues_upgrade_for_connected_older_device(self) -> None:
        self._connect(MAC, OLDER_VERSION)
        self.assertIsNone(self.mgr.request(self.record))
        self.assertTrue(self.queue.pending_upgrade(MAC))
        self.assertEqual(self.mgr.status(MAC), "requested")

    def test_queued_upgrade_carries_archive_path_and_version(self) -> None:
        self._connect(MAC, OLDER_VERSION)
        self.mgr.request(self.record)
        self.assertEqual(
            self.queue.pop_upgrade(MAC),
            {"mac": MAC, "path": FIRMWARE_PATH, "version": ARCHIVE_VERSION},
        )

    def test_second_request_refused_while_one_is_active(self) -> None:
        self._connect(MAC, OLDER_VERSION)
        self._connect(OTHER_MAC, OLDER_VERSION)
        self.mgr.request(self.record)
        self._rejected("upgrade_in_progress", self._record(OTHER_MAC))
        self.assertFalse(self.queue.pending_upgrade(OTHER_MAC))

    def test_not_connected_device_is_refused(self) -> None:
        self._rejected("not_connected", self._record(OTHER_MAC))
        self._connect(MAC, OLDER_VERSION)
        self.t[0] = 121.0
        self._rejected("not_connected", self.record)

    def test_model_outside_table_is_refused(self) -> None:
        self._connect(MAC, OLDER_VERSION)
        self._rejected("no_bundle", self._record(MAC, "EM3"))

    def test_unreadable_version_is_refused(self) -> None:
        for version in (None, "", "beta"):
            with self.subTest(version=version):
                self._connect(MAC, version)
                self._rejected("unreadable_version", self.record)

    def test_same_version_is_not_older(self) -> None:
        self._connect(MAC, ARCHIVE_VERSION)
        self._rejected("not_older", self.record)

    def test_unavailable_archive_is_refused(self) -> None:
        self.mgr = self._manager(FirmwareArchive(self.root / "missing", bundles={"P3E": dict(BUNDLE)}))
        self._connect(MAC, OLDER_VERSION)
        self._rejected("archive_unavailable", self.record)

    def test_requested_times_out_when_never_sent(self) -> None:
        self._connect(MAC, OLDER_VERSION)
        self.mgr.request(self.record)
        self.assertEqual(self.mgr.status(MAC), "requested")
        self.t[0] = UPGRADE_TIMEOUT_S + 1.0
        self.assertEqual(self.mgr.status(MAC), "not_confirmed")
        self.assertIsNone(self.mgr._active)
        self.assertFalse(self.queue.pending_upgrade(MAC))
        self._connect(OTHER_MAC, OLDER_VERSION)
        self.assertIsNone(self.mgr.request(self._record(OTHER_MAC)))
        self.assertTrue(self.queue.pending_upgrade(OTHER_MAC))

    def test_confirmed_by_new_version_within_timeout(self) -> None:
        self._connect(MAC, OLDER_VERSION)
        self.mgr.request(self.record)
        self.mgr.mark_sent(MAC)
        self.assertEqual(self.mgr.status(MAC), "sent")
        self.states.set_version(MAC, ARCHIVE_VERSION)
        self.t[0] = 10.0
        self.mgr.on_inform(MAC)
        self.assertEqual(self.mgr.status(MAC), "updated")
        self.assertIsNone(self.mgr._active)
        self._connect(OTHER_MAC, OLDER_VERSION)
        self.mgr.request(self._record(OTHER_MAC))
        self.assertTrue(self.queue.pending_upgrade(OTHER_MAC))

    def test_not_confirmed_after_timeout_without_new_version(self) -> None:
        self._connect(MAC, OLDER_VERSION)
        self.mgr.request(self.record)
        self.mgr.mark_sent(MAC)
        self.t[0] = 200.0
        self.mgr.on_inform(MAC)
        self.assertEqual(self.mgr.status(MAC), "not_confirmed")
        self.assertIsNone(self.mgr._active)
        self._connect(OTHER_MAC, OLDER_VERSION)
        self.mgr.request(self._record(OTHER_MAC))
        self.assertTrue(self.queue.pending_upgrade(OTHER_MAC))

    def test_new_version_after_timeout_is_updated(self) -> None:
        self._connect(MAC, OLDER_VERSION)
        self.mgr.request(self.record)
        self.mgr.mark_sent(MAC)
        self.t[0] = 200.0
        self.states.set_version(MAC, ARCHIVE_VERSION)
        self.mgr.on_inform(MAC)
        self.assertEqual(self.mgr.status(MAC), "updated")
        self.assertIsNone(self.mgr._active)
        self._connect(OTHER_MAC, OLDER_VERSION)
        self.mgr.request(self._record(OTHER_MAC))
        self.assertTrue(self.queue.pending_upgrade(OTHER_MAC))

    def test_still_sent_at_exact_timeout(self) -> None:
        self.assertEqual(UPGRADE_TIMEOUT_S, 180)
        self._connect(MAC, OLDER_VERSION)
        self.mgr.request(self.record)
        self.mgr.mark_sent(MAC)
        self.t[0] = float(UPGRADE_TIMEOUT_S)
        self.assertEqual(self.mgr.status(MAC), "sent")
        self.t[0] = UPGRADE_TIMEOUT_S + 1.0
        self.assertEqual(self.mgr.status(MAC), "not_confirmed")

    def test_firmware_view_older_device(self) -> None:
        self._connect(MAC, OLDER_VERSION)
        view = self.mgr.firmware_view(self.record)
        self.assertEqual(view["comparison"], "older")
        self.assertEqual(view["device_version"], OLDER_VERSION)
        self.assertEqual(view["archive_version"], ARCHIVE_VERSION)
        self.assertTrue(view["available"])
        self.assertIsNone(view["upgrade_status"])

    def test_firmware_view_model_outside_table(self) -> None:
        self._connect(MAC, OLDER_VERSION)
        view = self.mgr.firmware_view(self._record(MAC, "EM3"))
        self.assertEqual(view["comparison"], "no_bundle")

    def test_firmware_view_unavailable_archive(self) -> None:
        self.mgr = self._manager(FirmwareArchive(self.root / "missing", bundles={"P3E": dict(BUNDLE)}))
        self._connect(MAC, OLDER_VERSION)
        view = self.mgr.firmware_view(self.record)
        self.assertEqual(view["comparison"], "no_archive")
        self.assertFalse(view["available"])

    def test_firmware_view_unreadable_version(self) -> None:
        self._connect(MAC, None)
        view = self.mgr.firmware_view(self.record)
        self.assertEqual(view["comparison"], "unreadable")
        self.assertEqual(view["device_version"], "")

    def test_firmware_view_shows_upgrade_status(self) -> None:
        self._connect(MAC, OLDER_VERSION)
        self.mgr.request(self.record)
        view = self.mgr.firmware_view(self.record)
        self.assertEqual(view["upgrade_status"], "requested")
