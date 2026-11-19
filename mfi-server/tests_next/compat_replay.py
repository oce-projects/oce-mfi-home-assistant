"""Replay bench of the compatibility fixtures of the new server (EPIC-01b).

Not a test file: unittest does not collect it. test_compat_replay.py imports it.
A fixture is one JSON file in fixtures/compat/: the route code, the handler that
must answer it, the request and the keys of the expected answer. The handlers
are stubs until their owner epic implements them; a stub raises
NotImplementedError when called, and its fixture is PENDING.

Standard library only, offline.
"""
from __future__ import annotations

import importlib
import json
import pathlib

FIXTURES_DIR = pathlib.Path(__file__).resolve().parent / "fixtures" / "compat"
REQUIRED_KEYS = ("code", "source", "owner_epic", "handler", "request", "expected")
VALID_CODES = frozenset({"R-ADOPT", "R-POWER", "R-FORGET", "R-RESET", "R-UPDATE", "R-MPORT", "R-SERIAL", "R-MPOWER", "R-WEB", "R-DISC"})
VALID_SOURCES = frozenset({"synthetic", "recording"})
KNOWN_EPICS = frozenset({f"EPIC-{i:02d}" for i in range(0, 20)} | {"EPIC-01b"})
HANDLER_PREFIX = "mfi_server_next."


def load_fixtures() -> list[tuple[pathlib.Path, dict]]:
    """Return (path, data) for every *.json fixture, sorted by file name."""
    loaded = []
    for path in sorted(FIXTURES_DIR.glob("*.json")):
        with path.open(encoding="utf-8") as handle:
            try:
                loaded.append((path, json.load(handle)))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path.name}: {exc}") from exc
    return loaded


def _is_dotted(name: object) -> bool:
    """True for a dotted name with at least a module and an attribute, such as module.attr."""
    if not isinstance(name, str):
        return False
    parts = name.split(".")
    return len(parts) >= 2 and all(parts)


def _in(value: object, allowed: frozenset) -> bool:
    return isinstance(value, str) and value in allowed


def validate_fixture(data: dict) -> list[str]:
    """Return the problems of one fixture in plain words; an empty list means the fixture is valid."""
    if not isinstance(data, dict):
        return ["fixture is not a JSON object"]
    problems = [f"missing key {key}" for key in REQUIRED_KEYS if key not in data]
    if "code" in data and not _in(data["code"], VALID_CODES):
        problems.append(f"unknown code {data['code']!r}")
    if "source" in data and not _in(data["source"], VALID_SOURCES):
        problems.append(f"unknown source {data['source']!r}")
    if "owner_epic" in data and not _in(data["owner_epic"], KNOWN_EPICS):
        problems.append(f"unknown owner_epic {data['owner_epic']!r}")
    if "handler" in data:
        handler = data["handler"]
        if not _is_dotted(handler):
            problems.append(f"handler {handler!r} is not module.attr")
        elif not handler.startswith(HANDLER_PREFIX):
            problems.append(f"handler {handler!r} is not inside mfi_server_next")
    if "expected" in data and not isinstance(data["expected"], dict):
        problems.append("expected is not an object")
    return problems


def resolve_handler(dotted: str):
    """Return the object named by a dotted name: the module is the part before the last dot.

    Raises ValueError when the name is outside mfi_server_next, and
    ModuleNotFoundError or AttributeError when the name does not exist.
    """
    if not _is_dotted(dotted):
        raise ValueError(f"handler {dotted!r} is not module.attr")
    if not dotted.startswith(HANDLER_PREFIX):
        raise ValueError(f"handler {dotted!r} is not inside mfi_server_next")
    module_name, _, attr = dotted.rpartition(".")
    return getattr(importlib.import_module(module_name), attr)


def is_pending(handler) -> bool:
    """True when calling the handler with no arguments raises NotImplementedError (a stub).

    A handler that returns normally is not pending; any other exception propagates.
    """
    try:
        handler()
    except NotImplementedError:
        return True
    return False
