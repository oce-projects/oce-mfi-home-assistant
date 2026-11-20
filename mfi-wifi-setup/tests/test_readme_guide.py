"""Offline test for the mfi-wifi-setup README guide sections.

Standard library only.

Run from the repository root:
    python3 -m unittest discover -s mfi-wifi-setup/tests -t mfi-wifi-setup -v
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

import mfi_wifi_setup

FOLDER = Path(__file__).resolve().parent.parent
ROOT = FOLDER.parent
README = FOLDER / "README.md"
WIFI_SETUP = ROOT / "docs" / "WIFI-SETUP.md"


class TestReadmeGuide(unittest.TestCase):
    def test_guide_sections_are_in_order(self):
        text = README.read_text(encoding="utf-8")
        run_pos = text.find("## Run")
        step_pos = text.find("## Step by step")
        troub_pos = text.find("## Troubleshooting")
        v2_pos = text.find("## Version 2: guided setup (0.3.0)")
        self.assertGreater(step_pos, run_pos)
        self.assertGreater(troub_pos, step_pos)
        self.assertGreater(v2_pos, troub_pos)

    def test_step_by_step_has_the_device_facts(self):
        text = README.read_text(encoding="utf-8")
        step_start = text.find("## Step by step")
        step_end = text.find("## ", step_start + 1)
        step_text = text[step_start:step_end]
        for phrase in ("alternates colors", "Solid yellow", "Flashing yellow", "Flashing blue", "Solid blue", "Quick Start Guide", "6080", "UNVERIFIED"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, step_text, f"'{phrase}' missing in Step by step")

    def test_readme_version_matches_package(self):
        text = README.read_text(encoding="utf-8")
        match = re.search(r"^Version (\d+\.\d+\.\d+)", text, re.M)
        self.assertIsNotNone(match, "no Version line in README.md")
        self.assertEqual(match.group(1), mfi_wifi_setup.__version__)

    def test_spec_links_the_guide(self):
        text = WIFI_SETUP.read_text(encoding="utf-8")
        self.assertIn("mfi-wifi-setup/README.md", text)
        self.assertIn("Step by step", text)


if __name__ == "__main__":
    unittest.main()
