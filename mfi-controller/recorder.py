"""Compatibility recorder of the mFi Controller add-on.

Started by run.sh as a separate process (python3 /recorder.py, user mfi). When
recording is on, the controller moves to 16080 (inform, HTTP) and 16443 (web,
HTTPS); this program listens on the public ports 6080 and 6443 and forwards each
request unchanged to the controller and the answer back unchanged. Every
exchange is appended as one JSON line to <out>/<YYYY-MM-DD>.jsonl. Sensitive
headers and fields are replaced by REDACTED before the line is written.

Standard library only. Python 3.4: no f-strings, annotations, async or typing.
"""

import argparse
import base64
import http.client
import http.server
import json
import logging
import os
import socketserver
import ssl
import sys
import threading
import time
import urllib.parse

REDACTED = "REDACTED"
SENSITIVE_HEADER_NAMES = ("cookie", "set-cookie", "authorization")  # compared in lower case
SENSITIVE_KEY_PARTS = ("password", "passphrase", "token", "authkey", "x_password", "secret")  # case-insensitive substring
HOP_BY_HOP_HEADERS = (
    "connection", "keep-alive", "proxy-connection", "te", "trailer",
    "transfer-encoding", "upgrade", "content-length", "host",
)
SKIPPED_RESPONSE_HEADERS = HOP_BY_HOP_HEADERS + ("server", "date")
TIMEOUT_SECONDS = 130
LISTEN_HOST = "0.0.0.0"
INFORM_PORT = 6080
WEB_PORT = 6443

log = logging.getLogger("mfi-recorder")
_write_lock = threading.Lock()
_limit_logged = set()


def _is_sensitive_key(key):
    lowered = str(key).lower()
    for part in SENSITIVE_KEY_PARTS:
        if part in lowered:
            return True
    return False


def _header_value(headers, name):
    wanted = name.lower()
    for key, value in headers:
        if key.lower() == wanted:
            return value
    return None


def redact_headers(headers):
    """Return a new list of (name, value) pairs with sensitive values replaced."""
    out = []
    for name, value in headers:
        if name.lower() in SENSITIVE_HEADER_NAMES:
            out.append((name, REDACTED))
        else:
            out.append((name, value))
    return out


def redact_json_obj(obj):
    """Return a new JSON structure where sensitive keys hold REDACTED."""
    if isinstance(obj, dict):
        out = {}
        for key in obj:
            if _is_sensitive_key(key):
                out[key] = REDACTED
            else:
                out[key] = redact_json_obj(obj[key])
        return out
    if isinstance(obj, list):
        return [redact_json_obj(item) for item in obj]
    return obj


def redact_body(body, content_type):
    """Return body with sensitive JSON or form fields replaced; other bodies unchanged."""
    ctype = (content_type or "").lower()
    if "json" in ctype:
        try:
            obj = json.loads(body.decode("utf-8"))
        except ValueError:
            return body
        return json.dumps(redact_json_obj(obj), separators=(",", ":")).encode("utf-8")
    if "form-urlencoded" in ctype:
        try:
            text = body.decode("utf-8")
        except ValueError:
            return body
        pairs = urllib.parse.parse_qsl(text, keep_blank_values=True)
        redacted = [(key, REDACTED if _is_sensitive_key(key) else value) for key, value in pairs]
        return urllib.parse.urlencode(redacted).encode("utf-8")
    return body


def _file_size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _log_limit_once(day_file):
    if day_file in _limit_logged:
        return
    _limit_logged.add(day_file)
    log.warning("size limit reached for %s: no more lines are written for this day", os.path.basename(day_file))


def _b64(data):
    return base64.b64encode(data).decode("ascii")


def record_line(out_dir, port_label, client, method, path, req_headers, req_body, status,
                resp_headers, resp_body, resp_content_type, max_mb):
    """Append one JSON line for an exchange; return False when the day's size limit is reached."""
    now = time.time()
    port = int(port_label)
    limit_bytes = int(max_mb * 1024 * 1024)
    day_file = os.path.join(out_dir, time.strftime("%Y-%m-%d", time.localtime(now)) + ".jsonl")
    ctype = (resp_content_type or "").lower()
    if port == INFORM_PORT:
        stored = resp_body
        omitted = False
    elif "json" in ctype or "form" in ctype:
        stored = redact_body(resp_body, resp_content_type)
        omitted = False
    else:
        stored = b""
        omitted = True
    req_ctype = _header_value(req_headers, "Content-Type")
    if port == INFORM_PORT:
        req_stored = redact_body(req_body, req_ctype)
    else:
        req_lc = (req_ctype or "").lower()
        if "json" in req_lc or "x-www-form-urlencoded" in req_lc:
            req_stored = redact_body(req_body, req_ctype)
        else:
            req_stored = b""
    entry = {
        "t": int(now * 1000),
        "port": port,
        "client": client,
        "method": method,
        "path": path,
        "req_headers": redact_headers(req_headers),
        "req_body_b64": _b64(req_stored),
        "status": int(status),
        "resp_headers": redact_headers(resp_headers),
        "resp_body_b64": _b64(stored),
        "body_omitted": omitted,
    }
    if omitted:
        entry["resp_length"] = len(resp_body)
    line = json.dumps(entry) + "\n"
    with _write_lock:
        if _file_size(day_file) >= limit_bytes:
            _log_limit_once(day_file)
            return False
        fd = os.open(day_file, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a") as handle:
            handle.write(line)
    return True


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class ProxyHandler(http.server.BaseHTTPRequestHandler):
    server_version = "mfi-recorder"

    def do_GET(self):
        self._forward()

    do_POST = do_GET
    do_PUT = do_GET
    do_DELETE = do_GET

    def log_message(self, format, *args):
        log.debug(format, *args)

    def _forward(self):
        req_headers = list(self.headers.items())
        length = self._content_length()
        if length is None:
            log.warning("rejecting a request with a bad Content-Length from %s", self.client_address[0])
            self.close_connection = True
            self._send_empty(400)
            return
        req_body = self.rfile.read(length)
        try:
            status, resp_headers, resp_body = self._send_upstream(req_headers, req_body)
        except Exception as exc:
            log.error("controller unreachable (%s): answering 502", type(exc).__name__)
            self._send_empty(502)
            return
        self._send_back(status, resp_headers, resp_body)
        try:
            record_line(self.server.out_dir, self.server.port_label, self.client_address[0],
                        self.command, self.path, req_headers, req_body, status, resp_headers,
                        resp_body, _header_value(resp_headers, "Content-Type"), self.server.max_mb)
        except (OSError, ValueError) as exc:
            log.error("recording failed (%s)", type(exc).__name__)

    def _content_length(self):
        raw = self.headers.get("Content-Length")
        if not raw:
            return 0
        try:
            n = int(raw)
        except ValueError:
            return None
        if n < 0:
            return None
        return n

    def _send_upstream(self, req_headers, req_body):
        host, port = self.server.proxy_target
        if self.server.proxy_tls:
            conn = http.client.HTTPSConnection(host, port, timeout=TIMEOUT_SECONDS,
                                               context=self.server.upstream_context)
        else:
            conn = http.client.HTTPConnection(host, port, timeout=TIMEOUT_SECONDS)
        try:
            strip = set(HOP_BY_HOP_HEADERS)
            if self.server.port_label == WEB_PORT:
                strip.add("accept-encoding")
            headers = dict((name, value) for name, value in req_headers
                           if name.lower() not in strip)
            conn.request(self.command, self.path, body=req_body, headers=headers)
            resp = conn.getresponse()
            return resp.status, resp.getheaders(), resp.read()
        finally:
            conn.close()

    def _send_back(self, status, resp_headers, resp_body):
        self.send_response(status)
        for name, value in resp_headers:
            if name.lower() not in SKIPPED_RESPONSE_HEADERS:
                self.send_header(name, value)
        self.send_header("Content-Length", str(len(resp_body)))
        self.end_headers()
        self.wfile.write(resp_body)

    def _send_empty(self, status):
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()


def _upstream_context(target_host):
    if target_host == "127.0.0.1":
        context = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
        context.verify_mode = ssl.CERT_NONE
        return context
    return ssl.create_default_context()


def build_proxy_server(bind_host, listen_port, target_host, target_port, out_dir, port_label,
                       max_mb=200, use_tls=False, cert_file=None, key_file=None):
    """Return a bound server that forwards to target_host:target_port and records; not serving yet."""
    os.makedirs(out_dir, exist_ok=True)
    server = ThreadingHTTPServer((bind_host, int(listen_port)), ProxyHandler)
    try:
        server.proxy_target = (target_host, int(target_port))
        server.out_dir = out_dir
        server.port_label = int(port_label)
        server.max_mb = max_mb
        server.proxy_tls = server.port_label == WEB_PORT
        server.upstream_context = _upstream_context(target_host) if server.proxy_tls else None
        if use_tls:
            context = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
            context.load_cert_chain(cert_file, key_file)
            server.socket = context.wrap_socket(server.socket, server_side=True)
    except Exception:
        server.server_close()
        raise
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description="Records the traffic between mFi devices and the mFi Controller.")
    parser.add_argument("--inform-listen", type=int, default=INFORM_PORT, help="port the devices reach (default 6080)")
    parser.add_argument("--inform-target", type=int, default=16080, help="controller inform port (default 16080)")
    parser.add_argument("--https-listen", type=int, default=WEB_PORT, help="port of the web UI (default 6443)")
    parser.add_argument("--https-target", type=int, default=16443, help="controller web port (default 16443)")
    parser.add_argument("--cert", required=True, help="PEM certificate for the web port")
    parser.add_argument("--key", required=True, help="PEM key for the web port")
    parser.add_argument("--out", required=True, help="folder for the <date>.jsonl files")
    parser.add_argument("--max-mb", type=int, default=200, help="size limit of each day file in MB (default 200)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="[mfi-recorder] %(asctime)s %(levelname)s %(message)s")
    inform = build_proxy_server(LISTEN_HOST, args.inform_listen, "127.0.0.1", args.inform_target,
                                args.out, INFORM_PORT, args.max_mb)
    web = build_proxy_server(LISTEN_HOST, args.https_listen, "127.0.0.1", args.https_target,
                             args.out, WEB_PORT, args.max_mb, use_tls=True,
                             cert_file=args.cert, key_file=args.key)
    log.info("recording inform %d -> %d and web %d -> %d into %s",
             args.inform_listen, args.inform_target, args.https_listen, args.https_target, args.out)

    worker = threading.Thread(target=inform.serve_forever)
    worker.daemon = True
    worker.start()
    try:
        web.serve_forever()
    except KeyboardInterrupt:
        log.info("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
