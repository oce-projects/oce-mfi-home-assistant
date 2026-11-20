"""Tests of the automation rules of mfi_server_next (EPIC-05).

CA1: one test runs each row of the table 'Old rule -> new automation'.
CA2: copy, disabled rule, nested conditions, time window, output timers in
     seconds, minutes and hours, and vacation mode.
CA3: an automations.json in the format of today is read without losing data.

Offline, standard library only. The telnet, HTTP, scene and brightness calls
are fakes that record their calls; nothing opens a socket and nothing sleeps:
the tests move a fake clock. Test data: host name mport-serial.test, port 2323,
MAC 02aabbccdd01 and the URL example.test only.
Run from the repository root: python3 -m unittest discover -s mfi-server/tests_next -v
"""
import calendar
import time
import unittest
from copy import deepcopy

from mfi_server_next.rules import (
    AutomationEngine,
    AutomationStore,
    normalize,
    parse_duration,
    validate,
)

MAC = "02aabbccdd01"
SWITCH_1 = "switch.mfi_02aabbccdd01_1"
SWITCH_2 = "switch.mfi_02aabbccdd01_2"
SWITCH_3 = "switch.mfi_02aabbccdd01_3"
LIGHT = "light.mfi_02aabbccdd01_1"
SENSOR = "sensor.mfi_02aabbccdd01_1_active_pwr"
CALENDAR = "calendar.home"
SCENE = "scene.evening"
SERIAL_ENTITY = "mport_serial_1"
SERIAL_HOST = "mport-serial.test"
SERIAL_PORT = 2323
HOOK_URL = "http://example.test/hook"
HOOK_URL_TLS = "https://example.test/hook"
RESOLVE = {SWITCH_1: (MAC, 1), SWITCH_2: (MAC, 2), SWITCH_3: (MAC, 3), LIGHT: (MAC, 1)}
NOW = 1000.0
# Monday 2026-11-16 08:00:00 is the local time shown at NOW.
LOCAL_AT_NOW = calendar.timegm((2026, 11, 16, 8, 0, 0))


class FakeDevice:
    """Fakes of the engine's callables: a clock the test moves, states, and a log of every call."""

    def __init__(self):
        self.now = NOW
        self.states = {}
        self.outputs = []
        self.brightness = []
        self.scenes = []
        self.posts = []
        self.serial = []

    def clock(self):
        return self.now

    def entities(self, entity_id):
        return self.states.get(entity_id)

    def resolve(self, entity_id):
        return RESOLVE.get(entity_id)

    def set_output(self, mac, port, value):
        self.outputs.append((mac, port, value))

    def set_brightness(self, mac, port, value, brightness):
        self.brightness.append((mac, port, value, brightness))

    def run_scene(self, entity_id):
        self.scenes.append(entity_id)

    def http_post(self, url, payload):
        self.posts.append((url, payload))

    def serial_send(self, host, port, text):
        self.serial.append((host, port, text))

    def serial_target(self, entity_id):
        return (SERIAL_HOST, SERIAL_PORT) if entity_id == SERIAL_ENTITY else None

    def localtime(self, now):
        return time.gmtime(LOCAL_AT_NOW + (now - NOW))


class FakeStore:
    """Fake of mfi_server_next.store.Store: JSON documents kept in a dict by file name."""

    def __init__(self):
        self.files = {}

    def read_json(self, name, default=None):
        return deepcopy(self.files[name]) if name in self.files else default

    def write_json(self, name, obj, *, private=False):
        self.files[name] = deepcopy(obj)


def make_engine(fake, **options):
    """Return an engine wired to the fakes; options override the wiring or set the script switch."""
    wiring = {
        "localtime": fake.localtime,
        "set_brightness": fake.set_brightness,
        "run_scene": fake.run_scene,
        "http_post": fake.http_post,
        "serial_send": fake.serial_send,
        "serial_target": fake.serial_target,
    }
    wiring.update(options)
    return AutomationEngine(fake.entities, fake.set_output, fake.resolve, fake.clock, **wiring)


def run(automation, *, states=None, now=NOW, **options):
    """Load one automation into a new engine, trigger it at now, and return the fake and the engine."""
    fake = FakeDevice()
    fake.states = dict(states or {})
    fake.now = now
    engine = make_engine(fake, **options)
    engine.load([automation])
    engine.trigger(automation["id"])
    return fake, engine


def turn_on(entity_id):
    return {"action": "switch.turn_on", "target": {"entity_id": entity_id}}


def turn_off(entity_id):
    return {"action": "switch.turn_off", "target": {"entity_id": entity_id}}


def is_on(entity_id):
    return {"condition": "state", "entity_id": entity_id, "state": "on"}


def condition_rule(conditions):
    return {"id": "cond", "conditions": conditions, "actions": [turn_on(SWITCH_1)]}


def result_of(conditions, states):
    """Trigger a rule with the given conditions and states and return the result of its only run."""
    fake, engine = run(condition_rule(conditions), states=states)
    return engine.traces("cond")[0]["result"]


class EpicRowsTest(unittest.TestCase):
    """CA1: each row of the table 'Old rule -> new automation' is executed by a test."""

    def test_numeric_state_with_for_fires_after_the_wait(self):
        automation = {
            "id": "row_numeric",
            "triggers": [{"trigger": "numeric_state", "entity_id": SENSOR, "above": 100, "for": "00:01:00"}],
            "actions": [turn_on(SWITCH_1)],
        }
        self.assertEqual(validate(automation), [])
        fake = FakeDevice()
        engine = make_engine(fake)
        engine.load([automation])
        engine.entity_changed(SENSOR, 90.0, 120.0)
        engine.tick(NOW + 59)
        self.assertEqual(fake.outputs, [])
        engine.tick(NOW + 60)
        self.assertEqual(fake.outputs, [(MAC, 1, 1)])

    def test_edge_trigger_with_level_condition(self):
        automation = {
            "id": "row_edge",
            "triggers": [{"trigger": "state", "entity_id": SWITCH_1, "to": "on"}],
            "conditions": [is_on(SWITCH_2)],
            "actions": [turn_on(SWITCH_3)],
        }
        self.assertEqual(validate(automation), [])
        fake = FakeDevice()
        fake.states = {SWITCH_2: "on"}
        engine = make_engine(fake)
        engine.load([automation])
        engine.entity_changed(SWITCH_1, "off", "on")
        self.assertEqual(fake.outputs, [(MAC, 3, 1)])
        # Staying on is not an edge: no new run.
        engine.entity_changed(SWITCH_1, "on", "on")
        # The level condition is checked when the edge fires.
        fake.states[SWITCH_2] = "off"
        engine.entity_changed(SWITCH_1, "off", "on")
        self.assertEqual(fake.outputs, [(MAC, 3, 1)])
        self.assertEqual([t["result"] for t in engine.traces("row_edge")], ["finished", "condition_false"])

    def test_and_condition(self):
        conditions = [{"condition": "and", "conditions": [is_on(SWITCH_2), is_on(SWITCH_3)]}]
        self.assertEqual(validate(condition_rule(conditions)), [])
        self.assertEqual(result_of(conditions, {SWITCH_2: "on", SWITCH_3: "on"}), "finished")
        self.assertEqual(result_of(conditions, {SWITCH_2: "on", SWITCH_3: "off"}), "condition_false")

    def test_or_condition(self):
        conditions = [{"condition": "or", "conditions": [is_on(SWITCH_2), is_on(SWITCH_3)]}]
        self.assertEqual(validate(condition_rule(conditions)), [])
        self.assertEqual(result_of(conditions, {SWITCH_2: "off", SWITCH_3: "on"}), "finished")
        self.assertEqual(result_of(conditions, {SWITCH_2: "off", SWITCH_3: "off"}), "condition_false")

    def test_not_condition(self):
        conditions = [{"condition": "not", "conditions": [is_on(SWITCH_2)]}]
        self.assertEqual(validate(condition_rule(conditions)), [])
        self.assertEqual(result_of(conditions, {SWITCH_2: "off"}), "finished")
        self.assertEqual(result_of(conditions, {SWITCH_2: "on"}), "condition_false")

    def test_time_trigger_with_weekday_trigger_and_time_condition(self):
        automation = {
            "id": "row_time",
            "triggers": [{"trigger": "time", "at": "08:00:30", "weekday": ["mon"]}],
            "conditions": [{"condition": "time", "weekday": ["mon"]}],
            "actions": [turn_on(SWITCH_1)],
        }
        self.assertEqual(validate(automation), [])
        fake = FakeDevice()
        engine = make_engine(fake)
        engine.load([automation])
        engine.tick(NOW + 29)
        self.assertEqual(fake.outputs, [])
        engine.tick(NOW + 30)
        self.assertEqual(fake.outputs, [(MAC, 1, 1)])
        self.assertEqual(engine.traces("row_time")[0]["result"], "finished")

    def test_calendar_trigger_runs_on_the_matching_event(self):
        automation = {
            "id": "row_calendar",
            "triggers": [{"trigger": "calendar", "entity_id": CALENDAR, "event": "start"}],
            "actions": [turn_on(SWITCH_1)],
        }
        self.assertEqual(validate(automation), [])
        fake = FakeDevice()
        engine = make_engine(fake)
        engine.load([automation])
        engine.calendar_fired(CALENDAR, "end")
        self.assertEqual(fake.outputs, [])
        engine.calendar_fired(CALENDAR, "start")
        self.assertEqual(fake.outputs, [(MAC, 1, 1)])

    def test_switch_turn_on_and_turn_off(self):
        automation = {"id": "row_switch", "actions": [turn_on(SWITCH_1), turn_off(SWITCH_2)]}
        self.assertEqual(validate(automation), [])
        fake, _ = run(automation)
        self.assertEqual(fake.outputs, [(MAC, 1, 1), (MAC, 2, 0)])

    def test_light_turn_on_sets_the_brightness(self):
        automation = {
            "id": "row_light",
            "actions": [{"action": "light.turn_on", "target": {"entity_id": LIGHT}, "data": {"brightness": 40}}],
        }
        self.assertEqual(validate(automation), [])
        fake, engine = run(automation)
        self.assertEqual(fake.outputs, [(MAC, 1, 1)])
        self.assertEqual(fake.brightness, [(MAC, 1, 1, 40)])
        too_bright = deepcopy(automation)
        too_bright["actions"][0]["data"]["brightness"] = 101
        self.assertTrue(any("brightness" in problem for problem in validate(too_bright)))

    def test_scene_turn_on_runs_the_scene(self):
        automation = {"id": "row_scene", "actions": [{"action": "scene.turn_on", "target": {"entity_id": SCENE}}]}
        self.assertEqual(validate(automation), [])
        fake, engine = run(automation)
        self.assertEqual(fake.scenes, [SCENE])
        self.assertEqual(engine.traces("row_scene")[0]["result"], "finished")

    def test_http_post_calls_the_client_with_http_and_https_urls(self):
        automation = {
            "id": "row_http",
            "actions": [
                {"action": "http_post", "data": {"url": HOOK_URL, "payload": {"value": 1}}},
                {"action": "http_post", "data": {"url": HOOK_URL_TLS}},
            ],
        }
        self.assertEqual(validate(automation), [])
        fake, _ = run(automation)
        self.assertEqual(fake.posts, [(HOOK_URL, {"value": 1}), (HOOK_URL_TLS, None)])

    def test_automation_trigger_runs_the_target_body(self):
        target = {"id": "target_rule", "actions": [turn_on(SWITCH_1)]}
        caller = {
            "id": "caller",
            "actions": [{"action": "automation.trigger", "target": {"entity_id": "automation.target_rule"}}],
        }
        self.assertEqual(validate(caller), [])
        fake = FakeDevice()
        engine = make_engine(fake)
        engine.load([target, caller])
        engine.trigger("caller")
        self.assertEqual(fake.outputs, [(MAC, 1, 1)])
        self.assertEqual(engine.traces("caller")[0]["result"], "finished")

    def test_automation_turn_on_and_turn_off_change_the_enabled_flag(self):
        watcher = {
            "id": "watcher",
            "enabled": False,
            "triggers": [{"trigger": "state", "entity_id": SWITCH_2, "to": "on"}],
            "actions": [turn_on(SWITCH_1)],
        }
        enable = {
            "id": "enable_watcher",
            "actions": [{"action": "automation.turn_on", "target": {"entity_id": "automation.watcher"}}],
        }
        disable = {
            "id": "disable_watcher",
            "actions": [{"action": "automation.turn_off", "target": {"entity_id": "automation.watcher"}}],
        }
        self.assertEqual(validate(enable), [])
        self.assertEqual(validate(disable), [])
        fake = FakeDevice()
        engine = make_engine(fake)
        engine.load([watcher, enable, disable])
        engine.entity_changed(SWITCH_2, "off", "on")
        self.assertEqual(fake.outputs, [])
        engine.trigger("enable_watcher")
        engine.entity_changed(SWITCH_2, "off", "on")
        self.assertEqual(fake.outputs, [(MAC, 1, 1)])
        engine.trigger("disable_watcher")
        engine.entity_changed(SWITCH_2, "on", "off")
        engine.entity_changed(SWITCH_2, "off", "on")
        self.assertEqual(fake.outputs, [(MAC, 1, 1)])

    def test_script_action_sends_the_text_to_the_adopted_serial(self):
        automation = {
            "id": "row_script",
            "actions": [{"action": "script", "data": {"entity_id": SERIAL_ENTITY, "text": "hello"}}],
        }
        self.assertEqual(validate(automation, allow_script_action=True), [])
        fake, engine = run(automation, allow_script_action=True)
        self.assertEqual(fake.serial, [(SERIAL_HOST, SERIAL_PORT, "hello")])
        self.assertEqual(engine.traces("row_script")[0]["result"], "finished")


class CopyAndEnableTest(unittest.TestCase):
    """CA2: copy of a rule, and a disabled rule that AutomationStore.set_enabled turns back on."""

    def source_automations(self):
        return [
            {
                "id": "source_rule",
                "alias": "Luce sera",
                "triggers": [{"trigger": "state", "entity_id": SWITCH_2, "to": "on"}],
                "actions": [turn_on(SWITCH_1)],
            },
            {"id": "other_rule", "actions": [turn_off(SWITCH_2)]},
        ]

    def test_copy_duplicates_the_rule_under_a_new_id(self):
        store = AutomationStore(FakeStore())
        original = self.source_automations()
        copied = store.copy(original, "source_rule", "copy_rule")
        self.assertEqual([item["id"] for item in copied], ["source_rule", "other_rule", "copy_rule"])
        self.assertEqual(copied[2]["alias"], "Luce sera")
        self.assertEqual(copied[2]["actions"], copied[0]["actions"])
        self.assertEqual(original, self.source_automations())

    def test_copy_is_independent_of_its_source(self):
        store = AutomationStore(FakeStore())
        copied = store.copy(self.source_automations(), "source_rule", "copy_rule")
        copied[2]["actions"][0]["target"]["entity_id"] = SWITCH_3
        self.assertEqual(copied[0]["actions"][0]["target"]["entity_id"], SWITCH_1)

    def test_copy_runs_under_its_new_id(self):
        store = AutomationStore(FakeStore())
        copied = store.copy(self.source_automations(), "source_rule", "copy_rule")
        fake = FakeDevice()
        engine = make_engine(fake)
        engine.load(copied)
        engine.trigger("copy_rule")
        self.assertEqual(fake.outputs, [(MAC, 1, 1)])

    def test_copy_refuses_a_missing_source_an_existing_id_and_a_bad_id(self):
        store = AutomationStore(FakeStore())
        automations = self.source_automations()
        with self.assertRaises(ValueError):
            store.copy(automations, "missing_rule", "copy_rule")
        with self.assertRaises(ValueError):
            store.copy(automations, "source_rule", "other_rule")
        with self.assertRaises(ValueError):
            store.copy(automations, "source_rule", "Copy-Rule")

    def test_disabled_rule_does_not_fire_from_its_trigger(self):
        rule = {
            "id": "off_rule",
            "enabled": False,
            "triggers": [{"trigger": "state", "entity_id": SWITCH_2, "to": "on"}],
            "actions": [turn_on(SWITCH_1)],
        }
        fake = FakeDevice()
        engine = make_engine(fake)
        engine.load([rule])
        engine.entity_changed(SWITCH_2, "off", "on")
        engine.tick(NOW + 10)
        self.assertEqual(fake.outputs, [])
        self.assertEqual(engine.traces("off_rule"), [])

    def test_set_enabled_turns_the_rule_back_on(self):
        store = AutomationStore(FakeStore())
        rules = [
            {
                "id": "off_rule",
                "enabled": False,
                "triggers": [{"trigger": "state", "entity_id": SWITCH_2, "to": "on"}],
                "actions": [turn_on(SWITCH_1)],
            }
        ]
        enabled = store.set_enabled(rules, "off_rule", True)
        self.assertTrue(enabled[0]["enabled"])
        self.assertFalse(rules[0]["enabled"])
        fake = FakeDevice()
        engine = make_engine(fake)
        engine.load(enabled)
        engine.entity_changed(SWITCH_2, "off", "on")
        self.assertEqual(fake.outputs, [(MAC, 1, 1)])
        disabled = store.set_enabled(enabled, "off_rule", False)
        fake_again = FakeDevice()
        engine = make_engine(fake_again)
        engine.load(disabled)
        engine.entity_changed(SWITCH_2, "off", "on")
        self.assertEqual(fake_again.outputs, [])


class ConditionsAndWindowTest(unittest.TestCase):
    """CA2: nested and/or/not conditions and the time window of a condition."""

    def test_nested_conditions_follow_the_and_or_not_tree(self):
        conditions = [
            {
                "condition": "and",
                "conditions": [
                    {"condition": "or", "conditions": [is_on(SWITCH_2), is_on(SWITCH_3)]},
                    {"condition": "not", "conditions": [is_on(LIGHT)]},
                ],
            }
        ]
        self.assertEqual(validate(condition_rule(conditions)), [])
        cases = [
            ({SWITCH_2: "on", SWITCH_3: "off", LIGHT: "off"}, "finished"),
            ({SWITCH_2: "off", SWITCH_3: "on", LIGHT: "off"}, "finished"),
            ({SWITCH_2: "off", SWITCH_3: "off", LIGHT: "off"}, "condition_false"),
            ({SWITCH_2: "on", SWITCH_3: "off", LIGHT: "on"}, "condition_false"),
        ]
        for states, expected in cases:
            with self.subTest(states=states):
                self.assertEqual(result_of(conditions, states), expected)

    def test_time_window_runs_inside_and_not_outside(self):
        rule = {
            "id": "window",
            "conditions": [{"condition": "time", "after": "08:00", "before": "09:00"}],
            "actions": [turn_on(SWITCH_1)],
        }
        self.assertEqual(validate(rule), [])
        # Offsets from 08:00: 07:59:59 out, 08:00 in (after is inclusive), 08:30 in, 09:00 out (before is exclusive), 10:00 out.
        cases = [(-1, False), (0, True), (1800, True), (3600, False), (7200, False)]
        for offset, inside in cases:
            with self.subTest(offset=offset):
                fake, engine = run(rule, now=NOW + offset)
                self.assertEqual(fake.outputs, [(MAC, 1, 1)] if inside else [])
                expected = "finished" if inside else "condition_false"
                self.assertEqual(engine.traces("window")[0]["result"], expected)

    def test_time_window_crossing_midnight(self):
        rule = {
            "id": "night",
            "conditions": [{"condition": "time", "after": "22:00", "before": "06:00"}],
            "actions": [turn_on(SWITCH_1)],
        }
        self.assertEqual(validate(rule), [])
        # Offsets from 08:00: 23:00 is inside the window, 12:00 is outside.
        cases = [(15 * 3600, True), (4 * 3600, False)]
        for offset, inside in cases:
            with self.subTest(offset=offset):
                fake, engine = run(rule, now=NOW + offset)
                self.assertEqual(fake.outputs, [(MAC, 1, 1)] if inside else [])
                expected = "finished" if inside else "condition_false"
                self.assertEqual(engine.traces("night")[0]["result"], expected)


class OutputTimerTest(unittest.TestCase):
    """CA2: a switch.turn_on with 'for' switches back off after the duration, in seconds, minutes and hours."""

    def test_timer_durations_are_read_in_seconds(self):
        self.assertEqual(parse_duration({"seconds": 300}), 300.0)
        self.assertEqual(parse_duration({"minutes": 5}), 300.0)
        self.assertEqual(parse_duration({"hours": 1}), 3600.0)
        self.assertEqual(parse_duration("00:05:00"), 300.0)

    def test_output_timer_switches_back_after_the_duration(self):
        cases = [({"seconds": 300}, 300), ({"minutes": 5}, 300), ({"hours": 1}, 3600), ("00:05:00", 300)]
        for duration, seconds in cases:
            with self.subTest(duration=duration):
                rule = {
                    "id": "timer_rule",
                    "actions": [{"action": "switch.turn_on", "target": {"entity_id": SWITCH_2}, "for": duration}],
                }
                self.assertEqual(validate(rule), [])
                fake, engine = run(rule)
                self.assertEqual(fake.outputs, [(MAC, 2, 1)])
                engine.tick(NOW + seconds - 1)
                self.assertEqual(fake.outputs, [(MAC, 2, 1)])
                engine.tick(NOW + seconds)
                self.assertEqual(fake.outputs, [(MAC, 2, 1), (MAC, 2, 0)])
                self.assertEqual(engine.traces("timer_rule")[0]["result"], "finished")


class VacationModeTest(unittest.TestCase):
    """CA2: vacation mode records the ports and switches them off when it ends."""

    def test_vacation_on_records_the_port_without_switching_it(self):
        fake = FakeDevice()
        engine = make_engine(fake)
        engine.set_vacation(True, [SWITCH_1])
        self.assertEqual(fake.outputs, [])

    def test_vacation_off_switches_the_recorded_port_off(self):
        fake = FakeDevice()
        engine = make_engine(fake)
        engine.set_vacation(True, [SWITCH_1])
        engine.set_vacation(False)
        self.assertEqual(fake.outputs, [(MAC, 1, 0)])

    def test_vacation_off_again_does_not_switch_twice(self):
        fake = FakeDevice()
        engine = make_engine(fake)
        engine.set_vacation(True, [SWITCH_1])
        engine.set_vacation(False)
        engine.set_vacation(False)
        self.assertEqual(fake.outputs, [(MAC, 1, 0)])

    def test_vacation_flag_must_be_a_boolean(self):
        engine = make_engine(FakeDevice())
        with self.assertRaises(ValueError):
            engine.set_vacation("yes", [SWITCH_1])


OLD_FORMAT_FILE = {
    "schema": 1,
    "automations": [
        {
            "id": "old_rule",
            "alias": "Vecchia regola",
            "description": "scritta dal formato di oggi",
            "enabled": False,
            "mode": "restart",
            "max": 3,
            "trigger": [{"platform": "numeric_state", "entity_id": SENSOR, "above": 100, "for": "00:01:00"}],
            "condition": [{"condition": "time", "after": "07:00", "before": "23:00", "weekday": ["mon", "fri"]}],
            "action": [
                {
                    "service": "switch.turn_on",
                    "target": {"entity_id": SWITCH_1},
                    "for": {"minutes": 5},
                }
            ],
        }
    ],
}


class OldFormatTest(unittest.TestCase):
    """CA3: an automations.json written in the format of today is read without losing data."""

    def test_old_keys_are_read_without_losing_data(self):
        store = FakeStore()
        store.files["automations.json"] = deepcopy(OLD_FORMAT_FILE)
        loaded = AutomationStore(store).load()
        self.assertEqual(len(loaded), 1)
        rule = loaded[0]
        self.assertEqual(rule["id"], "old_rule")
        self.assertEqual(rule["alias"], "Vecchia regola")
        self.assertEqual(rule["description"], "scritta dal formato di oggi")
        self.assertFalse(rule["enabled"])
        self.assertEqual(rule["mode"], "restart")
        self.assertEqual(rule["max"], 3)
        for old_key in ("trigger", "condition", "action"):
            self.assertNotIn(old_key, rule)
        trigger = rule["triggers"][0]
        self.assertEqual(trigger["trigger"], "numeric_state")
        self.assertNotIn("platform", trigger)
        self.assertEqual(trigger["entity_id"], SENSOR)
        self.assertEqual(trigger["above"], 100)
        self.assertEqual(trigger["for"], "00:01:00")
        condition = rule["conditions"][0]
        self.assertEqual(condition["condition"], "time")
        self.assertEqual(condition["after"], "07:00")
        self.assertEqual(condition["before"], "23:00")
        self.assertEqual(condition["weekday"], ["mon", "fri"])
        action = rule["actions"][0]
        self.assertEqual(action["action"], "switch.turn_on")
        self.assertNotIn("service", action)
        self.assertEqual(action["target"], {"entity_id": SWITCH_1})
        self.assertEqual(action["for"], {"minutes": 5})
        self.assertEqual(rule, normalize(OLD_FORMAT_FILE["automations"][0]))
        self.assertEqual(validate(rule), [])

    def test_saved_file_is_read_back_unchanged(self):
        store = FakeStore()
        store.files["automations.json"] = deepcopy(OLD_FORMAT_FILE)
        loaded = AutomationStore(store).load()
        AutomationStore(store).save(loaded)
        self.assertEqual(store.files["automations.json"]["schema"], 1)
        self.assertEqual(AutomationStore(store).load(), loaded)

    def test_missing_file_is_an_empty_list(self):
        self.assertEqual(AutomationStore(FakeStore()).load(), [])


if __name__ == "__main__":
    unittest.main()
