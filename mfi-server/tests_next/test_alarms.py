"""Tests of mfi_server_next.alarms (EPIC-08 ST1): definitions, raise, lifecycle, archive, system alerts and events.

Standard library only. Uses a real sqlite3 database in a temporary folder and a fake clock.
No network and no device.
"""
import shutil
import tempfile
import unittest

from mfi_server_next.alarms import (
    ALARM_FIELDS,
    ALARM_TABLE,
    ALARMDEF_TABLE,
    STARTUP_DEFS,
    SYSTEM_ALERT_KEY,
    AlarmStore,
)
from mfi_server_next.events import EventLog
from mfi_server_next.store import Store

DEVICE = "aabbccddeeff"
OTHER_DEVICE = "ffeeddccbbaa"
LOST = "EVT_AP_Lost_Contact"


class Clock:
    """A fake clock: the value is read by the AlarmStore and the EventLog through a lambda."""

    def __init__(self, value):
        self.value = value


class AlarmStoreTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.mkdtemp()
        self.store = Store.open(self._dir)
        self.clock = Clock(1_000_000)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self._dir, ignore_errors=True)

    def make_events(self):
        return EventLog(self.store, now=lambda: self.clock.value)

    def make_alarms(self, event_log=None):
        return AlarmStore(self.store, event_log, now=lambda: self.clock.value)

    def count(self, table):
        with self.store.transaction() as conn:
            return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def definition(self, key):
        with self.store.transaction() as conn:
            return conn.execute(
                f"SELECT repeat, auto_close, level, system FROM {ALARMDEF_TABLE} WHERE key = ?", (key,)
            ).fetchone()

    def test_ca1_definitions_are_created_once(self):
        alarms = self.make_alarms()
        self.assertEqual(len(STARTUP_DEFS), 6)
        self.assertEqual(self.count(ALARMDEF_TABLE), 6)
        self.assertEqual(self.definition(LOST), (1, 1, 1, 0))

        self.make_alarms()
        self.assertEqual(self.count(ALARMDEF_TABLE), 6)
        self.assertEqual(alarms.ensure_definitions(), 0)
        self.assertEqual(self.count(ALARMDEF_TABLE), 6)

    def test_ca2_same_cause_raises_one_alarm(self):
        alarms = self.make_alarms()
        for offset in (0, 60, 120):
            self.clock.value = 1_000_000 + offset
            alarm_id = alarms.raise_alarm(LOST, device=DEVICE)
        rows = alarms.list_alarms()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["occurs"], 3)
        self.assertEqual(rows[0]["id"], alarm_id)
        self.assertEqual(rows[0]["ts"], 1_000_120)

    def test_ca2_other_device_is_another_cause(self):
        alarms = self.make_alarms()
        first = alarms.raise_alarm(LOST, device=DEVICE)
        second = alarms.raise_alarm(LOST, device=OTHER_DEVICE)
        self.assertNotEqual(first, second)
        self.assertEqual(len(alarms.list_alarms()), 2)
        self.assertEqual([row["id"] for row in alarms.list_alarms(device=DEVICE)], [first])

    def test_ca2_raise_after_clear_opens_a_new_alarm(self):
        alarms = self.make_alarms()
        first = alarms.raise_alarm(LOST, device=DEVICE)
        self.assertTrue(alarms.clear(LOST, device=DEVICE))
        second = alarms.raise_alarm(LOST, device=DEVICE)
        self.assertNotEqual(first, second)
        self.assertEqual(len(alarms.list_alarms()), 2)
        self.assertEqual([row["id"] for row in alarms.list_alarms(active=1)], [second])

    def test_archived_alarm_is_not_reused_for_same_cause(self):
        alarms = self.make_alarms()
        first = alarms.raise_alarm(LOST, device=DEVICE)
        self.assertTrue(alarms.archive(first))
        second = alarms.raise_alarm(LOST, device=DEVICE)
        self.assertNotEqual(first, second)
        self.assertEqual(len(alarms.list_alarms()), 2)

    def test_clear_keeps_alarm_open_when_definition_has_no_auto_close(self):
        alarms = self.make_alarms()
        alarm_id = alarms.raise_alarm("EVT_AD_UpdateAvailable")
        self.assertFalse(alarms.clear("EVT_AD_UpdateAvailable"))
        self.assertEqual([row["id"] for row in alarms.list_alarms(active=1)], [alarm_id])

    def test_clear_without_open_alarm_returns_false(self):
        alarms = self.make_alarms()
        self.assertFalse(alarms.clear(LOST, device=DEVICE))

    def test_ca3_acknowledge_and_archive_change_state_and_filter(self):
        alarms = self.make_alarms()
        self.clock.value = 1_000_500
        alarm_id = alarms.raise_alarm(LOST, device=DEVICE)
        self.assertTrue(alarms.acknowledge(alarm_id, by="admin"))
        row = alarms.list_alarms()[0]
        self.assertEqual(row["handled_by"], "admin")
        self.assertEqual(row["handled_ts"], 1_000_500)
        self.assertEqual(row["archived"], 0)

        self.assertTrue(alarms.archive(alarm_id))
        self.assertEqual(alarms.list_alarms()[0]["archived"], 1)
        self.assertEqual(alarms.list_alarms(archived=0), [])
        self.assertEqual([row["id"] for row in alarms.list_alarms(archived=1)], [alarm_id])

    def test_ca3_unknown_id_changes_nothing(self):
        alarms = self.make_alarms()
        self.assertFalse(alarms.acknowledge(999, by="admin"))
        self.assertFalse(alarms.archive(999))
        self.assertEqual(alarms.list_alarms(), [])

    def test_list_filters_by_active_and_device(self):
        alarms = self.make_alarms()
        mine = alarms.raise_alarm(LOST, device=DEVICE)
        other = alarms.raise_alarm(LOST, device=OTHER_DEVICE)
        self.assertTrue(alarms.clear(LOST, device=OTHER_DEVICE))
        self.assertEqual([row["id"] for row in alarms.list_alarms(active=0)], [other])
        self.assertEqual([row["id"] for row in alarms.list_alarms(active=1)], [mine])
        self.assertEqual([row["id"] for row in alarms.list_alarms(device=DEVICE)], [mine])

    def test_ca4_create_system_alert_makes_system_alarm(self):
        alarms = self.make_alarms()
        alarm_id = alarms.create_system_alert("tank overflow")
        rows = alarms.list_alarms()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], alarm_id)
        self.assertEqual(rows[0]["key"], SYSTEM_ALERT_KEY)
        self.assertIsNone(rows[0]["device"])
        self.assertEqual(rows[0]["msg"], "tank overflow")
        self.assertEqual(rows[0]["level"], 2)
        self.assertEqual(set(rows[0]), set(ALARM_FIELDS))
        self.assertEqual(self.definition(SYSTEM_ALERT_KEY), (0, 0, 0, 1))
        self.assertEqual(self.count(ALARMDEF_TABLE), 7)

    def test_ca4_second_system_alert_for_open_cause_is_one_row(self):
        alarms = self.make_alarms()
        first = alarms.create_system_alert("tank overflow")
        second = alarms.create_system_alert("tank overflow")
        self.assertEqual(first, second)
        self.assertEqual(len(alarms.list_alarms()), 1)
        self.assertEqual(alarms.list_alarms()[0]["occurs"], 2)
        self.assertEqual(self.count(ALARMDEF_TABLE), 7)

    def test_ca5_raise_writes_one_event(self):
        events = self.make_events()
        alarms = self.make_alarms(events)
        alarms.raise_alarm(LOST, device=DEVICE)
        rows = events.list_events()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["key"], LOST)
        self.assertEqual(rows[0]["device"], DEVICE)
        self.assertEqual(rows[0]["level"], 1)
        self.assertEqual(rows[0]["msg"], LOST)

    def test_ca5_same_cause_writes_only_one_event(self):
        events = self.make_events()
        alarms = self.make_alarms(events)
        for _ in range(3):
            alarms.raise_alarm(LOST, device=DEVICE)
        self.assertEqual(len(events.list_events()), 1)
        self.assertEqual(alarms.list_alarms()[0]["occurs"], 3)

    def test_ca5_event_uses_given_message_and_level(self):
        events = self.make_events()
        alarms = self.make_alarms(events)
        alarms.raise_alarm("EVT_Custom_Check", device=DEVICE, msg="custom text", level=5)
        row = events.list_events()[0]
        self.assertEqual(row["msg"], "custom text")
        self.assertEqual(row["level"], 5)

    def test_raise_without_event_log_still_stores_alarm(self):
        alarms = self.make_alarms()
        alarm_id = alarms.raise_alarm(LOST, device=DEVICE)
        self.assertEqual([row["id"] for row in alarms.list_alarms()], [alarm_id])
        self.assertEqual(self.count(ALARM_TABLE), 1)


if __name__ == "__main__":
    unittest.main()
