"""Offline test: the version of mfi_wifi_setup matches the newest CHANGELOG.md entry.

Standard library only.

Run from the repository root:
    python3 -m unittest discover -s mfi-wifi-setup/tests -t mfi-wifi-setup -v
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

import mfi_wifi_setup

CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"
ENTRY = re.compile(r"^##\s+(\d+\.\d+\.\d+)\b", re.M)


class TestVersion(unittest.TestCase):
    def test_version_format(self):
        self.assertIsNotNone(re.fullmatch(r"\d+\.\d+\.\d+", mfi_wifi_setup.__version__))

    def test_newest_changelog_entry_matches_package(self):
        text = CHANGELOG.read_text(encoding="utf-8")
        match = ENTRY.search(text)
        self.assertIsNotNone(match, "no ## X.Y.Z entry in CHANGELOG.md")
        self.assertEqual(match.group(1), mfi_wifi_setup.__version__)


if __name__ == "__main__":
    unittest.main()
