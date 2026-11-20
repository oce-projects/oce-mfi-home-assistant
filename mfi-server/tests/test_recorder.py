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
import struct
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


class HostEchoController(http.server.BaseHTTPRequestHandler):
    """Stands in for the controller: records the Host headers it gets; /redirect answers 302 with a Location."""

    seen_hosts = []

    def do_POST(self):
        self.seen_hosts.extend(self.headers.get_all("Host") or [])
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "https://ha.example:6443/manage")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
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


class TestHostHeader(RecordedProxyTest):
    def setUp(self):
        super().setUp()
        HostEchoController.seen_hosts[:] = []

    def start_echo(self):
        echo = http.server.HTTPServer(("127.0.0.1", 0), HostEchoController)
        self.addCleanup(stop, echo, serve(echo))
        return echo.server_address[1]

    def test_host_header_is_forwarded_unchanged(self):
        port = self.start_proxy(self.start_echo())
        status, body = self.inform(port, {"Host": "ha.example:6080",
                                          "Content-Type": "application/octet-stream"})
        self.assertEqual(status, CONTROLLER_STATUS)
        self.assertEqual(body, CONTROLLER_BODY)
        self.assertEqual(HostEchoController.seen_hosts, ["ha.example:6080"])

    def test_redirect_location_is_passed_unchanged(self):
        port = self.start_proxy(self.start_echo())
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            conn.request("POST", "/redirect", body=b"", headers={"Host": "ha.example:6443"})
            resp = conn.getresponse()
            resp.read()
            status, location = resp.status, resp.getheader("Location")
        finally:
            conn.close()
        self.assertTrue(self.recorded.acquire(timeout=5), "record_line was not called")
        self.assertEqual(status, 302)
        self.assertEqual(location, "https://ha.example:6443/manage")
        self.assertEqual(HostEchoController.seen_hosts, ["ha.example:6443"])


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
        self.assertNotIn("host", recorder.HOP_BY_HOP_HEADERS)
        for name in ("host", "server", "date"):
            with self.subTest(name=name):
                self.assertIn(name, recorder.SKIPPED_RESPONSE_HEADERS)
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


UDP_SRC = "203.0.113.5"
UDP_DST = "198.51.100.7"
# address tuple of recvfrom on AF_PACKET: (ifname, protocol, packet type, hardware type, hardware address)
UDP_ADDR = ("eth0", 3, 0, 1, b"")


def ipv4_udp_frame(src_ip, dst_ip, src_port, dst_port, payload=b"", protocol=17,
                   ethertype=0x0800, frag=0, options=b""):
    """Build an Ethernet II frame with an IPv4 header (optional options) and a UDP header, by hand."""
    eth = bytes([0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 2]) + struct.pack(">H", ethertype)
    udp = struct.pack(">HHHH", src_port, dst_port, 8 + len(payload), 0) + payload
    ver_ihl = 0x40 | ((20 + len(options)) // 4)
    ip = struct.pack(">BBHHHBBH", ver_ihl, 0, 20 + len(options) + len(udp), 0, frag, 64, protocol, 0)
    ip += bytes(int(part) for part in src_ip.split("."))
    ip += bytes(int(part) for part in dst_ip.split("."))
    ip += options
    return eth + ip + udp


class TestUdpParse(unittest.TestCase):
    def test_ipv4_udp_frame_to_port_10001_is_decoded(self):
        frame = ipv4_udp_frame(UDP_SRC, UDP_DST, 40000, 10001, b"\x01\x00\x00\x00")
        self.assertEqual(recorder.parse_ipv4_udp(frame),
                         (UDP_SRC, 40000, UDP_DST, 10001, b"\x01\x00\x00\x00"))

    def test_empty_udp_payload_is_decoded(self):
        frame = ipv4_udp_frame(UDP_SRC, UDP_DST, 3478, 40000)
        self.assertEqual(recorder.parse_ipv4_udp(frame), (UDP_SRC, 3478, UDP_DST, 40000, b""))

    def test_tcp_frame_is_none(self):
        frame = ipv4_udp_frame(UDP_SRC, UDP_DST, 40000, 10001, b"x", protocol=6)
        self.assertIsNone(recorder.parse_ipv4_udp(frame))

    def test_non_ipv4_frame_is_none(self):
        frame = ipv4_udp_frame(UDP_SRC, UDP_DST, 40000, 10001, b"x", ethertype=0x0806)
        self.assertIsNone(recorder.parse_ipv4_udp(frame))

    def test_truncated_frames_are_none(self):
        frame = ipv4_udp_frame(UDP_SRC, UDP_DST, 40000, 10001, b"\x01\x00\x00\x00")
        self.assertIsNone(recorder.parse_ipv4_udp(frame[:20]))
        self.assertIsNone(recorder.parse_ipv4_udp(frame[:33]))
        self.assertIsNone(recorder.parse_ipv4_udp(frame[:40]))

    def test_port_filter(self):
        self.assertFalse(recorder.udp_port_wanted(53, 53))
        self.assertTrue(recorder.udp_port_wanted(10001, 40000))
        self.assertTrue(recorder.udp_port_wanted(40000, 3478))

    def test_udp_53_is_dropped_by_the_filter(self):
        parsed = recorder.parse_ipv4_udp(ipv4_udp_frame(UDP_SRC, UDP_DST, 53, 53, b"dns"))
        self.assertIsNotNone(parsed)
        self.assertFalse(recorder.udp_port_wanted(parsed[1], parsed[3]))

    def test_padding_after_the_udp_payload_is_trimmed(self):
        frame = ipv4_udp_frame(UDP_SRC, UDP_DST, 40000, 10001, b"\x01\x00\x00\x00") + b"\x00" * 14
        self.assertEqual(recorder.parse_ipv4_udp(frame),
                         (UDP_SRC, 40000, UDP_DST, 10001, b"\x01\x00\x00\x00"))

    def test_ip_fragment_after_the_first_is_none(self):
        frame = ipv4_udp_frame(UDP_SRC, UDP_DST, 40000, 10001, b"data", frag=0x0001)
        self.assertIsNone(recorder.parse_ipv4_udp(frame))

    def test_ipv4_header_options_are_skipped(self):
        frame = ipv4_udp_frame(UDP_SRC, UDP_DST, 40000, 10001, b"\x01\x00\x00\x00",
                               options=b"\x00\x00\x00\x00")
        self.assertEqual(recorder.parse_ipv4_udp(frame),
                         (UDP_SRC, 40000, UDP_DST, 10001, b"\x01\x00\x00\x00"))


class TestUdpCapture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_unavailable_socket_logs_one_line_and_returns(self):
        def refuse():
            raise PermissionError("operation not permitted")

        with self.assertLogs("mfi-recorder", level="WARNING") as logs:
            recorder.capture_udp(self.tmp, 200, open_socket=refuse)
        self.assertEqual(len(logs.records), 1)
        self.assertTrue(logs.records[0].getMessage().startswith("udp capture unavailable: "))

    def test_capture_drops_udp_53_and_keeps_discovery(self):
        sock = mock.Mock()
        sock.recvfrom.side_effect = [
            (ipv4_udp_frame(UDP_SRC, UDP_DST, 53, 53, b"dns"), UDP_ADDR),
            (ipv4_udp_frame(UDP_SRC, UDP_DST, 40000, 10001, b"\x01\x00\x00\x00"), UDP_ADDR),
            OSError("capture stopped by the test"),
        ]
        with self.assertLogs("mfi-recorder", level="ERROR"):
            recorder.capture_udp(self.tmp, 200, open_socket=lambda: sock)
        lines = read_lines(self.tmp)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["port"], "udp10001")
        sock.close.assert_called_once_with()

    def test_over_the_limit_nothing_is_written(self):
        path = day_file(self.tmp)
        with open(str(path), "w") as handle:
            handle.write("x" * 2000)
        self.assertFalse(recorder.record_udp_line(self.tmp, UDP_SRC, 40000, UDP_DST, 3478, b"\x88\x88", 0.001))
        self.assertEqual(path.stat().st_size, 2000)

    def test_under_the_limit_the_line_has_the_shared_keys(self):
        self.assertTrue(recorder.record_udp_line(self.tmp, UDP_SRC, 40000, UDP_DST, 10001,
                                                 b"\x01\x00\x00\x00", 1))
        self.assertTrue(recorder.record_udp_line(self.tmp, UDP_SRC, 40000, UDP_DST, 3478, b"\x88\x88", 1))
        lines = read_lines(self.tmp)
        self.assertEqual(len(lines), 2)
        first = lines[0]
        self.assertEqual(sorted(first), ["dst", "payload_b64", "port", "src", "time"])
        self.assertIsInstance(first["time"], int)
        self.assertEqual(first["port"], "udp10001")
        self.assertEqual(first["src"], "203.0.113.5:40000")
        self.assertEqual(first["dst"], "198.51.100.7:10001")
        self.assertEqual(base64.b64decode(first["payload_b64"]), b"\x01\x00\x00\x00")
        self.assertEqual(lines[1]["port"], "udp3478")
        self.assertEqual(lines[1]["dst"], "198.51.100.7:3478")
        self.assertEqual(base64.b64decode(lines[1]["payload_b64"]), b"\x88\x88")

    def test_write_error_is_logged_once(self):
        sock = mock.Mock()
        sock.recvfrom.side_effect = [
            (ipv4_udp_frame(UDP_SRC, UDP_DST, 40000, 10001, b"\x01\x00\x00\x00"), UDP_ADDR),
            (ipv4_udp_frame(UDP_SRC, UDP_DST, 40000, 3478, b"\x88\x88"), UDP_ADDR),
            OSError("capture stopped by the test"),
        ]
        with mock.patch.object(recorder, "record_udp_line", side_effect=OSError("disk full")):
            with self.assertLogs("mfi-recorder", level="ERROR") as logs:
                recorder.capture_udp(self.tmp, 200, open_socket=lambda: sock)
        failed = [r for r in logs.records if "udp recording failed" in r.getMessage()]
        self.assertEqual(len(failed), 1)


class TestFrameFilter(unittest.TestCase):
    def test_outgoing_copy_on_lo_is_skipped(self):
        self.assertFalse(recorder.frame_usable(("lo", 3, recorder.PACKET_OUTGOING, 772, b"")))

    def test_outgoing_frame_on_another_interface_is_kept(self):
        self.assertTrue(recorder.frame_usable(("eth0", 3, recorder.PACKET_OUTGOING, 1, b"")))

    def test_incoming_frame_on_lo_is_kept(self):
        self.assertTrue(recorder.frame_usable(("lo", 3, 0, 772, b"")))

    def test_ethernet_and_loopback_hardware_types_are_kept(self):
        self.assertTrue(recorder.frame_usable(("eth0", 3, 0, 1, b"")))
        self.assertTrue(recorder.frame_usable(("eth0", 3, 0, 772, b"")))

    def test_other_hardware_types_are_skipped(self):
        for hatype in (0, 2, 65534):
            with self.subTest(hatype=hatype):
                self.assertFalse(recorder.frame_usable(("eth0", 3, 0, hatype, b"")))

    def test_capture_writes_neither_outgoing_copies_nor_foreign_link_types(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        sock = mock.Mock()
        sock.recvfrom.side_effect = [
            (ipv4_udp_frame(UDP_SRC, UDP_DST, 40000, 10001, b"\x01\x00\x00\x00"),
             ("lo", 3, recorder.PACKET_OUTGOING, 772, b"")),
            (ipv4_udp_frame(UDP_SRC, UDP_DST, 40000, 10001, b"\x02\x00\x00\x00"),
             ("eth0", 3, 0, 65534, b"")),
            (ipv4_udp_frame(UDP_SRC, UDP_DST, 40000, 10001, b"\x03\x00\x00\x00"), UDP_ADDR),
            OSError("capture stopped by the test"),
        ]
        with self.assertLogs("mfi-recorder", level="ERROR"):
            recorder.capture_udp(tmp, 200, open_socket=lambda: sock)
        lines = read_lines(tmp)
        self.assertEqual(len(lines), 1)
        self.assertEqual(base64.b64decode(lines[0]["payload_b64"]), b"\x03\x00\x00\x00")


class FakeServer(object):
    def __init__(self, port_label, calls):
        self.port_label = port_label
        self.calls = calls

    def serve_forever(self, poll_interval=0.5):
        if self.port_label == recorder.WEB_PORT:
            raise KeyboardInterrupt

    def server_close(self):
        self.calls.append("close")


class FakePasswd(object):
    def __init__(self, uid, gid):
        self.pw_uid = uid
        self.pw_gid = gid


class TestMainOrder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.calls = []
        self.given = []
        self.capture_done = threading.Event()
        self.sock = mock.Mock()
        self.open_error = None
        self.drop_error = None

        def open_socket():
            self.calls.append("open")
            if self.open_error is not None:
                raise self.open_error
            return self.sock

        def build(*args, **kwargs):
            self.calls.append("build")
            return FakeServer(args[5], self.calls)

        def drop(name):
            self.calls.append("drop:" + name)
            if self.drop_error is not None:
                raise self.drop_error

        def capture(out_dir, max_mb, open_socket=None):
            self.given.append(open_socket())
            self.calls.append("capture")
            self.capture_done.set()

        for target, name, new in (
            (recorder, "open_capture_socket", open_socket),
            (recorder, "build_proxy_server", build),
            (recorder, "drop_privileges", drop),
            (recorder, "capture_udp", capture),
            (recorder.logging, "basicConfig", mock.Mock()),
        ):
            patcher = mock.patch.object(target, name, new)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_main(self, udp=True):
        argv = ["--cert", "cert.pem", "--key", "key.pem", "--out", self.tmp]
        if udp:
            argv.append("--udp-capture")
        return recorder.main(argv)

    def test_socket_opens_before_the_drop_and_capture_starts_after_it(self):
        self.assertEqual(self.run_main(), 0)
        self.assertTrue(self.capture_done.wait(5))
        self.assertEqual(self.calls, ["open", "build", "build", "drop:mfi", "capture"])
        self.assertEqual(self.given, [self.sock])

    def test_without_udp_capture_no_socket_is_opened(self):
        self.assertEqual(self.run_main(udp=False), 0)
        self.assertEqual(self.calls, ["build", "build", "drop:mfi"])

    def test_unavailable_socket_logs_one_warning_and_tcp_goes_on(self):
        self.open_error = PermissionError("operation not permitted")
        with self.assertLogs("mfi-recorder", level="WARNING") as logs:
            rc = self.run_main()
        self.assertEqual(rc, 0)
        messages = [r.getMessage() for r in logs.records if r.levelname == "WARNING"]
        self.assertEqual(messages, ["udp capture unavailable: operation not permitted"])
        self.assertEqual(self.calls, ["open", "build", "build", "drop:mfi"])

    def test_failed_drop_exits_with_1_and_starts_nothing(self):
        self.drop_error = RuntimeError("not root and not user mfi")
        with self.assertLogs("mfi-recorder", level="ERROR"):
            rc = self.run_main()
        self.assertEqual(rc, 1)
        self.assertEqual(self.calls, ["open", "build", "build", "drop:mfi", "close", "close"])


class TestDropPrivileges(unittest.TestCase):
    def test_root_drops_groups_group_and_user_in_order(self):
        state = {"uid": 0}
        calls = []
        names = []

        def getpwnam(name):
            names.append(name)
            return FakePasswd(500, 501)

        def setuid(uid):
            calls.append(("setuid", uid))
            state["uid"] = uid

        recorder.drop_privileges("mfi", getuid=lambda: state["uid"], getpwnam=getpwnam,
                                 setgroups=lambda groups: calls.append(("setgroups", list(groups))),
                                 setgid=lambda gid: calls.append(("setgid", gid)), setuid=setuid)
        self.assertEqual(names, ["mfi"])
        self.assertEqual(calls, [("setgroups", []), ("setgid", 501), ("setuid", 500)])

    def test_root_that_stays_root_raises(self):
        def nothing(*args):
            return None

        with self.assertRaises(RuntimeError):
            recorder.drop_privileges("mfi", getuid=lambda: 0, getpwnam=lambda name: FakePasswd(500, 500),
                                     setgroups=nothing, setgid=nothing, setuid=nothing)

    def test_already_the_user_does_nothing(self):
        def refuse(*args):
            raise AssertionError("must not change user")

        recorder.drop_privileges("mfi", getuid=lambda: 500, getpwnam=lambda name: FakePasswd(500, 500),
                                 setgroups=refuse, setgid=refuse, setuid=refuse)

    def test_another_user_raises_and_names_the_user(self):
        calls = []
        with self.assertRaises(RuntimeError) as ctx:
            recorder.drop_privileges("mfi", getuid=lambda: 1000, getpwnam=lambda name: FakePasswd(500, 500),
                                     setgroups=lambda groups: calls.append("setgroups"),
                                     setgid=lambda gid: calls.append("setgid"),
                                     setuid=lambda uid: calls.append("setuid"))
        self.assertIn("mfi", str(ctx.exception))
        self.assertEqual(calls, [])

    def test_unknown_user_raises_runtime_error(self):
        def missing(name):
            raise KeyError(name)

        def nothing(*args):
            return None

        with self.assertRaises(RuntimeError):
            recorder.drop_privileges("no-such-user", getuid=lambda: 0, getpwnam=missing,
                                     setgroups=nothing, setgid=nothing, setuid=nothing)

    def test_setgid_failure_stops_before_setuid(self):
        calls = []

        def setgid(gid):
            calls.append(("setgid", gid))
            raise PermissionError("operation not permitted")

        def setuid(uid):
            calls.append(("setuid", uid))

        with self.assertRaises(PermissionError):
            recorder.drop_privileges("mfi", getuid=lambda: 0,
                                     getpwnam=lambda name: FakePasswd(500, 501),
                                     setgroups=lambda groups: calls.append(("setgroups", list(groups))),
                                     setgid=setgid, setuid=setuid)
        self.assertEqual(calls, [("setgroups", []), ("setgid", 501)])

    def test_setgroups_failure_stops_before_setgid_and_setuid(self):
        calls = []

        def setgroups(groups):
            calls.append(("setgroups", list(groups)))
            raise PermissionError("operation not permitted")

        def setgid(gid):
            calls.append(("setgid", gid))

        def setuid(uid):
            calls.append(("setuid", uid))

        with self.assertRaises(PermissionError):
            recorder.drop_privileges("mfi", getuid=lambda: 0,
                                     getpwnam=lambda name: FakePasswd(500, 501),
                                     setgroups=setgroups, setgid=setgid, setuid=setuid)
        self.assertEqual(calls, [("setgroups", [])])


if __name__ == "__main__":
    unittest.main()
