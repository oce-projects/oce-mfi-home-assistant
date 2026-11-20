"""Offline checks of the new web page: translations, markup, script rules, dark theme, views and the static route.

The page files are read as text, with no browser and no network. The static route runs on 127.0.0.1 only.
Run from the repository root: python3 -m unittest discover -s mfi-server/tests_next -v
"""
import http.client
import http.server
import json
import re
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

from mfi_server_next import page_api

WEB = Path(__file__).resolve().parent.parent / "mfi_server_next" / "web"
I18N_ATTR_RE = re.compile(r'data-i18n(?:-placeholder)?="([a-z0-9_]+)"')
JS_KEY_RE = re.compile(r"""(?<![\w.])t\(\s*["']([a-z0-9_]+)["']""")
SCRIPT_RE = re.compile(r"<script\b.*?</script>", re.DOTALL | re.IGNORECASE)
STYLE_RE = re.compile(r"<style\b.*?</style>", re.DOTALL | re.IGNORECASE)
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
TEXT_RE = re.compile(r">([^<]*)<")
VIEW_IDS = (
    "view-devices", "view-ports", "view-measures", "view-rules",
    "view-events", "view-users", "view-maps", "view-system",
)


class TestTranslations(unittest.TestCase):
    """CA1: the two language files have the same keys, and every key used by the page exists in both."""

    @classmethod
    def setUpClass(cls):
        cls.en = json.loads((WEB / "i18n/en.json").read_text(encoding="utf-8"))
        cls.it = json.loads((WEB / "i18n/it.json").read_text(encoding="utf-8"))
        cls.index = (WEB / "index.html").read_text(encoding="utf-8")
        cls.app = (WEB / "app.js").read_text(encoding="utf-8")

    def test_both_languages_have_the_same_keys(self):
        self.assertEqual(set(self.en), set(self.it))

    def test_at_least_80_percent_of_italian_values_differ_from_english(self):
        different = [key for key in self.en if self.it.get(key) != self.en[key]]
        self.assertGreaterEqual(len(different) * 100, 80 * len(self.en))

    def test_every_used_key_exists_in_both_languages(self):
        used = set(I18N_ATTR_RE.findall(self.index)) | set(JS_KEY_RE.findall(self.app))
        self.assertTrue(used, "no i18n keys found")
        for key in sorted(used):
            with self.subTest(key=key):
                self.assertIn(key, self.en)
                self.assertIn(key, self.it)


class TestMarkup(unittest.TestCase):
    """CA2: index.html has no visible text written by hand; all text comes from translation attributes."""

    def test_index_has_no_visible_text_outside_translation_attributes(self):
        markup = SCRIPT_RE.sub("", (WEB / "index.html").read_text(encoding="utf-8"))
        markup = STYLE_RE.sub("", markup)
        markup = COMMENT_RE.sub("", markup)
        for chunk in TEXT_RE.findall(markup):
            with self.subTest(text=chunk.strip()):
                self.assertEqual(chunk.strip(), "", f"visible text written by hand: {chunk.strip()!r}")


class TestScript(unittest.TestCase):
    """CA3: app.js uses no external resource, no innerHTML, and stores the language under its own key."""

    @classmethod
    def setUpClass(cls):
        cls.app = (WEB / "app.js").read_text(encoding="utf-8")

    def test_no_innerhtml(self):
        self.assertNotIn("innerHTML", self.app)

    def test_no_http_address(self):
        self.assertNotIn("http://", self.app)

    def test_no_https_address(self):
        self.assertNotIn("https://", self.app)

    def test_language_is_stored_and_detected(self):
        self.assertIn("localStorage", self.app)
        self.assertIn("navigator.language", self.app)
        self.assertIn("mfi_next_lang", self.app)


class TestTheme(unittest.TestCase):
    """CA4: style.css has a dark variant that only redefines variables already declared for light."""

    def test_dark_theme_redefines_only_existing_variables(self):
        css = (WEB / "style.css").read_text(encoding="utf-8")
        light = re.search(r":root\s*\{([^}]*)\}", css)
        dark = re.search(re.escape("@media (prefers-color-scheme: dark)") + r"\s*\{\s*:root\s*\{([^}]*)\}", css)
        self.assertIsNotNone(light, "light :root block not found")
        self.assertIsNotNone(dark, "dark :root block not found")
        light_vars = set(re.findall(r"(--[a-z0-9-]+)\s*:", light.group(1)))
        dark_vars = set(re.findall(r"(--[a-z0-9-]+)\s*:", dark.group(1)))
        self.assertTrue(dark_vars, "dark theme redefines no variable")
        self.assertTrue(dark_vars <= light_vars, f"dark theme adds {sorted(dark_vars - light_vars)}")


class TestViews(unittest.TestCase):
    """CA6: every view section is present in index.html."""

    def test_all_view_sections_exist(self):
        html = (WEB / "index.html").read_text(encoding="utf-8")
        for vid in VIEW_IDS:
            with self.subTest(view=vid):
                self.assertIn('id="' + vid + '"', html)


class TestStaticRoute(unittest.TestCase):
    """CA5: the static route serves only the fixed web files and refuses '..' and unknown names."""

    def setUp(self):
        context = SimpleNamespace(settings={"mode": "standalone"}, web_dir=str(WEB))
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), page_api.make_handler(context))
        self.addCleanup(self.server.server_close)
        self.port = self.server.server_address[1]
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(self.server.shutdown)

    def get(self, path):
        """Send one GET to the local server; return (status, body bytes)."""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request("GET", path)
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()

    def test_root_serves_index_html(self):
        status, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertEqual(body, (WEB / "index.html").read_bytes())

    def test_index_html_path_serves_the_same_file(self):
        status, body = self.get("/index.html")
        self.assertEqual(status, 200)
        self.assertEqual(body, (WEB / "index.html").read_bytes())

    def test_style_css_is_served(self):
        status, body = self.get("/style.css")
        self.assertEqual(status, 200)
        self.assertEqual(body, (WEB / "style.css").read_bytes())

    def test_app_js_is_served(self):
        status, _ = self.get("/app.js")
        self.assertEqual(status, 200)

    def test_translation_files_are_served(self):
        status, body = self.get("/i18n/en.json")
        self.assertEqual(status, 200)
        self.assertEqual(body, (WEB / "i18n/en.json").read_bytes())
        status, _ = self.get("/i18n/it.json")
        self.assertEqual(status, 200)

    def test_unknown_file_is_404(self):
        status, _ = self.get("/nope.css")
        self.assertEqual(status, 404)

    def test_parent_directory_is_404(self):
        status, _ = self.get("/i18n/../secret")
        self.assertEqual(status, 404)


class TestRulesView(unittest.TestCase):
    """The rules row must contain the name, state and copy button cells, not an empty row."""

    def test_rule_row_is_not_an_empty_tr(self):
        app = (WEB / "app.js").read_text(encoding="utf-8")
        match = re.search(r"function renderRuleRow\(rule\)\s*\{(.*?)\n\}", app, re.DOTALL)
        self.assertIsNotNone(match, "renderRuleRow not found")
        body = match.group(1)
        self.assertNotRegex(body, r'return\s+el\("tr"\)\s*;', "renderRuleRow returns an empty row")
        self.assertIn("nameCell", body)
        self.assertIn("stateCell", body)
        self.assertIn("actionCell", body)
        self.assertRegex(body, r"\.append\([^)]*nameCell[^)]*stateCell[^)]*actionCell")


if __name__ == "__main__":
    unittest.main()
