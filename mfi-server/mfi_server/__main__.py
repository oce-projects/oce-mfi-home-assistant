"""Command line entry point of mfi-server.

    python3 -m mfi_server [--data DIR]                      run the inform server
    python3 -m mfi_server decode FILE --key-file KEYFILE    decode one captured packet
    python3 -m mfi_server import-backup FILE [--data DIR]   import devices from a .unf backup
    python3 -m mfi_server set-password [--data DIR]         set the password of the standalone API

Keys are never printed. Errors go to stderr with exit code 2.
"""
from __future__ import annotations

import argparse
import getpass
import json
import logging
import os
import re
import socket
import sys
import threading
import time
from collections.abc import Mapping
from pathlib import Path

from mfi_server.api import make_api_server
from mfi_server.auth import Sessions, LoginLimiter, hash_password, save_password_hash
from mfi_server.bridge import MqttBridge
from mfi_server.commands import CommandQueue
from mfi_server.config import Settings, load_settings, supervisor_mqtt
from mfi_server.control import OutputControl
from mfi_server.history import History
from mfi_server.measurements import Measurements
from mfi_server.mqtt import MqttClient
from mfi_server.packet import PacketError, decode
from mfi_server.server import make_server
from mfi_server.states import DeviceStates
from mfi_server.store import DeviceStore
from mfi_server.unf import import_backup

logger = logging.getLogger(__name__)

KEY_HEX_RE = re.compile(r"[0-9a-fA-F]{32}")
KEY_FILE_MESSAGE = "key file must contain 32 hex characters"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
MQTT_CLIENT_ID = "mfi-server"
MIN_PASSWORD_LENGTH = 12
HISTORY_PURGE_INTERVAL_S = 3600


def main(argv: list[str] | None = None, environ: Mapping[str, str] | None = None) -> int:
    """Run one command and return its exit code (0 ok, 2 error)."""
    args = list(sys.argv[1:] if argv is None else argv)
    env = os.environ if environ is None else environ
    try:
        if args and args[0] == "decode":
            return _decode_command(args[1:])
        if args and args[0] == "import-backup":
            return _import_command(args[1:])
        if args and args[0] == "set-password":
            return _set_password_command(args[1:])
        return _serve(args, env)
    except SystemExit as exc:
        # argparse exits on bad arguments; its exit code is the answer.
        return exc.code if isinstance(exc.code, int) else 2


def _fail(message: str) -> int:
    """Write one error line to stderr and return the error exit code."""
    print(f"error: {message}", file=sys.stderr)
    return 2


def _read_key(path: Path) -> bytes:
    """Read the device key: 32 hex characters, surrounding white space ignored."""
    try:
        text = path.read_text(encoding="utf-8").strip()
    except UnicodeDecodeError as exc:
        raise ValueError(KEY_FILE_MESSAGE) from exc
    if not KEY_HEX_RE.fullmatch(text):
        raise ValueError(KEY_FILE_MESSAGE)
    return bytes.fromhex(text)


def _decode_command(args: list[str]) -> int:
    """Decode one captured inform packet and print its JSON payload."""
    parser = argparse.ArgumentParser(prog="mfi_server decode")
    parser.add_argument("file")
    parser.add_argument("--key-file", required=True)
    options = parser.parse_args(args)
    try:
        key = _read_key(Path(options.key_file))
        data = Path(options.file).read_bytes()
        _, payload, _ = decode(data, [key])
    except PacketError as exc:
        return _fail(exc.reason)
    except (OSError, ValueError) as exc:
        return _fail(str(exc))
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _import_command(args: list[str]) -> int:
    """Import the devices of a .unf backup into the device archive."""
    parser = argparse.ArgumentParser(prog="mfi_server import-backup")
    parser.add_argument("file")
    parser.add_argument("--data", default="./data")
    options = parser.parse_args(args)
    try:
        records = import_backup(Path(options.file).read_bytes())
        devices, ports = DeviceStore(Path(options.data)).import_records(records)
    except (OSError, ValueError) as exc:
        return _fail(str(exc))
    print(f"imported {devices} devices, {ports} ports")
    return 0


def _set_password_command(args: list[str]) -> int:
    """Set the password of the standalone API; it is typed twice and never read from the command line."""
    parser = argparse.ArgumentParser(prog="mfi_server set-password")
    parser.add_argument("--data", default="./data")
    options = parser.parse_args(args)
    data_dir = Path(options.data)
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        password = getpass.getpass("Password: ")
        repeat = getpass.getpass("Repeat: ")
        if password != repeat:
            return _fail("passwords do not match")
        if len(password) < MIN_PASSWORD_LENGTH:
            return _fail(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
        save_password_hash(data_dir, hash_password(password))
    except OSError as exc:
        return _fail(str(exc))
    print("password set")
    return 0


def _mqtt_broker(settings: Settings, environ: Mapping[str, str]) -> dict | None:
    """Return the MQTT broker: the settings first, then the Supervisor in add-on mode; None if there is none."""
    if settings.mqtt_host:
        return {
            "host": settings.mqtt_host,
            "port": settings.mqtt_port,
            "username": settings.mqtt_username,
            "password": settings.mqtt_password,
        }
    if settings.mode == "addon":
        return supervisor_mqtt(environ)
    return None


def _run_bridge(bridge: MqttBridge, stop_event: threading.Event) -> None:
    """Run the bridge until stop_event is set; a failure is logged and the inform server keeps running."""
    try:
        bridge.run(stop_event)
    except Exception as exc:
        logger.error("MQTT bridge stopped: %s", type(exc).__name__)


def _start_bridge(
    settings: Settings,
    environ: Mapping[str, str],
    store: DeviceStore,
    states: DeviceStates,
    control: OutputControl,
    measurements: Measurements,
    stop_event: threading.Event,
) -> None:
    """Start the MQTT bridge in a daemon thread, but only when a broker is configured."""
    broker = _mqtt_broker(settings, environ)
    if broker is None:
        return
    client = MqttClient(
        broker["host"],
        broker["port"],
        broker["username"],
        broker["password"],
        MQTT_CLIENT_ID,
        on_message=lambda topic, payload: None,  # replaced below, once the bridge exists
        will_topic=f"{settings.mqtt_topic_prefix}/status",
        will_payload=b"offline",
    )
    bridge = MqttBridge(client, store, states, control, measurements, settings, time.time)
    client.on_message = bridge.on_message
    threading.Thread(target=_run_bridge, args=(bridge, stop_event), daemon=True).start()


def _purge_history(history: History, stop_event: threading.Event) -> None:
    """Delete the history older than the retention period every hour until stop_event is set."""
    while not stop_event.wait(HISTORY_PURGE_INTERVAL_S):
        history.purge()


def _serve(argv: list[str], environ: Mapping[str, str]) -> int:
    """Run the inform server until it is interrupted."""
    try:
        settings = load_settings(argv, environ)
    except ValueError as exc:
        return _fail(str(exc))
    logging.basicConfig(level=settings.log_level.upper(), format=LOG_FORMAT)
    try:
        store = DeviceStore(settings.data_dir)
    except ValueError as exc:
        logger.error("cannot open the device archive: %s", exc)
        return 2
    if settings.backup_file:
        try:
            store.import_records(import_backup(Path(settings.backup_file).read_bytes()))
        except (OSError, ValueError) as exc:
            logger.error("backup import failed: %s", exc)
    states = DeviceStates()
    queue = CommandQueue()
    measurements = Measurements()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((settings.bind_address, settings.wakeup_port))
    except OSError as exc:
        sock.close()
        logger.error("cannot bind the wake-up socket: %s", exc)
        return 2
    control = OutputControl(store, states, queue, sock)
    history = History(settings.data_dir / "history.sqlite3", retention_days=settings.history_days)
    measurements.add_listener(history.record)
    sessions = Sessions(time.time)
    limiter = LoginLimiter(time.time)
    api_server = make_api_server(settings, store, states, measurements, history, control, sessions, limiter)
    threading.Thread(target=api_server.serve_forever, daemon=True).start()
    server = make_server(settings, store, states, queue, measurements)
    logger.info(
        "listening on %s:%d (mode %s)",
        settings.bind_address,
        server.server_address[1],
        settings.mode,
    )
    stop_event = threading.Event()
    threading.Thread(target=_purge_history, args=(history, stop_event), daemon=True).start()
    _start_bridge(settings, environ, store, states, control, measurements, stop_event)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("stopped by user")
    finally:
        stop_event.set()
        server.shutdown()
        server.server_close()
        api_server.shutdown()
        api_server.server_close()
        try:
            sock.close()
        except OSError as exc:
            logger.warning("closing the wake-up socket failed: %s", exc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
