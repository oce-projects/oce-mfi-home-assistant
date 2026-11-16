"""Tests of the password rules of set-password: auth.password_problems."""
from __future__ import annotations

import unittest

from mfi_server.auth import password_problems


class PasswordProblemsTest(unittest.TestCase):
    def test_acceptable_passwords_have_no_problems(self):
        self.assertEqual(password_problems("Abcdefgh1!xy"), [])
        self.assertEqual(password_problems("Àbcdefgh1 xy"), [])

    def test_missing_upper_case(self):
        self.assertEqual(password_problems("abcdefgh1!xy"), ["no_upper"])

    def test_missing_lower_case(self):
        self.assertEqual(password_problems("ABCDEFGH1!XY"), ["no_lower"])

    def test_missing_digit(self):
        self.assertEqual(password_problems("Abcdefghi!xy"), ["no_digit"])

    def test_missing_special_character(self):
        self.assertEqual(password_problems("Abcdefgh12xy"), ["no_special"])

    def test_too_short(self):
        self.assertEqual(password_problems("Ab1!"), ["too_short"])

    def test_empty_password_has_every_problem(self):
        self.assertEqual(
            password_problems(""),
            ["too_short", "no_upper", "no_lower", "no_digit", "no_special"],
        )


if __name__ == "__main__":
    unittest.main()
