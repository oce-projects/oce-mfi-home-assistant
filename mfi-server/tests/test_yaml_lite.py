"""Tests of the reduced YAML reader: automation syntax, scalars and the rejected constructs."""
from __future__ import annotations

import unittest

from mfi_server.yaml_lite import YamlError, loads

AUTOMATION_TEXT = """\
# Morning lamp
id: morning_lamp
alias: "Morning lamp"
triggers:
  - trigger: time
    at: 07:30:00  # no quotes on purpose
conditions:
  - condition: state
    entity_id: switch.mfi_aabbccddeeff_1
    state: 'off'
actions:
  - action: switch.turn_on
    target:
      entity_id: [switch.mfi_aabbccddeeff_1, "switch.mfi_aabbccddeeff_2"]
enabled: true
"""


class TestLoads(unittest.TestCase):
    def test_automation_with_lists_maps_comments_and_quotes(self):
        obj = loads(AUTOMATION_TEXT)
        self.assertEqual(
            obj,
            {
                "id": "morning_lamp",
                "alias": "Morning lamp",
                "triggers": [{"trigger": "time", "at": "07:30:00"}],
                "conditions": [
                    {"condition": "state", "entity_id": "switch.mfi_aabbccddeeff_1", "state": "off"}
                ],
                "actions": [
                    {
                        "action": "switch.turn_on",
                        "target": {
                            "entity_id": [
                                "switch.mfi_aabbccddeeff_1",
                                "switch.mfi_aabbccddeeff_2",
                            ]
                        },
                    }
                ],
                "enabled": True,
            },
        )
        at = obj["triggers"][0]["at"]
        self.assertIs(type(at), str)
        self.assertEqual(at, "07:30:00")

    def test_quoted_time_is_the_same_string(self):
        self.assertEqual(loads('at: "07:30:00"'), {"at": "07:30:00"})

    def test_scalar_types(self):
        obj = loads("a: 12\nb: -3\nc: 1.5\nd: true\ne: false\nf: null\ng: ~\nh: 'true'\ni: 1e3\n")
        self.assertEqual(
            obj,
            {"a": 12, "b": -3, "c": 1.5, "d": True, "e": False, "f": None, "g": None, "h": "true", "i": 1000.0},
        )
        self.assertIs(type(obj["h"]), str)
        self.assertIs(type(obj["a"]), int)

    def test_comment_marker_inside_quotes_is_kept(self):
        self.assertEqual(loads('note: "a # b"  # real comment'), {"note": "a # b"})

    def test_single_quote_escape(self):
        self.assertEqual(loads("text: 'it''s'"), {"text": "it's"})

    def test_inline_lists(self):
        self.assertEqual(loads("tags: [a, 'b c', 3]"), {"tags": ["a", "b c", 3]})
        self.assertEqual(loads("x: []"), {"x": []})

    def test_top_level_list_gives_several_automations(self):
        text = """\
- id: first
  enabled: false
- id: second
  mode: restart
"""
        obj = loads(text)
        self.assertIsInstance(obj, list)
        self.assertEqual(len(obj), 2)
        self.assertEqual(obj[0], {"id": "first", "enabled": False})
        self.assertEqual(obj[1], {"id": "second", "mode": "restart"})

    def test_empty_documents_give_none(self):
        self.assertIsNone(loads(""))
        self.assertIsNone(loads("# only a comment\n\n"))

    def test_tab_indentation_gives_error_on_its_line(self):
        with self.assertRaises(YamlError) as ctx:
            loads("name: x\n\tb: 1\n")
        self.assertEqual(ctx.exception.line, 2)

    def test_anchor_gives_error_on_its_line(self):
        with self.assertRaises(YamlError) as ctx:
            loads("name: x\nbase: &anchor\n  k: 1\n")
        self.assertEqual(ctx.exception.line, 2)

    def test_alias_gives_error_on_its_line(self):
        with self.assertRaises(YamlError) as ctx:
            loads("name: x\ncopy: *base\n")
        self.assertEqual(ctx.exception.line, 2)

    def test_duplicate_key_gives_error_on_second_occurrence(self):
        with self.assertRaises(YamlError) as ctx:
            loads("name: a\ntrigger: 1\nname: b\n")
        self.assertEqual(ctx.exception.line, 3)

    def test_inline_map_block_scalar_and_tag_are_rejected(self):
        cases = {
            "x: {a: 1}\n": 1,
            "a: 1\nb: |\n  text\n": 2,
            "a: 1\nb: >-\n  text\n": 2,
            "a: 1\nb: !!str 5\n": 2,
        }
        for text, line in cases.items():
            with self.subTest(text=text):
                with self.assertRaises(YamlError) as ctx:
                    loads(text)
                self.assertEqual(ctx.exception.line, line)

    def test_nested_inline_list_is_rejected(self):
        with self.assertRaises(YamlError) as ctx:
            loads("a: [[1], 2]\n")
        self.assertEqual(ctx.exception.line, 1)

    def test_bad_indentation_gives_error_on_its_line(self):
        with self.assertRaises(YamlError) as ctx:
            loads("a:\n    b: 1\n  c: 2\n")
        self.assertEqual(ctx.exception.line, 3)


if __name__ == "__main__":
    unittest.main()
