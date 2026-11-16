"""Keeps the examples of mfi-server aligned with the real settings.

Reads the files in mfi-server/examples and README.md as text: no network,
no Docker, no systemd.
"""
from __future__ import annotations

import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from mfi_server.config import FILE_KEYS, ENV_NAMES, load_settings, Settings

EX = Path(__file__).resolve().parent.parent / "examples"
README = Path(__file__).resolve().parent.parent / "README.md"

# Same expressions as tests/test_repository.py.
PRIVATE_PATTERNS = {
    "private IPv4 address": re.compile(r"(?<![\d.])(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3})(?!\d|\.\d)"),
    "UNC path to a LAN share": re.compile(r"\\\\\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\\"),
    "local Windows drive path": re.compile(r"\b[A-Z]:\\[A-Za-z_]"),
    "personal name": re.compile(r"(?i)\boscar\b"),
    "e-mail address": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z]{2,}"),
    "MAC address": re.compile(r"(?i)\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b"),
}

ALLOWED_MATCHES = {
    "192.168.1.20": "factory default IP of mFi devices, official Quick Start Guides (docs/PROTOCOL.md)",
    "172.30.32.2": "Home Assistant Supervisor ingress address, developers.home-assistant.io (mfi-server/mfi_server/api.py)",
}


def private_hits(name: str, text: str) -> list[str]:
    hits = []
    for label, rx in PRIVATE_PATTERNS.items():
        for m in rx.finditer(text):
            if m.group(0) in ALLOWED_MATCHES:
                continue
            line = text.count("\n", 0, m.start()) + 1
            hits.append(f"{name}:{line}: {label}: {m.group(0)!r}")
    return hits


class TestExamples(unittest.TestCase):
    def test_settings_example_has_file_keys_and_loads(self):
        keys = json.loads((EX / "settings.example.json").read_text(encoding="utf-8"))
        self.assertEqual(set(keys), set(FILE_KEYS))
        with tempfile.TemporaryDirectory() as d:
            shutil.copyfile(EX / "settings.example.json", Path(d) / "settings.json")
            s = load_settings(["--data", d], {}, options_path=Path(d) / "no-options.json")
            defaults = Settings(data_dir=Path(d))
        self.assertIsInstance(s, Settings)
        for key in FILE_KEYS:
            with self.subTest(key=key):
                self.assertEqual(getattr(s, key), getattr(defaults, key))
        self.assertEqual(s.inform_port, 6080)
        self.assertEqual(s.web_port, 8099)
        self.assertEqual(s.history_days, 30)
        self.assertEqual(s.mqtt_host, "")
        self.assertEqual(s.bind_address, "0.0.0.0")

    def test_env_example_empty_values_keep_defaults(self):
        environ = {name: "" for name in ENV_NAMES.values()}
        with tempfile.TemporaryDirectory() as d:
            s = load_settings(["--data", d], environ, options_path=Path(d) / "no-options.json")
            defaults = Settings(data_dir=Path(d))
        for key in FILE_KEYS:
            with self.subTest(key=key):
                self.assertEqual(getattr(s, key), getattr(defaults, key))

    def test_env_example_lists_exactly_env_names(self):
        text = (EX / "mfi-server.env.example").read_text(encoding="utf-8")
        names = re.findall(r"(?m)^([A-Z_]+)=", text)
        mfi_names = [n for n in names if n.startswith("MFI_")]
        self.assertEqual(set(mfi_names), set(ENV_NAMES.values()))
        self.assertEqual(len(mfi_names), len(ENV_NAMES), "one line per variable")
        self.assertLessEqual(set(re.findall(r"MFI_[A-Z_]+", text)), set(ENV_NAMES.values()))

    def test_compose_and_service_expose_ports_and_data(self):
        defaults = Settings(data_dir=Path("."))
        compose = (EX / "docker-compose.yml").read_text(encoding="utf-8")
        expected = (
            f'"{defaults.inform_port}:{defaults.inform_port}"',
            f'"{defaults.wakeup_port}:{defaults.wakeup_port}/udp"',
            f'"{defaults.web_port}:{defaults.web_port}"',
            "--data",
            "/data",
        )
        for fragment in expected:
            with self.subTest(file="docker-compose.yml", fragment=fragment):
                self.assertIn(fragment, compose)
        unit = (EX / "mfi-server.service").read_text(encoding="utf-8")
        for fragment in ("ExecStart", "-m mfi_server --data", "DynamicUser=yes"):
            with self.subTest(file="mfi-server.service", fragment=fragment):
                self.assertIn(fragment, unit)

    def test_readme_names_every_env_var(self):
        text = README.read_text(encoding="utf-8")
        for name in ENV_NAMES.values():
            with self.subTest(name=name):
                self.assertIn(name, text)

    def test_example_files_have_no_private_data(self):
        hits = []
        for name in ("mfi-server.service", "mfi-server.env.example", "docker-compose.yml", "settings.example.json"):
            hits += private_hits(name, (EX / name).read_text(encoding="utf-8"))
        self.assertEqual(hits, [], "\n".join(hits))


if __name__ == "__main__":
    unittest.main()
