"""Offline tests for mfi_wifi_setup.messages: key parity, placeholders and language choice."""
from __future__ import annotations

import unittest

from mfi_wifi_setup.messages import MESSAGES, choose_language, tr

ALL_KEYS = {
    "title",
    "step1_title",
    "network_name",
    "status_checking",
    "status_found",
    "not_on_network",
    "not_answering",
    "step2_button",
    "step3_title",
    "copy_button",
    "close_button",
    "page_ready",
    "how_to_stop",
}
REQUIRED_KEYS = {"not_on_network", "not_answering", "page_ready", "how_to_stop"}


class TestMessageKeys(unittest.TestCase):
    def test_italian_and_english_have_the_same_keys(self):
        self.assertEqual(set(MESSAGES["it"]), set(MESSAGES["en"]))

    def test_key_set_is_the_documented_one(self):
        self.assertEqual(set(MESSAGES["en"]), ALL_KEYS)

    def test_no_value_is_empty_or_blank(self):
        for lang in ("it", "en"):
            for key, text in MESSAGES[lang].items():
                with self.subTest(lang=lang, key=key):
                    self.assertTrue(text.strip(), f"{lang}.{key} is empty")

    def test_required_keys_present_in_both_languages(self):
        for lang in ("it", "en"):
            with self.subTest(lang=lang):
                self.assertLessEqual(REQUIRED_KEYS, set(MESSAGES[lang]))

    def test_placeholders_present_in_both_languages(self):
        for lang in ("it", "en"):
            with self.subTest(lang=lang):
                self.assertIn("{mac6}", MESSAGES[lang]["network_name"])
                self.assertIn("{model}", MESSAGES[lang]["status_found"])
                self.assertIn("{firmware}", MESSAGES[lang]["status_found"])


class TestLanguageChoice(unittest.TestCase):
    def test_italian_codes_choose_italian(self):
        self.assertEqual(choose_language("it_IT"), "it")
        self.assertEqual(choose_language("IT"), "it")

    def test_english_code_chooses_english(self):
        self.assertEqual(choose_language("en_US"), "en")

    def test_other_language_falls_back_to_english(self):
        self.assertEqual(choose_language("de_DE"), "en")

    def test_missing_or_empty_code_falls_back_to_english(self):
        self.assertEqual(choose_language(None), "en")
        self.assertEqual(choose_language(""), "en")


class TestTranslationLookup(unittest.TestCase):
    def test_unknown_language_gets_english(self):
        self.assertIs(tr("de"), MESSAGES["en"])

    def test_known_languages_get_their_own_dict(self):
        self.assertIs(tr("it"), MESSAGES["it"])
        self.assertIs(tr("en"), MESSAGES["en"])


if __name__ == "__main__":
    unittest.main()
