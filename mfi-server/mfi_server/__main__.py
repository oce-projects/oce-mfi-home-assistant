"""Command line entry point of mfi-server.

    python3 -m mfi_server [--data DIR]                      run the inform server
    python3 -m mfi_server decode FILE --key-file KEYFILE    decode one captured packet
    python3 -m mfi_server import-backup FILE [--data DIR]   import devices from a .unf backup

Keys are never printed. Errors go to stderr with exit code 2.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path

from mfi_server.commands import CommandQueue
from mfi_server.config import load_settings
from mfi_server.measurements import Measurements
from mfi_server.packet import PacketError, decode
from mfi_server.server import make_server
from mfi_server.states import DeviceStates
from mfi_server.store import DeviceStore
from mfi_server.unf import import_backup

logger = logging.getLogger(__name__)

KEY_HEX_RE = re.compile(r"[0-9a-fA-F]{32}")
KEY_FILE_MESSAGE = "key file must contain 32 hex characters"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def main(argv: list[str] | None = None, environ: Mapping[str, str] | None = None) -> int:
    """Run one command and return its exit code (0 ok, 2 error)."""
    args = list(sys.argv[1:] if argv is None else argv)
    env = os.environ if environ is None else environ
    try:
        if args and args[0] == "decode":
            return _decode_command(args[1:])
        if args and args[0] == "import-backup":
            return _import_command(args[1:])
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
    server = make_server(settings, store, DeviceStates(), CommandQueue(), Measurements())
    logger.info(
        "listening on %s:%d (mode %s)",
        settings.bind_address,
        server.server_address[1],
        settings.mode,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("stopped by user")
    finally:
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
