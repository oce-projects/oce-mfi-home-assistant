"""Offline test: the program icon of mfi-wifi-setup (icon.ico, icon.py and the window code).

Reads the window and the icon module as text with ast, so tkinter is never
imported. Standard library only.

Run from the repository root:
    python3 -m unittest discover -s mfi-wifi-setup/tests -t mfi-wifi-setup -v
"""
from __future__ import annotations

import ast
import contextlib
import importlib.util
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mfi_wifi_setup import icon

FOLDER = Path(__file__).resolve().parent.parent  # mfi-wifi-setup/
ROOT = FOLDER.parent  # repository root
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
ICON_SIZES = (16, 32, 48, 256)
BG = (67, 160, 71)
FG = (255, 255, 255)

_spec = importlib.util.spec_from_file_location("make_icons", ROOT / "tools" / "make_icons.py")
make_icons = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(make_icons)


def png_end(data: bytes, start: int) -> int:
    """Offset just after the IEND chunk of the PNG that starts at start."""
    pos = start + len(PNG_SIGNATURE)
    while True:
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        kind = data[pos + 4:pos + 8]
        pos += 12 + length
        if kind == b"IEND":
            return pos


def frozen_in(folder: str) -> contextlib.ExitStack:
    """Pretend to run from a PyInstaller .exe whose temporary folder is folder."""
    stack = contextlib.ExitStack()
    stack.enter_context(mock.patch.object(icon.sys, "frozen", True, create=True))
    stack.enter_context(mock.patch.object(icon.sys, "_MEIPASS", folder, create=True))
    return stack


class TestIcoFile(unittest.TestCase):
    def setUp(self):
        self.data = make_icons.render_ico(ICON_SIZES, BG, FG)

    def test_ico_header_and_entries(self):
        self.assertEqual(self.data[:6], b"\x00\x00\x01\x00\x04\x00")
        widths = []
        expected_offset = 6 + 16 * len(ICON_SIZES)
        for index, size in enumerate(ICON_SIZES):
            pos = 6 + 16 * index
            w, h, _colors, _reserved, planes, bits, length, offset = struct.unpack(
                "<BBBBHHII", self.data[pos:pos + 16]
            )
            widths.append(w)
            self.assertEqual((w, h), (size % 256, size % 256))
            self.assertEqual((planes, bits), (1, 32))
            self.assertEqual(offset, expected_offset)
            self.assertEqual(self.data[offset:offset + 8], PNG_SIGNATURE)
            self.assertEqual(png_end(self.data, offset) - offset, length)
            self.assertEqual(struct.unpack(">II", self.data[offset + 16:offset + 24]), (size, size))
            expected_offset += length
        self.assertEqual(widths, [16, 32, 48, 0])
        self.assertEqual(expected_offset, len(self.data))

    def test_size_out_of_range_is_refused(self):
        for size in (0, 257):
            with self.subTest(size=size):
                with self.assertRaises(ValueError):
                    make_icons.render_ico((size,), BG, FG)

    def test_icon_file_matches_the_generator(self):
        path = FOLDER / "icon.ico"
        self.assertTrue(path.is_file(), "missing mfi-wifi-setup/icon.ico: run python3 tools/make_icons.py")
        entries = [entry for entry in make_icons.ICO_FILES if entry[0] == "mfi-wifi-setup/icon.ico"]
        self.assertEqual(len(entries), 1)
        _relpath, sizes, bg, fg = entries[0]
        self.assertEqual(path.read_bytes(), make_icons.render_ico(sizes, bg, fg))


class TestIconPath(unittest.TestCase):
    def test_source_icon_is_found(self):
        with mock.patch.object(icon.sys, "frozen", False, create=True):
            self.assertEqual(icon.icon_path(), FOLDER / "icon.ico")

    def test_frozen_icon_is_read_from_meipass(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "icon.ico").write_bytes(b"x")
            with frozen_in(tmp):
                self.assertEqual(icon.icon_path(), Path(tmp) / "icon.ico")

    def test_frozen_missing_icon_gives_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            with frozen_in(tmp):
                self.assertIsNone(icon.icon_path())


class TestIconSources(unittest.TestCase):
    def test_icon_module_has_no_tkinter(self):
        source = (FOLDER / "mfi_wifi_setup" / "icon.py").read_text(encoding="utf-8")
        names = []
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                names += [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names.append(node.module or "")
        self.assertEqual([name for name in names if name.split(".")[0] == "tkinter"], [])

    def test_window_sets_the_icon_safely(self):
        source = (FOLDER / "mfi_wifi_setup" / "window.py").read_text(encoding="utf-8")
        functions = {node.name: node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.FunctionDef)}
        self.assertIn("_set_icon", functions)
        set_icon = functions["_set_icon"]
        handlers = [node for node in ast.walk(set_icon) if isinstance(node, ast.ExceptHandler)]
        self.assertTrue(
            any(isinstance(h.type, ast.Attribute) and h.type.attr == "TclError" for h in handlers),
            "_set_icon must catch tk.TclError",
        )
        self.assertTrue(
            any(isinstance(n, ast.Attribute) and n.attr == "iconbitmap" for n in ast.walk(set_icon)),
            "_set_icon must call iconbitmap",
        )
        run_calls = [
            node for node in ast.walk(functions["run"])
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_set_icon"
        ]
        self.assertTrue(run_calls, "run() must call _set_icon")


if __name__ == "__main__":
    unittest.main()
