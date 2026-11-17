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
# download link opened by the user in a new tab; the page loads nothing from it
ALLOWED_EXTERNAL_LINKS = (
    'href="https://github.com/oce-projects/oce-mfi-home-assistant/releases/latest"',
)
SCRIPT_RE = re.compile(r"<script\b.*?</script>", re.DOTALL | re.IGNORECASE)
STYLE_RE = re.compile(r"<style\b.*?</style>", re.DOTALL | re.IGNORECASE)
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
TEXT_RE = re.compile(r">([^<]*)<")
TAB_LINK_RE = re.compile(r'<a\b[^>]*\bclass="([^"]*\btab\b[^"]*)"[^>]*\bhref="([^"]*)"[^>]*>')
TAB_RE = re.compile(r'<a\b[^>]*\bclass="([^"]*\btab\b[^"]*)"[^>]*>')
TILE_RE = re.compile(r'<div\b[^>]*\bclass="([^"]*\btile\b[^"]*)"[^>]*>')
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
            for link in ALLOWED_EXTERNAL_LINKS:
                text = text.replace(link, "")
            with self.subTest(file=name):
                found = [m.group(0) for m in FORBIDDEN_ADDRESS_RE.finditer(text)]
                self.assertEqual(found, [], f"{name}: absolute or external address")

    def test_forbidden_address_still_catches_other_links(self):
        samples = (
            'href="https://example.com/x"',
            'href="/api"',
            'fetch("/api")',
            'href="https://github.com/oce-projects/oce-mfi-home-assistant/releases/latest/x.exe"',
        )
        for sample in samples:
            text = sample
            for link in ALLOWED_EXTERNAL_LINKS:
                text = text.replace(link, "")
            with self.subTest(sample=sample):
                self.assertIsNotNone(FORBIDDEN_ADDRESS_RE.search(text), sample)

    def test_wifi_setup_link_opens_in_new_tab(self):
        html = self.html["index.html"]
        url = "https://github.com/oce-projects/oce-mfi-home-assistant/releases/latest"
        tag = re.search(r'<a\b[^>]*' + re.escape(url) + r'[^>]*>', html)
        self.assertIsNotNone(tag, "no <a> with the allowed URL")
        self.assertIn('target="_blank"', tag.group(0))
        self.assertIn('rel="noopener noreferrer"', tag.group(0))

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

    def test_header_tabs_are_relative_and_share_classes(self):
        links = []
        for name, text in self.html.items():
            found = TAB_LINK_RE.findall(text)
            with self.subTest(file=name):
                self.assertEqual(len(found), 4, "each page has four tabs")
            for classes, href in found:
                links.append((name, classes.split(), href))
        for name, _c, href in links:
            with self.subTest(file=name, href=href):
                self.assertFalse(href.startswith("/") or href.startswith("http"), href)
        class_sets = {tuple(sorted(c)) for _n, c, _h in links}
        self.assertEqual(len(class_sets), 1, "tabs differ in classes")

    def test_current_tab_is_marked_on_each_page(self):
        expected = {"index.html": 'href="#overview"', "automations.html": 'href="automations.html"'}
        for name, href in expected.items():
            with self.subTest(file=name):
                marked = [m.group(0) for m in TAB_RE.finditer(self.html[name]) if 'aria-current="page"' in m.group(0)]
                self.assertEqual(len(marked), 1)
                self.assertIn(href, marked[0])

    def test_index_links_to_automations_and_back(self):
        self.assertIn("automations.html", self.html)
        self.assertIn('href="automations.html"', self.html["index.html"])
        self.assertIn('href="index.html#', self.html["automations.html"])

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

    def test_tabs_are_tab_sections(self):
        html = self.html["index.html"]
        for section_id in ("overview", "devices-tab", "discovery-tab"):
            with self.subTest(section=section_id):
                self.assertRegex(
                    html,
                    r'<section id="' + section_id + r'"[^>]*class="[^"]*\btab-section\b[^"]*"',
                )
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

    def test_app_js_maps_adopt_errors_to_keys(self):
        app = self.js["app.js"]
        self.assertIn("ADOPT_ERROR_KEYS", app)
        for key in ("adopt_error_not_factory_default", "adopt_error_auth_failed", "adopt_error_connection_failed"):
            with self.subTest(key=key):
                self.assertIn(key, app)

    def test_app_js_shows_adopt_for_unknown_is_default_mfi(self):
        app = self.js["app.js"]
        self.assertIn("function adoptable", app)
        self.assertIn("device.is_default == null", app)
        self.assertIn("MFI_MODELS.has", app)
        self.assertIn("const MFI_MODELS", app)

    def test_tabs_share_one_class_set(self):
        class_sets = []
        for name in ("index.html", "automations.html"):
            found = [tuple(sorted(c.split())) for c in TAB_RE.findall(self.html[name])]
            with self.subTest(file=name):
                self.assertGreaterEqual(len(found), 4)
                class_sets.extend(found)
        self.assertEqual(len(set(class_sets)), 1, "tabs differ in classes")

    def test_tiles_are_four_with_one_class_set(self):
        found = [tuple(sorted(c.split())) for c in TILE_RE.findall(self.html["index.html"])]
        self.assertEqual(len(found), 4)
        self.assertEqual(len(set(found)), 1, "tiles differ in classes")

    def test_app_js_switches_tabs_by_hash(self):
        app = self.js["app.js"]
        for text in ("location.hash", "hashchange", '"#overview"', "hidden"):
            with self.subTest(text=text):
                self.assertIn(text, app)

    def test_overview_tiles_are_filled_by_app_js(self):
        html = self.html["index.html"]
        app = self.js["app.js"]
        for tile_id in ("tile-power", "tile-connected", "tile-disconnected", "tile-outlets"):
            with self.subTest(tile=tile_id):
                self.assertIn('id="' + tile_id + '"', html)
        for text in ("active_pwr", "tile-power", "tile-outlets"):
            with self.subTest(text=text):
                self.assertIn(text, app)

    def test_device_cards_and_switches_have_styles(self):
        app = self.js["app.js"]
        css = read_text("style.css")
        for text in ("device-card device-card--", 'el("button", "switch"', "aria-pressed", "device-card__icon"):
            with self.subTest(text=text):
                self.assertIn(text, app)
        for sel in (".device-card", ".switch", ".device-card__icon", ".tile", ".tabs", ".tab"):
            with self.subTest(selector=sel):
                self.assertRegex(css, re.escape(sel) + r"[\s{,:]")

    def test_dark_theme_redefines_only_existing_variables(self):
        css = read_text("style.css")
        marker = "@media (prefers-color-scheme: dark)"
        light_block = re.search(r":root\s*\{([^}]*)\}", css)
        dark_block = re.search(re.escape(marker) + r"\s*\{\s*:root\s*\{([^}]*)\}", css)
        self.assertIsNotNone(light_block, "light :root block not found")
        self.assertIsNotNone(dark_block, "dark :root block not found")
        light = set(re.findall(r"(--[a-z0-9-]+)\s*:", light_block.group(1)))
        dark = set(re.findall(r"(--[a-z0-9-]+)\s*:", dark_block.group(1)))
        self.assertTrue(dark, "dark theme redefines no variable")
        self.assertTrue(dark <= light, f"dark theme adds {sorted(dark - light)}")

    def test_new_overview_keys_present_in_both_languages(self):
        keys = (
            "nav_overview", "nav_search", "tile_power", "tile_connected",
            "tile_disconnected", "tile_outlets", "tile_outlets_value",
        )
        for key in keys:
            with self.subTest(key=key):
                self.assertIn(key, self.en)
                self.assertIn(key, self.it)


if __name__ == "__main__":
    unittest.main()
