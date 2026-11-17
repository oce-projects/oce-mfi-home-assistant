"""Offline tests for tools/bump_version.py (standard library only).

Every test works on a copy of the version files in a temporary folder. The
starting versions are written by hand in this file; the real files of the
repository are never read or changed.
"""

import datetime
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "tools" / "bump_version.py"
LINE = "test change for the version bump"
OLD_CHANGELOG = "# Changelog\n\n## 1.2.3 - 2020-01-01\n\n- start\n"

# Starting files of each component, with version 1.2.3 written by hand.
FILES = {
    "repo": {
        "VERSION": "1.2.3\n",
        "CHANGELOG.md": OLD_CHANGELOG,
    },
    "mfi-server": {
        "mfi-server/config.yaml": 'name: "mFi Server"\nversion: "1.2.3"\nslug: "mfi_server"\n',
        "mfi-server/CHANGELOG.md": OLD_CHANGELOG,
        "mfi-server/Dockerfile": 'FROM python:3\nARG BUILD_VERSION="1.2.3"\n',
        "mfi-server/mfi_server/__init__.py": '"""mFi Server."""\n\n__version__ = "1.2.3"\n',
    },
    "mfi-controller": {
        "mfi-controller/config.yaml": 'name: "Controller"\nversion: "1.2.3"\n',
        "mfi-controller/CHANGELOG.md": OLD_CHANGELOG,
        "mfi-controller/Dockerfile": 'FROM debian\nARG BUILD_VERSION="1.2.3"\n',
    },
    "mfi-wifi-setup": {
        "mfi-wifi-setup/mfi_wifi_setup/__init__.py": '"""Setup."""\n\n__version__ = "1.2.3"\n',
        "mfi-wifi-setup/CHANGELOG.md": OLD_CHANGELOG,
    },
}

ALL_FILES = [rel for files in FILES.values() for rel in files]


def today_utc():
    """Today's date in UTC, as the tool writes it."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


def sha256_of(path):
    """SHA-256 of a file, used to prove that nothing was written."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


class BumpVersionTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for files in FILES.values():
            for rel, text in files.items():
                self.write(rel, text)

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def read(self, rel):
        return (self.root / rel).read_text(encoding="utf-8")

    def snapshot(self):
        return {rel: sha256_of(self.root / rel) for rel in ALL_FILES}

    def run_script(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(self.root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )

    def assert_bumped(self, rel, expected):
        text = self.read(rel)
        if rel == "VERSION":
            self.assertEqual(text, expected + "\n")
        elif rel.endswith("CHANGELOG.md"):
            entry = f"## {expected} - {today_utc()}\n\n- {LINE}\n\n"
            self.assertIn(entry, text)
            self.assertLess(text.index(entry), text.index("## 1.2.3 - 2020-01-01"))
            self.assertTrue(text.startswith("# Changelog\n\n"))
        elif rel.endswith("config.yaml"):
            self.assertIn(f'version: "{expected}"\n', text)
            self.assertNotIn('"1.2.3"', text)
        elif rel.endswith("Dockerfile"):
            self.assertIn(f'ARG BUILD_VERSION="{expected}"\n', text)
            self.assertNotIn('"1.2.3"', text)
        elif rel.endswith("__init__.py"):
            self.assertIn(f'__version__ = "{expected}"\n', text)
            self.assertNotIn('"1.2.3"', text)
        else:
            self.fail(f"no check for {rel}")

    def check_bump(self, component, level, expected):
        result = self.run_script(component, level, LINE)
        self.assertEqual(result.returncode, 0, result.stderr)
        for rel in FILES[component]:
            self.assert_bumped(rel, expected)

    # Bumps: every component, every level, every file of the component.

    def test_repo_patch(self):
        self.check_bump("repo", "patch", "1.2.4")

    def test_repo_minor(self):
        self.check_bump("repo", "minor", "1.3.0")

    def test_repo_major(self):
        self.check_bump("repo", "major", "2.0.0")

    def test_mfi_server_patch(self):
        self.check_bump("mfi-server", "patch", "1.2.4")

    def test_mfi_server_minor(self):
        self.check_bump("mfi-server", "minor", "1.3.0")

    def test_mfi_server_major(self):
        self.check_bump("mfi-server", "major", "2.0.0")

    def test_mfi_controller_patch(self):
        self.check_bump("mfi-controller", "patch", "1.2.4")

    def test_mfi_controller_minor(self):
        self.check_bump("mfi-controller", "minor", "1.3.0")

    def test_mfi_controller_major(self):
        self.check_bump("mfi-controller", "major", "2.0.0")

    def test_mfi_wifi_setup_patch(self):
        self.check_bump("mfi-wifi-setup", "patch", "1.2.4")

    def test_mfi_wifi_setup_minor(self):
        self.check_bump("mfi-wifi-setup", "minor", "1.3.0")

    def test_mfi_wifi_setup_major(self):
        self.check_bump("mfi-wifi-setup", "major", "2.0.0")

    def test_non_ascii_line_is_kept(self):
        line = "correzione: àèìòù"
        result = self.run_script("repo", "patch", line)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"- {line}\n", self.read("CHANGELOG.md"))

    # --check

    def test_check_coherent_exits_zero(self):
        result = self.run_script("--check")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_check_finds_build_arg_mismatch(self):
        self.write("mfi-server/Dockerfile", 'FROM python:3\nARG BUILD_VERSION="1.2.9"\n')
        result = self.run_script("--check")
        self.assertEqual(result.returncode, 1)
        self.assertIn("mfi-server/Dockerfile", result.stdout)

    # Refusals: nothing is written.

    def test_mismatch_writes_nothing(self):
        self.write("mfi-server/Dockerfile", 'FROM python:3\nARG BUILD_VERSION="1.2.9"\n')
        before = self.snapshot()
        result = self.run_script("mfi-server", "patch", LINE)
        self.assertEqual(result.returncode, 1)
        self.assertIn("mfi-server/Dockerfile", result.stderr)
        self.assertEqual(self.snapshot(), before)

    def test_dry_run_lists_changes_and_writes_nothing(self):
        before = self.snapshot()
        result = self.run_script("mfi-server", "minor", LINE, "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        for rel in FILES["mfi-server"]:
            self.assertIn(rel, result.stdout)
        self.assertIn("1.3.0", result.stdout)
        self.assertEqual(self.snapshot(), before)

    def test_empty_changelog_line_is_rejected(self):
        before = self.snapshot()
        for line in ("", "   "):
            result = self.run_script("repo", "patch", line)
            self.assertEqual(result.returncode, 1)
        self.assertEqual(self.snapshot(), before)

    def test_line_with_newline_is_rejected(self):
        before = self.snapshot()
        result = self.run_script("repo", "patch", "first\nsecond")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.snapshot(), before)

    def test_unknown_component_is_rejected(self):
        before = self.snapshot()
        result = self.run_script("mfi-unknown", "patch", LINE)
        self.assertEqual(result.returncode, 1)
        self.assertIn("mfi-unknown", result.stderr)
        self.assertEqual(self.snapshot(), before)

    def test_unknown_level_is_rejected(self):
        before = self.snapshot()
        result = self.run_script("repo", "huge", LINE)
        self.assertEqual(result.returncode, 1)
        self.assertIn("huge", result.stderr)
        self.assertEqual(self.snapshot(), before)

    def test_help_exits_zero(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("usage:", result.stdout)


if __name__ == "__main__":
    unittest.main()
