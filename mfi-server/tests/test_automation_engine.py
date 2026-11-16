"""Tests of the automation engine: triggers, conditions, actions, modes, traces and errors.

Offline, standard library only. A fake clock that the test moves replaces time.sleep:
python3 -m unittest discover -s mfi-server/tests -t mfi-server -v
"""
from __future__ import annotations

import calendar
import time
import unittest

from mfi_server.automation_engine import AutomationEngine

MAC = "02aabbccdd01"
SWITCH_1 = "switch.mfi_02aabbccdd01_1"
SWITCH_2 = "switch.mfi_02aabbccdd01_2"
SENSOR = "sensor.mfi_02aabbccdd01_1_active_pwr"
RESOLVE = {SWITCH_1: (MAC, 1), SWITCH_2: (MAC, 2)}
NOW = 1000.0
# Monday 2026-11-16 08:00:00: the local time that the fake clock shows at NOW.
LOCAL_AT_NOW = calendar.timegm((2026, 11, 16, 8, 0, 0))


class FakeDevice:
    """Fakes of the engine's dependencies: a clock the test moves, a log of outputs and a dict of states."""

    def __init__(self) -> None:
        self.now = NOW
        self.states: dict[str, object] = {}
        self.calls: list[tuple[str, int, int]] = []
        self.fail = False

    def clock(self) -> float:
        return self.now

    def entities(self, entity_id: str) -> object:
        return self.states.get(entity_id)

    def resolve(self, entity_id: str) -> tuple[str, int] | None:
        return RESOLVE.get(entity_id)

    def set_output(self, mac: str, port: int, value: int) -> None:
        if self.fail:
            raise RuntimeError("device lost")
        self.calls.append((mac, port, value))

    def localtime(self, now: float) -> time.struct_time:
        return time.gmtime(LOCAL_AT_NOW + (now - NOW))


def make_engine(fake: FakeDevice) -> AutomationEngine:
    return AutomationEngine(fake.entities, fake.set_output, fake.resolve, fake.clock, localtime=fake.localtime)


def turn_on(entity_id: str) -> dict:
    return {"action": "switch.turn_on", "target": {"entity_id": entity_id}}


def turn_off(entity_id: str) -> dict:
    return {"action": "switch.turn_off", "target": {"entity_id": entity_id}}


def run_once(automation: dict, states: dict | None = None) -> tuple[FakeDevice, AutomationEngine]:
    """Load one automation, trigger it once and return the fake device and the engine."""
    fake = FakeDevice()
    fake.states = dict(states or {})
    engine = make_engine(fake)
    engine.load([automation])
    engine.trigger(automation["id"])
    return fake, engine


def hold_automation() -> dict:
    return {
        "id": "hold",
        "triggers": [{"trigger": "state", "entity_id": SWITCH_1, "to": "on", "for": "00:00:30"}],
        "actions": [turn_on(SWITCH_2)],
    }


def pulse_automation(mode: str = "single", limit: int = 10) -> dict:
    """An automation whose run lasts one minute before it turns SWITCH_1 on."""
    return {
        "id": "pulse",
        "mode": mode,
        "max": limit,
        "actions": [{"delay": "00:01:00"}, turn_on(SWITCH_1)],
    }


class TriggerTest(unittest.TestCase):
    def test_for_fires_after_the_wait(self):
        fake = FakeDevice()
        engine = make_engine(fake)
        engine.load([hold_automation()])
        engine.entity_changed(SWITCH_1, "off", "on")
        engine.tick(NOW + 29)
        self.assertEqual(fake.calls, [])
        engine.tick(NOW + 30)
        self.assertEqual(fake.calls, [(MAC, 2, 1)])

    def test_for_is_cancelled_when_the_state_returns(self):
        fake = FakeDevice()
        engine = make_engine(fake)
        engine.load([hold_automation()])
        engine.entity_changed(SWITCH_1, "off", "on")
        fake.now = NOW + 20
        engine.entity_changed(SWITCH_1, "on", "off")
        engine.tick(NOW + 30)
        self.assertEqual(fake.calls, [])

    def test_numeric_state_fires_only_on_entering_the_range(self):
        fake = FakeDevice()
        engine = make_engine(fake)
        engine.load(
            [
                {
                    "id": "hot",
                    "triggers": [{"trigger": "numeric_state", "entity_id": SENSOR, "above": 100}],
                    "actions": [turn_on(SWITCH_1)],
                }
            ]
        )
        engine.entity_changed(SENSOR, 90.0, 120.0)
        self.assertEqual(fake.calls, [(MAC, 1, 1)])
        engine.entity_changed(SENSOR, 120.0, 130.0)
        self.assertEqual(fake.calls, [(MAC, 1, 1)])

    def test_time_trigger_fires_at_the_instant(self):
        fake = FakeDevice()
        engine = make_engine(fake)
        engine.load(
            [
                {
                    "id": "morning",
                    "triggers": [{"trigger": "time", "at": "08:00:30"}],
                    "actions": [turn_on(SWITCH_1)],
                }
            ]
        )
        fired = []
        for offset in range(0, 40):
            before = len(fake.calls)
            engine.tick(NOW + offset)
            if len(fake.calls) > before:
                fired.append(offset)
        self.assertEqual(fired, [30])

    def test_time_pattern_fires_every_five_minutes(self):
        fake = FakeDevice()
        engine = make_engine(fake)
        engine.load(
            [
                {
                    "id": "five",
                    "triggers": [{"trigger": "time_pattern", "minutes": "/5"}],
                    "actions": [turn_on(SWITCH_1)],
                }
            ]
        )
        fired = []
        for offset in range(0, 601, 60):
            before = len(fake.calls)
            engine.tick(NOW + offset)
            if len(fake.calls) > before:
                fired.append(offset)
        # Offsets 0, 300 and 600 are 08:00, 08:05 and 08:10.
        self.assertEqual(fired, [0, 300, 600])

    def test_weekday_condition_blocks_monday(self):
        fake = FakeDevice()
        engine = make_engine(fake)
        engine.load(
            [
                {
                    "id": "weekend",
                    "triggers": [{"trigger": "time", "at": "08:00:30"}],
                    "conditions": [{"condition": "time", "weekday": ["sat", "sun"]}],
                    "actions": [turn_on(SWITCH_1)],
                }
            ]
        )
        engine.tick(NOW + 30)
        self.assertEqual(engine.traces("weekend")[0]["result"], "condition_false")
        self.assertEqual(fake.calls, [])

    def test_weekday_condition_allows_the_listed_day(self):
        fake = FakeDevice()
        engine = make_engine(fake)
        engine.load(
            [
                {
                    "id": "monday",
                    "triggers": [{"trigger": "time", "at": "08:00:30"}],
                    "conditions": [{"condition": "time", "weekday": ["mon"]}],
                    "actions": [turn_on(SWITCH_1)],
                }
            ]
        )
        engine.tick(NOW + 30)
        self.assertEqual(engine.traces("monday")[0]["result"], "finished")
        self.assertEqual(fake.calls, [(MAC, 1, 1)])

    def test_disabled_automation_does_not_fire_from_triggers_but_trigger_runs_it(self):
        fake = FakeDevice()
        engine = make_engine(fake)
        engine.load(
            [
                {
                    "id": "off_auto",
                    "enabled": False,
                    "triggers": [{"trigger": "state", "entity_id": SWITCH_1, "to": "on"}],
                    "actions": [turn_on(SWITCH_2)],
                }
            ]
        )
        engine.entity_changed(SWITCH_1, "off", "on")
        self.assertEqual(fake.calls, [])
        engine.trigger("off_auto")
        self.assertEqual(fake.calls, [(MAC, 2, 1)])


class ActionTest(unittest.TestCase):
    def test_delay_splits_the_run(self):
        fake = FakeDevice()
        engine = make_engine(fake)
        engine.load(
            [
                {
                    "id": "split",
                    "actions": [turn_on(SWITCH_1), {"delay": "00:01:00"}, turn_off(SWITCH_1)],
                }
            ]
        )
        engine.trigger("split")
        self.assertEqual(fake.calls, [(MAC, 1, 1)])
        engine.tick(NOW + 59)
        self.assertEqual(fake.calls, [(MAC, 1, 1)])
        engine.tick(NOW + 60)
        self.assertEqual(fake.calls, [(MAC, 1, 1), (MAC, 1, 0)])
        self.assertEqual(engine.traces("split")[0]["result"], "finished")

    def test_if_takes_the_then_branch(self):
        branch = {
            "id": "branch",
            "actions": [
                {
                    "if": [{"condition": "state", "entity_id": SWITCH_2, "state": "on"}],
                    "then": [turn_off(SWITCH_2)],
                    "else": [{"action": "switch.toggle", "target": {"entity_id": SWITCH_1}}],
                }
            ],
        }
        fake, _ = run_once(branch, {SWITCH_2: "on"})
        self.assertEqual(fake.calls, [(MAC, 2, 0)])

    def test_if_takes_the_else_branch(self):
        branch = {
            "id": "branch",
            "actions": [
                {
                    "if": [{"condition": "state", "entity_id": SWITCH_2, "state": "on"}],
                    "then": [turn_off(SWITCH_2)],
                    "else": [{"action": "switch.toggle", "target": {"entity_id": SWITCH_1}}],
                }
            ],
        }
        fake, _ = run_once(branch, {SWITCH_2: "off", SWITCH_1: "off"})
        self.assertEqual(fake.calls, [(MAC, 1, 1)])

    def test_choose_takes_the_matching_branch(self):
        rule = {
            "id": "sensor_rule",
            "actions": [
                {
                    "choose": [
                        {
                            "conditions": [{"condition": "numeric_state", "entity_id": SENSOR, "below": 5}],
                            "sequence": [turn_off(SWITCH_1)],
                        }
                    ],
                    "default": [turn_on(SWITCH_1)],
                }
            ],
        }
        fake, _ = run_once(rule, {SENSOR: 3.0})
        self.assertEqual(fake.calls, [(MAC, 1, 0)])

    def test_choose_falls_back_to_default(self):
        rule = {
            "id": "sensor_rule",
            "actions": [
                {
                    "choose": [
                        {
                            "conditions": [{"condition": "numeric_state", "entity_id": SENSOR, "below": 5}],
                            "sequence": [turn_off(SWITCH_1)],
                        }
                    ],
                    "default": [turn_on(SWITCH_1)],
                }
            ],
        }
        fake, _ = run_once(rule, {SENSOR: 10.0})
        self.assertEqual(fake.calls, [(MAC, 1, 1)])


class ModeTest(unittest.TestCase):
    def test_single_skips_the_second_trigger(self):
        fake = FakeDevice()
        engine = make_engine(fake)
        engine.load([pulse_automation("single")])
        engine.trigger("pulse")
        engine.trigger("pulse")
        self.assertEqual([t["result"] for t in engine.traces("pulse")], ["skipped"])

    def test_restart_stops_the_first_run(self):
        fake = FakeDevice()
        engine = make_engine(fake)
        engine.load([pulse_automation("restart")])
        engine.trigger("pulse")
        engine.trigger("pulse")
        self.assertEqual([t["result"] for t in engine.traces("pulse")], ["stopped"])
        engine.tick(NOW + 60)
        self.assertEqual([t["result"] for t in engine.traces("pulse")], ["stopped", "finished"])
        self.assertEqual(fake.calls, [(MAC, 1, 1)])

    def test_queued_drops_the_third_trigger(self):
        fake = FakeDevice()
        engine = make_engine(fake)
        engine.load([pulse_automation("queued", limit=2)])
        engine.trigger("pulse")
        engine.trigger("pulse")
        engine.trigger("pulse")
        self.assertEqual([t["result"] for t in engine.traces("pulse")], ["skipped"])
        engine.tick(NOW + 60)
        self.assertEqual([t["result"] for t in engine.traces("pulse")], ["skipped", "finished"])
        engine.tick(NOW + 120)
        self.assertEqual([t["result"] for t in engine.traces("pulse")], ["skipped", "finished", "finished"])
        self.assertEqual(fake.calls, [(MAC, 1, 1), (MAC, 1, 1)])

    def test_parallel_runs_two_at_once(self):
        fake = FakeDevice()
        engine = make_engine(fake)
        engine.load([pulse_automation("parallel")])
        engine.trigger("pulse")
        engine.trigger("pulse")
        engine.tick(NOW + 60)
        self.assertEqual(fake.calls, [(MAC, 1, 1), (MAC, 1, 1)])
        self.assertEqual([t["result"] for t in engine.traces("pulse")], ["finished", "finished"])


class ErrorAndTraceTest(unittest.TestCase):
    def test_unknown_entity_is_an_error_and_the_others_continue(self):
        fake = FakeDevice()
        engine = make_engine(fake)
        engine.load(
            [
                {"id": "broken", "actions": [turn_on("switch.mfi_ffeeddccbbaa_9")]},
                {"id": "good", "actions": [turn_on(SWITCH_1)]},
            ]
        )
        engine.trigger("broken")
        engine.trigger("good")
        broken = engine.traces("broken")[0]
        self.assertEqual(broken["result"], "error")
        self.assertIn("unknown entity", broken["message"])
        self.assertEqual(engine.traces("good")[0]["result"], "finished")
        self.assertEqual(fake.calls, [(MAC, 1, 1)])

    def test_output_failure_is_an_error(self):
        fake = FakeDevice()
        engine = make_engine(fake)
        engine.load([{"id": "good", "actions": [turn_on(SWITCH_1)]}])
        fake.fail = True
        engine.trigger("good")
        trace = engine.traces("good")[0]
        self.assertEqual(trace["result"], "error")
        self.assertEqual(trace["message"], "device lost")

    def test_unknown_service_is_an_error_and_sets_no_output(self):
        fake = FakeDevice()
        engine = make_engine(fake)
        engine.load(
            [
                {
                    "id": "weird",
                    "actions": [
                        {"action": "switch.explode", "target": {"entity_id": SWITCH_1}},
                        turn_on(SWITCH_2),
                    ],
                }
            ]
        )
        engine.trigger("weird")
        trace = engine.traces("weird")[0]
        self.assertEqual(trace["result"], "error")
        self.assertIn("unknown service", trace["message"])
        self.assertEqual(fake.calls, [])

    def test_trigger_and_traces_reject_an_unknown_id(self):
        fake = FakeDevice()
        engine = make_engine(fake)
        engine.load([{"id": "good", "actions": [turn_on(SWITCH_1)]}])
        with self.assertRaises(KeyError):
            engine.trigger("missing")
        with self.assertRaises(KeyError):
            engine.traces("missing")

    def test_traces_keep_only_the_last_five_runs(self):
        fake = FakeDevice()
        engine = make_engine(fake)
        engine.load([{"id": "good", "actions": [turn_on(SWITCH_1)]}])
        for _ in range(6):
            engine.trigger("good")
        traces = engine.traces("good")
        self.assertEqual(len(traces), 5)
        self.assertEqual([t["run_id"] for t in traces], [2, 3, 4, 5, 6])

    def test_load_stops_the_running_runs(self):
        fake = FakeDevice()
        engine = make_engine(fake)
        engine.load([pulse_automation()])
        engine.trigger("pulse")
        engine.load([pulse_automation()])
        self.assertEqual([t["result"] for t in engine.traces("pulse")], ["stopped"])
        engine.tick(NOW + 60)
        self.assertEqual(fake.calls, [])


if __name__ == "__main__":
    unittest.main()
