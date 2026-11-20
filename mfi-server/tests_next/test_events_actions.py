"""Tests of the notify.email and mfi.event actions of the rules engine (EPIC-06).

The engine gets fake callbacks that record what they receive: no e-mail is sent,
no socket is opened and no EventLog is used. Recipient addresses are built by
concatenation, so this file holds no e-mail address written out in full.
Run from the repository root: python3 -m unittest discover -s mfi-server/tests_next -v
"""
import unittest

from mfi_server_next.rules import AutomationEngine, validate

NOW = 1000.0
ADDR = "alerts" + "@" + "mfi." + "example"
ADDR_2 = "owner" + "@" + "mfi." + "example"
MAX_MINUTES = 10 ** 9


class FakeSinks:
    """Fakes of the two callbacks: each one keeps every data dict it was given."""

    def __init__(self):
        self.mails = []
        self.events = []

    def notify_email(self, data):
        self.mails.append(data)

    def record_event(self, data):
        self.events.append(data)


def make_engine(**callbacks):
    """Return an engine with no devices; callbacks are the notify_email and record_event fakes."""
    return AutomationEngine(
        lambda entity_id: None,
        lambda mac, port, value: None,
        lambda entity_id: None,
        lambda: NOW,
        **callbacks,
    )


def mail_rule(data):
    return {"id": "mail_rule", "actions": [{"action": "notify.email", "data": data}]}


def event_rule(data):
    return {"id": "event_rule", "actions": [{"action": "mfi.event", "data": data}]}


def run_rule(rule, **callbacks):
    """Load one automation into a new engine, trigger it, and return the engine."""
    engine = make_engine(**callbacks)
    engine.load([rule])
    engine.trigger(rule["id"])
    return engine


class ValidateTest(unittest.TestCase):
    def test_notify_email_with_addr_and_body_is_valid(self):
        self.assertEqual(validate(mail_rule({"addr": [ADDR], "body": "Porta spenta"})), [])

    def test_notify_email_with_all_optional_keys_is_valid(self):
        data = {
            "addr": [ADDR, ADDR_2],
            "subject": "Allarme",
            "body": "Porta spenta",
            "key": "port_1",
            "hold_minutes": 10,
        }
        self.assertEqual(validate(mail_rule(data)), [])

    def test_notify_email_text_may_be_non_ascii(self):
        self.assertEqual(validate(mail_rule({"addr": [ADDR], "body": "Attenzione: è spenta"})), [])

    def test_notify_email_without_addr_is_refused(self):
        errors = validate(mail_rule({"body": "Porta spenta"}))
        self.assertTrue(any("addr" in e and "required" in e for e in errors), errors)

    def test_notify_email_without_body_is_refused(self):
        errors = validate(mail_rule({"addr": [ADDR]}))
        self.assertTrue(any("body" in e and "required" in e for e in errors), errors)

    def test_notify_email_unknown_key_is_refused(self):
        errors = validate(mail_rule({"addr": [ADDR], "body": "x", "extra": 1}))
        self.assertTrue(any("unknown key 'extra'" in e for e in errors), errors)

    def test_notify_email_addr_must_be_a_non_empty_list_of_strings(self):
        for addr in ([], [""], "alerts", [ADDR, 5], [None]):
            with self.subTest(addr=addr):
                errors = validate(mail_rule({"addr": addr, "body": "x"}))
                self.assertTrue(any("data.addr: must be" in e for e in errors), errors)

    def test_notify_email_hold_minutes_range(self):
        cases = [
            (0, True),
            (MAX_MINUTES, True),
            (-1, False),
            (MAX_MINUTES + 1, False),
            ("5", False),
            (True, False),
        ]
        for value, ok in cases:
            with self.subTest(value=value):
                errors = validate(mail_rule({"addr": [ADDR], "body": "x", "hold_minutes": value}))
                self.assertEqual(errors == [], ok, errors)

    def test_mfi_event_with_key_and_msg_is_valid(self):
        self.assertEqual(validate(event_rule({"key": "EVT_PORT", "msg": "Porta spenta"})), [])

    def test_mfi_event_with_all_optional_keys_is_valid(self):
        data = {"key": "EVT_PORT", "msg": "Porta spenta", "device": "mport_1", "level": 2, "dedup_minutes": 5}
        self.assertEqual(validate(event_rule(data)), [])

    def test_mfi_event_without_key_is_refused(self):
        errors = validate(event_rule({"msg": "Porta spenta"}))
        self.assertTrue(any("key" in e and "required" in e for e in errors), errors)

    def test_mfi_event_without_msg_is_refused(self):
        errors = validate(event_rule({"key": "EVT_PORT"}))
        self.assertTrue(any("msg" in e and "required" in e for e in errors), errors)

    def test_mfi_event_key_and_msg_must_be_non_empty_strings(self):
        for field in ("key", "msg"):
            for value in ("", None, 5):
                with self.subTest(field=field, value=value):
                    data = {"key": "EVT_PORT", "msg": "Porta spenta"}
                    data[field] = value
                    errors = validate(event_rule(data))
                    self.assertTrue(
                        any(f"data.{field}: must be a non-empty string" in e for e in errors), errors
                    )

    def test_mfi_event_dedup_minutes_and_level_ranges(self):
        cases = [
            ("dedup_minutes", 0, True),
            ("dedup_minutes", -1, False),
            ("dedup_minutes", None, False),
            ("level", 0, True),
            ("level", 10, True),
            ("level", 11, False),
            ("level", -1, False),
            ("level", None, False),
        ]
        for field, value, ok in cases:
            with self.subTest(field=field, value=value):
                data = {"key": "EVT_PORT", "msg": "Porta spenta", field: value}
                errors = validate(event_rule(data))
                self.assertEqual(errors == [], ok, errors)

    def test_notify_phone_is_still_an_unknown_action(self):
        errors = validate({"id": "phone", "actions": [{"action": "notify.phone", "data": {"msg": "x"}}]})
        self.assertTrue(any("unknown action" in e for e in errors), errors)


class NotifyEmailRunTest(unittest.TestCase):
    def test_callback_receives_the_data_dict_unchanged(self):
        data = {
            "addr": [ADDR, ADDR_2],
            "subject": "Allarme",
            "body": "Porta spenta",
            "key": "port_1",
            "hold_minutes": 10,
        }
        sinks = FakeSinks()
        engine = run_rule(mail_rule(data), notify_email=sinks.notify_email)
        self.assertEqual(sinks.mails, [data])
        self.assertEqual(sinks.events, [])
        self.assertEqual(engine.traces("mail_rule")[0]["result"], "finished")

    def test_without_a_sender_the_trace_records_the_error(self):
        engine = run_rule(mail_rule({"addr": [ADDR], "body": "Porta spenta"}))
        trace = engine.traces("mail_rule")[0]
        self.assertEqual(trace["result"], "error")
        self.assertEqual(trace["message"], "email notification not configured")
        self.assertEqual(trace["steps"], [{"path": "actions[0]", "result": "error"}])

    def test_a_failing_sender_is_recorded_in_the_trace(self):
        def broken(data):
            raise OSError("smtp unavailable")

        engine = run_rule(mail_rule({"addr": [ADDR], "body": "Porta spenta"}), notify_email=broken)
        trace = engine.traces("mail_rule")[0]
        self.assertEqual(trace["result"], "error")
        self.assertEqual(trace["message"], "smtp unavailable")


class MfiEventRunTest(unittest.TestCase):
    def test_callback_receives_the_data_dict_unchanged(self):
        data = {"key": "EVT_PORT", "msg": "Porta spenta", "device": "mport_1", "level": 2, "dedup_minutes": 5}
        sinks = FakeSinks()
        engine = run_rule(event_rule(data), record_event=sinks.record_event)
        self.assertEqual(sinks.events, [data])
        self.assertEqual(sinks.mails, [])
        self.assertEqual(engine.traces("event_rule")[0]["result"], "finished")

    def test_without_a_recorder_the_trace_records_the_error(self):
        engine = run_rule(event_rule({"key": "EVT_PORT", "msg": "Porta spenta"}))
        trace = engine.traces("event_rule")[0]
        self.assertEqual(trace["result"], "error")
        self.assertEqual(trace["message"], "event recording not configured")
        self.assertEqual(trace["steps"], [{"path": "actions[0]", "result": "error"}])

    def test_a_failing_recorder_is_recorded_in_the_trace(self):
        def broken(data):
            raise OSError("disk full")

        engine = run_rule(event_rule({"key": "EVT_PORT", "msg": "Porta spenta"}), record_event=broken)
        trace = engine.traces("event_rule")[0]
        self.assertEqual(trace["result"], "error")
        self.assertEqual(trace["message"], "disk full")


if __name__ == "__main__":
    unittest.main()
