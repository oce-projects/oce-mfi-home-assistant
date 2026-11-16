"""Model of the automations of mfi-server, in the format of Home Assistant.

Standard library only. normalize() converts the old Home Assistant keys to the
current ones and fills in the defaults. validate() lists every problem as
"<path>: <reason>". parse_duration() reads a duration in seconds. Evaluating the
triggers is the job of automation_engine, not of this module.
"""
from __future__ import annotations

import copy
import math
import re

MODES = ("single", "restart", "queued", "parallel")
DEFAULT_MODE = "single"
DEFAULT_MAX = 10
MAX_LIMIT = 100
TEMPLATE_MARK = "{{"
ID_RE = re.compile(r"[a-z0-9_]{1,64}")
CLOCK_RE = re.compile(r"([0-9]{2}):([0-9]{2})(?::([0-9]{2}))?")
DURATION_RE = re.compile(r"([0-9]+):([0-5][0-9]):([0-5][0-9])")
PATTERN_RE = re.compile(r"/([0-9]+)")
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DURATION_UNITS = {"hours": 3600, "minutes": 60, "seconds": 1}
UNSUPPORTED_TYPES = frozenset(
    {"sun", "mqtt", "repeat", "wait_template", "wait_for_trigger", "variables", "event", "template"}
)
SWITCH_SERVICES = ("switch.turn_on", "switch.turn_off", "switch.toggle")
TOP_KEYS = frozenset({"id", "alias", "description", "enabled", "mode", "max", "triggers", "conditions", "actions"})
TRIGGER_KEYS = {
    "state": frozenset({"trigger", "entity_id", "from", "to", "for"}),
    "numeric_state": frozenset({"trigger", "entity_id", "above", "below", "for"}),
    "time": frozenset({"trigger", "at"}),
    "time_pattern": frozenset({"trigger", "hours", "minutes", "seconds"}),
}
CONDITION_KEYS = {
    "state": frozenset({"condition", "entity_id", "state"}),
    "numeric_state": frozenset({"condition", "entity_id", "above", "below"}),
    "time": frozenset({"condition", "after", "before", "weekday"}),
    "and": frozenset({"condition", "conditions"}),
    "or": frozenset({"condition", "conditions"}),
    "not": frozenset({"condition", "conditions"}),
}


def normalize(obj: dict) -> dict:
    """Return a new automation in the current format: old keys renamed, defaults filled in. Idempotent."""
    result = copy.deepcopy(obj)
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


def validate(obj: dict) -> list[str]:
    """Return the problems of an automation as "<path>: <reason>" strings; an empty list means valid."""
    if not isinstance(obj, dict):
        return ["not a mapping"]
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
        _validate_actions(model["actions"], "actions", errors)
    return errors


def parse_duration(value: object) -> float:
    """Return a duration in seconds from "HH:MM:SS" (or "H:MM:SS") or from a mapping of hours, minutes and seconds.

    Raises ValueError when the value is not a valid duration.
    """
    if isinstance(value, str):
        match = DURATION_RE.fullmatch(value)
        if match is None:
            raise ValueError(f"invalid duration: {value!r}")
        hours, minutes, seconds = (int(part) for part in match.groups())
        return float(hours * 3600 + minutes * 60 + seconds)
    if isinstance(value, dict):
        if not value or set(value) - set(DURATION_UNITS):
            raise ValueError("duration mapping must have hours, minutes or seconds only")
        total = 0.0
        for unit, amount in value.items():
            if (
                isinstance(amount, bool)
                or not isinstance(amount, (int, float))
                or not math.isfinite(amount)
                or amount < 0
            ):
                raise ValueError(f"invalid {unit}")
            total += amount * DURATION_UNITS[unit]
        return float(total)
    raise ValueError("duration must be a string or a mapping")


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
    elif kind == "time_pattern":
        _check_pattern(item, "hours", 23, path, errors)
        _check_pattern(item, "minutes", 59, path, errors)
        _check_pattern(item, "seconds", 59, path, errors)


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


def _validate_actions(value: object, path: str, errors: list[str]) -> None:
    items = _as_list(value, path, errors)
    for index, item in enumerate(items or []):
        _validate_action(item, f"{path}[{index}]", errors)


def _validate_action(item: object, path: str, errors: list[str]) -> None:
    if not isinstance(item, dict):
        errors.append(_err(path, "must be a mapping"))
    elif "action" in item:
        _validate_service(item, path, errors)
    elif "delay" in item:
        _validate_delay(item, path, errors)
    elif "if" in item:
        _validate_if(item, path, errors)
    elif "choose" in item:
        _validate_choose(item, path, errors)
    elif "condition" in item:
        _validate_condition(item, path, errors)
    elif any(key in UNSUPPORTED_TYPES for key in item):
        errors.append(_err(path, "not supported yet"))
    else:
        errors.append(_err(path, "unknown action"))


def _validate_service(item: dict, path: str, errors: list[str]) -> None:
    if not _check_kind(item["action"], SWITCH_SERVICES, "action", path, errors):
        return
    _check_keys(item, {"action", "target"}, path, errors)
    _check_target(item, path, errors)


def _check_target(item: dict, path: str, errors: list[str]) -> None:
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
    if not names or not all(_is_template(name) or (isinstance(name, str) and name) for name in names):
        errors.append(_err(_join(target_path, "entity_id"), "must be a non-empty string or a list of them"))


def _validate_delay(item: dict, path: str, errors: list[str]) -> None:
    _check_keys(item, {"delay"}, path, errors)
    _check_duration(item, "delay", path, errors)


def _validate_if(item: dict, path: str, errors: list[str]) -> None:
    _check_keys(item, {"if", "then", "else"}, path, errors)
    _validate_conditions(item["if"], _join(path, "if"), errors)
    if _required(item, "then", path, errors):
        _validate_actions(item["then"], _join(path, "then"), errors)
    if "else" in item:
        _validate_actions(item["else"], _join(path, "else"), errors)


def _validate_choose(item: dict, path: str, errors: list[str]) -> None:
    _check_keys(item, {"choose", "default"}, path, errors)
    _validate_branches(item["choose"], _join(path, "choose"), errors)
    if "default" in item:
        _validate_actions(item["default"], _join(path, "default"), errors)


def _validate_branches(value: object, path: str, errors: list[str]) -> None:
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
            _validate_actions(branch["sequence"], _join(branch_path, "sequence"), errors)
