"""Abuse tests of the automation rules: the script action, unadopted targets, long text, unknown types and a runaway automation.

Offline, standard library only. Telnet and HTTP are fakes that record their calls;
nothing opens a socket. Test data: host names, port 2323, MAC 0418d6000001 and
the allowed address 192.168.1.20 only.
Run from the repository root: python3 -m unittest discover -s mfi-server/tests_next -v
"""
import time
import unittest

from mfi_server_next.rules import AutomationEngine, validate

SERIAL_ENTITY = "mport_serial_1"
SERIAL_HOST = "mport-serial.test"
SERIAL_PORT = 2323
UNADOPTED_ENTITY = "mport_serial_9"
SWITCH_ENTITY = "switch.mfi_0418d6000001_1"
MAC = "0418d6000001"
HOOK_URL = "http://example.test/hook"
NOW = 1000.0


class FakeTelnet:
    """Fake of the serial send: knows one adopted mPort Serial and records every text sent to it."""

    def __init__(self):
        self.sent = []

    def target(self, entity_id):
        return (SERIAL_HOST, SERIAL_PORT) if entity_id == SERIAL_ENTITY else None

    def send(self, host, port, text):
        self.sent.append((host, port, text))


class FakeHttp:
    """Fake of the HTTP POST: records every call."""

    def __init__(self):
        self.posts = []

    def post(self, url, payload):
        self.posts.append((url, payload))


class FakeDevice:
    """Fake of the device outputs: records every output set and knows one switch."""

    def __init__(self):
        self.outputs = []

    def entities(self, entity_id):
        return None

    def resolve(self, entity_id):
        return (MAC, 1) if entity_id == SWITCH_ENTITY else None

    def set_output(self, mac, port, value):
        self.outputs.append((mac, port, value))

    def clock(self):
        return NOW


def build(telnet, http=None, **options):
    """Return an engine wired to the fakes, and the device fake it switches."""
    device = FakeDevice()
    engine = AutomationEngine(
        device.entities,
        device.set_output,
        device.resolve,
        device.clock,
        localtime=time.gmtime,
        http_post=http.post if http is not None else None,
        serial_send=telnet.send,
        serial_target=telnet.target,
        **options
    )
    return engine, device


def script_automation(text="hello", entity=SERIAL_ENTITY):
    return {
        "id": "script_rule",
        "actions": [{"action": "script", "data": {"entity_id": entity, "text": text}}],
    }


def loop_automation():
    return {
        "id": "loop",
        "actions": [{"action": "automation.trigger", "target": {"entity_id": "automation.loop"}}],
    }


class ScriptValidationTest(unittest.TestCase):
    def test_script_action_is_disabled_by_default(self):
        errors = validate(script_automation())
        self.assertTrue(any("script" in e and "disabled" in e for e in errors), errors)

    def test_script_action_validates_when_enabled(self):
        self.assertEqual(validate(script_automation(), allow_script_action=True), [])

    def test_text_at_the_limit_is_accepted(self):
        errors = validate(script_automation(text="x" * 10), allow_script_action=True, script_max_length=10)
        self.assertEqual(errors, [])

    def test_text_over_the_limit_is_refused(self):
        errors = validate(script_automation(text="x" * 11), allow_script_action=True, script_max_length=10)
        self.assertTrue(any("too long" in e for e in errors), errors)


class ScriptRuntimeTest(unittest.TestCase):
    def test_disabled_script_never_reaches_telnet(self):
        telnet = FakeTelnet()
        engine, _ = build(telnet)
        engine.load([script_automation()])
        engine.trigger("script_rule")
        self.assertEqual(telnet.sent, [])
        trace = engine.traces("script_rule")[0]
        self.assertEqual(trace["result"], "error")
        self.assertEqual(trace["message"], "script action is disabled")

    def test_script_to_an_unadopted_device_is_refused(self):
        telnet = FakeTelnet()
        engine, _ = build(telnet, allow_script_action=True)
        engine.load([script_automation(entity=UNADOPTED_ENTITY)])
        engine.trigger("script_rule")
        self.assertEqual(telnet.sent, [])
        trace = engine.traces("script_rule")[0]
        self.assertEqual(trace["result"], "error")
        self.assertEqual(trace["message"], "device is not an adopted mPort Serial")

    def test_text_over_the_limit_is_never_sent(self):
        telnet = FakeTelnet()
        engine, _ = build(telnet, allow_script_action=True, script_max_length=10)
        engine.load([script_automation(text="x" * 11)])
        engine.trigger("script_rule")
        self.assertEqual(telnet.sent, [])
        trace = engine.traces("script_rule")[0]
        self.assertEqual(trace["result"], "error")
        self.assertEqual(trace["message"], "script text too long")

    def test_enabled_script_reaches_the_adopted_serial(self):
        telnet = FakeTelnet()
        engine, _ = build(telnet, allow_script_action=True)
        engine.load([script_automation(text="hello")])
        engine.trigger("script_rule")
        self.assertEqual(telnet.sent, [(SERIAL_HOST, SERIAL_PORT, "hello")])
        self.assertEqual(engine.traces("script_rule")[0]["result"], "finished")


class UnknownTypeTest(unittest.TestCase):
    def test_unknown_action_type_is_refused(self):
        automation = {"id": "odd", "actions": [{"action": "notify.phone", "data": {}}]}
        errors = validate(automation)
        self.assertTrue(any("unknown action" in e for e in errors), errors)

    def test_unsupported_action_type_is_refused(self):
        automation = {"id": "wait", "actions": [{"wait_template": "ready"}]}
        errors = validate(automation)
        self.assertTrue(any("not supported yet" in e for e in errors), errors)


class HttpTest(unittest.TestCase):
    def test_http_post_needs_http_or_https(self):
        automation = {
            "id": "hook",
            "actions": [{"action": "http_post", "data": {"url": "ftp://example.test/hook"}}],
        }
        errors = validate(automation)
        self.assertTrue(any("data.url: must be http or https" in e for e in errors), errors)

    def test_http_post_reaches_the_injected_client(self):
        telnet, http = FakeTelnet(), FakeHttp()
        engine, _ = build(telnet, http=http)
        engine.load([{"id": "hook", "actions": [{"action": "http_post", "data": {"url": HOOK_URL, "payload": {"x": 1}}}]}])
        engine.trigger("hook")
        self.assertEqual(http.posts, [(HOOK_URL, {"x": 1})])
        self.assertEqual(engine.traces("hook")[0]["result"], "finished")


class RunawayTest(unittest.TestCase):
    def test_self_triggering_automation_stops_at_max_depth(self):
        engine, _ = build(FakeTelnet(), max_depth=3)
        engine.load([loop_automation()])
        engine.trigger("loop")
        traces = engine.traces("loop")
        self.assertEqual(len(traces), 1)
        self.assertEqual(traces[0]["result"], "error")
        self.assertEqual(traces[0]["message"], "max automation depth reached")

    def test_trigger_chain_within_the_limit_runs(self):
        engine, device = build(FakeTelnet())
        engine.load(
            [
                {"id": "other", "actions": [{"action": "switch.turn_on", "target": {"entity_id": SWITCH_ENTITY}}]},
                {"id": "chain", "actions": [{"action": "automation.trigger", "target": {"entity_id": "automation.other"}}]},
            ]
        )
        engine.trigger("chain")
        self.assertEqual(device.outputs, [(MAC, 1, 1)])
        self.assertEqual(engine.traces("chain")[0]["result"], "finished")


if __name__ == "__main__":
    unittest.main()
