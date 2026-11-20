"""Tests of mfi_server_next.maps (EPIC-12 ST1): map images, scale, locked icons and hypothesis fields.

Standard library only. Uses a real Store (sqlite3 and JSON) in a temporary folder, a fixed clock and tiny
synthetic image bytes built in the test. No network and no device.
"""
import stat
import tempfile
import unittest
from pathlib import Path

from mfi_server_next.maps import MapStore
from mfi_server_next.store import Store

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16
DEVICE = "aabbccddeeff"
HYPOTHESIS_FIELDS = ("locations", "geofences", "liveviews", "widgets", "templates", "configtemplates", "motion_fields")
MAP_FIELDS = {"id", "name", "scale", "scale_unit", "image", "icons", "created"} | set(HYPOTHESIS_FIELDS)
NOW = 1_000_000


class MapStoreTestCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.store = Store.open(self.folder)
        self.addCleanup(self.store.close)
        self.maps = MapStore(self.store, now=lambda: NOW)


class TestImageCreateReadDelete(MapStoreTestCase):
    def test_ca1_create_read_delete_keeps_image_under_server_name(self):
        created = self.maps.create_map("Ground floor", image=PNG)
        self.assertIsInstance(created["id"], str)
        self.assertNotEqual(created["id"], "")
        self.assertRegex(created["image"], r"^map_[0-9a-f]+\.png$")
        image_file = self.folder / "maps" / created["image"]
        self.assertTrue(image_file.is_file())
        self.assertEqual(image_file.read_bytes(), PNG)
        self.assertEqual(stat.S_IMODE(image_file.stat().st_mode), 0o600)
        self.assertEqual(self.maps.get_map(created["id"])["id"], created["id"])
        self.assertEqual(self.maps.image_path(created["id"]), image_file)

        self.assertTrue(self.maps.delete_map(created["id"]))
        self.assertIsNone(self.maps.get_map(created["id"]))
        self.assertFalse(image_file.exists())

    def test_client_name_never_becomes_file_name(self):
        created = self.maps.create_map("../../evil", image=PNG)
        self.assertEqual(created["name"], "../../evil")
        self.assertRegex(created["image"], r"^map_[0-9a-f]+\.png$")
        self.assertFalse((self.folder / "evil.png").exists())
        self.assertEqual([p.name for p in (self.folder / "maps").iterdir()], [created["image"]])

    def test_jpeg_is_stored_with_jpg_name(self):
        created = self.maps.create_map("Photo", image=JPEG)
        self.assertRegex(created["image"], r"^map_[0-9a-f]+\.jpg$")
        self.assertEqual((self.folder / "maps" / created["image"]).read_bytes(), JPEG)

    def test_map_without_image(self):
        created = self.maps.create_map("Plain")
        self.assertIsNone(created["image"])
        self.assertIsNone(self.maps.image_path(created["id"]))
        self.assertFalse((self.folder / "maps").exists())

    def test_unknown_ids_build_no_path(self):
        self.maps.create_map("Ground floor", image=PNG)
        self.assertIsNone(self.maps.get_map("../maps.json"))
        self.assertIsNone(self.maps.image_path("../maps.json"))
        self.assertFalse(self.maps.delete_map("../maps.json"))
        self.assertEqual(len(self.maps.list_maps()), 1)

    def test_unsupported_image_is_refused(self):
        with self.assertRaises(ValueError) as cm:
            self.maps.create_map("GIF", image=b"GIF89a" + b"\x00" * 16)
        self.assertEqual(str(cm.exception), "unsupported_image")
        self.assertEqual(self.maps.list_maps(), [])

    def test_image_over_limit_is_refused(self):
        small = MapStore(self.store, max_image_bytes=len(PNG) - 1, now=lambda: NOW)
        with self.assertRaises(ValueError) as cm:
            small.create_map("Big", image=PNG)
        self.assertEqual(str(cm.exception), "image_too_large")
        self.assertEqual(self.maps.list_maps(), [])

    def test_image_at_limit_is_accepted(self):
        exact = MapStore(self.store, max_image_bytes=len(PNG), now=lambda: NOW)
        created = exact.create_map("Exact", image=PNG)
        self.assertIsNotNone(exact.get_map(created["id"]))

    def test_create_map_rolls_back_image_when_save_fails(self):
        def boom(*args, **kwargs):
            raise OSError("disk full")
        self.store.write_json = boom
        with self.assertRaises(OSError):
            self.maps.create_map("Ground floor", image=PNG)
        maps_dir = self.folder / "maps"
        remaining = list(maps_dir.iterdir()) if maps_dir.exists() else []
        self.assertEqual(remaining, [])

    def test_hypothesis_fields_start_empty(self):
        created = self.maps.create_map("Ground floor")
        self.assertEqual(set(created), MAP_FIELDS)
        for field in HYPOTHESIS_FIELDS:
            with self.subTest(field=field):
                self.assertEqual(created[field], [])


class TestScaleAndLock(MapStoreTestCase):
    def test_ca2_scale_and_locked_icon_are_read_back(self):
        created = self.maps.create_map(
            "Roof", scale=2.5, scale_unit="feet", icons=[{"device": DEVICE, "x": 10, "y": 20, "locked": True}]
        )
        stored = self.maps.get_map(created["id"])
        self.assertEqual(stored["scale"], 2.5)
        self.assertEqual(stored["scale_unit"], "feet")
        self.assertIs(stored["icons"][0]["locked"], True)
        self.assertEqual(stored["icons"][0]["x"], 10)

    def test_ca2_metres_and_icon_without_lock_read_back_unlocked(self):
        created = self.maps.create_map("Cellar", scale_unit="metres", icons=[{"device": DEVICE, "x": 1, "y": 2}])
        stored = self.maps.get_map(created["id"])
        self.assertEqual(stored["scale_unit"], "metres")
        self.assertIs(stored["icons"][0]["locked"], False)
        self.assertEqual(stored["icons"][0]["device"], DEVICE)

    def test_ca2_unknown_scale_unit_is_refused(self):
        with self.assertRaises(ValueError):
            self.maps.create_map("Bad", scale_unit="leagues")
        self.assertEqual(self.maps.list_maps(), [])

    def test_non_finite_or_non_positive_scale_is_refused(self):
        for bad in (float("nan"), float("inf"), float("-inf"), 0, -5, -2.5):
            with self.subTest(scale=bad):
                with self.assertRaises(ValueError):
                    self.maps.create_map("Bad", scale=bad)
        self.assertEqual(self.maps.list_maps(), [])

    def test_huge_integer_scale_is_refused(self):
        with self.assertRaises(ValueError):
            self.maps.create_map("Huge", scale=10 ** 400)
        self.assertEqual(self.maps.list_maps(), [])

    def test_invalid_inputs_are_refused(self):
        cases = [
            ("", {}),
            ("   ", {}),
            (7, {}),
            ("Bad", {"scale": "2"}),
            ("Bad", {"scale": True}),
            ("Bad", {"icons": "x"}),
            ("Bad", {"icons": ["x"]}),
        ]
        for name, kwargs in cases:
            with self.subTest(name=name, kwargs=kwargs):
                with self.assertRaises(ValueError):
                    self.maps.create_map(name, **kwargs)
        self.assertEqual(self.maps.list_maps(), [])


class TestUpdateAndList(MapStoreTestCase):
    def test_update_changes_unit_and_lock_and_reads_back(self):
        created = self.maps.create_map(
            "Roof", scale_unit="metres", icons=[{"device": DEVICE, "x": 1, "y": 2, "locked": False}]
        )
        updated = self.maps.update_map(
            created["id"],
            {"scale_unit": "feet", "icons": [{"device": DEVICE, "x": 1, "y": 2, "locked": True}]},
        )
        self.assertEqual(updated["scale_unit"], "feet")
        stored = self.maps.get_map(created["id"])
        self.assertEqual(stored["scale_unit"], "feet")
        self.assertIs(stored["icons"][0]["locked"], True)
        self.assertEqual(stored["name"], "Roof")

    def test_update_refuses_unknown_field_and_unknown_id(self):
        created = self.maps.create_map("Roof")
        with self.assertRaises(ValueError):
            self.maps.update_map(created["id"], {"image": "map_x.png"})
        self.assertIsNone(self.maps.update_map("../maps.json", {"name": "x"}))
        self.assertIsNone(self.maps.get_map(created["id"])["image"])

    def test_update_refuses_invalid_values_and_keeps_the_record(self):
        created = self.maps.create_map("Roof", scale_unit="metres")
        for changes in ({"name": ""}, {"scale_unit": "x"}, {"scale": float("inf")}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    self.maps.update_map(created["id"], changes)
        stored = self.maps.get_map(created["id"])
        self.assertEqual(stored["name"], "Roof")
        self.assertEqual(stored["scale_unit"], "metres")

    def test_list_returns_every_map(self):
        self.maps.create_map("Ground floor", image=PNG)
        self.maps.create_map("Roof", scale=2.5, scale_unit="feet")
        self.assertEqual(len(self.maps.list_maps()), 2)
        self.assertEqual(sorted(item["name"] for item in self.maps.list_maps()), ["Ground floor", "Roof"])


if __name__ == "__main__":
    unittest.main()
