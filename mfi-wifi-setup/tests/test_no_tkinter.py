"""Offline test: the core of mfi_wifi_setup never needs tkinter.

Only window.py imports tkinter. The six core modules are checked two ways:
their syntax tree has no import of tkinter, and they import normally while
tkinter is made unavailable. Standard library only.

Run from the repository root:
    python3 -m unittest discover -s mfi-wifi-setup/tests -t mfi-wifi-setup -v
"""
from __future__ import annotations

import ast
import importlib
import sys
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent / "mfi_wifi_setup"
CORE_FILES = (
    "bridge.py",
    "device_check.py",
    "messages.py",
    "config_store.py",
    "wifi_survey.py",
    "wifi_configure.py",
)
CORE_MODULES = tuple("mfi_wifi_setup." + name[:-3] for name in CORE_FILES)
BLOCKED = ("tkinter", "tkinter.ttk", "tkinter.messagebox", "tkinter.font")


def tkinter_imports(source: str, filename: str = "<core>") -> list[str]:
    """Every import of tkinter in the source: 'import tkinter' or 'from tkinter ... import ...'."""
    found = []
    for node in ast.walk(ast.parse(source, filename=filename)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "tkinter" or alias.name.startswith("tkinter."):
                    found.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "tkinter" or module.startswith("tkinter."):
                found.append(f"from {module} import ...")
    return found


class TestCoreSourceHasNoTkinter(unittest.TestCase):
    def test_core_modules_do_not_import_tkinter(self):
        for name in CORE_FILES:
            with self.subTest(module=name):
                source = (PACKAGE / name).read_text(encoding="utf-8")
                self.assertEqual(tkinter_imports(source, name), [], name)

    def test_scanner_flags_planted_imports(self):
        planted = "import os\nimport tkinter\nfrom tkinter import ttk\nfrom tkinter.font import Font\n"
        self.assertEqual(len(tkinter_imports(planted)), 3)
        self.assertEqual(tkinter_imports("import json\nfrom pathlib import Path\n"), [])

    def test_package_init_imports_no_submodule(self):
        source = (PACKAGE / "__init__.py").read_text(encoding="utf-8")
        nodes = [n for n in ast.walk(ast.parse(source)) if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertEqual(nodes, [])


class TestCoreImportsWithoutTkinter(unittest.TestCase):
    def setUp(self):
        names = BLOCKED + CORE_MODULES + ("mfi_wifi_setup",)
        self.saved = {name: sys.modules.get(name) for name in names}
        # Remove the cached modules so each import really runs the module code.
        for name in CORE_MODULES + ("mfi_wifi_setup",):
            sys.modules.pop(name, None)
        for name in BLOCKED:
            sys.modules[name] = None

    def tearDown(self):
        for name, module in self.saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    def test_tkinter_is_unavailable(self):
        with self.assertRaises(ImportError):
            importlib.import_module("tkinter")

    def test_core_modules_import_without_tkinter(self):
        for name in CORE_MODULES:
            with self.subTest(module=name):
                self.assertIsNotNone(importlib.import_module(name))


if __name__ == "__main__":
    unittest.main()
