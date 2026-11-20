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

    def test_numbered_steps_start_a_list_item(self):
        text = README.read_text(encoding="utf-8")
        step_start = text.find("## Step by step")
        step_end = text.find("## ", step_start + 1)
        lines = text[step_start:step_end].splitlines()
        numbered = [i for i, line in enumerate(lines) if re.match(r"^\d+\. ", line)]
        self.assertEqual(len(numbered), 7)
        for i in numbered:
            if i == 0:
                continue
            prev = lines[i - 1].strip()
            self.assertTrue(prev == "" or re.match(r"^\d+\. ", prev), f"line {i} does not start a list item")

    def test_readme_does_not_claim_mfi_server_adopts(self):
        text = README.read_text(encoding="utf-8")
        self.assertNotIn("in a table", text)
        self.assertNotIn("the device appears and is adopted", text)
        self.assertNotIn("it adopts the device", text)

    def test_troubleshooting_marks_deduced_causes(self):
        text = README.read_text(encoding="utf-8")
        troub_start = text.find("## Troubleshooting")
        troub_end = text.find("## ", troub_start + 1)
        self.assertGreaterEqual(text[troub_start:troub_end].count("UNVERIFIED"), 2)

    def test_changelog_has_no_wrong_date(self):
        changelog = (FOLDER / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertNotIn("2026-11-21", changelog)

    def test_spec_links_the_guide(self):
        text = WIFI_SETUP.read_text(encoding="utf-8")
        self.assertIn("mfi-wifi-setup/README.md", text)
        self.assertIn("Step by step", text)
        self.assertIn("mfi-server 1.0.0 does not adopt devices yet", text)


if __name__ == "__main__":
    unittest.main()
