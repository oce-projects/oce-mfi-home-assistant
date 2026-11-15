"""Tests for mfi_server.automation_store: the automations.json archive.

Each test works in its own temporary folder. Standard library only.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from mfi_server.automation_store import FILE_NAME, AutomationStore

VALID = {
    "id": "lamp_evening",
    "triggers": [{"trigger": "time", "at": "19:00"}],
    "actions": [{"action": "switch.turn_on", "target": {"entity_id": "switch.mfi_02aabbccdd01_1"}}],
}
OLD_STYLE = {
    "id": "old_style",
    "trigger": [{"platform": "time", "at": "19:00"}],
    "action": [{"service": "switch.turn_on", "target": {"entity_id": "switch.mfi_02aabbccdd01_1"}}],
}


def yaml_item(automation_id: str, at: str = "07:30:00") -> str:
    """Return one automation of a YAML list."""
    return (
        f"- id: {automation_id}\n"
        "  triggers:\n"
        "    - trigger: time\n"
        f'      at: "{at}"\n'
        "  actions:\n"
        "    - action: switch.toggle\n"
        "      target:\n"
        "        entity_id: switch.mfi_02aabbccdd01_1\n"
    )


class StoreTestCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.path = self.folder / FILE_NAME
        self.tmp_path = self.folder / (FILE_NAME + ".tmp")


class TestPersistence(StoreTestCase):
    def test_put_is_read_back_by_a_new_store_and_file_has_schema_1(self):
        store = AutomationStore(self.folder)
        store.put(VALID)
        reopened = AutomationStore(self.folder)
        listed = reopened.list()
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["id"], "lamp_evening")
        self.assertEqual(listed[0]["max"], 10)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["schema"], 1)
        self.assertEqual(len(data["automations"]), 1)
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)
        self.assertFalse(self.tmp_path.exists())

    def test_old_keys_are_stored_in_the_new_format(self):
        AutomationStore(self.folder).put(OLD_STYLE)
        stored = AutomationStore(self.folder).get("old_style")
        self.assertEqual(stored["triggers"], [{"trigger": "time", "at": "19:00"}])
        self.assertNotIn("trigger", stored)
        self.assertTrue(stored["enabled"])
        self.assertEqual(stored["mode"], "single")


class TestPut(StoreTestCase):
    def test_automation_without_id_is_rejected_and_nothing_is_written(self):
        store = AutomationStore(self.folder)
        bad = dict(VALID)
        del bad["id"]
        with self.assertRaises(ValueError) as ctx:
            store.put(bad)
        self.assertIsInstance(ctx.exception.args[0], list)
        self.assertIn("id: required", ctx.exception.args[0])
        self.assertEqual(store.list(), [])
        self.assertFalse(self.path.exists())

    def test_unknown_key_is_reported_in_the_error_list(self):
        store = AutomationStore(self.folder)
        with self.assertRaises(ValueError) as ctx:
            store.put(dict(VALID, colour="red"))
        self.assertIn("unknown key 'colour'", ctx.exception.args[0])
        self.assertEqual(store.list(), [])

    def test_list_returns_copies_ordered_by_id(self):
        store = AutomationStore(self.folder)
        store.put(VALID)
        store.put(OLD_STYLE)
        listed = store.list()
        self.assertEqual([item["id"] for item in listed], ["lamp_evening", "old_style"])
        listed[0]["id"] = "changed"
        self.assertEqual([item["id"] for item in store.list()], ["lamp_evening", "old_style"])

    def test_get_and_delete(self):
        store = AutomationStore(self.folder)
        self.assertIsNone(store.get("lamp_evening"))
        store.put(VALID)
        self.assertEqual(store.get("lamp_evening")["id"], "lamp_evening")
        store.delete("lamp_evening")
        self.assertIsNone(store.get("lamp_evening"))
        self.assertEqual(AutomationStore(self.folder).list(), [])
        with self.assertRaises(KeyError):
            store.delete("lamp_evening")


class TestCorruptFile(StoreTestCase):
    def test_damaged_file_raises_and_is_never_rewritten(self):
        bad_documents = {
            "not json": "{not json",
            "root is a list": "[]",
            "schema 2": json.dumps({"schema": 2, "automations": []}),
            "automations not a list": json.dumps({"schema": 1, "automations": {}}),
            "invalid automation": json.dumps({"schema": 1, "automations": [{"id": "BAD ID"}]}),
        }
        for label, text in bad_documents.items():
            with self.subTest(label=label):
                self.path.write_text(text, encoding="utf-8")
                with self.assertRaises(ValueError):
                    AutomationStore(self.folder)
                self.assertEqual(self.path.read_text(encoding="utf-8"), text)


class TestImportYaml(StoreTestCase):
    def test_list_of_two_automations_is_imported(self):
        store = AutomationStore(self.folder)
        text = yaml_item("lamp_morning") + yaml_item("lamp_night", "23:00")
        ids = store.import_yaml(text)
        self.assertEqual(ids, ["lamp_morning", "lamp_night"])
        self.assertEqual([item["id"] for item in store.list()], ["lamp_morning", "lamp_night"])
        self.assertEqual(len(AutomationStore(self.folder).list()), 2)

    def test_single_mapping_is_one_automation(self):
        store = AutomationStore(self.folder)
        text = (
            "id: lamp_single\n"
            "actions:\n"
            "  - action: switch.toggle\n"
            "    target:\n"
            "      entity_id: switch.mfi_02aabbccdd01_1\n"
        )
        self.assertEqual(store.import_yaml(text), ["lamp_single"])
        self.assertEqual(len(store.list()), 1)

    def test_duplicate_id_in_one_import_stores_nothing(self):
        store = AutomationStore(self.folder)
        with self.assertRaises(ValueError) as ctx:
            store.import_yaml(yaml_item("lamp_one") * 2)
        self.assertIn("[1] id: duplicate in this import", ctx.exception.args[0])
        self.assertEqual(store.list(), [])
        self.assertFalse(self.path.exists())

    def test_one_invalid_item_stores_nothing(self):
        store = AutomationStore(self.folder)
        with self.assertRaises(ValueError) as ctx:
            store.import_yaml(yaml_item("lamp_one") + yaml_item("BAD ID"))
        self.assertTrue(any(error.startswith("[1] ") for error in ctx.exception.args[0]))
        self.assertEqual(store.list(), [])
        self.assertFalse(self.path.exists())

    def test_yaml_syntax_error_is_reported_with_its_line(self):
        store = AutomationStore(self.folder)
        with self.assertRaises(ValueError) as ctx:
            store.import_yaml("- id: lamp\n\tactions: []\n")
        self.assertEqual(ctx.exception.args[0], ["line 2: tabs are not allowed for indentation"])
        self.assertEqual(store.list(), [])

    def test_empty_document_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            AutomationStore(self.folder).import_yaml("")
        self.assertEqual(ctx.exception.args[0], ["document is empty"])

    def test_scalar_document_is_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            AutomationStore(self.folder).import_yaml("42")
        self.assertEqual(ctx.exception.args[0], ["top level must be a mapping or a list of mappings"])


if __name__ == "__main__":
    unittest.main()
