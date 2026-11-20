"""Floor plans and the placement of devices on them (EPIC-12). Standard library only.

MapStore keeps the map records in maps.json, written through store.write_json, and the image files in
data_dir/maps/. Image file names are made here (uuid4 hex plus the extension of the magic bytes), never from
the map name or the icons, so a request cannot choose a path or overwrite a file. The fields marked
"needs device test (R-WEB)" are hypotheses from docs/controller/ui.md and stay empty until a device confirms them.
"""
from __future__ import annotations

import math
import os
import pathlib
import threading
import time
import uuid


class MapStore:
    """Map records and map images. Receives the Store object and never imports the package."""

    MAPS_FILE = "maps.json"
    IMAGE_SUBDIR = "maps"
    PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
    JPEG_MAGIC = b"\xff\xd8\xff"
    DEFAULT_MAX_IMAGE_BYTES = 5242880
    SCALE_UNITS = ("metres", "feet")
    UPDATABLE = ("name", "scale", "scale_unit", "icons")

    def __init__(self, store, *, max_image_bytes=DEFAULT_MAX_IMAGE_BYTES, now=time.time):
        self._store = store
        self._max_image_bytes = max_image_bytes
        self._now = now
        self._lock = threading.Lock()

    def list_maps(self) -> list[dict]:
        """Return every map, sorted by creation time and then by id."""
        return sorted(self._load().values(), key=lambda item: (item["created"], item["id"]))

    def get_map(self, map_id) -> dict | None:
        """Return the stored map with this id, or None. Only stored keys match, so no path is built from map_id."""
        return self._stored(self._load(), map_id)

    def create_map(self, name, *, scale=None, scale_unit="metres", image=None, icons=None) -> dict:
        """Store a new map, with its image when given. Return the stored record."""
        name, scale, scale_unit, icons = self._checked(name, scale, scale_unit, icons)
        data = self._checked_image(image)
        map_id = uuid.uuid4().hex
        image_name = None
        if data is not None:
            extension = ".png" if data.startswith(self.PNG_MAGIC) else ".jpg"
            image_name = f"map_{map_id}{extension}"
        record = {
            "id": map_id,
            "name": name,
            "scale": scale,
            "scale_unit": scale_unit,
            "image": image_name,
            "icons": icons,
            "created": int(self._now()),
            "locations": [],  # needs device test (R-WEB)
            "geofences": [],  # needs device test (R-WEB)
            "liveviews": [],  # needs device test (R-WEB)
            "widgets": [],  # needs device test (R-WEB)
            "templates": [],  # needs device test (R-WEB)
            "configtemplates": [],  # needs device test (R-WEB)
            "motion_fields": [],  # needs device test (R-WEB)
        }
        try:
            with self._lock:
                if data is not None:
                    self._write_image(image_name, data)
                maps = self._load()
                maps[map_id] = record
                self._save(maps)
        except BaseException:
            # Remove the image of a map that was not saved, so no orphan file stays in maps/.
            if image_name is not None:
                self._image_file(image_name).unlink(missing_ok=True)
            raise
        return record

    def update_map(self, map_id, changes) -> dict | None:
        """Change name, scale, scale unit or icons of a stored map. Return the record, or None for an unknown id."""
        with self._lock:
            maps = self._load()
            record = self._stored(maps, map_id)
            if record is None:
                return None
            if not isinstance(changes, dict):
                raise ValueError("changes")
            for field in changes:
                if field not in self.UPDATABLE:
                    raise ValueError(f"unknown field: {field}")
            merged = {field: changes.get(field, record[field]) for field in self.UPDATABLE}
            name, scale, scale_unit, icons = self._checked(
                merged["name"], merged["scale"], merged["scale_unit"], merged["icons"]
            )
            record.update(name=name, scale=scale, scale_unit=scale_unit, icons=icons)
            self._save(maps)
        return record

    def delete_map(self, map_id) -> bool:
        """Remove the map and its image file. Return False when map_id is not stored."""
        with self._lock:
            maps = self._load()
            record = self._stored(maps, map_id)
            if record is None:
                return False
            del maps[map_id]
            self._save(maps)
        if record["image"] is not None:
            self._image_file(record["image"]).unlink(missing_ok=True)
        return True

    def image_path(self, map_id) -> pathlib.Path | None:
        """Return the path of the map image when the map is stored and the file exists, else None."""
        record = self._stored(self._load(), map_id)
        if record is None or record["image"] is None:
            return None
        path = self._image_file(record["image"])
        return path if path.is_file() else None

    def _load(self) -> dict:
        return self._store.read_json(self.MAPS_FILE, {"maps": {}})["maps"]

    def _save(self, maps: dict) -> None:
        self._store.write_json(self.MAPS_FILE, {"maps": maps}, private=True)

    @staticmethod
    def _stored(maps: dict, map_id) -> dict | None:
        if not isinstance(map_id, str):
            return None
        return maps.get(map_id)

    def _image_file(self, name) -> pathlib.Path:
        if not isinstance(name, str) or name in ("", ".", "..") or pathlib.PurePath(name).name != name:
            raise ValueError("unsafe image name")
        return self._store.data_dir / self.IMAGE_SUBDIR / name

    def _write_image(self, name, data: bytes) -> None:
        os.makedirs(self._store.data_dir / self.IMAGE_SUBDIR, mode=0o700, exist_ok=True)
        fd = os.open(self._image_file(name), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())

    def _checked(self, name, scale, scale_unit, icons):
        """Validate the map fields and return them, with every icon carrying a bool 'locked'."""
        if not isinstance(name, str) or not name.strip():
            raise ValueError("name")
        if scale_unit not in self.SCALE_UNITS:
            raise ValueError("scale_unit")
        if scale is not None and (
            isinstance(scale, bool)
            or not isinstance(scale, (int, float))
            or not math.isfinite(scale)
            or scale <= 0
        ):
            raise ValueError("scale")
        if icons is None:
            icons = []
        if not isinstance(icons, list):
            raise ValueError("icons")
        checked = []
        for icon in icons:
            if not isinstance(icon, dict):
                raise ValueError("icons")
            item = dict(icon)
            item["locked"] = bool(icon.get("locked"))
            checked.append(item)
        return name, scale, scale_unit, checked

    def _checked_image(self, image) -> bytes | None:
        """Return the image bytes when they are a PNG or JPEG within the size limit, else raise ValueError."""
        if image is None:
            return None
        if not isinstance(image, (bytes, bytearray)):
            raise ValueError("image")
        data = bytes(image)
        if not data.startswith((self.PNG_MAGIC, self.JPEG_MAGIC)):
            raise ValueError("unsupported_image")
        if len(data) > self._max_image_bytes:
            raise ValueError("image_too_large")
        return data
