"""Checks of the mFi Server web page: translations, markup and script rules.

The page files are read as text: no browser, no Node, no network.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "mfi_server" / "web"

I18N_ATTR_RE = re.compile(r'data-i18n(?:-placeholder|-title)?="([a-z0-9_]+)"')
JS_KEY_RE = re.compile(r"""t\(\s*["']([a-z0-9_]+)["']""")
FORBIDDEN_ADDRESS_RE = re.compile(r"""(?:fetch\(|href=|src=)\s*["']?\s*(?:/|http)""")
SCRIPT_RE = re.compile(r"<script\b.*?</script>", re.DOTALL | re.IGNORECASE)
STYLE_RE = re.compile(r"<style\b.*?</style>", re.DOTALL | re.IGNORECASE)
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
TEXT_RE = re.compile(r">([^<]*)<")


def read_text(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


class TestWebPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = read_text("index.html")
        cls.app = read_text("app.js")
        cls.en = json.loads(read_text("i18n/en.json"))
        cls.it = json.loads(read_text("i18n/it.json"))

    def test_both_languages_have_the_same_keys(self):
        self.assertEqual(set(self.en), set(self.it))

    def test_every_used_key_exists_in_both_languages(self):
        used_index = set(I18N_ATTR_RE.findall(self.index))
        used_js = set(JS_KEY_RE.findall(self.app))
        self.assertTrue(used_index, "no data-i18n keys found in index.html")
        self.assertTrue(used_js, "no t(...) keys found in app.js")
        for key in sorted(used_index | used_js):
            with self.subTest(key=key):
                self.assertIn(key, self.en)
                self.assertIn(key, self.it)

    def test_at_least_80_percent_of_italian_values_differ_from_english(self):
        different = [key for key in self.en if self.it.get(key) != self.en[key]]
        self.assertGreaterEqual(
            len(different) * 100,
            80 * len(self.en),
            f"only {len(different)} of {len(self.en)} Italian values differ",
        )

    def test_index_has_no_visible_text_outside_i18n_elements(self):
        markup = SCRIPT_RE.sub("", self.index)
        markup = STYLE_RE.sub("", markup)
        markup = COMMENT_RE.sub("", markup)
        for text in TEXT_RE.findall(markup):
            self.assertEqual(text.strip(), "", f"visible text outside data-i18n: {text.strip()!r}")

    def test_no_absolute_or_external_addresses(self):
        for name, text in (("index.html", self.index), ("app.js", self.app)):
            with self.subTest(file=name):
                found = [match.group(0) for match in FORBIDDEN_ADDRESS_RE.finditer(text)]
                self.assertEqual(found, [], f"{name}: absolute or external address")

    def test_app_does_not_use_innerhtml(self):
        self.assertNotIn("innerHTML", self.app)

    def test_language_selector_and_storage(self):
        self.assertIn('<select id="lang"', self.index)
        self.assertIn("mfi_lang", self.app)
        self.assertIn("localStorage", self.app)
        self.assertIn("navigator.language", self.app)


if __name__ == "__main__":
    unittest.main()
