"""Offline tests of the import of the old controller rules (EPIC-19): conversion, skips, idempotent store and route.

Documents are synthetic dictionaries: no backup file and no BSON is read. The route runs on 127.0.0.1 only.
Run from the repository root: python3 -m unittest discover -s mfi-server/tests_next -v
"""
import gzip
import http.client
import http.server
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

from mfi_server_next import auth, page_api, rules, rules_import
from mfi_server_next.store import Store

WEB_I18N = Path(__file__).resolve().parent.parent / "mfi_server_next" / "web" / "i18n"
ADMIN_PASSWORD = "Abcdefghij1!"
READ_ONLY_PASSWORD = "Bcdefghijk2@"
NEW_KEYS = ("import_rules_action", "import_rules_report", "import_rules_error")


def oid(number):
    """A 24-character lower-case hex id, like the ObjectId of the controller."""
    return "%024x" % number


RULE = oid(1)
SENSOR = oid(10)
SWITCH = oid(11)
LIGHT = oid(12)
CALENDAR = oid(13)
SCENE = oid(30)
TARGET_RULE = oid(40)


def ruleset(number=2, **fields):
    doc = {
        "_id": oid(number), "rulesetId": RULE, "trigger": "sensor", "sId": SENSOR,
        "compare": 0, "limit": 1, "duration": 0, "enable": True,
        "allorany": "all", "edgeorlevel": "edge",
    }
    doc.update(fields)
    return doc


def action(number, **fields):
    doc = {"_id": oid(number), "rulesetId": RULE, "type": "relaySwitch", "sId": SWITCH, "val": 1, "timer": 0}
    doc.update(fields)
    return doc


def rule_backup(actions, *, rulesets=None, **collections):
    """A backup with one rule (label Hall); by default it has one edge trigger, so the rule is valid."""
    backup = {
        "rule": [{"_id": RULE, "label": "Hall"}],
        "ruleset": [ruleset()] if rulesets is None else rulesets,
        "ruleaction": actions,
    }
    backup.update(collections)
    return backup


def scene_backup(actions):
    return {
        "scene": [{"_id": SCENE, "label": "Evening"}],
        "sceneaction": actions,
    }


class ConvertCase(unittest.TestCase):
    def only(self, backup, *, allow_script_action=False):
        """Convert a backup that must give exactly one automation and no skipped entry."""
        result = rules_import.convert_rules(backup, allow_script_action=allow_script_action)
        self.assertEqual(result["report"]["skipped"], [])
        self.assertEqual(result["report"]["converted"], 1)
        self.assertEqual(len(result["automations"]), 1)
        return result["automations"][0]


class RulesTableTest(ConvertCase):
    """CA1: one synthetic document per row of the 'Old rule -> new automation' table."""

    def test_sensor_threshold_with_duration_is_numeric_trigger_for(self):
        auto = self.only(rule_backup([action(20)], rulesets=[ruleset(compare=0, limit=25.5, duration=2)]))
        self.assertEqual(auto["id"], "old_rule_" + RULE)
        self.assertEqual(auto["alias"], "Hall")
        self.assertEqual(auto["triggers"], [{
            "trigger": "numeric_state", "entity_id": "sensor.old_" + SENSOR, "above": 25.5, "for": {"minutes": 2},
        }])
        self.assertEqual(auto["conditions"], [])
        self.assertEqual(rules.validate(auto), [])

    def test_edge_is_trigger_and_level_is_condition(self):
        backup = rule_backup([action(20)], rulesets=[
            ruleset(2, compare=0, limit=5),
            ruleset(3, compare=4, limit=9, edgeorlevel="level"),
        ])
        auto = self.only(backup)
        self.assertEqual(auto["triggers"], [{"trigger": "numeric_state", "entity_id": "sensor.old_" + SENSOR, "above": 5}])
        self.assertEqual(auto["conditions"], [{"condition": "numeric_state", "entity_id": "sensor.old_" + SENSOR, "below": 9}])
        self.assertEqual(rules.validate(auto), [])

    def test_any_wraps_several_conditions_in_or(self):
        backup = rule_backup([action(20)], rulesets=[
            ruleset(2, compare=0, limit=5),
            ruleset(3, compare=0, limit=1, edgeorlevel="level", allorany="any"),
            ruleset(4, compare=4, limit=9, edgeorlevel="level", allorany="any"),
        ])
        auto = self.only(backup)
        self.assertEqual(auto["conditions"], [{"condition": "or", "conditions": [
            {"condition": "numeric_state", "entity_id": "sensor.old_" + SENSOR, "above": 1},
            {"condition": "numeric_state", "entity_id": "sensor.old_" + SENSOR, "below": 9},
        ]}])
        self.assertEqual(rules.validate(auto), [])

    def test_all_wraps_several_conditions_in_and(self):
        backup = rule_backup([action(20)], rulesets=[
            ruleset(2, compare=0, limit=5),
            ruleset(3, compare=0, limit=1, edgeorlevel="level", allorany="all"),
            ruleset(4, compare=4, limit=9, edgeorlevel="level", allorany="all"),
        ])
        auto = self.only(backup)
        self.assertEqual(auto["conditions"][0]["condition"], "and")
        self.assertEqual(len(auto["conditions"][0]["conditions"]), 2)
        self.assertEqual(rules.validate(auto), [])

    def test_weekly_interval_is_time_condition(self):
        # start 1920 = Monday 08:00, end 2460 = Monday 17:00 (minutes from Sunday 00:00)
        interval = {"_id": oid(50), "trigger": "time", "stateId": RULE, "start": 1920, "end": 2460}
        auto = self.only(rule_backup([action(20)], rulestatecalendar=[interval]))
        self.assertEqual(auto["conditions"], [{"condition": "time", "after": "08:00", "before": "17:00", "weekday": ["mon"]}])
        self.assertEqual(auto["triggers"], [{"trigger": "numeric_state", "entity_id": "sensor.old_" + SENSOR, "above": 1}])
        self.assertEqual(rules.validate(auto), [])

    def test_weekly_interval_alone_fires_at_its_start(self):
        interval = {"_id": oid(50), "trigger": "time", "stateId": RULE, "start": 1920, "end": 2460}
        auto = self.only(rule_backup([action(20)], rulesets=[], rulestatecalendar=[interval]))
        self.assertEqual(auto["triggers"], [{"trigger": "time", "at": "08:00", "weekday": ["mon"]}])
        self.assertEqual(auto["conditions"], [{"condition": "time", "after": "08:00", "before": "17:00", "weekday": ["mon"]}])
        self.assertEqual(rules.validate(auto), [])

    def test_several_weekly_intervals_each_become_a_trigger(self):
        monday = {"_id": oid(50), "trigger": "time", "stateId": RULE, "start": 1920, "end": 2460}
        tuesday = {"_id": oid(52), "trigger": "time", "stateId": RULE, "start": 3420, "end": 3960}
        auto = self.only(rule_backup([action(20)], rulesets=[], rulestatecalendar=[monday, tuesday]))
        self.assertEqual(auto["triggers"], [
            {"trigger": "time", "at": "08:00", "weekday": ["mon"]},
            {"trigger": "time", "at": "09:00", "weekday": ["tue"]},
        ])
        self.assertEqual(auto["conditions"], [{"condition": "or", "conditions": [
            {"condition": "time", "after": "08:00", "before": "17:00", "weekday": ["mon"]},
            {"condition": "time", "after": "09:00", "before": "18:00", "weekday": ["tue"]},
        ]}])
        self.assertEqual(rules.validate(auto), [])

    def test_calendar_is_calendar_trigger(self):
        schedule = {"_id": oid(51), "rulesetId": RULE, "trigger": "calendar", "sId": CALENDAR}
        auto = self.only(rule_backup([action(20)], rulesets=[], ruleschedule=[schedule]))
        self.assertEqual(auto["triggers"], [{"trigger": "calendar", "entity_id": "calendar.old_" + CALENDAR, "event": "start"}])
        self.assertEqual(rules.validate(auto), [])

    def test_relay_switch_is_switch_turn_on_or_off(self):
        auto = self.only(rule_backup([action(20, val=1), action(21, val=0)]))
        self.assertEqual(auto["actions"], [
            {"action": "switch.turn_on", "target": {"entity_id": ["switch.old_" + SWITCH]}},
            {"action": "switch.turn_off", "target": {"entity_id": ["switch.old_" + SWITCH]}},
        ])
        self.assertEqual(rules.validate(auto), [])

    def test_dimmer_scene_action_is_light_with_brightness(self):
        scene_action = {"_id": oid(31), "sceneId": SCENE, "type": "relaySwitch", "sId": LIGHT, "val": 1, "dimmer_level": 40}
        auto = self.only(scene_backup([scene_action]))
        self.assertEqual(auto["id"], "old_scene_" + SCENE)
        self.assertEqual(auto["actions"], [
            {"action": "light.turn_on", "target": {"entity_id": ["light.old_" + LIGHT]}, "data": {"brightness": 40}},
        ])
        self.assertEqual(rules.validate(auto), [])

    def test_scene_action_is_scene_turn_on(self):
        auto = self.only(rule_backup([action(20, type="scene", sceneId=SCENE)]))
        self.assertEqual(auto["actions"], [{"action": "scene.turn_on", "target": {"entity_id": ["scene.old_" + SCENE]}}])
        self.assertEqual(rules.validate(auto), [])

    def test_email_is_notify_email(self):
        auto = self.only(rule_backup([action(20, type="email", addr=["ops"], val="Door open", minute=5)]))
        self.assertEqual(auto["actions"], [
            {"action": "notify.email", "data": {"addr": ["ops"], "body": "Door open", "hold_minutes": 5}},
        ])
        self.assertEqual(rules.validate(auto), [])

    def test_url_is_http_post(self):
        auto = self.only(rule_backup([action(20, type="url", val="https://hooks.test/alert")]))
        self.assertEqual(auto["actions"], [
            {"action": "http_post", "data": {"url": "https://hooks.test/alert", "payload": {"rule": "Hall"}}},
        ])
        self.assertEqual(rules.validate(auto), [])

    def test_event_is_mfi_event(self):
        auto = self.only(rule_backup([action(20, type="event", val="Door", alert=True, minute=10)]))
        self.assertEqual(auto["actions"], [
            {"action": "mfi.event", "data": {"key": "EVT_mFi_SensorRuleset", "msg": "Door", "level": 2, "dedup_minutes": 10}},
        ])
        self.assertEqual(rules.validate(auto), [])

    def test_rule_action_is_automation_trigger(self):
        auto = self.only(rule_backup([action(20, type="rule", raId=TARGET_RULE)]))
        self.assertEqual(auto["actions"], [
            {"action": "automation.trigger", "target": {"entity_id": ["automation.old_rule_" + TARGET_RULE]}},
        ])
        self.assertEqual(rules.validate(auto), [])

    def test_state_action_is_automation_turn_off_when_val_is_false(self):
        auto = self.only(rule_backup([action(20, type="state", stateId=TARGET_RULE, val=0)]))
        self.assertEqual(auto["actions"], [
            {"action": "automation.turn_off", "target": {"entity_id": ["automation.old_rule_" + TARGET_RULE]}},
        ])
        self.assertEqual(rules.validate(auto), [])

    def test_script_is_script_action_when_allowed(self):
        auto = self.only(rule_backup([action(20, type="script", val="hello")]), allow_script_action=True)
        self.assertEqual(auto["actions"], [
            {"action": "script", "data": {"entity_id": "switch.old_" + SWITCH, "text": "hello"}},
        ])
        self.assertTrue(auto["enabled"])
        self.assertEqual(rules.validate(auto, allow_script_action=True), [])


class GunzipLimitTest(unittest.TestCase):
    """The decompression of db.gz is bounded, so a gzip bomb cannot exhaust memory."""

    def test_small_data_round_trips(self):
        self.assertEqual(rules_import._gunzip_limited(gzip.compress(b"hello")), b"hello")

    def test_output_past_the_limit_is_rejected(self):
        payload = gzip.compress(b"A" * 100000)
        with self.assertRaises(ValueError):
            rules_import._gunzip_limited(payload, limit=1000)


class UnknownTypeTest(ConvertCase):
    """CA2: an unknown type is kept in report.skipped with its reason; nothing is lost in silence."""

    def test_unknown_action_type_is_skipped_with_reason(self):
        result = rules_import.convert_rules(rule_backup([action(20, type="wait")]))
        self.assertEqual(result["automations"], [])
        self.assertEqual(result["report"]["converted"], 0)
        self.assertEqual(len(result["report"]["skipped"]), 1)
        skipped = result["report"]["skipped"][0]
        self.assertEqual(skipped["id"], "old_rule_" + RULE)
        self.assertIn("unknown action type", skipped["reason"])

    def test_unknown_trigger_value_is_skipped(self):
        result = rules_import.convert_rules(rule_backup([action(20)], rulesets=[ruleset(trigger="mqtt")]))
        self.assertEqual(result["automations"], [])
        self.assertEqual(result["report"]["skipped"][0]["reason"], "ruleset trigger mqtt not converted")

    def test_unknown_scene_action_type_is_skipped(self):
        result = rules_import.convert_rules(scene_backup([{"_id": oid(31), "sceneId": SCENE, "type": "email"}]))
        self.assertEqual(result["automations"], [])
        self.assertEqual(result["report"]["skipped"][0]["id"], "old_scene_" + SCENE)

    def test_counts_add_up_to_the_input_documents(self):
        backup = rule_backup([action(20)])
        backup["rule"].append({"_id": oid(3), "label": "Bad"})
        backup["ruleset"].append(ruleset(4, rulesetId=oid(3)))
        backup["ruleaction"].append(action(21, rulesetId=oid(3), type="wait"))
        result = rules_import.convert_rules(backup)
        self.assertEqual(result["report"]["converted"], 1)
        self.assertEqual(result["report"]["skipped"], [{"id": "old_rule_" + oid(3), "reason": "unknown action type wait"}])
        self.assertEqual(result["report"]["converted"] + len(result["report"]["skipped"]), 2)

    def test_rule_without_id_is_reported_not_dropped(self):
        result = rules_import.convert_rules({"rule": [{"label": "no id"}]})
        self.assertEqual(result["automations"], [])
        self.assertEqual(result["report"]["skipped"], [{"id": "", "reason": "missing or invalid _id"}])


class StoreTwiceTest(unittest.TestCase):
    """CA3: a second import of the same backup does not create duplicates."""

    def test_second_import_keeps_the_same_automations(self):
        backup = rule_backup([action(20)])
        backup["scene"] = [{"_id": SCENE, "label": "Evening"}]
        backup["sceneaction"] = [{"_id": oid(31), "sceneId": SCENE, "type": "relaySwitch", "sId": LIGHT, "val": 1}]
        result = rules_import.convert_rules(backup)
        with tempfile.TemporaryDirectory() as tmp:
            rules_import.store_automations(result["automations"], tmp, clock=lambda: 1700000000.0)
            merged = rules_import.store_automations(result["automations"], tmp, clock=lambda: 1700000001.0)
            db = Store.open(tmp)
            try:
                loaded = rules.AutomationStore(db).load()
            finally:
                db.close()
        ids = [item["id"] for item in loaded]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(loaded), 2)
        self.assertEqual(len(merged), 2)

    def test_store_keeps_existing_automation_without_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Store.open(tmp)
            try:
                rules.AutomationStore(db).save(
                    [{"alias": "legacy", "triggers": [], "conditions": [], "actions": []}]
                )
            finally:
                db.close()
            result = rules_import.convert_rules(rule_backup([action(20)]))
            rules_import.store_automations(result["automations"], tmp, clock=lambda: 1700000000.0)
            db = Store.open(tmp)
            try:
                loaded = rules.AutomationStore(db).load()
            finally:
                db.close()
        aliases = [item.get("alias") for item in loaded]
        self.assertIn("legacy", aliases)


class ScriptOffTest(ConvertCase):
    """CA4: with allow_script_action False a script automation is imported switched off, with a note."""

    def test_script_is_imported_disabled_and_noted(self):
        result = rules_import.convert_rules(rule_backup([action(20, type="script", val="hello")]), allow_script_action=False)
        self.assertEqual(len(result["automations"]), 1)
        self.assertIs(result["automations"][0]["enabled"], False)
        self.assertIn({"id": "old_rule_" + RULE, "reason": "script action disabled"}, result["report"]["skipped"])
        self.assertEqual(result["report"]["converted"], 1)

    def test_disabled_script_is_stored_and_stays_disabled(self):
        result = rules_import.convert_rules(rule_backup([action(20, type="script", val="hello")]))
        with tempfile.TemporaryDirectory() as tmp:
            rules_import.store_automations(result["automations"], tmp, clock=lambda: 1700000000.0)
            db = Store.open(tmp)
            try:
                loaded = rules.AutomationStore(db).load()
            finally:
                db.close()
        self.assertEqual(len(loaded), 1)
        self.assertIs(loaded[0]["enabled"], False)


class ImportRouteTest(unittest.TestCase):
    """CA5: the import route refuses a read-only user and answers the admin with the report."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = Store.open(tmp.name)
        self.addCleanup(self.store.close)
        self.auth = auth.AuthManager(self.store)
        self.auth.add_user("boss", ADMIN_PASSWORD, auth.ROLE_ADMIN)
        self.auth.add_user("viewer", READ_ONLY_PASSWORD, auth.ROLE_READ_ONLY)
        self.report = {"converted": 1, "skipped": []}
        self.calls = []
        self.refuse = False
        self.fail_io = False
        context = SimpleNamespace(
            auth=self.auth,
            settings={"mode": "standalone", "comet_timeout_s": 0.05, "max_body": 65536},
            import_rules=self.import_rules,
        )
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), page_api.make_handler(context))
        self.addCleanup(self.server.server_close)
        self.port = self.server.server_address[1]
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(self.server.shutdown)

    def import_rules(self, body):
        self.calls.append(body)
        if self.refuse:
            raise ValueError("not a backup")
        if self.fail_io:
            raise OSError("disk full")
        return self.report

    def call(self, method, path, *, body=None, cookie=None):
        headers = {"Cookie": f"{page_api.SESSION_COOKIE}={cookie}"} if cookie else {}
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()

    def login(self, username, password):
        body = json.dumps({"username": username, "password": password}).encode("utf-8")
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request("POST", "/api/v1/login", body=body)
            response = conn.getresponse()
            response.read()
            self.assertEqual(response.status, 200)
            set_cookie = response.getheader("Set-Cookie")
        finally:
            conn.close()
        return set_cookie.split(";", 1)[0].split("=", 1)[1]

    def test_read_only_user_gets_403_and_no_import_runs(self):
        token = self.login("viewer", READ_ONLY_PASSWORD)
        status, _ = self.call("POST", "/api/v1/upload/rules", body=b"x", cookie=token)
        self.assertEqual(status, 403)
        self.assertEqual(self.calls, [])

    def test_admin_gets_the_report(self):
        token = self.login("boss", ADMIN_PASSWORD)
        status, data = self.call("POST", "/api/v1/upload/rules", body=b"x", cookie=token)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data), {"report": self.report})
        self.assertEqual(self.calls, [b"x"])

    def test_invalid_backup_is_400(self):
        token = self.login("boss", ADMIN_PASSWORD)
        self.refuse = True
        status, data = self.call("POST", "/api/v1/upload/rules", body=b"x", cookie=token)
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(data), {"error": "invalid"})

    def test_io_error_during_import_is_500_json(self):
        token = self.login("boss", ADMIN_PASSWORD)
        self.fail_io = True
        status, data = self.call("POST", "/api/v1/upload/rules", body=b"x", cookie=token)
        self.assertEqual(status, 500)
        self.assertEqual(json.loads(data), {"error": "io_error"})

    def test_without_session_is_401(self):
        status, _ = self.call("POST", "/api/v1/upload/rules", body=b"x")
        self.assertEqual(status, 401)
        self.assertEqual(self.calls, [])


class ImportKeysTest(unittest.TestCase):
    """CA5: the new keys exist in both language files with their placeholders."""

    def load(self, name):
        return json.loads((WEB_I18N / name).read_text(encoding="utf-8"))

    def test_new_keys_exist_in_both_languages(self):
        for name in ("en.json", "it.json"):
            data = self.load(name)
            for key in NEW_KEYS:
                with self.subTest(file=name, key=key):
                    self.assertIn(key, data)
                    self.assertNotEqual(data[key].strip(), "")

    def test_placeholders_are_identical_in_both_languages(self):
        en = self.load("en.json")["import_rules_report"]
        it = self.load("it.json")["import_rules_report"]
        for placeholder in ("{converted}", "{skipped}"):
            self.assertIn(placeholder, en)
            self.assertIn(placeholder, it)


if __name__ == "__main__":
    unittest.main()
