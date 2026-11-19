"""Checks the compatibility recorder mfi-controller/recorder.py.

Run from the repository root:
    python3 -m unittest discover -s mfi-server/tests -t mfi-server -v

Standard library only; offline. Servers listen on 127.0.0.1 on free ports and
write into temporary folders. The recorder is loaded by path, as test_icons.py
does. A spy around record_line signals when a line is written, so a test does
not read the day file before the recorder has finished the exchange.
"""
import ast
import base64
import http.client
import http.server
import importlib.util
import json
import shutil
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]

_spec = importlib.util.spec_from_file_location("recorder", ROOT / "mfi-controller" / "recorder.py")
recorder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(recorder)

CONTROLLER_STATUS = 201
CONTROLLER_BODY = b"\x00\x01known-controller-bytes\xff"
INFORM_BODY = b"\x10\x20inform-request-bytes\xfe"
CLIENT = "127.0.0.1"


class FakeController(http.server.BaseHTTPRequestHandler):
    """Stands in for the controller: answers every POST with fixed bytes."""

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        self.send_response(CONTROLLER_STATUS)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(CONTROLLER_BODY)))
        self.end_headers()
        self.wfile.write(CONTROLLER_BODY)

    def log_message(self, fmt, *args):
        pass


def serve(server):
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05})
    thread.daemon = True
    thread.start()
    return thread


def stop(server, thread):
    server.shutdown()
    server.server_close()
    thread.join(5)


def free_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
    finally:
        sock.close()


def ask(port, method, path, body, headers):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        return resp.status, resp.read()
    finally:
        conn.close()


def day_file(folder):
    return Path(folder) / (time.strftime("%Y-%m-%d", time.localtime()) + ".jsonl")


def read_lines(folder):
    path = day_file(folder)
    if not path.exists():
        return []
    with open(str(path)) as handle:
        return [json.loads(line) for line in handle if line.strip()]


class TestRedact(unittest.TestCase):
    def test_sensitive_headers_are_replaced_and_others_kept(self):
        headers = [("Cookie", "x"), ("Set-Cookie", "y"), ("Authorization", "z"), ("Host", "h")]
        out = recorder.redact_headers(headers)
        self.assertEqual(out, [("Cookie", "REDACTED"), ("Set-Cookie", "REDACTED"),
                               ("Authorization", "REDACTED"), ("Host", "h")])
        self.assertEqual(headers[0], ("Cookie", "x"))

    def test_header_names_are_compared_in_lower_case(self):
        self.assertEqual(recorder.redact_headers([("cookie", "q"), ("AUTHORIZATION", "r")]),
                         [("cookie", "REDACTED"), ("AUTHORIZATION", "REDACTED")])

    def test_empty_header_list(self):
        self.assertEqual(recorder.redact_headers([]), [])

    def test_header_name_that_contains_a_secret_word_is_replaced(self):
        self.assertEqual(recorder.redact_headers([("X-Auth-Token", "abc"), ("X-Api-Secret", "s"), ("Host", "h")]),
                         [("X-Auth-Token", "REDACTED"), ("X-Api-Secret", "REDACTED"), ("Host", "h")])

    def test_json_sensitive_fields_are_replaced(self):
        body = recorder.redact_body(b'{"name":"a","x_password":"p","Token":"t"}', "application/json")
        self.assertEqual(json.loads(body.decode("utf-8")),
                         {"name": "a", "x_password": "REDACTED", "Token": "REDACTED"})

    def test_nested_json_and_lists(self):
        obj = {"outer": [{"AuthKey": "k", "ok": 1}], "info": {"secret": "s", "n": None}}
        self.assertEqual(recorder.redact_json_obj(obj),
                         {"outer": [{"AuthKey": "REDACTED", "ok": 1}], "info": {"secret": "REDACTED", "n": None}})

    def test_json_non_ascii_text_is_kept(self):
        body = recorder.redact_body('{"name":"\u00c0lba","token":"t"}'.encode("utf-8"), "application/json")
        self.assertEqual(json.loads(body.decode("utf-8")), {"name": "\u00c0lba", "token": "REDACTED"})

    def test_form_password_is_replaced(self):
        body = recorder.redact_body(b"user=a&password=p", "application/x-www-form-urlencoded")
        self.assertIn(b"user=a", body)
        self.assertIn(b"password=REDACTED", body)

    def test_blank_sensitive_form_field_is_still_replaced(self):
        body = recorder.redact_body(b"password=&user=a", "application/x-www-form-urlencoded")
        self.assertIn(b"password=REDACTED", body)

    def test_other_bodies_are_unchanged(self):
        raw = b"\x00\xffbinary password=p"
        self.assertEqual(recorder.redact_body(raw, "application/octet-stream"), raw)
        self.assertEqual(recorder.redact_body(raw, None), raw)
        bad_json = b'{"password": '
        self.assertEqual(recorder.redact_body(bad_json, "application/json"), bad_json)
        bad_form = b"\xff=1"
        self.assertEqual(recorder.redact_body(bad_form, "application/x-www-form-urlencoded"), bad_form)


class TestRecordLine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def record(self, port_label, resp_body, resp_ctype, req_headers=(), req_body=b"", max_mb=200):
        return recorder.record_line(self.tmp, port_label, CLIENT, "POST", "/x", list(req_headers),
                                    req_body, 200, [("Set-Cookie", "set-secret-value"), ("Server", "x")],
                                    resp_body, resp_ctype, max_mb)

    def test_6080_keeps_the_raw_body(self):
        raw = b"\x00\xffraw"
        self.assertTrue(self.record(6080, raw, None))
        entry = read_lines(self.tmp)[0]
        self.assertIsInstance(entry["t"], int)
        self.assertEqual(entry["port"], 6080)
        self.assertEqual(base64.b64decode(entry["resp_body_b64"]), raw)
        self.assertFalse(entry["body_omitted"])
        self.assertNotIn("resp_length", entry)
        self.assertIn(["Set-Cookie", "REDACTED"], entry["resp_headers"])

    def test_6443_html_body_is_omitted_and_length_kept(self):
        page = b"<html>page</html>"
        self.assertTrue(self.record(6443, page, "text/html"))
        entry = read_lines(self.tmp)[0]
        self.assertEqual(entry["port"], 6443)
        self.assertTrue(entry["body_omitted"])
        self.assertEqual(entry["resp_length"], len(page))
        self.assertEqual(entry["resp_body_b64"], "")

    def test_6443_json_body_is_kept_and_redacted(self):
        self.assertTrue(self.record(6443, b'{"name":"a","password":"p"}', "application/json"))
        entry = read_lines(self.tmp)[0]
        self.assertFalse(entry["body_omitted"])
        self.assertNotIn("resp_length", entry)
        self.assertEqual(json.loads(base64.b64decode(entry["resp_body_b64"]).decode("utf-8")),
                         {"name": "a", "password": "REDACTED"})

    def test_6443_form_body_is_kept_and_redacted(self):
        self.assertTrue(self.record(6443, b"user=a&passphrase=q", "application/x-www-form-urlencoded"))
        entry = read_lines(self.tmp)[0]
        self.assertFalse(entry["body_omitted"])
        self.assertIn(b"passphrase=REDACTED", base64.b64decode(entry["resp_body_b64"]))

    def test_secrets_are_not_written(self):
        self.record(6080, b"ok", "application/octet-stream",
                    req_headers=[("Cookie", "cookie-secret-value"), ("Content-Type", "application/json")],
                    req_body=b'{"authkey":"key-secret-value"}')
        with open(str(day_file(self.tmp))) as handle:
            text = handle.read()
        for secret in ("cookie-secret-value", "key-secret-value", "set-secret-value"):
            self.assertNotIn(secret, text)
        entry = read_lines(self.tmp)[0]
        self.assertEqual(json.loads(base64.b64decode(entry["req_body_b64"]).decode("utf-8")),
                         {"authkey": "REDACTED"})

    def test_6443_binary_request_body_is_omitted(self):
        recorder.record_line(
            self.tmp, 6443, CLIENT, "POST", "/upload",
            [("Content-Type", "multipart/form-data; boundary=x")], b"device-key-bytes",
            200, [("Content-Type", "application/json")], b'{"ok":1}', "application/json", 200)
        entry = read_lines(self.tmp)[0]
        self.assertEqual(entry["req_body_b64"], "")
        with open(str(day_file(self.tmp))) as handle:
            self.assertNotIn("device-key-bytes", handle.read())

    def test_6443_malformed_json_response_is_omitted(self):
        self.assertTrue(self.record(6443, b'{"password":"malformed-secret", bad', "application/json"))
        entry = read_lines(self.tmp)[0]
        self.assertTrue(entry["body_omitted"])
        self.assertEqual(entry["resp_body_b64"], "")
        self.assertEqual(entry["resp_length"], len(b'{"password":"malformed-secret", bad'))
        with open(str(day_file(self.tmp))) as handle:
            self.assertNotIn("malformed-secret", handle.read())

    def test_6443_multipart_response_is_omitted(self):
        self.assertTrue(self.record(6443, b'{"password":"mp-secret"}', "multipart/form-data; boundary=x"))
        entry = read_lines(self.tmp)[0]
        self.assertTrue(entry["body_omitted"])
        self.assertEqual(entry["resp_body_b64"], "")
        with open(str(day_file(self.tmp))) as handle:
            self.assertNotIn("mp-secret", handle.read())

    def test_sensitive_query_parameters_in_the_path_are_redacted(self):
        recorder.record_line(self.tmp, 6080, CLIENT, "GET", "/api/x?token=leak-token&keep=1", [],
                             b"", 200, [], b"ok", None, 200)
        entry = read_lines(self.tmp)[0]
        self.assertEqual(entry["path"], "/api/x?token=REDACTED&keep=1")
        with open(str(day_file(self.tmp))) as handle:
            self.assertNotIn("leak-token", handle.read())

    def test_size_limit_refuses_the_line_and_returns_false(self):
        path = day_file(self.tmp)
        with open(str(path), "w") as handle:
            handle.write("x" * 2000)
        self.assertFalse(self.record(6080, b"ok", None, max_mb=0.001))
        self.assertEqual(path.stat().st_size, 2000)

    def test_below_the_size_limit_the_line_is_written(self):
        path = day_file(self.tmp)
        with open(str(path), "w") as handle:
            handle.write("x" * 2000)
        self.assertTrue(self.record(6080, b"ok", None, max_mb=1))
        self.assertGreater(path.stat().st_size, 2000)


class RecordedProxyTest(unittest.TestCase):
    """Base class: a temporary folder, a spy on record_line, and helpers to start servers."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.recorded = threading.Semaphore(0)
        original = recorder.record_line

        def spy(*args, **kwargs):
            try:
                return original(*args, **kwargs)
            finally:
                self.recorded.release()

        patcher = mock.patch.object(recorder, "record_line", spy)
        patcher.start()
        self.addCleanup(patcher.stop)

    def start_controller(self):
        controller = http.server.HTTPServer(("127.0.0.1", 0), FakeController)
        self.addCleanup(stop, controller, serve(controller))
        return controller.server_address[1]

    def start_proxy(self, target_port, max_mb=200):
        proxy = recorder.build_proxy_server("127.0.0.1", 0, "127.0.0.1", target_port, self.tmp, 6080,
                                            max_mb=max_mb)
        self.addCleanup(stop, proxy, serve(proxy))
        return proxy.server_address[1]

    def inform(self, port, headers=None):
        """One inform request through the proxy; waits until its exchange is recorded."""
        if headers is None:
            headers = {"Content-Type": "application/octet-stream"}
        status, body = ask(port, "POST", "/inform", INFORM_BODY, headers)
        self.assertTrue(self.recorded.acquire(timeout=5), "record_line was not called")
        return status, body


class TestInformProxy(RecordedProxyTest):
    def test_answer_is_identical_and_the_line_is_written(self):
        port = self.start_proxy(self.start_controller())
        status, body = self.inform(port, {"Cookie": "session=cookie-secret",
                                          "Content-Type": "application/octet-stream"})
        self.assertEqual(status, CONTROLLER_STATUS)
        self.assertEqual(body, CONTROLLER_BODY)

        lines = read_lines(self.tmp)
        self.assertEqual(len(lines), 1)
        entry = lines[0]
        for key in ("t", "port", "client", "method", "path", "req_headers", "req_body_b64", "status",
                    "resp_headers", "resp_body_b64", "body_omitted"):
            self.assertIn(key, entry)
        self.assertIsInstance(entry["t"], int)
        self.assertEqual(entry["port"], 6080)
        self.assertEqual(entry["client"], CLIENT)
        self.assertEqual(entry["method"], "POST")
        self.assertEqual(entry["path"], "/inform")
        self.assertIn(["Cookie", "REDACTED"], entry["req_headers"])
        self.assertEqual(base64.b64decode(entry["req_body_b64"]), INFORM_BODY)
        self.assertEqual(entry["status"], CONTROLLER_STATUS)
        self.assertIn(["Content-Type", "application/octet-stream"], entry["resp_headers"])
        self.assertEqual(base64.b64decode(entry["resp_body_b64"]), CONTROLLER_BODY)
        self.assertFalse(entry["body_omitted"])
        self.assertNotIn("cookie-secret", json.dumps(entry))


class TestControllerDown(RecordedProxyTest):
    def test_502_then_the_proxy_still_serves(self):
        target = free_port()
        port = self.start_proxy(target)
        status, _ = ask(port, "POST", "/inform", INFORM_BODY, {})
        self.assertEqual(status, 502)
        status, _ = ask(port, "POST", "/inform", INFORM_BODY, {})
        self.assertEqual(status, 502)

        controller = http.server.HTTPServer(("127.0.0.1", target), FakeController)
        self.addCleanup(stop, controller, serve(controller))
        status, body = self.inform(port)
        self.assertEqual(status, CONTROLLER_STATUS)
        self.assertEqual(body, CONTROLLER_BODY)


class TestSizeLimit(RecordedProxyTest):
    def test_zero_limit_forwards_and_writes_nothing(self):
        port = self.start_proxy(self.start_controller(), max_mb=0)
        for _ in range(2):
            status, body = self.inform(port)
            self.assertEqual(status, CONTROLLER_STATUS)
            self.assertEqual(body, CONTROLLER_BODY)
        self.assertEqual(read_lines(self.tmp), [])

    def test_small_limit_stops_the_growth_and_keeps_forwarding(self):
        limit = int(0.001 * 1024 * 1024)
        port = self.start_proxy(self.start_controller(), max_mb=0.001)
        for _ in range(20):
            status, body = self.inform(port)
            self.assertEqual(status, CONTROLLER_STATUS)
            self.assertEqual(body, CONTROLLER_BODY)
        size = day_file(self.tmp).stat().st_size
        self.assertGreaterEqual(size, limit)

        status, body = self.inform(port)
        self.assertEqual(status, CONTROLLER_STATUS)
        self.assertEqual(body, CONTROLLER_BODY)
        self.assertEqual(day_file(self.tmp).stat().st_size, size)


class TestApi(unittest.TestCase):
    def test_public_names_match_the_contract(self):
        self.assertEqual(recorder.REDACTED, "REDACTED")
        self.assertEqual(recorder.SENSITIVE_HEADER_NAMES, ("cookie", "set-cookie", "authorization"))
        self.assertEqual(recorder.SENSITIVE_KEY_PARTS,
                         ("password", "passphrase", "token", "authkey", "x_password", "secret"))
        for name in ("redact_headers", "redact_json_obj", "redact_body", "record_line", "build_proxy_server", "main"):
            with self.subTest(name=name):
                self.assertTrue(callable(getattr(recorder, name)))
        self.assertTrue(issubclass(recorder.ThreadingHTTPServer, http.server.HTTPServer))


class TestPython34Subset(unittest.TestCase):
    """Scans the source of recorder.py: no syntax or modules newer than Python 3.4."""

    def setUp(self):
        self.source = (ROOT / "mfi-controller" / "recorder.py").read_text(encoding="utf-8")
        self.tree = ast.parse(self.source)

    def test_no_newer_syntax_nodes(self):
        names = ("JoinedStr", "AnnAssign", "NamedExpr", "AsyncFunctionDef", "AsyncFor", "AsyncWith", "Await")
        banned = tuple(getattr(ast, name) for name in names if hasattr(ast, name))
        found = [type(node).__name__ for node in ast.walk(self.tree) if isinstance(node, banned)]
        self.assertEqual(found, [])

    def test_no_annotations(self):
        problems = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.arg) and node.annotation is not None:
                problems.append("argument %s" % node.arg)
            if isinstance(node, ast.FunctionDef) and node.returns is not None:
                problems.append("return of %s" % node.name)
        self.assertEqual(problems, [])

    def test_no_banned_modules_or_calls(self):
        modules = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules.add((node.module or "").split(".")[0])
                if node.module == "subprocess":
                    self.assertNotIn("run", [alias.name for alias in node.names])
        self.assertFalse(modules & {"__future__", "secrets", "typing"}, modules)
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Attribute):
                self.assertNotIn(node.attr, ("read_text", "write_text"))
                if node.attr == "run":
                    self.assertFalse(isinstance(node.value, ast.Name) and node.value.id == "subprocess")

    def test_no_version_header(self):
        self.assertNotIn("# Version:", self.source)


if __name__ == "__main__":
    unittest.main()
