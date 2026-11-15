"""Tests of the password hashing, the session store and the login limiter of mfi-server."""
from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path

from mfi_server.auth import (
    LoginLimiter,
    Sessions,
    hash_password,
    load_password_hash,
    save_password_hash,
    verify_password,
)


class TestPasswordHash(unittest.TestCase):
    def test_hash_format_and_roundtrip(self):
        stored = hash_password("correct horse ab", iterations=1000)
        self.assertTrue(stored.startswith("pbkdf2_sha256$1000$"))
        self.assertEqual(len(stored.split("$")), 4)
        self.assertIs(verify_password("correct horse ab", stored), True)
        self.assertIs(verify_password("wrong", stored), False)

    def test_random_salt_is_16_bytes_and_differs(self):
        stored1 = hash_password("p", iterations=1000)
        stored2 = hash_password("p", iterations=1000)
        self.assertEqual(len(stored1.split("$")[2]), 32)
        self.assertNotEqual(stored1, stored2)

    def test_malformed_stored_is_false(self):
        for s in ("", "x", "pbkdf2_sha256$abc$aa$bb", "other$1000$aa$bb", "pbkdf2_sha256$1000$zz$zz"):
            with self.subTest(stored=s):
                self.assertIs(verify_password("p", s), False)

    def test_salt_is_used(self):
        stored1 = hash_password("p", salt=b"0123456789abcdef", iterations=1000)
        stored2 = hash_password("p", salt=b"0123456789abcdef", iterations=1000)
        self.assertEqual(stored1, stored2)
        stored3 = hash_password("p", salt=b"fedcba9876543210", iterations=1000)
        self.assertNotEqual(stored1, stored3)

    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            self.assertIsNone(load_password_hash(data_dir))
            save_password_hash(data_dir, "pbkdf2_sha256$1000$aa$bb")
            self.assertEqual(load_password_hash(data_dir), "pbkdf2_sha256$1000$aa$bb")
            self.assertFalse((data_dir / "auth.json.tmp").exists())

    def test_load_malformed_file_is_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            for content in ("not json", '["list"]', '{"other": 1}', '{"password_hash": 5}'):
                with self.subTest(content=content):
                    (data_dir / "auth.json").write_text(content, encoding="utf-8")
                    self.assertIsNone(load_password_hash(data_dir))

    def test_saved_auth_file_is_owner_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            save_password_hash(data_dir, "pbkdf2_sha256$1000$aa$bb")
            mode = stat.S_IMODE(os.stat(data_dir / "auth.json").st_mode)
            self.assertEqual(mode, 0o600)


class TestSessionsAndLimiter(unittest.TestCase):
    def test_sessions_create_valid_drop_and_expire(self):
        now = [0.0]
        s = Sessions(clock=lambda: now[0], ttl_s=100)
        t = s.create()
        self.assertIs(s.valid(t), True)
        now[0] = 101
        self.assertIs(s.valid(t), False)
        t2 = s.create()
        s.drop(t2)
        self.assertIs(s.valid(t2), False)

    def test_limiter_blocks_after_five_failures(self):
        now = [0.0]
        lim = LoginLimiter(clock=lambda: now[0])
        for _ in range(4):
            lim.failure("1.2.3.4")
        self.assertIs(lim.blocked("1.2.3.4"), False)
        lim.failure("1.2.3.4")
        self.assertIs(lim.blocked("1.2.3.4"), True)
        now[0] = 61
        self.assertIs(lim.blocked("1.2.3.4"), False)

    def test_limiter_is_per_ip(self):
        now = [0.0]
        lim = LoginLimiter(clock=lambda: now[0])
        for _ in range(5):
            lim.failure("1.2.3.4")
        self.assertIs(lim.blocked("1.2.3.4"), True)
        self.assertIs(lim.blocked("5.6.7.8"), False)


if __name__ == "__main__":
    unittest.main()
