"""Command line entry point of the new server (EPIC-15): migrates the data, then runs the services.

    python3 -m mfi_server_next [--data-dir DIR] [--host H] [--inform-port N]
                               [--web-port N] [--compat-port N] [--mode MODE]

Only mfi_server_next modules are imported here. The risky network functions stay off.
Errors go to stderr with exit code 2; a clean stop returns 0.
"""
from __future__ import annotations

import argparse
import http.server
import logging
import os
import re
import secrets
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from types import SimpleNamespace

from mfi_server_next import (
    alarms, auth, comet, compat_api, config, devices, events, firmware, inform, maps,
    migrate, mqtt, page_api, rules, rules_import, sensors, stats, store, tasks, udp_discovery,
)

logger = logging.getLogger(__name__)

DEFAULT_HOST = "0.0.0.0"
DEFAULT_WEB_PORT = 8099
DEFAULT_COMPAT_PORT = 8100
DEFAULT_MODE = "standalone"
MODES = ("standalone", "addon")
RISKY_FLAGS = ("allow_webshell", "allow_browser_ssh", "allow_upnp", "allow_guest_page", "allow_script_action")
PORT_MAX = 65535
SWITCH_ENTITY_RE = re.compile(r"switch\.mfi_([0-9a-f]{12})_([1-9][0-9]*)")
TICK_INTERVAL_S = 1.0
WAIT_STEP_S = 1.0
WORKER_JOIN_S = 5.0
FIRMWARE_DIR_ENV = "MFI_FIRMWARE_DIR"
WEB_DIR = Path(__file__).resolve().parent / "web"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def _port(text):
    """Parse a TCP port from the command line: 0 (ephemeral) to 65535."""
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a port number: {text}") from None
    if not 0 <= value <= PORT_MAX:
        raise argparse.ArgumentTypeError(f"port must be 0 to {PORT_MAX}: {text}")
    return value


def _parser():
    """The command line options of the server."""
    parser = argparse.ArgumentParser(prog="mfi_server_next", description="Run the mFi server.")
    parser.add_argument("--data-dir", default=config.DEFAULT_DATA_DIR, help="data folder (default: %(default)s)")
    parser.add_argument("--host", default=None,
                        help="address the servers listen on (default: the saved setting, else 0.0.0.0)")
    parser.add_argument("--inform-port", type=_port, default=None, help="inform port (default: the setting, 6080)")
    parser.add_argument("--web-port", type=_port, default=None,
                        help="web page port (default: the saved setting, else 8099)")
    parser.add_argument("--compat-port", type=_port, default=None,
                        help="compatible API port (default: the saved setting, else 8100)")
    parser.add_argument("--mode", choices=MODES, default=None,
                        help="standalone, or addon behind the Home Assistant ingress (default: standalone)")
    return parser


def _settings(args):
    """Effective settings: the stored ones, then the command line; every risky function stays off by default."""
    mode = args.mode if args.mode is not None else DEFAULT_MODE
    settings = dict(config.load_settings(args.data_dir, mode=mode))
    settings["mode"] = mode
    if args.host is not None:
        settings["host"] = args.host
    if args.web_port is not None:
        settings["web_port"] = args.web_port
    if args.compat_port is not None:
        settings["compat_port"] = args.compat_port
    if args.inform_port is not None:
        settings["inform_port"] = args.inform_port
    settings.setdefault("host", DEFAULT_HOST)
    settings.setdefault("web_port", DEFAULT_WEB_PORT)
    settings.setdefault("compat_port", DEFAULT_COMPAT_PORT)
    settings.setdefault("mode", DEFAULT_MODE)
    for flag in RISKY_FLAGS:
        settings.setdefault(flag, False)
    return settings


def _describe(exc):
    """One line for stderr: the text of the error, plus the file it names when the text does not show it."""
    text = str(exc) or type(exc).__name__
    path = getattr(exc, "path", None)
    if path and path not in text:
        text = f"{text} ({path})"
    return text


def _fail(message):
    """Write one error line to stderr and return the error exit code."""
    print(f"error: {message}", file=sys.stderr)
    return 2


def _firmware_context():
    """Firmware folder from MFI_FIRMWARE_DIR, and the firmware path only when that file is really there."""
    folder = os.environ.get(FIRMWARE_DIR_ENV) or None
    if folder is not None and (Path(folder) / firmware.FIRMWARE_PATH).is_file():
        return folder, {firmware.FIRMWARE_PATH}
    return folder, set()


def _load_devices(registry, db):
    """Load devices.json into the registry: a record with a valid key is adopted again, the others are pending."""
    skipped = 0
    for row in db.read_json(devices.DEVICES_FILE, default=[]) or []:
        mac = row.get("mac") if isinstance(row, dict) else None
        if not isinstance(mac, str) or devices.MAC_RE.fullmatch(mac) is None:
            skipped += 1
            continue
        key = row.get("x_authkey")
        if isinstance(key, str) and devices.AUTHKEY_RE.fullmatch(key) is not None:
            registry.adopt(
                mac,
                x_authkey=key,
                cfgversion=row.get("cfgversion"),
                portversion=row.get("portversion"),
                model=row.get("model"),
                ip=row.get("ip"),
            )
        else:
            registry.add(mac, model=row.get("model"), ip=row.get("ip"))
    if skipped:
        logger.warning("%d device records without a valid MAC were not loaded", skipped)


def _device_list(registry, db):
    """Copies of the device records saved in devices.json that the registry knows."""
    found = []
    for row in db.read_json(devices.DEVICES_FILE, default=[]) or []:
        mac = row.get("mac") if isinstance(row, dict) else None
        if isinstance(mac, str) and devices.MAC_RE.fullmatch(mac):
            record = registry.get(mac)
            if record is not None:
                found.append(record)
    return found


def _import_backup(body, folder, db, registry):
    """Import the devices of an uploaded .unf backup, then reload them into the registry; return the count."""
    with tempfile.TemporaryDirectory(prefix="mfi-backup-") as temp:
        path = Path(temp) / "backup.unf"
        path.write_bytes(body)
        try:
            imported = migrate.import_backup(path, data_dir=folder)
        except (migrate.MigrateError, ValueError) as exc:
            raise ValueError(_describe(exc)) from exc
    _load_devices(registry, db)
    return len(imported)


def _record_event(event_log, data):
    """Store the event of a rule action 'mfi.event'; its fields were checked by rules.validate."""
    event_log.record(
        key=data["key"],
        msg=data["msg"],
        device=data.get("device"),
        level=data.get("level", 0),
        dedup_minutes=data.get("dedup_minutes", 0),
    )


def _tick_loop(engine, stop):
    """Advance the automation engine once a second until stop is set; a failure is logged and the loop goes on."""
    while not stop.wait(TICK_INTERVAL_S):
        try:
            engine.tick(time.time())
        except Exception as exc:
            logger.error("automation tick failed: %s", type(exc).__name__)


def _discover(registry):
    """One best-effort UDP scan: the devices that answer are added as pending and saved."""
    try:
        found = udp_discovery.UdpDiscovery().scan()
    except Exception as exc:  # best effort: the servers keep running
        logger.warning("UDP discovery scan failed: %s", type(exc).__name__)
        return
    for device in found:
        registry.add(device["mac"], model=device["model"], ip=device["ip"])
    registry.save()
    logger.info("UDP discovery found %d devices", len(found))


def _guarded(name, target, *args):
    """Run one thread target; a failure is logged by name and kind, never with its traceback."""
    try:
        target(*args)
    except Exception as exc:
        logger.error("%s stopped: %s", name, type(exc).__name__)


def _close_all(closers):
    """Run every close function, newest first; a failure in one does not stop the others."""
    for close in reversed(closers):
        try:
            close()
        except Exception as exc:
            logger.error("close failed: %s", type(exc).__name__)


class _Actions:
    """Device actions of the web page. Each one enqueues a command or refuses with the reason."""

    def __init__(self, registry, queue, set_output, *, settings=None, runner=subprocess.run,
                 address_for=devices.local_address_for):
        self._registry = registry
        self._queue = queue
        self._set_output = set_output
        self._settings = settings or {}
        self._runner = runner
        self._address_for = address_for

    def _ssh_credentials(self):
        """The device administrator user and password from the settings; PermissionError names the one missing."""
        username = self._settings.get("device_ssh_username", "")
        if not username:
            raise PermissionError("device_ssh_username is not set")
        password = self._settings.get("device_ssh_password", "")
        if not password:
            raise PermissionError("device_ssh_password is not set")
        return username, password

    def _inform_url(self, device_ip):
        """The inform URL the device must use: server_address, else the local address toward the device."""
        host = self._settings.get("server_address", "")
        if not host:
            try:
                host = self._address_for(device_ip)
            except OSError as exc:
                raise ValueError("server_address could not be determined automatically") from exc
        return f"http://{host}:{self._settings.get('inform_port', 6080)}/inform"

    def _options(self):
        """The ssh extra options of the settings, keeping only the names the local ssh accepts."""
        return devices.usable_options(devices.parse_extra_options(self._settings.get("ssh_extra_options", "")))

    def _known(self, mac):
        """The record of mac: ValueError for a malformed MAC, LookupError for an unknown device."""
        record = self._registry.get(mac)
        if record is None:
            raise LookupError(mac)
        return record

    def adopt(self, mac):
        record = self._known(mac)
        if not record.get("ip"):
            raise ValueError("device has no known address")
        user, password = self._ssh_credentials()
        authkey = secrets.token_hex(16)
        devices.set_adopt(
            record["ip"],
            self._inform_url(record["ip"]),
            authkey,
            admin_user=user,
            admin_password=password,
            ssh_extra_options=tuple(self._options()),
            runner=self._runner,
        )
        self._registry.adopt(
            mac,
            x_authkey=authkey,
            cfgversion=record.get("cfgversion"),
            portversion=record.get("portversion"),
            model=record.get("model"),
            ip=record["ip"],
        )
        self._registry.save()

    def repoint(self, mac):
        """Point an adopted device at this server again with the key it already has; no new key, no registry change."""
        record = self._known(mac)
        key = record.get("x_authkey")
        if not isinstance(key, str) or devices.AUTHKEY_RE.fullmatch(key) is None:
            raise ValueError("device has no adoption key")
        if not record.get("ip"):
            raise ValueError("device has no known address")
        user, password = self._ssh_credentials()
        devices.set_adopt(
            record["ip"],
            self._inform_url(record["ip"]),
            key,
            admin_user=user,
            admin_password=password,
            ssh_extra_options=tuple(self._options()),
            runner=self._runner,
        )

    def forget(self, mac):
        self._known(mac)
        self._registry.forget(mac)
        self._registry.save()

    def reboot(self, mac):
        self._known(mac)
        raise PermissionError("reboot is not verified on a device yet")

    def locate(self, mac, data):
        self._known(mac)
        raise PermissionError("locate is not verified on a device yet")

    def upgrade(self, mac):
        record = self._known(mac)
        message = firmware.build_upgrade(record.get("model"))
        if message is None:
            raise ValueError("no firmware for this model")
        self._queue.enqueue({**message, "mac": mac})

    def set_output(self, mac, port, value):
        self._known(mac)
        if isinstance(value, bool):
            value = int(value)
        if type(port) is not int or port < 1:
            raise ValueError("port must be a positive integer")
        if type(value) is not int or value not in (0, 1):
            raise ValueError("value must be 0 or 1")
        self._set_output(mac, port, value)

    def set_port(self, mac, port, data):
        # The port is checked here; the sensors in data name their own ports.
        self._known(mac)
        if type(port) is not int or port < 1:
            raise ValueError("port must be a positive integer")
        if not isinstance(data, dict) or "model" not in data:
            raise ValueError("port settings need a model")
        self._queue.enqueue({**sensors.build_port_config(data), "mac": mac})


class Application:
    """The running services: three HTTP servers, the background workers and the stop event.

    stop() may be called more than once. Every server is closed even when it was never started.
    """

    def __init__(self, servers, workers, closers):
        self.servers = servers
        self.stop_event = threading.Event()
        self._workers = workers
        self._closers = closers
        self._threads = []
        self._serving = []
        self._stopped = False

    @property
    def addresses(self):
        """The (host, port) each server is bound to, by name."""
        return {name: server.server_address[:2] for name, server in self.servers.items()}

    def _spawn(self, name, target, *args):
        thread = threading.Thread(target=_guarded, args=(name, target) + args, name=name, daemon=True)
        thread.start()
        self._threads.append(thread)

    def start(self):
        """Start the three servers and the workers, each in a daemon thread."""
        for name, server in self.servers.items():
            self._spawn(name, server.serve_forever)
            self._serving.append(server)
        for name, target in self._workers:
            self._spawn(name, target, self.stop_event)

    def wait(self):
        """Block until stop() or a signal sets the stop event."""
        while not self.stop_event.wait(WAIT_STEP_S):
            pass

    def stop(self):
        """Stop the servers and the workers, then close every server and database."""
        if self._stopped:
            return
        self._stopped = True
        self.stop_event.set()
        try:
            for server in self._serving:
                server.shutdown()
        finally:
            for thread in self._threads:
                thread.join(WORKER_JOIN_S)
            _close_all(self._closers)


def build_application(settings, *, discovery=True):
    """Build the stores, the services and the three HTTP servers; nothing is started yet."""
    host = settings["host"]
    folder = Path(settings["data_dir"])
    days = settings["history_days"]
    closers = []
    try:
        db = store.Store.open(folder)
        closers.append(db.close)
        history = sqlite3.connect(folder / store.HISTORY_DB, check_same_thread=False)
        closers.append(history.close)
        registry = devices.DeviceRegistry(db)
        _load_devices(registry, db)
        queue = tasks.TaskQueue()
        auth_manager = auth.AuthManager(db)
        if auth_manager.migrate_from_legacy():
            logger.info("the old single password became the admin account")
        event_log = events.EventLog(db, retention_days=days)
        alarm_store = alarms.AlarmStore(db, event_log)
        aggregator = stats.Aggregator(history, retention_days=days)
        automation_store = rules.AutomationStore(db)
        output_state = {}

        def set_output(mac, port, value):
            queue.enqueue(tasks.build_output_command(mac, port, value))
            output_state[f"switch.mfi_{mac}_{port}"] = "on" if value == 1 else "off"

        def resolve(entity_id):
            match = SWITCH_ENTITY_RE.fullmatch(entity_id)
            if match is None or registry.get(match.group(1)) is None:
                return None
            return match.group(1), int(match.group(2))

        engine = rules.AutomationEngine(
            entities=output_state.get,
            set_output=set_output,
            resolve=resolve,
            clock=time.time,
            record_event=lambda data: _record_event(event_log, data),
            allow_script_action=settings["allow_script_action"],
        )
        engine.load(automation_store.load())
        bridge = mqtt.MqttBridge(settings, lambda: _device_list(registry, db), queue)
        sensor_registry = sensors.SensorRegistry()
        firmware_dir, firmware_paths = _firmware_context()
        page_context = SimpleNamespace(
            auth=auth_manager,
            devices=registry,
            events=event_log,
            alarms=alarm_store,
            stats=aggregator,
            automations=automation_store,
            comet=comet.CometBuffer(),
            actions=_Actions(registry, queue, set_output, settings=settings),
            maps=maps.MapStore(db),
            rules_engine=engine,
            import_backup=lambda body: _import_backup(body, folder, db, registry),
            import_rules=lambda body: rules_import.import_backup_rules(
                body, folder, allow_script_action=settings["allow_script_action"]),
            firmware_paths=firmware_paths,
            firmware_dir=firmware_dir,
            web_dir=WEB_DIR,
            settings=settings,
        )
        compat_context = SimpleNamespace(
            auth=auth_manager,
            tasks=queue,
            sensors=sensor_registry,
            settings=settings,
        )
        servers = {}
        servers["inform"] = inform.make_server(registry, queue, host=host, port=settings["inform_port"])
        closers.append(servers["inform"].server_close)
        servers["web"] = http.server.ThreadingHTTPServer(
            (host, settings["web_port"]), page_api.make_handler(page_context))
        closers.append(servers["web"].server_close)
        servers["compat"] = http.server.ThreadingHTTPServer(
            (host, settings["compat_port"]), compat_api.make_compat_handler(compat_context))
        closers.append(servers["compat"].server_close)
    except BaseException:
        _close_all(closers)
        raise
    workers = [
        ("automation ticks", lambda stop: _tick_loop(engine, stop)),
        ("MQTT bridge", lambda stop: bridge.run(stop)),
    ]
    if discovery:
        workers.append(("UDP discovery", lambda stop: _discover(registry)))
    return Application(servers, workers, closers)


def _install_signal_handlers(stop_event):
    """Make SIGTERM and SIGINT set stop_event; return the handlers they replaced."""

    def request_stop(signum, _frame):
        logger.info("stop requested by signal %d", signum)
        stop_event.set()

    previous = {}
    for sig in (signal.SIGTERM, signal.SIGINT):
        previous[sig] = signal.signal(sig, request_stop)
    return previous


def _restore_signal_handlers(previous):
    """Put back the handlers that _install_signal_handlers replaced."""
    for sig, handler in previous.items():
        signal.signal(sig, handler if handler is not None else signal.SIG_DFL)


def _apply_log_level(settings):
    """Set the root logger level from the log_level setting; an unknown name keeps INFO."""
    names = {"debug": logging.DEBUG, "info": logging.INFO, "warning": logging.WARNING, "error": logging.ERROR}
    level = names.get(settings.get("log_level", "info"), logging.INFO)
    logging.getLogger().setLevel(level)


def _apply_supervisor_mqtt(settings, *, environ=os.environ, opener=urllib.request.urlopen):
    """In add-on mode without mqtt_host, take the broker the Supervisor offers; otherwise settings stay as they are."""
    if settings.get("mode") != "addon" or settings.get("mqtt_host"):
        return
    broker = config.supervisor_mqtt(environ, opener)
    if not broker:
        return
    settings["mqtt_host"] = broker["host"]
    settings["mqtt_port"] = broker["port"]
    settings["mqtt_user"] = broker["username"]
    settings["mqtt_password"] = broker["password"]
    settings["mqtt_tls"] = broker["tls"]


def main(argv=None, *, on_ready=None, discovery=True):
    """Run the server until SIGTERM or SIGINT and return 0; return 2 when the data or the settings cannot be used.

    on_ready(app) runs once the servers are bound, before the wait. discovery=False skips the UDP scan (tests).
    """
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2
    try:
        settings = _settings(args)
    except (ValueError, OSError) as exc:
        return _fail(_describe(exc))
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    _apply_log_level(settings)
    _apply_supervisor_mqtt(settings)
    try:
        migrate.migrate_all(settings["data_dir"])
    except (migrate.MigrateError, ValueError, OSError, sqlite3.Error) as exc:
        return _fail(_describe(exc))
    try:
        app = build_application(settings, discovery=discovery)
    except (OSError, ValueError, sqlite3.Error) as exc:
        return _fail(_describe(exc))
    previous = {}
    try:
        previous = _install_signal_handlers(app.stop_event)
        app.start()
        logger.info("listening on %s", app.addresses)
        if on_ready is not None:
            on_ready(app)
        app.wait()
    finally:
        app.stop()
        _restore_signal_handlers(previous)
    logger.info("stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
