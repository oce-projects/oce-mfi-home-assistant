"""Checks of the mFi Server web pages: translations, markup and script rules.

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
NAV_LINK_RE = re.compile(r'<a\b[^>]*\bclass="([^"]*\btopbar__nav-link\b[^"]*)"[^>]*\bhref="([^"]*)"[^>]*>')
AUTOMATION_ROUTES = (
    "api/v1/automations/validate",
    "api/v1/automations/import",
    "/enable",
    "/trigger",
    "/traces",
)


def read_text(name):
    return (WEB / name).read_text(encoding="utf-8")


class TestWebPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = {p.name: p.read_text(encoding="utf-8") for p in sorted(WEB.glob("*.html"))}
        cls.js = {p.name: p.read_text(encoding="utf-8") for p in sorted(WEB.glob("*.js"))}
        cls.en = json.loads(read_text("i18n/en.json"))
        cls.it = json.loads(read_text("i18n/it.json"))

    def test_both_languages_have_the_same_keys(self):
        self.assertEqual(set(self.en), set(self.it))

    def test_every_used_key_exists_in_both_languages(self):
        used = set()
        for text in self.html.values():
            used |= set(I18N_ATTR_RE.findall(text))
        for text in self.js.values():
            used |= set(JS_KEY_RE.findall(text))
        self.assertTrue(used, "no i18n keys found")
        for key in sorted(used):
            with self.subTest(key=key):
                self.assertIn(key, self.en)
                self.assertIn(key, self.it)

    def test_at_least_80_percent_of_italian_values_differ_from_english(self):
        different = [key for key in self.en if self.it.get(key) != self.en[key]]
        self.assertGreaterEqual(len(different) * 100, 80 * len(self.en))

    def test_pages_have_no_visible_text_outside_i18n_elements(self):
        for name, text in self.html.items():
            markup = SCRIPT_RE.sub("", text)
            markup = STYLE_RE.sub("", markup)
            markup = COMMENT_RE.sub("", markup)
            for chunk in TEXT_RE.findall(markup):
                with self.subTest(file=name, text=chunk.strip()):
                    self.assertEqual(chunk.strip(), "", f"{name}: visible text {chunk.strip()!r}")

    def test_no_absolute_or_external_addresses(self):
        for name, text in {**self.html, **self.js}.items():
            with self.subTest(file=name):
                found = [m.group(0) for m in FORBIDDEN_ADDRESS_RE.finditer(text)]
                self.assertEqual(found, [], f"{name}: absolute or external address")

    def test_scripts_do_not_use_innerhtml(self):
        for name, text in self.js.items():
            with self.subTest(file=name):
                self.assertNotIn("innerHTML", text)

    def test_language_selector_and_storage(self):
        self.assertIn('<select id="lang"', self.html["index.html"])
        combined = "".join(self.js.values())
        self.assertIn("mfi_lang", combined)
        self.assertIn("localStorage", combined)
        self.assertIn("navigator.language", combined)

    def test_header_nav_links_are_relative_and_share_classes(self):
        links = []
        for name, text in self.html.items():
            for classes, href in NAV_LINK_RE.findall(text):
                links.append((name, classes.split(), href))
        self.assertTrue(links, "no header nav link found")
        for name, _c, href in links:
            with self.subTest(file=name, href=href):
                self.assertFalse(href.startswith("/") or href.startswith("http"), href)
        class_sets = {tuple(sorted(c)) for _n, c, _h in links}
        self.assertEqual(len(class_sets), 1, "header nav links differ in classes")

    def test_index_links_to_automations_and_back(self):
        self.assertIn("automations.html", self.html)
        self.assertIn('href="automations.html"', self.html["index.html"])
        self.assertIn('href="index.html"', self.html["automations.html"])

    def test_automations_js_uses_relative_automation_routes(self):
        self.assertIn("automations.js", self.js)
        text = self.js["automations.js"]
        for route in AUTOMATION_ROUTES:
            with self.subTest(route=route):
                self.assertIn(route, text)

    def test_app_js_uses_adopt_and_repoint_routes(self):
        text = self.js["app.js"]
        self.assertIn("/adopt", text)
        self.assertIn("/repoint", text)
        self.assertIn('"button"', text)
        self.assertIn("window.confirm", text)

    def test_buttons_have_class_or_known_id(self):
        css = read_text("style.css")
        html = self.html["index.html"]
        known_ids = {"login-button", "logout-button", "chart-close"}
        for tag in re.findall(r"<button\b[^>]*>", html):
            cls = re.search(r'class="([^"]*)"', tag)
            if cls and "button" in cls.group(1):
                continue
            bid = re.search(r'id="([^"]*)"', tag)
            self.assertIsNotNone(bid, tag)
            self.assertIn(bid.group(1), known_ids, tag)
            self.assertIn("#" + bid.group(1), css, tag)

    def test_discovery_search_is_primary(self):
        self.assertRegex(
            self.html["index.html"],
            r'<button id="discovery-search"[^>]*class="button button--primary"',
        )

    def test_devices_and_discovery_in_panels(self):
        html = self.html["index.html"]
        self.assertEqual(html.count('<section class="panel">'), 2)
        self.assertIn('<div class="section__head">', html)

    def test_style_has_table_and_tag_rules(self):
        css = read_text("style.css")
        for selector in (
            ".table-wrap", ".table", ".table th", ".table td",
            ".section__head", ".mono", ".tag", ".tag--default",
            ".tag--known", ".tag--other", ".other",
        ):
            with self.subTest(selector=selector):
                self.assertRegex(css, re.escape(selector) + r"[\s{,:]")

    def test_app_js_discovery_filters_mfi(self):
        app = self.js["app.js"]
        self.assertNotIn("device.is_default || !device.known", app)
        self.assertIn("MFI_MODELS", app)
        self.assertIn("repointDevice(", app)
        self.assertIn("formatMac", app)

    def test_app_js_groups_other_devices(self):
        app = self.js["app.js"]
        self.assertIn('el("details", "other")', app)
        self.assertIn("discovery_other_heading", app)

    def test_new_discovery_keys_present_and_old_removed(self):
        for key in (
            "discovery_col_name", "discovery_col_state", "discovery_state_default",
            "discovery_state_known", "discovery_state_other", "discovery_other_heading",
            "discovery_no_mfi", "backup_error", "backup_empty", "backup_missing",
        ):
            with self.subTest(key=key):
                self.assertIn(key, self.en)
                self.assertIn(key, self.it)
        for key in ("discovery_col_default", "discovery_col_known"):
            with self.subTest(key=key):
                self.assertNotIn(key, self.en)
                self.assertNotIn(key, self.it)

    def test_firmware_keys_present_in_both_languages(self):
        for key in (
            "firmware_label", "firmware_line", "firmware_unknown", "firmware_unreadable",
            "firmware_updated", "firmware_not_confirmed", "firmware_archive_unavailable",
            "upgrade", "upgrade_confirm", "upgrade_queued", "upgrade_in_progress_note",
            "upgrade_error_archive_unavailable", "upgrade_error_no_bundle",
            "upgrade_error_not_connected", "upgrade_error_unreadable_version",
            "upgrade_error_not_older", "upgrade_error_upgrade_in_progress",
        ):
            with self.subTest(key=key):
                self.assertIn(key, self.en)
                self.assertIn(key, self.it)

    def test_app_js_has_upgrade_flow(self):
        app = self.js["app.js"]
        for text in ('"/upgrade"', "upgradeDevice", "firmware_unreadable", "window.confirm"):
            with self.subTest(text=text):
                self.assertIn(text, app)

    def test_app_js_asks_confirmation_before_upgrade_request(self):
        app = self.js["app.js"]
        gate = re.compile(
            r'if\s*\(\s*!\s*window\.confirm\(\s*t\(\s*["\']upgrade_confirm["\']\s*\)\s*\)\s*\)\s*return'
        )
        self.assertRegex(app, gate, "the upgrade confirm result must gate an early return")
        self.assertLess(gate.search(app).start(), app.index('"/upgrade"'))


if __name__ == "__main__":
    unittest.main()
