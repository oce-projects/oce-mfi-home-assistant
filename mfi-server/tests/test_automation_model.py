"""Tests of the automation model: normalize, validate and parse_duration.

Offline, standard library only:
python3 -m unittest discover -s mfi-server/tests -t mfi-server -v
"""
from __future__ import annotations

import copy
import unittest

from mfi_server.automation_model import normalize, parse_duration, validate

SWITCH_1 = "switch.mfi_aabbccddeeff_1"
SWITCH_2 = "switch.mfi_aabbccddeeff_2"
SENSOR_1 = "sensor.mfi_aabbccddeeff_1_active_pwr"


def valid_automation() -> dict:
    """Return a new automation with every supported trigger, condition and action."""
    return {
        "id": "evening_lights",
        "triggers": [
            {"trigger": "state", "entity_id": SWITCH_1, "to": "on", "for": "00:00:05"},
            {"trigger": "numeric_state", "entity_id": SENSOR_1, "above": 100.5},
            {"trigger": "time", "at": "08:00:30"},
            {"trigger": "time_pattern", "minutes": "/5"},
        ],
        "conditions": [{"condition": "time", "after": "07:00", "before": "23:00", "weekday": ["mon", "fri"]}],
        "actions": [
            {"action": "switch.turn_on", "target": {"entity_id": SWITCH_2}},
            {"delay": "00:01:00"},
            {
                "if": [{"condition": "state", "entity_id": SWITCH_2, "state": "on"}],
                "then": [{"action": "switch.turn_off", "target": {"entity_id": SWITCH_2}}],
                "else": [{"action": "switch.toggle", "target": {"entity_id": SWITCH_1}}],
            },
            {
                "choose": [
                    {
                        "conditions": [{"condition": "numeric_state", "entity_id": SENSOR_1, "below": 5}],
                        "sequence": [{"action": "switch.turn_off", "target": {"entity_id": SWITCH_1}}],
                    }
                ],
                "default": [{"delay": {"minutes": 2}}],
            },
        ],
    }


def small_automation(**changes: object) -> dict:
    """Return a minimal valid automation, with the given keys replaced."""
    obj = {"id": "x", "actions": [{"delay": "00:00:01"}]}
    obj.update(changes)
    return obj


class ValidateTest(unittest.TestCase):
    def test_supported_automation_is_valid(self):
        self.assertEqual(validate(valid_automation()), [])

    def test_old_home_assistant_forms_are_valid(self):
        old = {
            "id": "lamp",
            "trigger": [{"platform": "state", "entity_id": SWITCH_1, "to": "on"}],
            "action": [{"service": "switch.turn_on", "target": {"entity_id": SWITCH_2}}],
        }
        self.assertEqual(validate(old), [])

    def test_template_value_is_not_supported(self):
        obj = valid_automation()
        obj["actions"][0]["target"]["entity_id"] = "{{ states('switch.x') }}"
        self.assertEqual(validate(obj), ["actions[0].target.entity_id: not supported yet"])

    def test_template_in_message_is_not_supported(self):
        obj = {"id": "notify_me", "actions": [{"action": "notify.mobile", "message": "{{ x }}"}]}
        self.assertIn("actions[0].message: not supported yet", validate(obj))

    def test_template_in_time_is_not_supported(self):
        obj = valid_automation()
        obj["triggers"][2]["at"] = "{{ now() }}"
        self.assertEqual(validate(obj), ["triggers[2].at: not supported yet"])

    def test_invalid_time_is_reported(self):
        for value in ("25:00", "08:60"):
            with self.subTest(value=value):
                obj = small_automation(triggers=[{"trigger": "time", "at": value}])
                self.assertEqual(validate(obj), ["triggers[0].at: invalid time"])

    def test_last_second_of_day_is_valid(self):
        obj = small_automation(triggers=[{"trigger": "time", "at": "23:59:59"}])
        self.assertEqual(validate(obj), [])

    def test_unknown_top_level_key(self):
        obj = valid_automation()
        obj["color"] = "red"
        self.assertEqual(validate(obj), ["unknown key 'color'"])

    def test_alias_and_description_are_accepted(self):
        obj = valid_automation()
        obj["alias"] = "Evening lights"
        obj["description"] = "Turns the lights on in the evening"
        self.assertEqual(validate(obj), [])

    def test_non_finite_number_is_reported(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(above=value):
                obj = small_automation(triggers=[{"trigger": "numeric_state", "entity_id": SENSOR_1, "above": value}])
                self.assertEqual(validate(obj), ["triggers[0].above: must be a number"])

    def test_unknown_key_in_trigger(self):
        obj = valid_automation()
        obj["triggers"][2]["foo"] = 1
        self.assertEqual(validate(obj), ["triggers[2]: unknown key 'foo'"])

    def test_unknown_key_in_action(self):
        obj = valid_automation()
        obj["actions"][1]["extra"] = 1
        self.assertEqual(validate(obj), ["actions[1]: unknown key 'extra'"])

    def test_unsupported_trigger_type(self):
        obj = small_automation(triggers=[{"trigger": "sun", "event": "sunrise"}])
        self.assertEqual(validate(obj), ["triggers[0]: not supported yet"])

    def test_unknown_trigger_type(self):
        obj = small_automation(triggers=[{"trigger": "webhook"}])
        self.assertEqual(validate(obj), ["triggers[0]: unknown trigger"])

    def test_unsupported_action_step(self):
        obj = small_automation(actions=[{"repeat": {"count": 2, "sequence": []}}])
        self.assertEqual(validate(obj), ["actions[0]: not supported yet"])

    def test_unknown_action(self):
        obj = small_automation(actions=[{"action": "light.turn_on", "target": {"entity_id": SWITCH_1}}])
        self.assertEqual(validate(obj), ["actions[0]: unknown action"])

    def test_unknown_condition(self):
        obj = small_automation(conditions=[{"condition": "zone"}])
        self.assertEqual(validate(obj), ["conditions[0]: unknown condition"])

    def test_id_rules(self):
        for value in ("lamp_1", "a" * 64):
            with self.subTest(valid=value):
                self.assertEqual(validate(small_automation(id=value)), [])
        for value in ("Lamp", "lampada_è", "a-b", "a" * 65):
            with self.subTest(invalid=value):
                self.assertEqual(validate(small_automation(id=value)), ["id: must match [a-z0-9_]{1,64}"])

    def test_missing_id(self):
        self.assertEqual(validate({"actions": [{"delay": "00:00:01"}]}), ["id: required"])

    def test_empty_input(self):
        self.assertEqual(validate({}), ["id: required", "actions: required"])

    def test_not_a_mapping(self):
        self.assertEqual(validate(None), ["not a mapping"])

    def test_mode_must_be_known(self):
        self.assertEqual(
            validate(small_automation(mode="bogus")),
            ["mode: must be one of single, restart, queued, parallel"],
        )
        for mode in ("single", "restart", "queued", "parallel"):
            with self.subTest(mode=mode):
                self.assertEqual(validate(small_automation(mode=mode)), [])

    def test_max_range(self):
        for value in (0, 101, True, "5"):
            with self.subTest(max=value):
                self.assertEqual(validate(small_automation(max=value)), ["max: must be an integer from 1 to 100"])
        for value in (1, 100):
            with self.subTest(max=value):
                self.assertEqual(validate(small_automation(max=value)), [])

    def test_numeric_state_needs_above_or_below(self):
        obj = small_automation(triggers=[{"trigger": "numeric_state", "entity_id": SENSOR_1}])
        self.assertEqual(validate(obj), ["triggers[0]: above or below required"])

    def test_time_pattern_values(self):
        for value in ("*", "/5", 0, 59):
            with self.subTest(valid=value):
                obj = small_automation(triggers=[{"trigger": "time_pattern", "minutes": value}])
                self.assertEqual(validate(obj), [])
        for value in ("/0", 60, "5", True):
            with self.subTest(invalid=value):
                obj = small_automation(triggers=[{"trigger": "time_pattern", "minutes": value}])
                self.assertEqual(
                    validate(obj),
                    ["triggers[0].minutes: must be an integer from 0 to 59, '*' or '/N'"],
                )

    def test_bad_delay_is_reported(self):
        for value in ("00:60:00", {"minutes": -1}):
            with self.subTest(delay=value):
                obj = small_automation(actions=[{"delay": value}])
                self.assertEqual(validate(obj), ["actions[0].delay: invalid duration"])

    def test_weekday_must_be_known(self):
        obj = small_automation(conditions=[{"condition": "time", "weekday": ["mon", "funday"]}])
        self.assertEqual(
            validate(obj),
            ["conditions[0].weekday: must be a list of mon, tue, wed, thu, fri, sat, sun"],
        )

    def test_triggers_must_be_list(self):
        self.assertEqual(validate(small_automation(triggers="state")), ["triggers: must be a list"])


class NormalizeTest(unittest.TestCase):
    def test_old_forms_become_new(self):
        old = {
            "id": "lamp",
            "trigger": [{"platform": "state", "entity_id": SWITCH_1, "to": "on"}],
            "action": [{"service": "switch.turn_on", "target": {"entity_id": SWITCH_2}}],
        }
        new = normalize(old)
        self.assertEqual(new["triggers"], [{"trigger": "state", "entity_id": SWITCH_1, "to": "on"}])
        self.assertEqual(new["actions"], [{"action": "switch.turn_on", "target": {"entity_id": SWITCH_2}}])
        self.assertNotIn("trigger", new)
        self.assertNotIn("action", new)
        self.assertIs(new["enabled"], True)
        self.assertEqual(new["mode"], "single")
        self.assertEqual(new["max"], 10)

    def test_nested_service_is_renamed(self):
        old = {
            "id": "x",
            "actions": [
                {
                    "if": [{"condition": "state", "entity_id": SWITCH_1, "state": "on"}],
                    "then": [{"service": "switch.toggle", "target": {"entity_id": SWITCH_1}}],
                }
            ],
        }
        new = normalize(old)
        self.assertEqual(new["actions"][0]["then"], [{"action": "switch.toggle", "target": {"entity_id": SWITCH_1}}])

    def test_defaults_are_filled_and_given_values_kept(self):
        new = normalize({"id": "x"})
        self.assertIs(new["enabled"], True)
        self.assertEqual(new["mode"], "single")
        self.assertEqual(new["max"], 10)
        kept = normalize({"id": "x", "enabled": False, "mode": "queued", "max": 3})
        self.assertIs(kept["enabled"], False)
        self.assertEqual(kept["mode"], "queued")
        self.assertEqual(kept["max"], 3)

    def test_normalize_is_idempotent(self):
        old = {
            "id": "lamp",
            "trigger": [{"platform": "time", "at": "08:00"}],
            "action": [{"service": "switch.turn_on", "target": {"entity_id": SWITCH_2}}],
        }
        once = normalize(old)
        self.assertEqual(normalize(once), once)

    def test_input_is_not_changed(self):
        old = {
            "id": "lamp",
            "trigger": [{"platform": "state", "entity_id": SWITCH_1}],
            "action": [{"service": "switch.turn_on", "target": {"entity_id": SWITCH_2}}],
        }
        before = copy.deepcopy(old)
        normalize(old)
        self.assertEqual(old, before)


class ParseDurationTest(unittest.TestCase):
    def test_clock_string(self):
        self.assertEqual(parse_duration("00:01:30"), 90.0)
        self.assertEqual(parse_duration("1:00:00"), 3600.0)

    def test_mapping(self):
        self.assertEqual(parse_duration({"minutes": 2}), 120.0)
        self.assertEqual(parse_duration({"hours": 1, "minutes": 30, "seconds": 15}), 5415.0)

    def test_invalid_values_raise(self):
        bad_values = [
            "1:2",
            "00:60:00",
            "00:00:60",
            "abc",
            "",
            "٠٠:٠١:٣٠",
            90,
            None,
            {},
            {"days": 1},
            {"minutes": -1},
            {"minutes": True},
            ["00:01:00"],
        ]
        for value in bad_values:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_duration(value)

    def test_non_finite_mapping_raises(self):
        for value in ({"seconds": float("nan")}, {"minutes": float("inf")}):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_duration(value)


if __name__ == "__main__":
    unittest.main()
