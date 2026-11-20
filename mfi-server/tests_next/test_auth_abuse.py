"""Abuse tests of the accounts: read_only role, expired or fake sessions, login limit (429) and trusted ingress.

Offline, standard library only. Each test works in its own temporary folder and
uses a fake clock. Passwords are fake test data.
Run from the repository root: python3 -m unittest discover -s mfi-server/tests_next -v
"""
import tempfile
import unittest
from pathlib import Path

from mfi_server_next import auth
from mfi_server_next.store import Store

PASSWORD = "Abcdefghij1!"
WRONG_PASSWORD = "sbagliata"
PEER = "1.2.3.4"
OTHER_PEER = "5.6.7.8"
LONG_PASSWORD = "A" * 9997 + "1a!"


class AuthTestCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = Store.open(Path(tmp.name))
        self.addCleanup(self.store.close)
        self.now = [0.0]

    def manager(self, **options) -> auth.AuthManager:
        return auth.AuthManager(self.store, clock=lambda: self.now[0], **options)


class TestReadOnlyRole(AuthTestCase):
    def test_read_only_user_is_refused_admin_action(self):
        mgr = self.manager()
        mgr.add_user("viewer", PASSWORD, auth.ROLE_READ_ONLY)
        token_ro = mgr.login("viewer", PASSWORD, "9.9.9.9")
        with self.assertRaises(auth.PermissionDenied) as cm:
            mgr.require_admin(token_ro)
        self.assertEqual(cm.exception.status, 403)

    def test_admin_user_passes_require_admin(self):
        mgr = self.manager()
        mgr.add_user("boss", PASSWORD, auth.ROLE_ADMIN)
        token_admin = mgr.login("boss", PASSWORD, "9.9.9.9")
        session = mgr.require_admin(token_admin)
        self.assertEqual(session["role"], auth.ROLE_ADMIN)
        self.assertEqual(session["username"], "boss")


class TestSessions(AuthTestCase):
    def test_expired_session_returns_none(self):
        mgr = self.manager(session_ttl_s=100)
        mgr.add_user("boss", PASSWORD, auth.ROLE_ADMIN)
        token = mgr.login("boss", PASSWORD, PEER)
        self.assertIsNotNone(mgr.check_session(token))
        self.now[0] = 101
        self.assertIsNone(mgr.check_session(token))

    def test_fake_token_returns_none(self):
        mgr = self.manager()
        self.assertIsNone(mgr.check_session("token-inventato"))

    def test_none_token_returns_none(self):
        mgr = self.manager()
        self.assertIsNone(mgr.check_session(None))


class TestLoginLimit(AuthTestCase):
    def test_sixth_attempt_is_blocked_with_429_even_with_right_password(self):
        mgr = self.manager()
        mgr.add_user("boss", PASSWORD, auth.ROLE_ADMIN)
        for _ in range(5):
            with self.assertRaises(auth.LoginFailed) as cm:
                mgr.login("boss", WRONG_PASSWORD, PEER)
            self.assertEqual(cm.exception.status, 401)
        with self.assertRaises(auth.TooManyAttempts) as cm:
            mgr.login("boss", PASSWORD, PEER)
        self.assertEqual(cm.exception.status, 429)

    def test_other_address_is_not_blocked(self):
        mgr = self.manager()
        mgr.add_user("boss", PASSWORD, auth.ROLE_ADMIN)
        for _ in range(5):
            with self.assertRaises(auth.LoginFailed):
                mgr.login("boss", WRONG_PASSWORD, PEER)
        token = mgr.login("boss", PASSWORD, OTHER_PEER)
        self.assertIsNotNone(mgr.check_session(token))

    def test_very_long_password_is_refused_without_crash(self):
        mgr = self.manager()
        mgr.add_user("boss", PASSWORD, auth.ROLE_ADMIN)
        with self.assertRaises(auth.LoginFailed) as cm:
            mgr.login("boss", LONG_PASSWORD, "7.7.7.7")
        self.assertEqual(cm.exception.status, 401)


class TestTrustedIngress(unittest.TestCase):
    def test_only_the_ingress_peer_is_trusted(self):
        self.assertIs(auth.trusted_ingress("172.30.32.2"), True)

    def test_other_addresses_are_not_trusted(self):
        for peer in ("203.0.113.3", "127.0.0.1", "", None):
            with self.subTest(peer=peer):
                self.assertIs(auth.trusted_ingress(peer), False)


if __name__ == "__main__":
    unittest.main()
