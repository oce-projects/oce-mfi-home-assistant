"""Compatibility recorder of the mFi Controller add-on.

Started by run.sh as a separate process (python3 /recorder.py). It starts as root
only to open the raw capture socket, then keeps running as user mfi (--user). When
recording is on, the controller moves to 16080 (inform, HTTP) and 16443 (web,
HTTPS); this program listens on the public ports 6080 and 6443 and forwards each
request unchanged to the controller and the answer back unchanged. Every
exchange is appended as one JSON line to <out>/<YYYY-MM-DD>.jsonl. Sensitive
headers and fields are replaced by REDACTED before the line is written.
With --udp-capture the program also listens passively (raw socket, never answers)
to UDP ports 10001 and 3478 and appends those packets to the same day file.

Standard library only. Python 3.4: no f-strings, annotations, async or typing.
"""

import argparse
import base64
import http.client
import http.server
import json
import logging
import os
import pwd
import socket
import socketserver
import ssl
import struct
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
UDP_PORTS = (10001, 3478)
ETH_P_ALL = 0x0003
ETH_HEADER_LEN = 14
ETHERTYPE_IPV4 = 0x0800
IPV4_MIN_HEADER_LEN = 20
IPPROTO_UDP = 17
UDP_HEADER_LEN = 8
PACKET_OUTGOING = 4  # packet type of a copy of an outgoing frame (linux/if_packet.h)
ARPHRD_ETHER = 1  # hardware type Ethernet (linux/if_arp.h)
ARPHRD_LOOPBACK = 772  # hardware type loopback (linux/if_arp.h)
RECORDER_USER = "mfi"

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
        if name.lower() in SENSITIVE_HEADER_NAMES or _is_sensitive_key(name):
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


def _redact_path(path):
    """Return path with the values of sensitive query parameters replaced by REDACTED."""
    if "?" not in path:
        return path
    base, _, query = path.partition("?")
    pairs = urllib.parse.parse_qsl(query, keep_blank_values=True)
    if not any(_is_sensitive_key(key) for key, _ in pairs):
        return path
    redacted = [(key, REDACTED if _is_sensitive_key(key) else value) for key, value in pairs]
    return base + "?" + urllib.parse.urlencode(redacted)


def _web_body(body, content_type):
    """Return (stored_bytes, omitted) for a web (6443) body.

    A decodable JSON or x-www-form-urlencoded body is redacted and kept; any other
    body - multipart, binary, or JSON/form that does not decode - is dropped
    (b"", True) so a secret in a malformed body is never written to the raw.
    """
    lc = (content_type or "").lower()
    if "json" in lc:
        try:
            json.loads(body.decode("utf-8"))
        except ValueError:
            return b"", True
        return redact_body(body, content_type), False
    if "x-www-form-urlencoded" in lc:
        try:
            body.decode("utf-8")
        except ValueError:
            return b"", True
        return redact_body(body, content_type), False
    return b"", True


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
    if port == INFORM_PORT:
        stored = resp_body
        omitted = False
    else:
        stored, omitted = _web_body(resp_body, resp_content_type)
    req_ctype = _header_value(req_headers, "Content-Type")
    if port == INFORM_PORT:
        req_stored = redact_body(req_body, req_ctype)
    else:
        req_stored = _web_body(req_body, req_ctype)[0]
    entry = {
        "t": int(now * 1000),
        "port": port,
        "client": client,
        "method": method,
        "path": _redact_path(path),
        "req_headers": redact_headers(req_headers),
        "req_body_b64": _b64(req_stored),
        "status": int(status),
        "resp_headers": redact_headers(resp_headers),
        "resp_body_b64": _b64(stored),
        "body_omitted": omitted,
    }
    if omitted:
        entry["resp_length"] = len(resp_body)
    return _append_entry(out_dir, now, entry, max_mb)


def _append_entry(out_dir, now, entry, max_mb):
    """Append one JSON line to the day file of now; return False when the day's size limit is reached."""
    limit_bytes = int(max_mb * 1024 * 1024)
    day_file = os.path.join(out_dir, time.strftime("%Y-%m-%d", time.localtime(now)) + ".jsonl")
    line = json.dumps(entry) + "\n"
    with _write_lock:
        if _file_size(day_file) >= limit_bytes:
            _log_limit_once(day_file)
            return False
        fd = os.open(day_file, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a") as handle:
            handle.write(line)
    return True


def udp_port_wanted(src_port, dst_port):
    """True when a UDP packet has port 10001 or 3478 as source or destination."""
    return src_port in UDP_PORTS or dst_port in UDP_PORTS


def _dotted(raw):
    """Format 4 raw bytes as a dotted IPv4 address."""
    return "%d.%d.%d.%d" % tuple(raw)


def parse_ipv4_udp(frame):
    """Return (src_ip, src_port, dst_ip, dst_port, payload) of an Ethernet II frame with IPv4 and UDP, else None."""
    if len(frame) < ETH_HEADER_LEN + IPV4_MIN_HEADER_LEN:
        return None
    if struct.unpack(">H", frame[12:14])[0] != ETHERTYPE_IPV4:
        return None
    ip = ETH_HEADER_LEN
    if frame[ip] >> 4 != 4:
        return None
    if frame[ip + 9] != IPPROTO_UDP:
        return None
    ihl = (frame[ip] & 0x0F) * 4
    if ihl < IPV4_MIN_HEADER_LEN:
        return None
    frag = struct.unpack(">H", frame[ip + 6:ip + 8])[0]
    if frag & 0x1FFF:
        return None
    udp = ip + ihl
    if len(frame) < udp + UDP_HEADER_LEN:
        return None
    src_port, dst_port = struct.unpack(">HH", frame[udp:udp + 4])
    udp_len = struct.unpack(">H", frame[udp + 4:udp + 6])[0]
    if udp_len < UDP_HEADER_LEN:
        return None
    payload = frame[udp + UDP_HEADER_LEN:udp + udp_len]
    return (_dotted(frame[ip + 12:ip + 16]), src_port, _dotted(frame[ip + 16:ip + 20]), dst_port,
            payload)


def record_udp_line(out_dir, src_ip, src_port, dst_ip, dst_port, payload, max_mb):
    """Append one UDP line in the shared format; return False when the day's size limit is reached."""
    now = time.time()
    label = "udp10001" if 10001 in (src_port, dst_port) else "udp3478"
    entry = {
        "time": int(now * 1000),
        "port": label,
        "src": "%s:%d" % (src_ip, src_port),
        "dst": "%s:%d" % (dst_ip, dst_port),
        "payload_b64": _b64(payload),
    }
    return _append_entry(out_dir, now, entry, max_mb)


def open_capture_socket():
    """Return a raw AF_PACKET socket that receives every Ethernet frame; raises OSError when not allowed."""
    return socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ETH_P_ALL))


def frame_usable(address):
    """True when a captured frame is parsed: not an outgoing copy on lo, and Ethernet or loopback link type.

    address is the tuple of recvfrom on AF_PACKET: (ifname, protocol, packet type, hardware type, hardware address).
    UNVERIFIED on a device: the field order follows the Python socket documentation; this filter is not
    tested on Home Assistant OS.
    """
    ifname, pkttype, hatype = address[0], address[2], address[3]
    if pkttype == PACKET_OUTGOING and ifname == "lo":
        return False
    return hatype in (ARPHRD_ETHER, ARPHRD_LOOPBACK)


def drop_privileges(name, getuid=os.getuid, getpwnam=pwd.getpwnam, setgroups=os.setgroups,
                    setgid=os.setgid, setuid=os.setuid):
    """Change from root to user name; a process that is not root must already be that user.

    Called after the raw socket is open: the capability to open it is lost on the change of user.
    Raises RuntimeError when the user does not exist, when the change does not take effect, or
    when the process is neither root nor that user.
    """
    try:
        entry = getpwnam(name)
    except KeyError:
        raise RuntimeError("user %s does not exist" % name)
    current = getuid()
    if current == 0:
        setgroups([])
        setgid(entry.pw_gid)
        setuid(entry.pw_uid)
        if getuid() == 0:
            raise RuntimeError("still root after the change to user %s" % name)
        return
    if current == entry.pw_uid:
        return
    raise RuntimeError("not root and not user %s (uid %d)" % (name, current))


def capture_udp(out_dir, max_mb, open_socket=None):
    """Listen passively to UDP 10001 and 3478 and record those packets; never answers.

    When the socket cannot be opened it logs one warning and returns, so TCP
    recording keeps working.
    """
    opener = open_socket or open_capture_socket
    try:
        sock = opener()
    except OSError as exc:
        log.warning("udp capture unavailable: %s", exc)
        return
    logged_write_error = False
    try:
        while True:
            try:
                frame, address = sock.recvfrom(65535)
            except OSError as exc:
                log.error("udp capture stopped: %s", exc)
                return
            if not frame_usable(address):
                continue
            parsed = parse_ipv4_udp(frame)
            if parsed is None:
                continue
            src_ip, src_port, dst_ip, dst_port, payload = parsed
            if not udp_port_wanted(src_port, dst_port):
                continue
            try:
                record_udp_line(out_dir, src_ip, src_port, dst_ip, dst_port, payload, max_mb)
            except OSError as exc:
                if not logged_write_error:
                    log.error("udp recording failed (%s)", type(exc).__name__)
                    logged_write_error = True
    finally:
        sock.close()


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
        context.options |= ssl.OP_NO_SSLv2 | ssl.OP_NO_SSLv3
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
            context.options |= ssl.OP_NO_SSLv2 | ssl.OP_NO_SSLv3
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
    parser.add_argument("--udp-capture", action="store_true",
                        help="passively record UDP ports 10001 and 3478 (needs NET_RAW)")
    parser.add_argument("--user", default=RECORDER_USER,
                        help="user the recorder runs as after the capture socket is open (default mfi)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="[mfi-recorder] %(asctime)s %(levelname)s %(message)s")
    capture_socket = None
    if args.udp_capture:
        # Opened while still root: a change of user takes away the right to open a raw socket.
        try:
            capture_socket = open_capture_socket()
        except OSError as exc:
            log.warning("udp capture unavailable: %s", exc)
    inform = build_proxy_server(LISTEN_HOST, args.inform_listen, "127.0.0.1", args.inform_target,
                                args.out, INFORM_PORT, args.max_mb)
    web = build_proxy_server(LISTEN_HOST, args.https_listen, "127.0.0.1", args.https_target,
                             args.out, WEB_PORT, args.max_mb, use_tls=True,
                             cert_file=args.cert, key_file=args.key)
    try:
        drop_privileges(args.user)
    except (RuntimeError, OSError) as exc:
        log.error("cannot run as user %s: %s", args.user, exc)
        inform.server_close()
        web.server_close()
        if capture_socket is not None:
            capture_socket.close()
        return 1
    log.info("recording inform %d -> %d and web %d -> %d into %s",
             args.inform_listen, args.inform_target, args.https_listen, args.https_target, args.out)

    if capture_socket is not None:
        udp_worker = threading.Thread(target=capture_udp, args=(args.out, args.max_mb, lambda: capture_socket))
        udp_worker.daemon = True
        udp_worker.start()

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
