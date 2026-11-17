#!/usr/bin/env python3
"""Bump the version of one component of this repository, or check that they agree.

Tool version: 1.0.0

Usage:
  python3 tools/bump_version.py <component> <patch|minor|major> "<changelog line>"
  python3 tools/bump_version.py --check

Options:
  --dry-run     print the planned changes, write nothing
  --root PATH   repository root (default: the folder above tools/)
  -h, --help    show the help

Components and their version files (paths from the root):
  repo            VERSION, CHANGELOG.md
  mfi-server      mfi-server/config.yaml, mfi-server/CHANGELOG.md,
                  mfi-server/Dockerfile, mfi-server/mfi_server/__init__.py
  mfi-controller  mfi-controller/config.yaml, mfi-controller/CHANGELOG.md,
                  mfi-controller/Dockerfile
  mfi-wifi-setup  mfi-wifi-setup/mfi_wifi_setup/__init__.py,
                  mfi-wifi-setup/CHANGELOG.md

A bump is all or nothing: every file of the component must show the same
current version, and all new contents are computed in memory before any file
is written. Put -- before a changelog line that starts with '-'.

Changelog of this tool:

- 1.0.0 (2026-11-17): first version. Bumps every version file of a component,
  adds a dated changelog entry, checks that the versions agree (--check), and
  supports --dry-run and --root.
"""

from __future__ import annotations

import datetime
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parent.parent

LEVELS = ("patch", "minor", "major")

USAGE = """usage: bump_version.py <component> <patch|minor|major> "<changelog line>" [--dry-run] [--root PATH]
       bump_version.py --check [--root PATH]

components: repo, mfi-server, mfi-controller, mfi-wifi-setup
options:
  --dry-run     print the planned changes and write nothing
  --check       check that the version files of every component agree
  --root PATH   repository root (default: the folder above tools/)
  -h, --help    show this help
Put -- before a changelog line that starts with '-'.
"""

# Regular expression of the version line for each kind of file.
# The group "v" holds the version. The first match is the one used.
PATTERNS = {
    "plain": r"^(?P<v>\d+\.\d+\.\d+)[ \t\r]*$",
    "config": r'^version: "(?P<v>\d+\.\d+\.\d+)"[ \t\r]*$',
    "dockerfile": r'^ARG BUILD_VERSION="(?P<v>\d+\.\d+\.\d+)"[ \t\r]*$',
    "init": r'^__version__ = "(?P<v>\d+\.\d+\.\d+)"[ \t\r]*$',
    "changelog": r"^##\s+(?P<v>\d+\.\d+\.\d+)",
}

# Component -> list of (path from the root, kind of file).
# For a changelog, the newest entry (the first "## X.Y.Z") is the current version.
COMPONENTS = {
    "repo": [
        ("VERSION", "plain"),
        ("CHANGELOG.md", "changelog"),
    ],
    "mfi-server": [
        ("mfi-server/config.yaml", "config"),
        ("mfi-server/CHANGELOG.md", "changelog"),
        ("mfi-server/Dockerfile", "dockerfile"),
        ("mfi-server/mfi_server/__init__.py", "init"),
    ],
    "mfi-controller": [
        ("mfi-controller/config.yaml", "config"),
        ("mfi-controller/CHANGELOG.md", "changelog"),
        ("mfi-controller/Dockerfile", "dockerfile"),
    ],
    "mfi-wifi-setup": [
        ("mfi-wifi-setup/mfi_wifi_setup/__init__.py", "init"),
        ("mfi-wifi-setup/CHANGELOG.md", "changelog"),
    ],
}


class ToolError(Exception):
    """A problem the user must fix: reported on stderr, exit code 1."""


def read_text(path):
    """Read a file keeping its own line endings."""
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


def find_version(text, kind):
    """Return the version found in a file of the given kind, or None."""
    match = re.search(PATTERNS[kind], text, re.MULTILINE)
    return match.group("v") if match else None


def read_component(root, component):
    """Return (path, kind, text, version) for every file of the component."""
    found = []
    for rel, kind in COMPONENTS[component]:
        path = root / rel
        if not path.is_file():
            raise ToolError(f"{rel}: file not found")
        text = read_text(path)
        version = find_version(text, kind)
        if version is None:
            raise ToolError(f"{rel}: no version line found")
        found.append((rel, kind, text, version))
    return found


def is_coherent(found):
    """True when every file of the component shows the same version."""
    return len({entry[3] for entry in found}) == 1


def describe(found):
    """One line per file with its current version."""
    return "\n".join(f"  {rel}: {version}" for rel, _, _, version in found)


def next_version(version, level):
    """Semantic version bump: patch, minor or major."""
    major, minor, patch = (int(part) for part in version.split("."))
    if level == "patch":
        return f"{major}.{minor}.{patch + 1}"
    if level == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major + 1}.0.0"


def insert_entry(text, new_version, line, today):
    """Put the new changelog entry above the first '## ' heading, or at the end."""
    entry = f"## {new_version} - {today}\n\n- {line}\n\n"
    heading = re.search(r"^## ", text, re.MULTILINE)
    if heading:
        return text[: heading.start()] + entry + text[heading.start():]
    separator = "" if not text or text.endswith("\n") else "\n"
    return text + separator + entry


def updated_text(kind, text, new_version, line, today):
    """Return the new content of one file."""
    if kind == "changelog":
        return insert_entry(text, new_version, line, today)
    match = re.search(PATTERNS[kind], text, re.MULTILINE)
    return text[: match.start("v")] + new_version + text[match.end("v"):]


def describe_change(rel, kind, old, new, today):
    """One line that says what changes in a file."""
    if kind == "changelog":
        return f"  {rel}: new entry '## {new} - {today}'"
    return f"  {rel}: {old} -> {new}"


def check_line(line):
    """The changelog line must be one non-empty line."""
    if "\n" in line or "\r" in line:
        raise ToolError("the changelog line must be a single line")
    if not line.strip():
        raise ToolError("the changelog line is empty")


def write_all(plan):
    """Write every new content: each into a temp file, then renamed over its target.

    If a rename fails, the files renamed before it are already new: the error is
    reported and the temp files that are left are removed.
    """
    temps = []
    try:
        for path, text in plan:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                newline="",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temps.append(handle.name)
                handle.write(text)
            shutil.copymode(path, handle.name)
        for (path, _), temp in zip(plan, temps):
            os.replace(temp, path)
    except OSError:
        for temp in temps:
            if os.path.exists(temp):
                os.unlink(temp)
        raise


def parse_args(argv):
    """Split the command line into options and positional arguments."""
    options = {"check": False, "dry_run": False, "root": None, "help": False}
    positional = []
    args = list(argv)
    index = 0
    while index < len(args):
        arg = args[index]
        index += 1
        if arg == "--":
            positional.extend(args[index:])
            break
        if arg in ("-h", "--help"):
            options["help"] = True
        elif arg == "--check":
            options["check"] = True
        elif arg == "--dry-run":
            options["dry_run"] = True
        elif arg == "--root":
            if index >= len(args):
                raise ToolError("--root needs a path")
            options["root"] = args[index]
            index += 1
        elif arg.startswith("--root="):
            options["root"] = arg[len("--root="):]
        elif arg.startswith("-"):
            raise ToolError(f"unknown option {arg} (put -- before a line that starts with -)")
        else:
            positional.append(arg)
    if options["root"] is not None and not options["root"].strip():
        raise ToolError("--root needs a path")
    return options, positional


def run_check(root, out):
    """Report every component whose version files disagree. Return the exit code."""
    ok = True
    for component in COMPONENTS:
        found = read_component(root, component)
        if is_coherent(found):
            out.write(f"{component}: OK, version {found[0][3]}\n")
        else:
            ok = False
            out.write(f"{component}: the files disagree:\n{describe(found)}\n")
    return 0 if ok else 1


def run_bump(root, component, level, line, dry_run, out):
    """Bump one component, or only show the plan when dry_run is set."""
    found = read_component(root, component)
    if not is_coherent(found):
        raise ToolError(
            f"{component}: the files disagree on the current version, nothing written:\n"
            f"{describe(found)}"
        )
    old = found[0][3]
    new = next_version(old, level)
    today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    plan = [
        (root / rel, updated_text(kind, text, new, line, today))
        for rel, kind, text, _ in found
    ]
    verb = "would change" if dry_run else "changed"
    out.write(f"{component}: {old} -> {new} ({level}), {verb}:\n")
    for rel, kind, _, _ in found:
        out.write(describe_change(rel, kind, old, new, today) + "\n")
    if dry_run:
        out.write("dry run: nothing written\n")
        return 0
    write_all(plan)
    return 0


def main(argv):
    """Run the tool. Return 0 on success, 1 on any error."""
    out = sys.stdout
    try:
        options, positional = parse_args(argv)
        if options["help"]:
            out.write(USAGE)
            return 0
        root = Path(options["root"]).resolve() if options["root"] else DEFAULT_ROOT
        if options["check"]:
            if positional:
                raise ToolError("--check takes no arguments")
            return run_check(root, out)
        if len(positional) != 3:
            raise ToolError('expected: <component> <patch|minor|major> "<changelog line>" (see --help)')
        component, level, line = positional
        if component not in COMPONENTS:
            raise ToolError(f"unknown component '{component}': use {', '.join(COMPONENTS)}")
        if level not in LEVELS:
            raise ToolError(f"unknown level '{level}': use patch, minor or major")
        check_line(line)
        return run_bump(root, component, level, line, options["dry_run"], out)
    except (ToolError, OSError) as exc:
        sys.stderr.write(f"bump_version: {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
