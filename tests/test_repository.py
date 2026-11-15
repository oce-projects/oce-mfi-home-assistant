"""Offline structure tests for the mfi-home-assistant repository.

Version: 1.0.0

Changelog:
1.0.0 - 2026-11-15 - first version: versions vs changelogs, repository.yaml,
        add-on folder layout, AGENTS.md size, no vendor files, no private data.
        Each scanner is also tested on planted samples, so a green run cannot
        come from a scanner that matches nothing.

Run from the repository root:
    python3 -m unittest discover -s tests -v

Standard library only; no network, no git, no Docker (DevAgentAi runs tests in
a container without network).
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
THIS_FILE = Path(__file__).resolve()
SKIP_DIRS = {".git", ".tickets", "__pycache__", ".venv", "node_modules"}

VENDOR_SUFFIXES = {".jar", ".zip", ".deb", ".bin", ".unf", ".exe", ".dmg", ".pkg"}
VENDOR_NAMES = {"db.gz", "ace.jar", "mfi.unix.zip", "firmware.bin"}

PRIVATE_PATTERNS = {
    "home LAN address of the maintainer": re.compile(r"\b192\.168\.1\.(9|120|228)\b"),
    "UNC path to a LAN share": re.compile(r"\\\\\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\\"),
    "local Windows drive path": re.compile(r"\b[A-Z]:\\[A-Za-z_]"),
    "personal name": re.compile(r"(?i)\boscar\b"),
    "e-mail address": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z]{2,}"),
    "MAC address": re.compile(r"(?i)\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b"),
}

TEXT_SUFFIXES = {".md", ".yaml", ".yml", ".json", ".py", ".sh", ".txt", ".toml", ".cfg", ""}
RULES_LIMIT = 12000  # DevAgentAi regole_max_car default
RULES_FILES = ["AGENTS.md", "docs/ARCHITECTURE.md"]

SEMVER = r"(\d+\.\d+\.\d+)"


def repo_files() -> list[Path]:
    out = []
    for p in ROOT.rglob("*"):
        if p.is_file() and not (SKIP_DIRS & set(p.relative_to(ROOT).parts)):
            out.append(p)
    return out


def newest_changelog_version(path: Path) -> str | None:
    m = re.search(r"^##\s+" + SEMVER, path.read_text(encoding="utf-8"), flags=re.M)
    return m.group(1) if m else None


def addon_version(config: Path) -> str | None:
    m = re.search(r'^version:\s*["\']?' + SEMVER + r'["\']?\s*$', config.read_text(encoding="utf-8"), flags=re.M)
    return m.group(1) if m else None


def addon_dirs() -> list[Path]:
    return sorted(p.parent for p in ROOT.glob("*/config.yaml"))


def vendor_hits(paths: list[Path]) -> list[str]:
    return [str(p) for p in paths if p.suffix.lower() in VENDOR_SUFFIXES or p.name.lower() in VENDOR_NAMES]


def private_hits(name: str, text: str) -> list[str]:
    hits = []
    for label, rx in PRIVATE_PATTERNS.items():
        for m in rx.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            hits.append(f"{name}:{line}: {label}: {m.group(0)!r}")
    return hits


class TestScannersCatchPlantedSamples(unittest.TestCase):
    """Guards against a green run caused by scanners that never match."""

    def test_private_scanner_flags_each_pattern(self):
        samples = {
            "home LAN address of the maintainer": "host 192.168.1.228 here",
            "UNC path to a LAN share": r"see \\10.0.0.5\share\x",
            "local Windows drive path": r"open W:\_FOLDER now",
            "personal name": "written by Oscar",
            "e-mail address": "mail someone@example.org",
            "MAC address": "mac 24:A4:3C:01:02:03",
        }
        for label, text in samples.items():
            with self.subTest(label=label):
                self.assertTrue(any(label in h for h in private_hits("sample", text)), label)

    def test_private_scanner_allows_documented_factory_ip(self):
        self.assertEqual(private_hits("sample", "factory default IP 192.168.1.20"), [])

    def test_vendor_scanner_flags_binaries(self):
        planted = [Path("x/ace.jar"), Path("x/mFi.unix.zip"), Path("x/backup.unf"), Path("x/firmware.bin")]
        self.assertEqual(len(vendor_hits(planted)), 4)
        self.assertEqual(vendor_hits([Path("x/README.md"), Path("x/Dockerfile")]), [])


class TestRepository(unittest.TestCase):
    def test_version_matches_changelog(self):
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        self.assertRegex(version, "^" + SEMVER + "$")
        self.assertEqual(version, newest_changelog_version(ROOT / "CHANGELOG.md"))

    def test_repository_yaml_keys(self):
        text = (ROOT / "repository.yaml").read_text(encoding="utf-8")
        for key in ("name", "url", "maintainer"):
            with self.subTest(key=key):
                self.assertRegex(text, rf"(?m)^{key}:\s*\S+")

    def test_rules_files_fit_devagentai_limit(self):
        total = sum(len((ROOT / f).read_text(encoding="utf-8")) for f in RULES_FILES)
        self.assertLess(total, RULES_LIMIT, f"{RULES_FILES} = {total} characters")

    def test_no_vendor_files(self):
        self.assertEqual(vendor_hits(repo_files()), [])

    def test_no_private_data(self):
        hits = []
        for p in repo_files():
            if p.resolve() == THIS_FILE or p.suffix.lower() not in TEXT_SUFFIXES:
                continue
            try:
                text = p.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            hits += private_hits(str(p.relative_to(ROOT)), text)
        self.assertEqual(hits, [], "\n".join(hits))


class TestAddons(unittest.TestCase):
    def test_each_addon_has_required_files(self):
        for d in addon_dirs():
            for f in ("config.yaml", "Dockerfile", "README.md", "CHANGELOG.md"):
                with self.subTest(addon=d.name, file=f):
                    self.assertTrue((d / f).is_file(), f"{d.name}/{f} missing")

    def test_each_addon_version_matches_its_changelog(self):
        for d in addon_dirs():
            with self.subTest(addon=d.name):
                v = addon_version(d / "config.yaml")
                self.assertIsNotNone(v, f"{d.name}/config.yaml has no semantic version")
                self.assertEqual(v, newest_changelog_version(d / "CHANGELOG.md"))

    def test_each_addon_declares_slug_and_arch(self):
        for d in addon_dirs():
            text = (d / "config.yaml").read_text(encoding="utf-8")
            with self.subTest(addon=d.name):
                self.assertRegex(text, r"(?m)^slug:\s*\S+")
                self.assertRegex(text, r"(?m)^arch:")


if __name__ == "__main__":
    unittest.main()
