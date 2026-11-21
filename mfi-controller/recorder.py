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
With --tcp-capture PORT it also rebuilds the HTTP exchanges of the inform port from
the passively captured TCP segments (same raw socket, never answers, never injects
packets) and appends them as lines of port 6080. Both captures are off by default.

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
# "host" is not hop-by-hop: the request keeps the Host of the client, so the controller builds its redirects with it.
HOP_BY_HOP_HEADERS = (
    "connection", "keep-alive", "proxy-connection", "te", "trailer",
    "transfer-encoding", "upgrade", "content-length",
)
SKIPPED_RESPONSE_HEADERS = HOP_BY_HOP_HEADERS + ("server", "date", "host")
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
IPPROTO_TCP = 6
TCP_FIN = 0x01
TCP_SYN = 0x02
TCP_RST = 0x04
TCP_MIN_HEADER_LEN = 20
TCP_SEQ_MOD = 2 ** 32
TCP_MAX_BYTES = 1048576  # bytes kept in memory per connection: both directions and waiting segments
TCP_MAX_FLOWS = 256
TCP_IDLE_SECONDS = 120
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


def parse_ipv4_tcp(frame):
    """Return (src_ip, src_port, dst_ip, dst_port, seq, flags, payload) of an Ethernet II frame with IPv4 and TCP, else None."""
    if len(frame) < ETH_HEADER_LEN + IPV4_MIN_HEADER_LEN:
        return None
    if struct.unpack(">H", frame[12:14])[0] != ETHERTYPE_IPV4:
        return None
    ip = ETH_HEADER_LEN
    if frame[ip] >> 4 != 4:
        return None
    ihl = (frame[ip] & 0x0F) * 4
    if ihl < IPV4_MIN_HEADER_LEN:
        return None
    if frame[ip + 9] != IPPROTO_TCP:
        return None
    frag = struct.unpack(">H", frame[ip + 6:ip + 8])[0]
    if frag & 0x1FFF:
        return None
    total_length = struct.unpack(">H", frame[ip + 2:ip + 4])[0]
    tcp = ip + ihl
    if len(frame) < tcp + TCP_MIN_HEADER_LEN:
        return None
    data_offset = (frame[tcp + 12] >> 4) * 4
    if data_offset < TCP_MIN_HEADER_LEN or tcp + data_offset > ip + total_length or ip + total_length > len(frame):
        return None
    src_port, dst_port = struct.unpack(">HH", frame[tcp:tcp + 4])
    seq = struct.unpack(">I", frame[tcp + 4:tcp + 8])[0]
    flags = frame[tcp + 13]
    payload = frame[tcp + data_offset:ip + total_length]
    return (_dotted(frame[ip + 12:ip + 16]), src_port, _dotted(frame[ip + 16:ip + 20]), dst_port,
            seq, flags, payload)


def _check_start_line(start_line, is_request):
    """Raise ValueError when the first line of an HTTP message is not a request or a status line."""
    parts = start_line.split(" ")
    if is_request:
        if len(parts) != 3 or not parts[0] or not parts[1]:
            raise ValueError("bad request line")
    elif not start_line.startswith("HTTP/") or len(parts) < 2 or not parts[1].isdigit():
        raise ValueError("bad status line")


def _decode_chunked(data):
    """Return (body, consumed) of a chunked body, None when it is not complete; ValueError on a bad chunk."""
    chunks = []
    pos = 0
    while True:
        line_end = data.find(b"\r\n", pos)
        if line_end == -1:
            return None
        try:
            size = int(data[pos:line_end].split(b";", 1)[0].strip(), 16)
        except ValueError:
            raise ValueError("bad chunk size")
        if size < 0:
            raise ValueError("negative chunk size")
        pos = line_end + 2
        if size == 0:
            while True:
                end = data.find(b"\r\n", pos)
                if end == -1:
                    return None
                if end == pos:
                    return b"".join(chunks), end + 2
                pos = end + 2
        if len(data) < pos + size + 2:
            return None
        if data[pos + size:pos + size + 2] != b"\r\n":
            raise ValueError("bad chunk end")
        chunks.append(data[pos:pos + size])
        pos += size + 2


def parse_http_message(data, is_request, closed=False):
    """Return (start_line, headers, body, consumed) of the first HTTP message in data, None when it is not complete.

    Raises ValueError when a line or a Content-Length is not valid. closed means the connection has
    ended, so an answer without a length runs to the end of data.
    """
    head_end = data.find(b"\r\n\r\n")
    if head_end == -1:
        return None
    lines = data[:head_end].split(b"\r\n")
    start_line = lines[0].decode("latin-1")
    _check_start_line(start_line, is_request)
    headers = []
    for raw in lines[1:]:
        name, sep, value = raw.partition(b":")
        if not sep or not name.strip():
            raise ValueError("bad header line")
        headers.append((name.decode("latin-1").strip(), value.decode("latin-1").strip()))
    pos = head_end + 4
    rest = data[pos:]
    transfer = _header_value(headers, "Transfer-Encoding")
    if transfer is not None and "chunked" in transfer.lower():
        decoded = _decode_chunked(rest)
        if decoded is None:
            return None
        body, used = decoded
        return start_line, headers, body, pos + used
    raw_length = _header_value(headers, "Content-Length")
    if raw_length is not None:
        if not raw_length.isdigit():
            raise ValueError("non-numeric Content-Length")
        length = int(raw_length)
        if len(rest) < length:
            return None
        return start_line, headers, rest[:length], pos + length
    if is_request:
        return start_line, headers, b"", pos
    if not closed:
        return None
    return start_line, headers, rest, len(data)


def _seq_delta(a, b):
    """Distance from b to a in TCP sequence numbers, which wrap at 2**32; negative when a comes before b."""
    return ((a - b + 2 ** 31) % TCP_SEQ_MOD) - 2 ** 31


class _TcpStream:
    """One direction of a TCP connection: the joined bytes and the segments that wait for a gap."""

    def __init__(self):
        self.next_seq = None
        self.buffer = b""
        self.pending = {}

    def size(self):
        return len(self.buffer) + sum(len(chunk) for chunk in self.pending.values())

    def add(self, seq, payload):
        if self.next_seq is None:
            self.next_seq = seq
        delta = _seq_delta(seq, self.next_seq)
        if delta == 0:
            self._append(payload)
            while self.next_seq in self.pending:
                self._append(self.pending.pop(self.next_seq))
        elif delta > 0:
            self.pending[seq] = payload
        elif -delta < len(payload):
            self._append(payload[-delta:])

    def _append(self, chunk):
        self.buffer += chunk
        self.next_seq = (self.next_seq + len(chunk)) % TCP_SEQ_MOD


class _TcpFlow:
    """State of one connection to the inform port: last packet time, closed flag and both directions."""

    def __init__(self, now):
        self.last = now
        self.closed = False
        self.to_server = _TcpStream()
        self.to_client = _TcpStream()

    def size(self):
        return self.to_server.size() + self.to_client.size()


class TcpInformAssembler:
    """Rebuilds the HTTP exchanges of the inform port from passively captured TCP segments; never answers.

    Every complete request and answer is written with record_line, as the proxy does. Connections from
    127.x are ignored: that is the proxy forwarding to the controller, already recorded by the proxy.
    """

    def __init__(self, out_dir, server_port, max_mb, clock=time.time):
        self.out_dir = out_dir
        self.server_port = int(server_port)
        self.max_mb = max_mb
        self.clock = clock
        self.flows = {}

    def feed(self, src_ip, src_port, dst_ip, dst_port, seq, flags, payload):
        """Add one captured TCP segment; writes the exchanges that it completes."""
        now = self.clock()
        self._expire(now)
        if dst_port == self.server_port:
            to_server = True
            client_ip, client_port, server_ip = src_ip, src_port, dst_ip
        elif src_port == self.server_port:
            to_server = False
            client_ip, client_port, server_ip = dst_ip, dst_port, src_ip
        else:
            return
        if client_ip.startswith("127."):
            return
        key = (client_ip, client_port, server_ip)
        flow = self.flows.get(key)
        if flow is None:
            if len(self.flows) >= TCP_MAX_FLOWS:
                self._drop_oldest()
            flow = _TcpFlow(now)
            self.flows[key] = flow
        flow.last = now
        stream = flow.to_server if to_server else flow.to_client
        if flags & TCP_SYN:
            stream.next_seq = (seq + 1) % TCP_SEQ_MOD
        elif payload:
            stream.add(seq, payload)
        if flags & (TCP_FIN | TCP_RST):
            flow.closed = True
        if flow.size() > TCP_MAX_BYTES:
            del self.flows[key]
            log.warning("tcp flow from %s dropped: more than %d bytes", client_ip, TCP_MAX_BYTES)
            return
        try:
            self._complete(client_ip, flow, flow.closed)
        except ValueError as exc:
            self.flows.pop(key, None)
            log.debug("tcp flow from %s dropped: not HTTP (%s)", client_ip, exc)
            return
        if flow.closed:
            self.flows.pop(key, None)

    def _complete(self, client_ip, flow, closed):
        """Write every exchange that is complete in the two buffers of the flow, then remove its bytes."""
        while True:
            request = parse_http_message(flow.to_server.buffer, True)
            if request is None:
                return
            answer = parse_http_message(flow.to_client.buffer, False, closed)
            if answer is None:
                return
            req_line, req_headers, req_body, req_used = request
            resp_line, resp_headers, resp_body, resp_used = answer
            method, path = req_line.split(" ")[0:2]
            status = int(resp_line.split(" ")[1])
            record_line(self.out_dir, INFORM_PORT, client_ip, method, path, req_headers, req_body, status,
                        resp_headers, resp_body, _header_value(resp_headers, "Content-Type"), self.max_mb)
            flow.to_server.buffer = flow.to_server.buffer[req_used:]
            flow.to_client.buffer = flow.to_client.buffer[resp_used:]

    def _expire(self, now):
        for key in list(self.flows):
            if now - self.flows[key].last > TCP_IDLE_SECONDS:
                del self.flows[key]

    def _drop_oldest(self):
        oldest = min(self.flows, key=lambda key: self.flows[key].last)
        del self.flows[oldest]


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


def capture_udp(out_dir, max_mb, open_socket=None, record_udp=True, tcp=None):
    """Listen passively to the raw link and record what is wanted; never answers.

    UDP 10001 and 3478 go to the day file when record_udp is True. TCP segments go to tcp (a
    TcpInformAssembler) when it is not None. When the socket cannot be opened it logs one warning
    and returns, so the recorder keeps running.
    """
    opener = open_socket or open_capture_socket
    try:
        sock = opener()
    except OSError as exc:
        log.warning("udp capture unavailable: %s", exc)
        return
    logged_write_error = False
    logged_tcp_error = False
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
            if parsed is not None:
                if not record_udp:
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
                continue
            if tcp is None:
                continue
            segment = parse_ipv4_tcp(frame)
            if segment is None:
                continue
            try:
                tcp.feed(*segment)
            except OSError as exc:
                if not logged_tcp_error:
                    log.error("tcp recording failed (%s)", type(exc).__name__)
                    logged_tcp_error = True
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
        try:
            self._send_back(status, resp_headers, resp_body)
        except OSError as exc:
            self.close_connection = True
            log.warning("client %s closed the connection before the answer was sent (%s): exchange recorded anyway",
                        self.client_address[0], type(exc).__name__)
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
    parser.add_argument("--tcp-capture", type=int, default=0,
                        help="passively record TCP port PORT (inform); 0 = off (needs NET_RAW)")
    parser.add_argument("--user", default=RECORDER_USER,
                        help="user the recorder runs as after the capture socket is open (default mfi)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="[mfi-recorder] %(asctime)s %(levelname)s %(message)s")
    capture_socket = None
    if args.udp_capture or args.tcp_capture != 0:
        # Opened while still root: a change of user takes away the right to open a raw socket.
        try:
            capture_socket = open_capture_socket()
        except OSError as exc:
            if args.udp_capture:
                log.warning("udp capture unavailable: %s", exc)
            else:
                log.warning("tcp capture unavailable: %s", exc)
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
        assembler = None
        if args.tcp_capture != 0:
            assembler = TcpInformAssembler(args.out, args.tcp_capture, args.max_mb)
            log.info("passive tcp capture of port %d", args.tcp_capture)
        capture_worker = threading.Thread(target=capture_udp, args=(args.out, args.max_mb, lambda: capture_socket),
                                          kwargs={"record_udp": args.udp_capture, "tcp": assembler})
        capture_worker.daemon = True
        capture_worker.start()

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
