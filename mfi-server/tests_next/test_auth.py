"""Tests for mfi_server_next.auth: password rules, users.json and the legacy admin migration.

Each test works in its own temporary folder. Standard library only.
"""
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from mfi_server_next import auth, crypto
from mfi_server_next.store import Store

FAKE_PASSWORD = "Abcdefghij1!"
FAKE_VIEWER_PASSWORD = "Zyxwvutsrq9?"
FAKE_LEGACY_PASSWORD = "OldPassw0rd!x"


class AuthTestCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.store = Store.open(self.folder)
        self.addCleanup(self.store.close)
        self.users_path = self.folder / auth.USERS_FILE

    def read_users_file(self) -> dict:
        with open(self.users_path, encoding="utf-8") as handle:
            return json.load(handle)


class TestPasswordRules(AuthTestCase):
    def test_acceptable_password_is_accepted(self):
        self.assertEqual(auth.password_problems(FAKE_PASSWORD), [])
        manager = auth.AuthManager(self.store)
        manager.add_user("admin", FAKE_PASSWORD, auth.ROLE_ADMIN)
        self.assertEqual(manager.role("admin"), auth.ROLE_ADMIN)
        self.assertIs(manager.verify("admin", FAKE_PASSWORD), True)

    def test_password_without_uppercase_is_rejected(self):
        self.assertEqual(auth.password_problems("abcdefghij1!"), ["no_upper"])
        manager = auth.AuthManager(self.store)
        with self.assertRaises(ValueError):
            manager.add_user("admin", "abcdefghij1!", auth.ROLE_ADMIN)
        self.assertIsNone(manager.role("admin"))
        self.assertFalse(self.users_path.exists())

    def test_short_password_is_rejected(self):
        self.assertEqual(auth.password_problems("Abc1!"), ["too_short"])
        manager = auth.AuthManager(self.store)
        with self.assertRaises(ValueError):
            manager.add_user("admin", "Abc1!", auth.ROLE_ADMIN)
        self.assertIsNone(manager.role("admin"))
        self.assertFalse(self.users_path.exists())

    def test_empty_password_breaks_every_rule_in_order(self):
        self.assertEqual(
            auth.password_problems(""),
            ["too_short", "no_upper", "no_lower", "no_digit", "no_special"],
        )

    def test_unknown_role_is_rejected(self):
        manager = auth.AuthManager(self.store)
        with self.assertRaises(ValueError):
            manager.add_user("admin", FAKE_PASSWORD, "superuser")
        self.assertFalse(self.users_path.exists())


class TestUsersFile(AuthTestCase):
    def setUp(self) -> None:
        super().setUp()
        manager = auth.AuthManager(self.store)
        manager.add_user("admin", FAKE_PASSWORD, auth.ROLE_ADMIN)
        manager.add_user("viewer", FAKE_VIEWER_PASSWORD, auth.ROLE_READ_ONLY)

    def test_users_file_holds_only_pbkdf2_hashes_with_salt(self):
        users = self.read_users_file()["users"]
        self.assertEqual(sorted(users), ["admin", "viewer"])
        self.assertEqual(users["viewer"]["role"], auth.ROLE_READ_ONLY)
        for username, entry in users.items():
            with self.subTest(user=username):
                stored = entry["password_hash"]
                self.assertTrue(stored.startswith("pbkdf2_sha256$"))
                fields = stored.split("$")
                self.assertEqual(len(fields), 4)
                self.assertEqual(fields[1], str(crypto.DEFAULT_ITERATIONS))
                self.assertEqual(len(fields[2]), 32)

    def test_plain_passwords_are_not_in_the_file(self):
        text = self.users_path.read_text(encoding="utf-8")
        self.assertNotIn(FAKE_PASSWORD, text)
        self.assertNotIn(FAKE_VIEWER_PASSWORD, text)

    def test_stored_hashes_verify_only_their_own_password(self):
        users = self.read_users_file()["users"]
        self.assertIs(crypto.pbkdf2_verify(FAKE_PASSWORD, users["admin"]["password_hash"]), True)
        self.assertIs(crypto.pbkdf2_verify(FAKE_PASSWORD, users["viewer"]["password_hash"]), False)
        self.assertIs(crypto.pbkdf2_verify(FAKE_VIEWER_PASSWORD, users["viewer"]["password_hash"]), True)

    def test_users_file_is_owner_only(self):
        self.assertEqual(stat.S_IMODE(os.stat(self.users_path).st_mode), 0o600)

    def test_users_survive_a_restart(self):
        reloaded = auth.AuthManager(self.store)
        self.assertIs(reloaded.verify("admin", FAKE_PASSWORD), True)
        self.assertEqual(reloaded.role("viewer"), auth.ROLE_READ_ONLY)


class TestLegacyMigration(AuthTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.legacy_hash = crypto.pbkdf2_hash(FAKE_LEGACY_PASSWORD, iterations=1000)
        self.store.write_json(auth.LEGACY_AUTH_FILE, {"password_hash": self.legacy_hash}, private=True)

    def test_legacy_hash_becomes_admin_unchanged(self):
        manager = auth.AuthManager(self.store)
        self.assertIs(manager.migrate_from_legacy(), True)
        users = self.read_users_file()["users"]
        self.assertEqual(users, {"admin": {"password_hash": self.legacy_hash, "role": auth.ROLE_ADMIN}})
        self.assertEqual(manager.role("admin"), auth.ROLE_ADMIN)

    def test_migrated_admin_verifies_the_old_password(self):
        self.assertIs(auth.AuthManager(self.store).migrate_from_legacy(), True)
        reloaded = auth.AuthManager(self.store)
        self.assertIs(reloaded.verify("admin", FAKE_LEGACY_PASSWORD), True)
        self.assertIs(reloaded.verify("admin", "wrong-password"), False)

    def test_second_migration_returns_false_and_keeps_file(self):
        manager = auth.AuthManager(self.store)
        self.assertIs(manager.migrate_from_legacy(), True)
        before = self.read_users_file()
        self.assertIs(manager.migrate_from_legacy(), False)
        self.assertIs(auth.AuthManager(self.store).migrate_from_legacy(), False)
        self.assertEqual(self.read_users_file(), before)

    def test_existing_users_block_the_migration(self):
        auth.AuthManager(self.store).add_user("viewer", FAKE_VIEWER_PASSWORD, auth.ROLE_READ_ONLY)
        manager = auth.AuthManager(self.store)
        self.assertIs(manager.migrate_from_legacy(), False)
        self.assertEqual(sorted(self.read_users_file()["users"]), ["viewer"])
        self.assertIsNone(manager.role("admin"))


class TestMigrationWithoutLegacyHash(AuthTestCase):
    def test_no_legacy_file_returns_false(self):
        manager = auth.AuthManager(self.store)
        self.assertIs(manager.migrate_from_legacy(), False)
        self.assertFalse(self.users_path.exists())

    def test_legacy_file_without_string_hash_returns_false(self):
        self.store.write_json(auth.LEGACY_AUTH_FILE, {"password_hash": 12345}, private=True)
        manager = auth.AuthManager(self.store)
        self.assertIs(manager.migrate_from_legacy(), False)
        self.assertFalse(self.users_path.exists())


if __name__ == "__main__":
    unittest.main()
