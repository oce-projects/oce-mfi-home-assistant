"""Automation rules of mfi_server_next: model, validation, engine and store. Implemented in EPIC-05.

Standard library only, clean room: the format follows the Home Assistant
automations (triggers, conditions, actions) and the engine is our own code;
no Home Assistant code is copied. Templates, sun, mqtt, repeat, wait_template,
wait_for_trigger, variables, event and template are rejected by validate().

The script action sends a text to the serial line of an adopted mPort Serial.
It is off by default (allow_script_action=False): validate() refuses it and the
engine records an error in the trace instead of sending anything.
"""
from __future__ import annotations

import math
import re
import threading
import time
from collections import deque
from collections.abc import Callable, Generator
from copy import deepcopy
from itertools import count
from typing import NamedTuple

DEFAULT_SCRIPT_MAX_LENGTH = 1024
DEFAULT_MAX_DEPTH = 10
SCHEMA = 1
DEFAULT_FILENAME = "automations.json"
MODES = ("single", "restart", "queued", "parallel")
DEFAULT_MODE = "single"
DEFAULT_MAX = 10
MAX_LIMIT = 100
MAX_DURATION = 10 ** 9  # seconds; larger single values are rejected to avoid overflow
TRACE_LIMIT = 5
DAY_SECONDS = 86400
TEMPLATE_MARK = "{{"
ID_RE = re.compile(r"[a-z0-9_]{1,64}")
CLOCK_RE = re.compile(r"([0-9]{2}):([0-9]{2})(?::([0-9]{2}))?")
DURATION_RE = re.compile(r"([0-9]+):([0-5][0-9]):([0-5][0-9])")
PATTERN_RE = re.compile(r"/([0-9]{1,4})")
URL_RE = re.compile(r"https?://\S+")
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DURATION_UNITS = {"hours": 3600, "minutes": 60, "seconds": 1}
UNSUPPORTED_TYPES = frozenset(
    {"sun", "mqtt", "repeat", "wait_template", "wait_for_trigger", "variables", "event", "template"}
)
SWITCH_SERVICES = ("switch.turn_on", "switch.turn_off", "switch.toggle")
INVERSE = {
    "switch.turn_on": "switch.turn_off",
    "switch.turn_off": "switch.turn_on",
    "switch.toggle": "switch.toggle",
}
LIGHT_SERVICE = "light.turn_on"
SCENE_SERVICE = "scene.turn_on"
AUTOMATION_SERVICES = ("automation.trigger", "automation.turn_on", "automation.turn_off")
HTTP_SERVICE = "http_post"
SCRIPT_SERVICE = "script"
NOTIFY_EMAIL_SERVICE = "notify.email"
EVENT_SERVICE = "mfi.event"
CALENDAR_EVENTS = ("start", "end")
TIME_KINDS = ("time", "time_pattern")
TOP_KEYS = frozenset(
    {"id", "alias", "description", "enabled", "mode", "max", "triggers", "conditions", "actions"}
)
TRIGGER_KEYS = {
    "state": frozenset({"trigger", "entity_id", "from", "to", "for"}),
    "numeric_state": frozenset({"trigger", "entity_id", "above", "below", "for"}),
    "time": frozenset({"trigger", "at", "weekday"}),
    "time_pattern": frozenset({"trigger", "hours", "minutes", "seconds"}),
    "calendar": frozenset({"trigger", "entity_id", "event", "offset", "duration"}),
}
CONDITION_KEYS = {
    "state": frozenset({"condition", "entity_id", "state"}),
    "numeric_state": frozenset({"condition", "entity_id", "above", "below"}),
    "time": frozenset({"condition", "after", "before", "weekday"}),
    "and": frozenset({"condition", "conditions"}),
    "or": frozenset({"condition", "conditions"}),
    "not": frozenset({"condition", "conditions"}),
}
SERVICE_KEYS = {
    "switch.turn_on": frozenset({"action", "target", "for"}),
    "switch.turn_off": frozenset({"action", "target", "for"}),
    "switch.toggle": frozenset({"action", "target", "for"}),
    LIGHT_SERVICE: frozenset({"action", "target", "data"}),
    SCENE_SERVICE: frozenset({"action", "target"}),
    "automation.trigger": frozenset({"action", "target"}),
    "automation.turn_on": frozenset({"action", "target"}),
    "automation.turn_off": frozenset({"action", "target"}),
    HTTP_SERVICE: frozenset({"action", "data"}),
    SCRIPT_SERVICE: frozenset({"action", "data"}),
    NOTIFY_EMAIL_SERVICE: frozenset({"action", "data"}),
    EVENT_SERVICE: frozenset({"action", "data"}),
}


class _Limits(NamedTuple):
    """The settings that validate() checks the script action against."""

    allow_script_action: bool
    script_max_length: int


class _Run:
    """One execution in progress: its generator, its trace and the time it waits until."""

    def __init__(self, generator: Generator, trace: dict) -> None:
        self.generator = generator
        self.trace = trace
        self.resume_at: float | None = None
        self.done = False


class _Automation:
    """One automation with the runtime state the engine keeps for it."""

    def __init__(self, obj: dict) -> None:
        self.obj = obj
        self.running: list[_Run] = []
        self.queue: deque[str] = deque()
        self.pending: dict[int, float] = {}
        self.last_fired: dict[int, int] = {}
        self.traces: deque[dict] = deque(maxlen=TRACE_LIMIT)


# ---------------------------------------------------------------- model


def normalize(obj: dict) -> dict:
    """Return a new automation in the current format: old keys renamed, defaults filled in. Idempotent."""
    result = deepcopy(obj)
    if not isinstance(result, dict):
        return result
    if "trigger" in result and "triggers" not in result:
        result["triggers"] = result.pop("trigger")
    if "condition" in result and "conditions" not in result:
        result["conditions"] = result.pop("condition")
    if "action" in result and "actions" not in result:
        result["actions"] = result.pop("action")
    for item in _dict_items(result.get("triggers")):
        if "platform" in item and "trigger" not in item:
            item["trigger"] = item.pop("platform")
    _normalize_actions(result.get("actions"))
    result.setdefault("enabled", True)
    result.setdefault("mode", DEFAULT_MODE)
    result.setdefault("max", DEFAULT_MAX)
    return result


def _normalize_actions(actions: object) -> None:
    """Rename the old service key of every action, also inside if, choose and their branches."""
    for item in _dict_items(actions):
        if "service" in item and "action" not in item:
            item["action"] = item.pop("service")
        _normalize_actions(item.get("then"))
        _normalize_actions(item.get("else"))
        _normalize_actions(item.get("default"))
        for branch in _dict_items(item.get("choose")):
            _normalize_actions(branch.get("sequence"))


def parse_duration(value: object) -> float:
    """Return a duration in seconds from "H:MM:SS" or from a mapping of hours, minutes and seconds.

    Raises ValueError when the value is not a valid duration.
    """
    if isinstance(value, str):
        match = DURATION_RE.fullmatch(value)
        if match is None:
            raise ValueError(f"invalid duration: {value!r}")
        hours, minutes, seconds = (int(part) for part in match.groups())
        total = hours * 3600 + minutes * 60 + seconds
        if total > MAX_DURATION:
            raise ValueError(f"duration too large: {value!r}")
        return float(total)
    if isinstance(value, dict):
        if not value or set(value) - set(DURATION_UNITS):
            raise ValueError("duration mapping must have hours, minutes or seconds only")
        total = 0.0
        for unit, amount in value.items():
            if isinstance(amount, bool) or not isinstance(amount, (int, float)):
                raise ValueError(f"invalid {unit}")
            if isinstance(amount, float) and not math.isfinite(amount):
                raise ValueError(f"invalid {unit}")
            if amount < 0 or amount > MAX_DURATION:
                raise ValueError(f"invalid {unit}")
            total += amount * DURATION_UNITS[unit]
        return float(total)
    raise ValueError("duration must be a string or a mapping")


# ---------------------------------------------------------------- validation


def validate(
    obj: dict,
    *,
    allow_script_action: bool = False,
    script_max_length: int = DEFAULT_SCRIPT_MAX_LENGTH,
) -> list[str]:
    """Return the problems of an automation as "<path>: <reason>" strings; an empty list means valid."""
    if not isinstance(obj, dict):
        return ["not a mapping"]
    limits = _Limits(allow_script_action is True, script_max_length)
    model = normalize(obj)
    errors: list[str] = []
    _scan_templates(model, "", errors)
    _check_keys(model, TOP_KEYS, "", errors)
    _check_id(model, errors)
    if "enabled" in model and not _is_template(model["enabled"]) and not isinstance(model["enabled"], bool):
        errors.append("enabled: must be true or false")
    mode = model.get("mode")
    if not _is_template(mode) and mode not in MODES:
        errors.append(f"mode: must be one of {', '.join(MODES)}")
    limit = model.get("max")
    if not _is_template(limit) and not _is_int(limit, 1, MAX_LIMIT):
        errors.append("max: must be an integer from 1 to 100")
    if "triggers" in model:
        _validate_triggers(model["triggers"], "triggers", errors)
    if "conditions" in model:
        _validate_conditions(model["conditions"], "conditions", errors)
    if _required(model, "actions", "", errors):
        _validate_actions(model["actions"], "actions", limits, errors)
    return errors


def _err(path: str, reason: str) -> str:
    """Return one problem as "<path>: <reason>"; the root of the automation has no path."""
    return f"{path}: {reason}" if path else reason


def _join(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def _is_template(value: object) -> bool:
    return isinstance(value, str) and TEMPLATE_MARK in value


def _is_int(value: object, low: int, high: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def _dict_items(value: object) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _as_list(value: object, path: str, errors: list[str]) -> list | None:
    """Return the value when it is a list; a template is left to _scan_templates and gives None."""
    if _is_template(value):
        return None
    if not isinstance(value, list):
        errors.append(_err(path, "must be a list"))
        return None
    return value


def _required(item: dict, key: str, path: str, errors: list[str]) -> bool:
    if key in item:
        return True
    errors.append(_err(_join(path, key), "required"))
    return False


def _check_keys(item: dict, allowed: frozenset | set, path: str, errors: list[str]) -> None:
    for key in item:
        if key not in allowed:
            errors.append(_err(path, f"unknown key '{key}'"))


def _check_kind(kind: object, known: dict | tuple | frozenset, what: str, path: str, errors: list[str]) -> bool:
    """Return True when the type is supported; otherwise record why not. Templates are reported by _scan_templates."""
    if _is_template(kind):
        return False
    if isinstance(kind, str) and kind in UNSUPPORTED_TYPES:
        errors.append(_err(path, "not supported yet"))
        return False
    if isinstance(kind, str) and kind in known:
        return True
    errors.append(_err(path, f"unknown {what}"))
    return False


def _scan_templates(value: object, path: str, errors: list[str]) -> None:
    """Report every string that contains a template, wherever it is in the automation."""
    if isinstance(value, str):
        if TEMPLATE_MARK in value:
            errors.append(_err(path, "not supported yet"))
    elif isinstance(value, dict):
        for key, child in value.items():
            _scan_templates(child, _join(path, str(key)), errors)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _scan_templates(child, f"{path}[{index}]", errors)


def _check_id(model: dict, errors: list[str]) -> None:
    if not _required(model, "id", "", errors):
        return
    value = model["id"]
    if _is_template(value):
        return
    if not isinstance(value, str) or ID_RE.fullmatch(value) is None:
        errors.append("id: must match [a-z0-9_]{1,64}")


def _check_text(item: dict, key: str, path: str, errors: list[str], required: bool = True) -> None:
    field = _join(path, key)
    if key not in item:
        if required:
            errors.append(_err(field, "required"))
        return
    value = item[key]
    if _is_template(value):
        return
    if not isinstance(value, str) or not value:
        errors.append(_err(field, "must be a non-empty string"))


def _check_number(item: dict, key: str, path: str, errors: list[str]) -> None:
    if key not in item or _is_template(item[key]):
        return
    value = item[key]
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or (isinstance(value, float) and not math.isfinite(value))
    ):
        errors.append(_err(_join(path, key), "must be a number"))


def _check_duration(item: dict, key: str, path: str, errors: list[str]) -> None:
    if key not in item or _is_template(item[key]):
        return
    try:
        parse_duration(item[key])
    except ValueError:
        errors.append(_err(_join(path, key), "invalid duration"))


def _valid_clock(value: object) -> bool:
    if not isinstance(value, str):
        return False
    match = CLOCK_RE.fullmatch(value)
    if match is None:
        return False
    hours, minutes, seconds = match.group(1), match.group(2), match.group(3) or "00"
    return int(hours) <= 23 and int(minutes) <= 59 and int(seconds) <= 59


def _check_clock(item: dict, key: str, path: str, errors: list[str], required: bool = True) -> None:
    if key not in item:
        if required:
            errors.append(_err(_join(path, key), "required"))
        return
    value = item[key]
    if _is_template(value):
        return
    if not _valid_clock(value):
        errors.append(_err(_join(path, key), "invalid time"))


def _pattern_ok(value: object, limit: int) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return 0 <= value <= limit
    if value == "*":
        return True
    match = PATTERN_RE.fullmatch(value) if isinstance(value, str) else None
    return match is not None and int(match.group(1)) >= 1


def _check_pattern(item: dict, key: str, limit: int, path: str, errors: list[str]) -> None:
    if key not in item or _is_template(item[key]):
        return
    if not _pattern_ok(item[key], limit):
        errors.append(_err(_join(path, key), f"must be an integer from 0 to {limit}, '*' or '/N'"))


def _check_weekdays(item: dict, path: str, errors: list[str]) -> None:
    if "weekday" not in item or _is_template(item["weekday"]):
        return
    days = item["weekday"]
    if not isinstance(days, list) or not all(
        _is_template(day) or (isinstance(day, str) and day in WEEKDAYS) for day in days
    ):
        errors.append(_err(_join(path, "weekday"), "must be a list of mon, tue, wed, thu, fri, sat, sun"))


def _validate_triggers(value: object, path: str, errors: list[str]) -> None:
    items = _as_list(value, path, errors)
    for index, item in enumerate(items or []):
        _validate_trigger(item, f"{path}[{index}]", errors)


def _validate_trigger(item: object, path: str, errors: list[str]) -> None:
    if not isinstance(item, dict):
        errors.append(_err(path, "must be a mapping"))
        return
    if not _required(item, "trigger", path, errors):
        return
    kind = item["trigger"]
    if not _check_kind(kind, TRIGGER_KEYS, "trigger", path, errors):
        return
    _check_keys(item, TRIGGER_KEYS[kind], path, errors)
    if kind == "state":
        _check_text(item, "entity_id", path, errors)
        _check_text(item, "from", path, errors, required=False)
        _check_text(item, "to", path, errors, required=False)
        _check_duration(item, "for", path, errors)
    elif kind == "numeric_state":
        _check_text(item, "entity_id", path, errors)
        _check_number(item, "above", path, errors)
        _check_number(item, "below", path, errors)
        if "above" not in item and "below" not in item:
            errors.append(_err(path, "above or below required"))
        _check_duration(item, "for", path, errors)
    elif kind == "time":
        _check_clock(item, "at", path, errors)
        _check_weekdays(item, path, errors)
    elif kind == "time_pattern":
        _check_pattern(item, "hours", 23, path, errors)
        _check_pattern(item, "minutes", 59, path, errors)
        _check_pattern(item, "seconds", 59, path, errors)
    else:
        _check_text(item, "entity_id", path, errors)
        if "event" in item and not _is_template(item["event"]) and item["event"] not in CALENDAR_EVENTS:
            errors.append(_err(_join(path, "event"), "must be start or end"))
        _required(item, "event", path, errors)
        _check_duration(item, "offset", path, errors)
        _check_duration(item, "duration", path, errors)


def _validate_conditions(value: object, path: str, errors: list[str]) -> None:
    items = _as_list(value, path, errors)
    for index, item in enumerate(items or []):
        _validate_condition(item, f"{path}[{index}]", errors)


def _validate_condition(item: object, path: str, errors: list[str]) -> None:
    if not isinstance(item, dict):
        errors.append(_err(path, "must be a mapping"))
        return
    if not _required(item, "condition", path, errors):
        return
    kind = item["condition"]
    if not _check_kind(kind, CONDITION_KEYS, "condition", path, errors):
        return
    _check_keys(item, CONDITION_KEYS[kind], path, errors)
    if kind == "state":
        _check_text(item, "entity_id", path, errors)
        _check_text(item, "state", path, errors)
    elif kind == "numeric_state":
        _check_text(item, "entity_id", path, errors)
        _check_number(item, "above", path, errors)
        _check_number(item, "below", path, errors)
    elif kind == "time":
        _check_clock(item, "after", path, errors, required=False)
        _check_clock(item, "before", path, errors, required=False)
        _check_weekdays(item, path, errors)
    elif _required(item, "conditions", path, errors):
        _validate_conditions(item["conditions"], _join(path, "conditions"), errors)


def _validate_actions(value: object, path: str, limits: _Limits, errors: list[str]) -> None:
    items = _as_list(value, path, errors)
    for index, item in enumerate(items or []):
        _validate_action(item, f"{path}[{index}]", limits, errors)


def _validate_action(item: object, path: str, limits: _Limits, errors: list[str]) -> None:
    if not isinstance(item, dict):
        errors.append(_err(path, "must be a mapping"))
    elif "action" in item:
        _validate_service(item, path, limits, errors)
    elif "delay" in item:
        _check_keys(item, {"delay"}, path, errors)
        _check_duration(item, "delay", path, errors)
    elif "if" in item:
        _validate_if(item, path, limits, errors)
    elif "choose" in item:
        _validate_choose(item, path, limits, errors)
    elif "condition" in item:
        _validate_condition(item, path, errors)
    elif any(key in UNSUPPORTED_TYPES for key in item):
        errors.append(_err(path, "not supported yet"))
    else:
        errors.append(_err(path, "unknown action"))


def _validate_service(item: dict, path: str, limits: _Limits, errors: list[str]) -> None:
    service = item["action"]
    if _is_template(service):
        return
    if not _check_kind(service, SERVICE_KEYS, "action", path, errors):
        return
    _check_keys(item, SERVICE_KEYS[service], path, errors)
    if service == HTTP_SERVICE:
        _check_http(item, path, errors)
    elif service == SCRIPT_SERVICE:
        _check_script(item, path, limits, errors)
    elif service == NOTIFY_EMAIL_SERVICE:
        _check_notify(item, path, errors)
    elif service == EVENT_SERVICE:
        _check_event(item, path, errors)
    else:
        _check_target(item, path, errors, automation=service in AUTOMATION_SERVICES)
        if service in SWITCH_SERVICES:
            _check_duration(item, "for", path, errors)
        if service == LIGHT_SERVICE:
            _check_light_data(item, path, errors)


def _check_target(item: dict, path: str, errors: list[str], automation: bool = False) -> None:
    if not _required(item, "target", path, errors):
        return
    target = item["target"]
    target_path = _join(path, "target")
    if _is_template(target):
        return
    if not isinstance(target, dict):
        errors.append(_err(target_path, "must be a mapping"))
        return
    _check_keys(target, {"entity_id"}, target_path, errors)
    if not _required(target, "entity_id", target_path, errors):
        return
    value = target["entity_id"]
    if _is_template(value):
        return
    names = value if isinstance(value, list) else [value]
    field = _join(target_path, "entity_id")
    if not names or not all(_is_template(name) or (isinstance(name, str) and name) for name in names):
        errors.append(_err(field, "must be a non-empty string or a list of them"))
        return
    if not automation:
        return
    for name in names:
        if _is_template(name):
            continue
        bare = name[len("automation."):] if name.startswith("automation.") else name
        if ID_RE.fullmatch(bare) is None:
            errors.append(_err(field, "must be automation.<id> or <id>"))


def _check_light_data(item: dict, path: str, errors: list[str]) -> None:
    if "data" not in item:
        return
    data = item["data"]
    data_path = _join(path, "data")
    if _is_template(data):
        return
    if not isinstance(data, dict):
        errors.append(_err(data_path, "must be a mapping"))
        return
    _check_keys(data, {"brightness"}, data_path, errors)
    if "brightness" in data and not _is_template(data["brightness"]):
        if not _is_int(data["brightness"], 0, 100):
            errors.append(_err(_join(data_path, "brightness"), "must be an integer from 0 to 100"))


def _check_http(item: dict, path: str, errors: list[str]) -> None:
    if not _required(item, "data", path, errors):
        return
    data = item["data"]
    data_path = _join(path, "data")
    if _is_template(data):
        return
    if not isinstance(data, dict):
        errors.append(_err(data_path, "must be a mapping"))
        return
    _check_keys(data, {"url", "payload"}, data_path, errors)
    if not _required(data, "url", data_path, errors):
        return
    url = data["url"]
    if _is_template(url):
        return
    if not isinstance(url, str) or URL_RE.fullmatch(url) is None:
        errors.append(_err(_join(data_path, "url"), "must be http or https"))


def _check_script(item: dict, path: str, limits: _Limits, errors: list[str]) -> None:
    if not limits.allow_script_action:
        errors.append(_err(path, "script action is disabled"))
    if not _required(item, "data", path, errors):
        return
    data = item["data"]
    data_path = _join(path, "data")
    if _is_template(data):
        return
    if not isinstance(data, dict):
        errors.append(_err(data_path, "must be a mapping"))
        return
    _check_keys(data, {"entity_id", "text"}, data_path, errors)
    _check_text(data, "entity_id", data_path, errors)
    if not _required(data, "text", data_path, errors):
        return
    text = data["text"]
    if _is_template(text):
        return
    if not isinstance(text, str) or not text:
        errors.append(_err(_join(data_path, "text"), "must be a non-empty string"))
        return
    if len(text) > limits.script_max_length:
        errors.append(_err(path, "script text too long"))


def _check_notify(item: dict, path: str, errors: list[str]) -> None:
    if not _required(item, "data", path, errors):
        return
    data = item["data"]
    data_path = _join(path, "data")
    if _is_template(data):
        return
    if not isinstance(data, dict):
        errors.append(_err(data_path, "must be a mapping"))
        return
    _check_keys(data, {"addr", "subject", "body", "key", "hold_minutes"}, data_path, errors)
    if _required(data, "addr", data_path, errors):
        addr = data["addr"]
        addr_path = _join(data_path, "addr")
        if not _is_template(addr) and (
            not isinstance(addr, list)
            or not addr
            or not all(_is_template(name) or (isinstance(name, str) and name) for name in addr)
        ):
            errors.append(_err(addr_path, "must be a non-empty list of non-empty strings"))
    _check_text(data, "body", data_path, errors)
    _check_text(data, "subject", data_path, errors, required=False)
    _check_text(data, "key", data_path, errors, required=False)
    if "hold_minutes" in data and not _is_template(data["hold_minutes"]):
        if not _is_int(data["hold_minutes"], 0, 10 ** 9):
            errors.append(_err(_join(data_path, "hold_minutes"), "must be an integer from 0 to 1000000000"))


def _check_event(item: dict, path: str, errors: list[str]) -> None:
    if not _required(item, "data", path, errors):
        return
    data = item["data"]
    data_path = _join(path, "data")
    if _is_template(data):
        return
    if not isinstance(data, dict):
        errors.append(_err(data_path, "must be a mapping"))
        return
    _check_keys(data, {"key", "msg", "device", "level", "dedup_minutes"}, data_path, errors)
    _check_text(data, "key", data_path, errors)
    _check_text(data, "msg", data_path, errors)
    if "dedup_minutes" in data and not _is_template(data["dedup_minutes"]):
        if not _is_int(data["dedup_minutes"], 0, 10 ** 9):
            errors.append(_err(_join(data_path, "dedup_minutes"), "must be an integer from 0 to 1000000000"))
    if "level" in data and not _is_template(data["level"]):
        if not _is_int(data["level"], 0, 10):
            errors.append(_err(_join(data_path, "level"), "must be an integer from 0 to 10"))


def _validate_if(item: dict, path: str, limits: _Limits, errors: list[str]) -> None:
    _check_keys(item, {"if", "then", "else"}, path, errors)
    _validate_conditions(item["if"], _join(path, "if"), errors)
    if _required(item, "then", path, errors):
        _validate_actions(item["then"], _join(path, "then"), limits, errors)
    if "else" in item:
        _validate_actions(item["else"], _join(path, "else"), limits, errors)


def _validate_choose(item: dict, path: str, limits: _Limits, errors: list[str]) -> None:
    _check_keys(item, {"choose", "default"}, path, errors)
    _validate_branches(item["choose"], _join(path, "choose"), limits, errors)
    if "default" in item:
        _validate_actions(item["default"], _join(path, "default"), limits, errors)


def _validate_branches(value: object, path: str, limits: _Limits, errors: list[str]) -> None:
    branches = _as_list(value, path, errors)
    for index, branch in enumerate(branches or []):
        branch_path = f"{path}[{index}]"
        if not isinstance(branch, dict):
            errors.append(_err(branch_path, "must be a mapping"))
            continue
        _check_keys(branch, {"conditions", "sequence"}, branch_path, errors)
        if _required(branch, "conditions", branch_path, errors):
            _validate_conditions(branch["conditions"], _join(branch_path, "conditions"), errors)
        if _required(branch, "sequence", branch_path, errors):
            _validate_actions(branch["sequence"], _join(branch_path, "sequence"), limits, errors)


# ---------------------------------------------------------------- engine helpers


def _second_of_day(local: time.struct_time) -> int:
    return local.tm_hour * 3600 + local.tm_min * 60 + local.tm_sec


def _clock_seconds(text: str) -> int:
    """Seconds since midnight of 'HH:MM' or 'HH:MM:SS'; validate() has already checked the text."""
    if len(text) == 5:
        text += ":00"
    return int(parse_duration(text))


def _in_range(item: dict, value: object) -> bool:
    """True when value is a number above and below the limits of item; an absent limit does not count."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    if "above" in item and not value > item["above"]:
        return False
    if "below" in item and not value < item["below"]:
        return False
    return True


def _pattern_matches(spec: object, value: int) -> bool:
    """Match one field of a time_pattern: '*', a number, or '/N' (every N)."""
    if spec == "*":
        return True
    if isinstance(spec, str):
        return value % int(spec[1:]) == 0
    return value == spec


def _weekday_ok(item: dict, local: time.struct_time) -> bool:
    """True when the item has no weekday list, or the local day is in it."""
    return "weekday" not in item or WEEKDAYS[local.tm_wday] in item["weekday"]


def _time_due(item: dict, local: time.struct_time) -> bool:
    """True when the local clock matches a time or a time_pattern trigger on an allowed weekday."""
    if not _weekday_ok(item, local):
        return False
    if item["trigger"] == "time":
        return _second_of_day(local) == _clock_seconds(item["at"])
    has_hm = "hours" in item or "minutes" in item
    specs = (
        (item.get("hours", "*"), local.tm_hour),
        (item.get("minutes", "*"), local.tm_min),
        (item.get("seconds", 0 if has_hm else "*"), local.tm_sec),
    )
    return all(_pattern_matches(spec, value) for spec, value in specs)


def _triggers(auto: _Automation) -> list[tuple[int, dict]]:
    """The trigger mappings of an automation with their index in the list."""
    items = auto.obj.get("triggers") or []
    return [(index, item) for index, item in enumerate(items) if isinstance(item, dict)]


def _entity_ids(item: dict) -> list[str]:
    value = item["target"]["entity_id"]
    return list(value) if isinstance(value, list) else [value]


def _automation_id(entity_id: str) -> str:
    """'automation.<id>' or '<id>' gives '<id>'."""
    return entity_id[len("automation."):] if entity_id.startswith("automation.") else entity_id


def _step(trace: dict, path: str, result: str) -> None:
    trace["steps"].append({"path": path, "result": result})


def _fail(trace: dict, path: str, message: str) -> str:
    """Record the failed step and the message of the run; return the 'error' result."""
    _step(trace, path, "error")
    trace["message"] = message
    return "error"


# ---------------------------------------------------------------- engine


class AutomationEngine:
    """Runs the automations: triggers, conditions, actions, delays, modes, vacation mode and traces."""

    def __init__(
        self,
        entities: Callable[[str], object],
        set_output: Callable[[str, int, int], None],
        resolve: Callable[[str], tuple[str, int] | None],
        clock: Callable[[], float],
        *,
        localtime: Callable[[float], time.struct_time] = time.localtime,
        set_brightness: Callable[[str, int, int, int], None] | None = None,
        run_scene: Callable[[str], None] | None = None,
        http_post: Callable[[str, object], None] | None = None,
        serial_send: Callable[[str, int, str], None] | None = None,
        serial_target: Callable[[str], tuple[str, int] | None] | None = None,
        notify_email: Callable[[dict], None] | None = None,
        record_event: Callable[[dict], None] | None = None,
        allow_script_action: bool = False,
        script_max_length: int = DEFAULT_SCRIPT_MAX_LENGTH,
        max_depth: int = DEFAULT_MAX_DEPTH,
    ) -> None:
        self._entities = entities
        self._set_output = set_output
        self._resolve = resolve
        self._clock = clock
        self._localtime = localtime
        self._set_brightness = set_brightness
        self._run_scene = run_scene
        self._http_post = http_post
        self._serial_send = serial_send
        self._serial_target = serial_target
        self._notify_email = notify_email
        self._record_event = record_event
        self._allow_script = allow_script_action is True
        self._script_max_length = script_max_length
        self._max_depth = max_depth
        self._lock = threading.RLock()
        self._automations: dict[str, _Automation] = {}
        self._ids = count(1)
        self._now = 0.0
        self._vacation: list[str] = []

    def load(self, automations: list[dict]) -> None:
        """Replace all the automations. Runs in progress end with result 'stopped'.

        The traces of an automation that keeps its id are carried over, so an edit does not erase its history.
        """
        with self._lock:
            loaded: dict[str, _Automation] = {}
            for obj in automations:
                if not isinstance(obj, dict):
                    raise ValueError("automation must be a mapping")
                normal = normalize(obj)
                automation_id = normal.get("id")
                if not isinstance(automation_id, str):
                    raise ValueError("automation needs an id")
                if automation_id in loaded:
                    raise ValueError(f"duplicate automation id {automation_id}")
                loaded[automation_id] = _Automation(normal)
            self._now = self._clock()
            old = self._automations
            for auto in old.values():
                auto.queue.clear()
                for run in list(auto.running):
                    self._finish(auto, run, "stopped")
            for automation_id, auto in loaded.items():
                if automation_id in old:
                    auto.traces.extend(old[automation_id].traces)
            self._automations = loaded

    def tick(self, now: float) -> None:
        """Advance to 'now': resume the runs whose delay ended, start the due waits and the time triggers."""
        with self._lock:
            self._now = now
            local = self._localtime(now)
            second = int(now)
            for auto in list(self._automations.values()):
                self._resume(auto, now)
                if auto.obj["enabled"]:
                    self._due_waits(auto, now)
                    self._time_triggers(auto, local, second)

    def entity_changed(self, entity_id: str, old: object, new: object) -> None:
        """Evaluate the state and numeric_state triggers of entity_id after a change from old to new."""
        with self._lock:
            self._now = self._clock()
            for auto in list(self._automations.values()):
                if not auto.obj["enabled"]:
                    continue
                for index, item in _triggers(auto):
                    if item.get("entity_id") != entity_id:
                        continue
                    if item.get("trigger") == "state":
                        self._state_event(auto, index, item, old, new)
                    elif item.get("trigger") == "numeric_state":
                        self._numeric_event(auto, index, item, old, new)

    def calendar_fired(self, entity_id: str, event: str) -> None:
        """Run the enabled automations whose calendar trigger matches entity_id and event now.

        The offset and the duration of a calendar trigger are only validated; they are not applied here.
        """
        with self._lock:
            self._now = self._clock()
            for auto in list(self._automations.values()):
                if not auto.obj["enabled"]:
                    continue
                for index, item in _triggers(auto):
                    if (
                        item.get("trigger") == "calendar"
                        and item.get("entity_id") == entity_id
                        and item.get("event") == event
                    ):
                        self._request(auto, f"triggers[{index}]")

    def trigger(self, automation_id: str) -> None:
        """Run the actions of an automation now. Triggers are skipped, the conditions are still checked.

        The enabled flag is ignored. Raises KeyError for an unknown id.
        """
        with self._lock:
            self._now = self._clock()
            self._request(self._automations[automation_id], "manual")

    def traces(self, automation_id: str) -> list[dict]:
        """Return the last runs of an automation, oldest first. Raises KeyError for an unknown id."""
        with self._lock:
            return deepcopy(list(self._automations[automation_id].traces))

    def set_vacation(self, on: bool, entity_ids=()) -> None:
        """Turn vacation mode on or off.

        On: record entity_ids; no output changes. Off: switch off every recorded port and clear the record.
        A port that cannot be switched off is reported in a RuntimeError after all ports were tried.
        """
        if not isinstance(on, bool):
            raise ValueError("on must be true or false")
        with self._lock:
            if on:
                for entity_id in _entity_list(entity_ids):
                    if entity_id not in self._vacation:
                        self._vacation.append(entity_id)
                return
            failures: list[str] = []
            for entity_id in self._vacation:
                try:
                    mac, port = self._locate(entity_id)
                    self._set_output(mac, port, 0)
                except Exception as exc:
                    failures.append(f"{entity_id}: {exc}")
            self._vacation = []
            if failures:
                raise RuntimeError("vacation mode end failed: " + "; ".join(failures))

    # ---- runs and waits

    def _resume(self, auto: _Automation, now: float) -> None:
        for run in list(auto.running):
            if not run.done and run.resume_at is not None and run.resume_at <= now:
                run.resume_at = None
                self._advance(auto, run)

    def _due_waits(self, auto: _Automation, now: float) -> None:
        for index, due in list(auto.pending.items()):
            if due <= now:
                auto.pending.pop(index)
                self._request(auto, f"triggers[{index}]")

    def _time_triggers(self, auto: _Automation, local: time.struct_time, second: int) -> None:
        for index, item in _triggers(auto):
            if item.get("trigger") not in TIME_KINDS or auto.last_fired.get(index) == second:
                continue
            if _time_due(item, local):
                auto.last_fired[index] = second
                self._request(auto, f"triggers[{index}]")

    def _state_event(self, auto: _Automation, index: int, item: dict, old: object, new: object) -> None:
        holds = "to" not in item or new == item["to"]
        if not holds:
            auto.pending.pop(index, None)
        elif old != new and ("from" not in item or old == item["from"]):
            self._start_wait(auto, index, item)

    def _numeric_event(self, auto: _Automation, index: int, item: dict, old: object, new: object) -> None:
        if not _in_range(item, new):
            auto.pending.pop(index, None)
        elif not _in_range(item, old):
            self._start_wait(auto, index, item)

    def _start_wait(self, auto: _Automation, index: int, item: dict) -> None:
        """Fire the trigger now, or arm its 'for' wait when it has one and none is armed yet."""
        if "for" not in item:
            self._request(auto, f"triggers[{index}]")
        elif index not in auto.pending:
            auto.pending[index] = self._now + parse_duration(item["for"])

    def _request(self, auto: _Automation, label: str) -> None:
        """Start a run of the automation, or queue, skip or replace it, as its mode says."""
        mode = auto.obj["mode"]
        limit = auto.obj["max"]
        if mode == "restart":
            for run in list(auto.running):
                self._finish(auto, run, "stopped")
            self._launch(auto, label)
        elif mode == "parallel":
            if len(auto.running) < limit:
                self._launch(auto, label)
            else:
                self._skip(auto, label)
        elif mode == "queued":
            if not auto.running and not auto.queue:
                self._launch(auto, label)
            elif len(auto.running) + len(auto.queue) < limit:
                auto.queue.append(label)
            else:
                self._skip(auto, label)
        elif auto.running:
            self._skip(auto, label)
        else:
            self._launch(auto, label)

    def _launch(self, auto: _Automation, label: str) -> None:
        trace = {
            "run_id": next(self._ids),
            "trigger": label,
            "start": self._now,
            "end": None,
            "result": None,
            "steps": [],
            "message": None,
        }
        run = _Run(self._body(auto.obj, trace, 0, ""), trace)
        auto.running.append(run)
        self._advance(auto, run)

    def _skip(self, auto: _Automation, label: str) -> None:
        auto.traces.append(
            {
                "run_id": next(self._ids),
                "trigger": label,
                "start": self._now,
                "end": self._now,
                "result": "skipped",
                "steps": [],
                "message": None,
            }
        )

    def _advance(self, auto: _Automation, run: _Run) -> None:
        """Run an execution until it waits for a delay or ends. An exception is recorded in the trace."""
        try:
            _, seconds = next(run.generator)
        except StopIteration as stop:
            self._finish(auto, run, stop.value)
            return
        except Exception as exc:
            run.trace["message"] = str(exc) or type(exc).__name__
            self._finish(auto, run, "error")
            return
        run.resume_at = self._now + seconds

    def _finish(self, auto: _Automation, run: _Run, result: str) -> None:
        run.generator.close()
        run.done = True
        run.trace["result"] = result
        run.trace["end"] = self._now
        auto.running.remove(run)
        auto.traces.append(run.trace)
        self._pump(auto)

    def _pump(self, auto: _Automation) -> None:
        """Start the queued runs of an automation while nothing runs."""
        while auto.queue and not auto.running:
            self._launch(auto, auto.queue.popleft())

    # ---- execution steps (generators: a delay suspends them)

    def _body(self, obj: dict, trace: dict, depth: int, prefix: str) -> Generator:
        """The whole execution: the automation conditions first, then the actions."""
        if not self._all(obj.get("conditions") or []):
            _step(trace, prefix + "conditions", "condition_false")
            return "condition_false"
        status = yield from self._sequence(obj.get("actions") or [], prefix + "actions", trace, depth)
        return "finished" if status == "ok" else status

    def _sequence(self, items: list, base: str, trace: dict, depth: int) -> Generator:
        for index, item in enumerate(items):
            status = yield from self._action(item, f"{base}[{index}]", trace, depth)
            if status != "ok":
                return status
        return "ok"

    def _action(self, item: object, path: str, trace: dict, depth: int) -> Generator:
        """Run one step. Returns 'ok', 'condition_false' or 'error'; a delay suspends the run."""
        if not isinstance(item, dict):
            return _fail(trace, path, "action must be a mapping")
        if "action" in item:
            service = item["action"]
            if service in SWITCH_SERVICES:
                return (yield from self._switch(item, path, trace))
            if service == "automation.trigger":
                return (yield from self._run_inline(item, path, trace, depth))
            return self._plain(item, path, trace)
        if "delay" in item:
            try:
                seconds = parse_duration(item["delay"])
            except ValueError as exc:
                return _fail(trace, path, str(exc))
            yield ("delay", seconds)
            _step(trace, path, "ok")
            return "ok"
        if "if" in item:
            branch = "then" if self._all(item["if"]) else "else"
            _step(trace, path, branch)
            return (yield from self._sequence(item.get(branch) or [], f"{path}.{branch}", trace, depth))
        if "choose" in item:
            return (yield from self._choose(item, path, trace, depth))
        if "condition" not in item:
            return _fail(trace, path, "unknown action")
        if self._condition(item):
            _step(trace, path, "ok")
            return "ok"
        _step(trace, path, "condition_false")
        return "condition_false"

    def _choose(self, item: dict, path: str, trace: dict, depth: int) -> Generator:
        for index, branch in enumerate(item["choose"]):
            if self._all(branch["conditions"]):
                _step(trace, path, f"choose[{index}]")
                return (
                    yield from self._sequence(branch["sequence"], f"{path}.choose[{index}].sequence", trace, depth)
                )
        if "default" not in item:
            _step(trace, path, "none")
            return "ok"
        _step(trace, path, "default")
        return (yield from self._sequence(item["default"], f"{path}.default", trace, depth))

    def _run_inline(self, item: dict, path: str, trace: dict, depth: int) -> Generator:
        """Run the body of each target automation inside this run, one level deeper.

        The depth guard stops a loop of automation.trigger calls at max_depth.
        """
        try:
            ids = [_automation_id(entity_id) for entity_id in _entity_ids(item)]
        except Exception as exc:
            return _fail(trace, path, str(exc) or type(exc).__name__)
        for automation_id in ids:
            target = self._automations.get(automation_id)
            if target is None:
                return _fail(trace, path, f"unknown automation {automation_id}")
            if depth + 1 > self._max_depth:
                return _fail(trace, path, "max automation depth reached")
            status = yield from self._body(target.obj, trace, depth + 1, f"{path}.")
            if status == "error":
                return "error"
        _step(trace, path, "ok")
        return "ok"

    def _switch(self, item: dict, path: str, trace: dict) -> Generator:
        """Set the outputs of a switch action; with 'for' wait, then perform the inverse action."""
        service = item["action"]
        try:
            entity_ids = _entity_ids(item)
            for entity_id in entity_ids:
                self._locate(entity_id)
            seconds = parse_duration(item["for"]) if "for" in item else None
            self._set_switches(service, entity_ids)
        except Exception as exc:
            return _fail(trace, path, str(exc) or type(exc).__name__)
        if seconds is not None:
            yield ("delay", seconds)
            try:
                self._set_switches(INVERSE[service], entity_ids)
            except Exception as exc:
                return _fail(trace, path, str(exc) or type(exc).__name__)
        _step(trace, path, "ok")
        return "ok"

    def _plain(self, item: dict, path: str, trace: dict) -> str:
        """Run a service action that does not wait: light, scene, automation flags, http_post, script, e-mail and event recording."""
        service = item["action"]
        if service == LIGHT_SERVICE:
            return self._light(item, path, trace)
        if service == SCENE_SERVICE:
            return self._scene(item, path, trace)
        if service in ("automation.turn_on", "automation.turn_off"):
            return self._automation_flag(item, path, trace, service == "automation.turn_on")
        if service == HTTP_SERVICE:
            return self._http(item, path, trace)
        if service == SCRIPT_SERVICE:
            return self._script(item, path, trace)
        if service == NOTIFY_EMAIL_SERVICE:
            return self._notify(item, path, trace)
        if service == EVENT_SERVICE:
            return self._event(item, path, trace)
        return _fail(trace, path, f"unknown service {service}")

    # ---- outputs and devices

    def _locate(self, entity_id: str) -> tuple[str, int]:
        located = self._resolve(entity_id)
        if located is None:
            raise LookupError(f"unknown entity {entity_id}")
        return located

    def _set_switches(self, service: str, entity_ids: list[str]) -> None:
        for entity_id in entity_ids:
            mac, port = self._locate(entity_id)
            if service == "switch.toggle":
                value = 0 if self._entities(entity_id) == "on" else 1
            else:
                value = 1 if service == "switch.turn_on" else 0
            self._set_output(mac, port, value)

    def _light(self, item: dict, path: str, trace: dict) -> str:
        try:
            data = item.get("data") or {}
            brightness = data.get("brightness")
            for entity_id in _entity_ids(item):
                mac, port = self._locate(entity_id)
                self._set_output(mac, port, 1)
                if brightness is not None and self._set_brightness is not None:
                    self._set_brightness(mac, port, 1, brightness)
        except Exception as exc:
            return _fail(trace, path, str(exc) or type(exc).__name__)
        _step(trace, path, "ok")
        return "ok"

    def _scene(self, item: dict, path: str, trace: dict) -> str:
        if self._run_scene is None:
            return _fail(trace, path, "scene support not configured")
        try:
            for entity_id in _entity_ids(item):
                self._run_scene(entity_id)
        except Exception as exc:
            return _fail(trace, path, str(exc) or type(exc).__name__)
        _step(trace, path, "ok")
        return "ok"

    def _automation_flag(self, item: dict, path: str, trace: dict, enabled: bool) -> str:
        try:
            ids = [_automation_id(entity_id) for entity_id in _entity_ids(item)]
            for automation_id in ids:
                if automation_id not in self._automations:
                    raise LookupError(f"unknown automation {automation_id}")
            for automation_id in ids:
                self._automations[automation_id].obj["enabled"] = enabled
        except Exception as exc:
            return _fail(trace, path, str(exc) or type(exc).__name__)
        _step(trace, path, "ok")
        return "ok"

    def _http(self, item: dict, path: str, trace: dict) -> str:
        if self._http_post is None:
            return _fail(trace, path, "http_post support not configured")
        try:
            data = item["data"]
            url = data["url"]
            if not isinstance(url, str) or URL_RE.fullmatch(url) is None:
                raise ValueError("url must be http or https")
            self._http_post(url, data.get("payload"))
        except Exception as exc:
            return _fail(trace, path, str(exc) or type(exc).__name__)
        _step(trace, path, "ok")
        return "ok"

    def _script(self, item: dict, path: str, trace: dict) -> str:
        """Send the text to the serial line of an adopted mPort Serial. Off unless the owner enabled it."""
        if not self._allow_script:
            return _fail(trace, path, "script action is disabled")
        try:
            data = item["data"]
            entity_id = data["entity_id"]
            text = data["text"]
            if not isinstance(text, str):
                raise ValueError("script text must be a string")
            if len(text) > self._script_max_length:
                return _fail(trace, path, "script text too long")
            if self._serial_send is None or self._serial_target is None:
                return _fail(trace, path, "script support not configured")
            target = self._serial_target(entity_id)
            if target is None:
                return _fail(trace, path, "device is not an adopted mPort Serial")
            host, port = target
            self._serial_send(host, port, text)
        except Exception as exc:
            return _fail(trace, path, str(exc) or type(exc).__name__)
        _step(trace, path, "ok")
        return "ok"

    def _notify(self, item: dict, path: str, trace: dict) -> str:
        """Hand the e-mail data to the injected sender. Off until a sender is configured."""
        if self._notify_email is None:
            return _fail(trace, path, "email notification not configured")
        try:
            self._notify_email(item["data"])
        except Exception as exc:
            return _fail(trace, path, str(exc) or type(exc).__name__)
        _step(trace, path, "ok")
        return "ok"

    def _event(self, item: dict, path: str, trace: dict) -> str:
        """Hand the event data to the injected recorder. Off until a recorder is configured."""
        if self._record_event is None:
            return _fail(trace, path, "event recording not configured")
        try:
            self._record_event(item["data"])
        except Exception as exc:
            return _fail(trace, path, str(exc) or type(exc).__name__)
        _step(trace, path, "ok")
        return "ok"

    # ---- conditions

    def _all(self, conditions: list) -> bool:
        return all(self._condition(item) for item in conditions)

    def _condition(self, item: dict) -> bool:
        if not isinstance(item, dict):
            raise ValueError("condition must be a mapping")
        kind = item.get("condition")
        if kind == "state":
            return self._entities(item["entity_id"]) == item["state"]
        if kind == "numeric_state":
            return _in_range(item, self._entities(item["entity_id"]))
        if kind == "time":
            return self._time_ok(item)
        if kind == "and":
            return self._all(item["conditions"])
        if kind == "or":
            return any(self._condition(child) for child in item["conditions"])
        if kind == "not":
            return not any(self._condition(child) for child in item["conditions"])
        raise ValueError(f"unknown condition {kind}")

    def _time_ok(self, item: dict) -> bool:
        """True when the local time of the tick is on a listed weekday and inside the window.

        'after' is inclusive and 'before' is exclusive; with after later than before the window crosses midnight.
        """
        local = self._localtime(self._now)
        if not _weekday_ok(item, local):
            return False
        if "after" not in item and "before" not in item:
            return True
        now_s = _second_of_day(local)
        after = _clock_seconds(item["after"]) if "after" in item else 0
        before = _clock_seconds(item["before"]) if "before" in item else DAY_SECONDS
        if after <= before:
            return after <= now_s < before
        return now_s >= after or now_s < before


def _entity_list(value: object) -> list[str]:
    """A list of non-empty entity ids; a single string is refused so it is not read as a list of letters."""
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise ValueError("entity_ids must be a list of entity ids")
    for entity_id in value:
        if not isinstance(entity_id, str) or not entity_id:
            raise ValueError("entity_ids must be a list of entity ids")
    return list(value)


# ---------------------------------------------------------------- store


def _index_of(automations: list[dict], automation_id: str) -> int:
    for index, item in enumerate(automations):
        if isinstance(item, dict) and item.get("id") == automation_id:
            return index
    raise ValueError(f"unknown automation {automation_id}")


class AutomationStore:
    """Keeps the automation definitions in automations.json, through the Store of the data folder."""

    def __init__(self, store, *, filename: str = DEFAULT_FILENAME) -> None:
        self._store = store
        self._filename = filename

    def load(self) -> list[dict]:
        """Return the normalized automations. A missing file is an empty list; a damaged file raises ValueError."""
        raw = self._store.read_json(self._filename, {"schema": SCHEMA, "automations": []})
        if not isinstance(raw, dict):
            raise ValueError(f"{self._filename}: the top level must be a JSON object")
        if type(raw.get("schema")) is not int or raw["schema"] != SCHEMA:
            raise ValueError(f"{self._filename}: schema must be {SCHEMA}")
        automations = raw.get("automations")
        if not isinstance(automations, list):
            raise ValueError(f"{self._filename}: automations must be a list")
        result = []
        for item in automations:
            if not isinstance(item, dict):
                raise ValueError(f"{self._filename}: every automation must be a mapping")
            result.append(normalize(item))
        return result

    def save(self, automations: list[dict]) -> None:
        """Write the normalized automations, sorted by id, to the archive file (mode 0600)."""
        clean = []
        for item in automations:
            if not isinstance(item, dict):
                raise ValueError("every automation must be a mapping")
            clean.append(normalize(item))
        clean.sort(key=lambda item: str(item.get("id", "")))
        self._store.write_json(self._filename, {"schema": SCHEMA, "automations": clean}, private=True)

    def copy(self, automations: list[dict], source_id: str, new_id: str) -> list[dict]:
        """Return a new list with a deep copy of source_id under new_id, appended at the end."""
        if not isinstance(new_id, str) or ID_RE.fullmatch(new_id) is None:
            raise ValueError("new id must match [a-z0-9_]{1,64}")
        source = automations[_index_of(automations, source_id)]
        if any(isinstance(item, dict) and item.get("id") == new_id for item in automations):
            raise ValueError(f"automation {new_id} already exists")
        clone = deepcopy(source)
        clone["id"] = new_id
        return [deepcopy(item) for item in automations] + [clone]

    def set_enabled(self, automations: list[dict], automation_id: str, enabled: bool) -> list[dict]:
        """Return a new list in which the enabled flag of automation_id is set."""
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be true or false")
        index = _index_of(automations, automation_id)
        result = [deepcopy(item) for item in automations]
        result[index]["enabled"] = enabled
        return result
