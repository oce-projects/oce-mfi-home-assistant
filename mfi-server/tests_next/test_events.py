"""Tests of mfi_server_next.events (EPIC-06 ST1): event log, list filters, dedup, retention and e-mail.

Standard library only. Uses a real sqlite3 database in a temporary folder and a fake clock.
No network: the SMTP server is a local fake.
"""
import logging
import shutil
import tempfile
import unittest

from mfi_server_next.events import EMAIL_FAILED_KEY, EventLog
from mfi_server_next.store import Store

PASSWORD = "secret-pass-123"
ADDR = ["alerts" + "@" + "mfi." + "example"]


class Clock:
    """A fake clock: the value is read by the EventLog through a lambda."""

    def __init__(self, value):
        self.value = value


class FakeSMTP:
    """Local stand-in for smtplib.SMTP: records each message it is asked to send."""

    def __init__(self, sent, login_error=None):
        self._sent = sent
        self._login_error = login_error

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def starttls(self):
        pass

    def login(self, user, password):
        if self._login_error is not None:
            raise self._login_error

    def send_message(self, msg):
        self._sent.append(msg)


def make_factory(sent, login_error=None):
    """Return an SMTP factory with the same call shape as smtplib.SMTP."""

    def factory(host, port, timeout=10):
        return FakeSMTP(sent, login_error)

    return factory


def smtp_settings(**overrides):
    settings = {
        "host": "smtp.example.com",
        "port": 587,
        "from_addr": "mfi" + "@" + "example" + ".com",
        "use_tls": True,
        "user": "sender",
        "password": PASSWORD,
    }
    settings.update(overrides)
    return settings


class EventLogTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.mkdtemp()
        self.store = Store.open(self._dir)
        self.clock = Clock(1_000_000)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self._dir, ignore_errors=True)

    def make_log(self, **kwargs):
        return EventLog(self.store, now=lambda: self.clock.value, **kwargs)

    def action_results(self):
        with self.store.transaction() as conn:
            return [row[0] for row in conn.execute("SELECT result FROM actionevent ORDER BY id").fetchall()]

    def test_ca1_list_filters_by_device_and_interval(self):
        log = self.make_log()
        self.clock.value = 1000
        log.record(key="EVT_A", msg="first on plug one", device="dev-one")
        self.clock.value = 2000
        log.record(key="EVT_B", msg="second on plug two", device="dev-two")
        self.clock.value = 3000
        log.record(key="EVT_C", msg="third on plug one", device="dev-one")
        self.clock.value = 4000
        log.record(key="EVT_D", msg="fourth without device")

        only_one = log.list_events(device="dev-one")
        self.assertEqual([row["msg"] for row in only_one], ["third on plug one", "first on plug one"])
        self.assertEqual({row["device"] for row in only_one}, {"dev-one"})

        window = log.list_events(since=1500, until=3000)
        self.assertEqual([row["msg"] for row in window], ["third on plug one", "second on plug two"])

        everything = log.list_events()
        self.assertEqual([row["ts"] for row in everything], [4000, 3000, 2000, 1000])
        self.assertEqual(set(everything[0]), {"id", "ts", "device", "key", "level", "msg"})

    def test_ca2_email_hold_blocks_second_send_until_window_passes(self):
        sent = []
        log = self.make_log(smtp_factory=make_factory(sent))
        settings = smtp_settings()
        self.clock.value = 10_000
        self.assertTrue(log.notify_email(settings, ADDR, "Power alarm", "Outlet 1 is off",
                                         key="power", hold_minutes=5))
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["Subject"], "Power alarm")

        self.clock.value = 10_060
        self.assertFalse(log.notify_email(settings, ADDR, "Power alarm", "Outlet 1 is off",
                                          key="power", hold_minutes=5))
        self.assertEqual(len(sent), 1)

        self.clock.value = 10_000 + 5 * 60 + 1
        self.assertTrue(log.notify_email(settings, ADDR, "Power alarm", "Outlet 1 is off",
                                         key="power", hold_minutes=5))
        self.assertEqual(len(sent), 2)

    def test_ca3_dedup_skips_same_event_within_window(self):
        log = self.make_log()
        self.clock.value = 20_000
        self.assertTrue(log.record(key="EVT_X", msg="same", device="dev-one", dedup_minutes=10))
        self.clock.value = 20_000 + 5 * 60
        self.assertFalse(log.record(key="EVT_X", msg="same", device="dev-one", dedup_minutes=10))
        self.assertTrue(log.record(key="EVT_X", msg="other", device="dev-one", dedup_minutes=10))
        self.clock.value = 20_000 + 10 * 60
        self.assertTrue(log.record(key="EVT_X", msg="same", device="dev-one", dedup_minutes=10))
        self.assertTrue(log.record(key="EVT_X", msg="same", device="dev-one"))
        self.assertEqual(len(log.list_events(device="dev-one")), 4)

    def test_ca4_smtp_failure_becomes_event_and_log_without_password(self):
        sent = []
        error = OSError("authentication refused for the sender account")
        log = self.make_log(smtp_factory=make_factory(sent, login_error=error))
        settings = smtp_settings()
        with self.assertLogs("mfi_server_next.events", level="ERROR") as captured:
            ok = log.notify_email(settings, ADDR, "Power alarm", "Outlet 1 is off", key="power")
        self.assertFalse(ok)
        self.assertEqual(sent, [])

        events = log.list_events()
        failed = [row for row in events if row["key"] == EMAIL_FAILED_KEY]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["level"], 2)
        self.assertTrue(failed[0]["msg"].startswith("e-mail notification failed: "))
        self.assertNotIn(PASSWORD, failed[0]["msg"])

        self.assertTrue(any(record.levelno == logging.ERROR for record in captured.records))
        self.assertNotIn(PASSWORD, "\n".join(captured.output))
        self.assertEqual(self.action_results(), ["error"])

    def test_ca5_prune_removes_only_events_older_than_limit(self):
        log = self.make_log()
        self.clock.value = 1000
        log.record(key="EVT_OLD", msg="old one")
        self.clock.value = 2000
        log.record(key="EVT_OLD", msg="old two")
        self.clock.value = 999_900
        log.record(key="EVT_NEW", msg="recent one")
        self.clock.value = 999_990
        log.record(key="EVT_NEW", msg="recent two")

        self.clock.value = 1_000_000
        removed = log.prune(max_age_seconds=500)
        self.assertEqual(removed, 2)
        self.assertEqual([row["msg"] for row in log.list_events()], ["recent two", "recent one"])

    def test_ca5_default_retention_uses_retention_days(self):
        log = self.make_log(retention_days=1)
        self.clock.value = 1000
        log.record(key="EVT_OLD", msg="old")
        self.clock.value = 1000 + 86401
        self.assertEqual(log.prune(), 1)
        self.assertEqual(log.list_events(), [])


if __name__ == "__main__":
    unittest.main()
