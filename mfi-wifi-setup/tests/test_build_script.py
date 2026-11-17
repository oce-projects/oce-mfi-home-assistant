"""Offline test: the Windows build script, its pinned PyInstaller and the build ignores.

The script is run by a person on Windows; this test only reads the files as
text, so it runs anywhere. Standard library only.

Run from the repository root:
    python3 -m unittest discover -s mfi-wifi-setup/tests -t mfi-wifi-setup -v
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

FOLDER = Path(__file__).resolve().parent.parent  # mfi-wifi-setup/
ROOT = FOLDER.parent  # repository root
BUILD_SCRIPT = FOLDER / "build_windows.cmd"
REQUIREMENTS = FOLDER / "requirements-build.txt"
ROOT_GITIGNORE = ROOT / ".gitignore"

REQUIRED_IN_SCRIPT = (
    "@echo off",
    "setlocal",
    "--onefile",
    "--windowed",
    "certutil",
    "SHA256",
    "if errorlevel 1",
    "rmdir",
    "requirements-build.txt",
)
LOCAL_PATHS = ("C:\\Users", "/home/", "/Users/")
PYINSTALLER_PIN = re.compile(r"^pyinstaller==\d+\.\d+\.\d+$", re.M)
REQUIRED_IGNORES = ("mfi-wifi-setup/dist/", "mfi-wifi-setup/build/", "*.spec")


class TestBuildScript(unittest.TestCase):
    def setUp(self):
        self.script = BUILD_SCRIPT.read_text(encoding="utf-8")

    def test_script_has_required_steps(self):
        for item in REQUIRED_IN_SCRIPT:
            with self.subTest(item=item):
                self.assertIn(item, self.script)

    def test_script_has_no_local_absolute_path(self):
        for path in LOCAL_PATHS:
            with self.subTest(path=path):
                self.assertNotIn(path, self.script)

    def test_cleans_build_dir_before_creating_venv(self):
        # A stale temporary folder from an interrupted build must be removed first.
        cleanup = self.script.index('rmdir /s /q "%BUILD_DIR%"')
        venv = self.script.index("python -m venv")
        self.assertLess(cleanup, venv)

    def test_hash_written_without_language_filter(self):
        # The .sha256 must not depend on English certutil header text.
        self.assertNotIn("findstr", self.script)
        self.assertIn("skip=1", self.script)

    def test_entry_point_uses_absolute_import(self):
        # PyInstaller runs the entry script as the top-level __main__ with no
        # parent package; a relative-import entry would crash in the frozen
        # .exe, so the build uses a small absolute-import launcher.
        self.assertIn("from mfi_wifi_setup.window import run", self.script)
        self.assertIn("--paths", self.script)


class TestBuildRequirements(unittest.TestCase):
    def test_pyinstaller_is_pinned(self):
        text = REQUIREMENTS.read_text(encoding="utf-8")
        self.assertRegex(text, PYINSTALLER_PIN)


class TestRootGitignore(unittest.TestCase):
    def test_build_output_is_ignored(self):
        lines = ROOT_GITIGNORE.read_text(encoding="utf-8").splitlines()
        for item in REQUIRED_IGNORES:
            with self.subTest(item=item):
                self.assertIn(item, lines)


if __name__ == "__main__":
    unittest.main()
