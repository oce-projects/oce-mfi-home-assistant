"""Offline checks for the option translations of the mFi Server add-on.

Run from the repository root:
    python3 -m unittest discover -s mfi-server/tests -t mfi-server -v

Standard library only; no YAML reader, no network. The translation files are
checked with line rules that follow the Home Assistant app format: one key per
option indented 2 spaces, with name and description indented 4 spaces.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ADON = Path(__file__).resolve().parent.parent
LANGUAGES = ("en", "it")


def config_keys(text: str) -> set[str]:
    keys = set()
    inside = False
    for line in text.splitlines():
        if line.startswith("options:"):
            inside = True
            continue
        if line.startswith("schema:"):
            break
        if inside:
            m = re.match(r"^  ([a-z_]+):", line)
            if m:
                keys.add(m.group(1))
    return keys


def translation_fields(text: str) -> dict[str, dict[str, str]]:
    fields: dict[str, dict[str, str]] = {}
    current = None
    inside = False
    for line in text.splitlines():
        if line.rstrip() == "configuration:":
            inside = True
            continue
        if not inside:
            continue
        m = re.match(r"^  ([a-z_]+):\s*$", line)
        if m:
            current = m.group(1)
            fields[current] = {}
            continue
        m = re.match(r"^    (name|description): (.*)$", line)
        if m and current is not None:
            fields[current][m.group(1)] = m.group(2).strip().strip('"')
    return fields


def translation_keys(text: str) -> set[str]:
    return set(translation_fields(text))


class TestTranslations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = config_keys((ADON / "config.yaml").read_text(encoding="utf-8"))
        cls.fields = {
            lang: translation_fields((ADON / "translations" / f"{lang}.yaml").read_text(encoding="utf-8"))
            for lang in LANGUAGES
        }

    def test_config_has_options(self):
        self.assertTrue(self.config, "no option keys found in config.yaml")

    def test_keys_match_config_options(self):
        for lang in LANGUAGES:
            with self.subTest(lang=lang):
                self.assertEqual(set(self.fields[lang]), self.config)

    def test_every_key_has_name_and_description(self):
        for lang in LANGUAGES:
            for key in sorted(self.config):
                entry = self.fields[lang].get(key, {})
                for field in ("name", "description"):
                    with self.subTest(lang=lang, key=key, field=field):
                        self.assertTrue(entry.get(field, "").strip(), f"{lang}.{key}.{field} is empty or missing")

    def test_italian_descriptions_differ_from_english(self):
        for key in sorted(self.config):
            with self.subTest(key=key):
                it_text = self.fields["it"].get(key, {}).get("description", "")
                en_text = self.fields["en"].get(key, {}).get("description", "")
                self.assertNotEqual(it_text, en_text)

    def test_key_check_fails_when_italian_key_is_missing(self):
        config_text = 'options:\n  a: ""\n  b: ""\nschema:\n  a: str\n  b: str\n'
        translation_text = 'configuration:\n  a:\n    name: "x"\n    description: "y"\n'
        self.assertEqual(config_keys(config_text), {"a", "b"})
        self.assertEqual(translation_keys(translation_text), {"a"})
        self.assertNotEqual(translation_keys(translation_text), config_keys(config_text))


if __name__ == "__main__":
    unittest.main()
