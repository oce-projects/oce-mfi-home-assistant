"""Offline checks of .github/workflows/windows-exe.yml.

The workflow builds the Windows .exe of mfi-wifi-setup on a Windows runner and
attaches it to each published release. The file is read as text (standard
library only, no YAML parser): the tests check the rules that matter for it.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "windows-exe.yml"
TEXT = WORKFLOW.read_text(encoding="utf-8") if WORKFLOW.is_file() else ""


def job_text(name):
    """Return the text of one job (a two-space key under `jobs:`), or ''."""
    pattern = rf"^  {name}:\n(.*?)(?=^  \w[\w-]*:\n|\Z)"
    match = re.search(pattern, TEXT, re.MULTILINE | re.DOTALL)
    return match.group(0) if match else ""


class WindowsWorkflowTest(unittest.TestCase):
    def test_workflow_file_exists(self):
        self.assertTrue(WORKFLOW.is_file(), "missing .github/workflows/windows-exe.yml")

    def test_events_are_manual_run_and_published_release(self):
        self.assertIn("workflow_dispatch:", TEXT)
        self.assertIn("release:", TEXT)
        self.assertIn("types: [published]", TEXT)

    def test_never_runs_on_pull_requests_or_pushes(self):
        self.assertIsNone(re.search(r"^\s*pull_request", TEXT, re.MULTILINE))
        self.assertIsNone(re.search(r"^\s*push\s*:", TEXT, re.MULTILINE))

    def test_default_permission_is_read_only(self):
        top = TEXT.split("\njobs:")[0]
        self.assertIn("permissions:\n  contents: read", top)

    def test_write_permission_only_in_attach_job(self):
        self.assertEqual(TEXT.count("contents: write"), 1)
        self.assertIn("contents: write", job_text("attach"))
        self.assertNotIn("contents: write", job_text("build"))

    def test_build_job_runs_on_windows_latest_with_python_313(self):
        build = job_text("build")
        self.assertIn("runs-on: windows-latest", build)
        self.assertIn("actions/checkout@v4", build)
        self.assertIn('python-version: "3.13"', build)

    def test_build_runs_the_windows_build_script(self):
        self.assertIn("mfi-wifi-setup\\build_windows.cmd", job_text("build"))

    def test_build_checks_both_files_and_uploads_them(self):
        build = job_text("build")
        self.assertIn("-Filter *.exe", build)
        self.assertIn("-Filter *.sha256", build)
        self.assertIn("throw", build)
        self.assertIn("actions/upload-artifact@v4", build)
        self.assertIn("mfi-wifi-setup/dist/*.exe", build)
        self.assertIn("mfi-wifi-setup/dist/*.sha256", build)
        self.assertIn("retention-days: 30", build)

    def test_attach_job_runs_only_on_release_after_build(self):
        attach = job_text("attach")
        self.assertIn("if: github.event_name == 'release'", attach)
        self.assertIn("needs: build", attach)
        self.assertIn("runs-on: ubuntu-latest", attach)

    def test_attach_job_uploads_exe_and_sha256_to_the_release(self):
        attach = job_text("attach")
        self.assertIn("actions/download-artifact@v4", attach)
        self.assertIn("GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}", attach)
        self.assertIn("gh release upload", attach)
        self.assertIn("dist/*.exe dist/*.sha256 --clobber", attach)


if __name__ == "__main__":
    unittest.main()
