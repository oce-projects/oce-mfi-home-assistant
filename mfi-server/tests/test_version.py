"""Checks that the add-on version is the same in every file that states it."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from mfi_server import __version__

ADDON = Path(__file__).resolve().parent.parent


class TestVersion(unittest.TestCase):
    def test_version_matches_config(self):
        text = (ADDON / "config.yaml").read_text(encoding="utf-8")
        m = re.search(r'^version:\s*"(\d+\.\d+\.\d+)"\s*$', text, flags=re.M)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), __version__)

    def test_version_matches_changelog(self):
        text = (ADDON / "CHANGELOG.md").read_text(encoding="utf-8")
        m = re.search(r"^##\s+(\d+\.\d+\.\d+)", text, flags=re.M)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), __version__)

    def test_version_matches_dockerfile(self):
        text = (ADDON / "Dockerfile").read_text(encoding="utf-8")
        m = re.search(r'^ARG BUILD_VERSION="(\d+\.\d+\.\d+)"\s*$', text, flags=re.M)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), __version__)

    def test_version_is_0_3_0(self):
        self.assertEqual(__version__, "0.3.0")


if __name__ == "__main__":
    unittest.main()
