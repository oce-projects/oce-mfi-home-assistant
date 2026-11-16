"""Checks the icons and logos written by tools/make_icons.py.

Run from the repository root:
    python3 -m unittest discover -s mfi-server/tests -t mfi-server -v

Standard library only; no network. The pixels are read here by decompressing
IDAT and undoing the filter: tools/make_icons.py writes only filter type 0, so
each scanline starts with a 0 byte and the 4 RGBA bytes of a pixel follow it
unchanged.
"""
from __future__ import annotations

import importlib.util
import struct
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SIGNATURE = b"\x89PNG\r\n\x1a\n"

_spec = importlib.util.spec_from_file_location("make_icons", ROOT / "tools" / "make_icons.py")
make_icons = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(make_icons)


def read_pixel(png: bytes, x: int, y: int) -> tuple:
    """Returns the RGBA pixel (x, y) of an 8-bit RGBA PNG written with filter 0."""
    pos = len(SIGNATURE)
    width = 0
    idat = b""
    while pos < len(png):
        (length,) = struct.unpack(">I", png[pos:pos + 4])
        kind = png[pos + 4:pos + 8]
        body = png[pos + 8:pos + 8 + length]
        if kind == b"IHDR":
            width, _height = struct.unpack(">II", body[0:8])
        elif kind == b"IDAT":
            idat += body
        pos += 12 + length
    raw = zlib.decompress(idat)
    stride = 1 + width * 4
    line = y * stride
    if raw[line] != 0:
        raise ValueError(f"row {y} uses filter {raw[line]}, expected 0")
    start = line + 1 + x * 4
    return tuple(raw[start:start + 4])


class TestIcons(unittest.TestCase):
    def test_every_icon_file_exists_with_png_signature_and_size(self):
        for relpath, width, height, _bg, _fg, _box in make_icons.ICONS:
            with self.subTest(file=relpath):
                path = ROOT / relpath
                self.assertTrue(path.is_file(), f"{relpath} missing: run python3 tools/make_icons.py")
                data = path.read_bytes()
                self.assertTrue(data.startswith(SIGNATURE))
                self.assertIn(struct.unpack(">II", data[16:24]), {(128, 128), (250, 100)})
                self.assertEqual(struct.unpack(">II", data[16:24]), (width, height))

    def test_every_icon_file_matches_the_generator_byte_for_byte(self):
        for relpath, width, height, bg, fg, icon_box in make_icons.ICONS:
            with self.subTest(file=relpath):
                data = (ROOT / relpath).read_bytes()
                expected = make_icons.render_png(width, height, bg, fg, icon_box)
                self.assertEqual(data, expected)

    def test_png_has_only_ihdr_idat_and_iend_chunks(self):
        for relpath, _width, _height, _bg, _fg, _box in make_icons.ICONS:
            with self.subTest(file=relpath):
                data = (ROOT / relpath).read_bytes()
                kinds = []
                pos = len(SIGNATURE)
                while pos < len(data):
                    (length,) = struct.unpack(">I", data[pos:pos + 4])
                    kinds.append(data[pos + 4:pos + 8])
                    pos += 12 + length
                self.assertEqual(kinds, [b"IHDR", b"IDAT", b"IEND"])

    def test_render_draws_plug_white_centre_and_blue_background(self):
        png = make_icons.render_png(128, 128, (30, 136, 229), (255, 255, 255), (0, 0, 128))
        self.assertEqual(read_pixel(png, 64, 64), (255, 255, 255, 255))
        self.assertEqual(read_pixel(png, 64, 20), (30, 136, 229, 255))
        self.assertEqual(read_pixel(png, 0, 0), (0, 0, 0, 0))


if __name__ == "__main__":
    unittest.main()
