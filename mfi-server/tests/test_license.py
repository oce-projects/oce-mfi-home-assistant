"""Checks that the repository carries the Apache-2.0 license text and the image label."""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LICENSE_PHRASES = [
    "Apache License",
    "Version 2.0, January 2004",
    "TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION",
    "1. Definitions.",
    "9. Accepting Warranty or Additional Liability.",
    "END OF TERMS AND CONDITIONS",
    "APPENDIX: How to apply the Apache License to your work.",
]


class TestLicense(unittest.TestCase):
    def test_license_file_has_apache_key_phrases(self):
        text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        for phrase in LICENSE_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_dockerfile_declares_apache_license(self):
        text = (ROOT / "mfi-server" / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn('org.opencontainers.image.licenses="Apache-2.0"', text)


if __name__ == "__main__":
    unittest.main()
