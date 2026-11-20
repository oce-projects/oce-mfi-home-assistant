"""Checks of the automation editor (EPIC-18): YAML round trip, YAML errors, the editor script and the editor routes.

Standard library only, offline. The server listens on 127.0.0.1 only. Test data uses example.test names only.
Run from the repository root: python3 -m unittest discover -s mfi-server/tests_next -v
"""
import http.client
import http.server
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

from mfi_server_next import auth, editor, page_api, rules
from mfi_server_next.store import Store

WEB = Path(__file__).resolve().parent.parent / "mfi_server_next" / "web"
ADMIN_PASSWORD = "Abcdefghij1!"
READ_ONLY_PASSWORD = "Bcdefghijk2!"

EXAMPLES = [
    {
        "id": "ex_state",
        "alias": "Luce accesa",
        "triggers": [{"trigger": "state", "entity_id": "switch.outlet_1", "to": "on", "for": "00:01:00"}],
        "actions": [{"action": "switch.turn_off", "target": {"entity_id": "switch.outlet_1"}}],
    },
    {
        "id": "ex_numeric",
        "triggers": [{"trigger": "numeric_state", "entity_id": "sensor.room_temp", "above": 21.5}],
        "actions": [
            {"action": "switch.turn_on", "target": {"entity_id": ["switch.outlet_2", "switch.outlet_3"]}, "for": "00:05:00"}
        ],
    },
    {
        "id": "ex_time",
        "triggers": [{"trigger": "time", "at": "08:00:00", "weekday": ["mon", "fri"]}],
        "conditions": [{"condition": "time", "after": "07:00", "before": "23:00"}],
        "actions": [{"action": "light.turn_on", "target": {"entity_id": "light.lamp"}, "data": {"brightness": 50}}],
    },
    {
        "id": "ex_pattern",
        "triggers": [{"trigger": "time_pattern", "minutes": "/5"}],
        "actions": [{"action": "scene.turn_on", "target": {"entity_id": "scene.evening"}}],
    },
    {
        "id": "ex_calendar",
        "triggers": [{"trigger": "calendar", "entity_id": "calendar.home", "event": "start"}],
        "actions": [
            {"delay": "00:00:30"},
            {"action": "automation.trigger", "target": {"entity_id": "automation.ex_state"}},
        ],
    },
    {
        "id": "ex_logic",
        "conditions": [
            {
                "condition": "and",
                "conditions": [
                    {"condition": "state", "entity_id": "switch.outlet_1", "state": "on"},
                    {
                        "condition": "or",
                        "conditions": [
                            {"condition": "numeric_state", "entity_id": "sensor.room_temp", "below": 30},
                            {
                                "condition": "not",
                                "conditions": [{"condition": "state", "entity_id": "switch.outlet_2", "state": "off"}],
                            },
                        ],
                    },
                ],
            }
        ],
        "actions": [{"action": "http_post", "data": {"url": "http://example.test/hook", "payload": {"value": 1}}}],
    },
    {
        "id": "ex_branch",
        "actions": [
            {
                "if": [{"condition": "state", "entity_id": "switch.outlet_1", "state": "on"}],
                "then": [{"action": "switch.toggle", "target": {"entity_id": "switch.outlet_2"}}],
                "else": [{"delay": "00:00:10"}],
            },
            {
                "choose": [
                    {
                        "conditions": [{"condition": "time", "weekday": ["sat", "sun"]}],
                        "sequence": [{"action": "scene.turn_on", "target": {"entity_id": "scene.weekend"}}],
                    }
                ],
                "default": [{"action": "switch.turn_off", "target": {"entity_id": "switch.outlet_3"}}],
            },
        ],
    },
    {
        "id": "ex_notify",
        "actions": [
            {
                "action": "notify.email",
                "data": {
                    "addr": ["first_recipient", "second_recipient"],
                    "subject": "Alarm",
                    "body": "Outlet 1 is off, it's ok",
                },
            },
            {"action": "mfi.event", "data": {"key": "outlet_off", "msg": "Outlet 1 changed"}},
        ],
    },
]

PRIMITIVES = {
    "flag_on": True,
    "flag_off": False,
    "count": 3,
    "ratio": 0.5,
    "clock": "08:00:00",
    "word": "on",
    "service": "switch.turn_on",
    "empty": "",
    "nothing": None,
    "nested": {"items": [True, 1.5, "on", -2]},
}

YAML_ERRORS = [
    ("a: 1\n\tb: 2", 2),
    ("a: 1\nb: 'open", 2),
    ("a: 1\nb: 2\na: 3", 3),
    ("hello", 1),
]


class TestRoundTrip(unittest.TestCase):
    """CA1: the writer and the reader give back the same value."""

    def test_examples_round_trip(self):
        for example in EXAMPLES:
            with self.subTest(id=example["id"]):
                a = rules.normalize(example)
                self.assertEqual(editor.from_yaml(editor.to_yaml(a)), a)

    def test_primitive_values_round_trip(self):
        self.assertEqual(editor.from_yaml(editor.to_yaml(PRIMITIVES)), PRIMITIVES)

    def test_empty_containers_round_trip(self):
        value = {"triggers": [], "data": {}, "count": 1}
        self.assertEqual(editor.from_yaml(editor.to_yaml(value)), value)
        self.assertEqual(editor.from_yaml(editor.to_yaml({})), {})

    def test_bool_is_written_bare(self):
        text = editor.to_yaml({"flag": True})
        self.assertIn("flag: true", text)
        self.assertNotIn("'true'", text)

    def test_strings_are_quoted_so_they_stay_strings(self):
        text = editor.to_yaml({"at": "08:00:00", "to": "on"})
        self.assertIn("at: '08:00:00'", text)
        self.assertIn("to: 'on'", text)
        self.assertEqual(editor.from_yaml(text), {"at": "08:00:00", "to": "on"})

    def test_apostrophe_is_doubled(self):
        text = editor.to_yaml({"text": "it's"})
        self.assertIn("'it''s'", text)
        self.assertEqual(editor.from_yaml(text), {"text": "it's"})

    def test_unsupported_type_is_refused(self):
        with self.assertRaises(TypeError):
            editor.to_yaml({"value": object()})


class TestYamlErrors(unittest.TestCase):
    """CA2: text outside the subset raises YamlError on the line of the problem."""

    def test_error_line_is_reported(self):
        for text, line in YAML_ERRORS:
            with self.subTest(text=text):
                with self.assertRaises(editor.YamlError) as caught:
                    editor.from_yaml(text)
                self.assertEqual(caught.exception.line, line)


class TestEditorScript(unittest.TestCase):
    """CA5: editor.js builds the DOM by hand, with relative addresses only."""

    @classmethod
    def setUpClass(cls):
        cls.text = (WEB / "editor.js").read_text(encoding="utf-8")

    def test_no_innerhtml(self):
        self.assertNotIn("innerHTML", self.text)

    def test_no_http_address(self):
        self.assertNotIn("http://", self.text)

    def test_no_https_address(self):
        self.assertNotIn("https://", self.text)

    def test_builds_the_dom_with_create_element_and_text_content(self):
        self.assertIn("createElement", self.text)
        self.assertIn("textContent", self.text)


class TestEditorRoutes(unittest.TestCase):
    """CA3: the editor routes map errors to status codes and respect the roles."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = Store.open(Path(tmp.name))
        self.addCleanup(self.store.close)
        self.auth = auth.AuthManager(self.store)
        self.auth.add_user("boss", ADMIN_PASSWORD, auth.ROLE_ADMIN)
        self.auth.add_user("viewer", READ_ONLY_PASSWORD, auth.ROLE_READ_ONLY)
        context = SimpleNamespace(
            auth=self.auth,
            automations=rules.AutomationStore(self.store),
            rules_engine=SimpleNamespace(traces=lambda automation_id: []),
            settings={"mode": "standalone", "max_body": 65536},
        )
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), page_api.make_handler(context))
        self.addCleanup(self.server.server_close)
        self.port = self.server.server_address[1]
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(self.server.shutdown)

    def call(self, method, path, payload=None, cookie=None):
        """Send one request to the local server; return (status, Set-Cookie header, decoded JSON body)."""
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Cookie": f"{page_api.SESSION_COOKIE}={cookie}"} if cookie else {}
        if body is not None:
            headers["Content-Type"] = "application/json"
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            raw = response.read()
            data = json.loads(raw) if raw else None
            return response.status, response.getheader("Set-Cookie"), data
        finally:
            conn.close()

    def login(self, username, password):
        status, set_cookie, _ = self.call("POST", "/api/v1/login", {"username": username, "password": password})
        self.assertEqual(status, 200)
        return set_cookie.split(";", 1)[0].split("=", 1)[1]

    def test_save_invalid_automation_is_400_with_details(self):
        token = self.login("boss", ADMIN_PASSWORD)
        status, _, data = self.call("POST", "/api/v1/editor/save", {"automation": {"id": "x"}}, cookie=token)
        self.assertEqual(status, 400)
        self.assertTrue(data["details"])

    def test_save_by_read_only_user_is_403(self):
        token = self.login("viewer", READ_ONLY_PASSWORD)
        status, _, _ = self.call("POST", "/api/v1/editor/save", {"automation": {"id": "x"}}, cookie=token)
        self.assertEqual(status, 403)

    def test_save_valid_automation_is_200(self):
        token = self.login("boss", ADMIN_PASSWORD)
        automation = {
            "id": "valid_rule",
            "actions": [{"action": "switch.turn_on", "target": {"entity_id": "switch.outlet_1"}}],
        }
        status, _, data = self.call("POST", "/api/v1/editor/save", {"automation": automation}, cookie=token)
        self.assertEqual(status, 200)
        self.assertEqual(data["automation"]["id"], "valid_rule")

    def test_traces_route_needs_only_a_session(self):
        token = self.login("viewer", READ_ONLY_PASSWORD)
        status, _, data = self.call("GET", "/api/v1/editor/traces/valid_rule", cookie=token)
        self.assertEqual(status, 200)
        self.assertEqual(data, {"traces": []})

    def test_from_yaml_route_reports_the_line(self):
        token = self.login("boss", ADMIN_PASSWORD)
        status, _, data = self.call("POST", "/api/v1/editor/from_yaml", {"yaml": "a: 1\n\tb: 2"}, cookie=token)
        self.assertEqual(status, 400)
        self.assertEqual(data["error"], "invalid_yaml")
        self.assertEqual(data["line"], 2)


if __name__ == "__main__":
    unittest.main()
