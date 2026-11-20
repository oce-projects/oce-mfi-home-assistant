"""Conversion of the rules of the previous controller into automations. Standard library only, clean room.

A controller rule is a rule document with its conditions (ruleset, linked by rulesetId), its actions
(ruleaction, linked by rulesetId), its weekly intervals (rulestatecalendar, linked by stateId) and its
calendars (ruleschedule, linked by rulesetId). A scene is a scene document with its sceneaction documents
(linked by sceneId). Each rule or scene becomes one automation in the format of rules.py, or one entry of
report.skipped with its reason: nothing is dropped silently.

Entity ids are placeholders (sensor.old_<sId>, switch.old_<sId>, light.old_<sId>, calendar.old_<sId>);
binding them to real entities is a later concern.
"""
import gzip
import io
import time

from mfi_server_next import bson, config, crypto, migrate, rules, store

COLLECTIONS = (
    "rule", "ruleset", "ruleaction", "rulecondition", "ruleschedule",
    "rulestatecalendar", "scene", "sceneaction", "script",
)
HEX_DIGITS = "0123456789abcdef"
DAY_MINUTES = 24 * 60
WEEK_MINUTES = 7 * DAY_MINUTES
# Day 0 is Sunday, as in the controller; the names follow the weekday list of rules.py.
DAY_NAMES = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")
MAX_MINUTES = rules.MAX_DURATION
EVENT_KEY = "EVT_mFi_SensorRuleset"
SCRIPT_NOTE = "script action disabled"


class _Skip(Exception):
    """A rule or scene that cannot be converted; its message is the reason written in the report."""


def _is_int(value, low, high):
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def _is_number(value):
    """True for a finite int or float that is not a bool: NaN and infinity fail the x - x == 0 test."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value - value == 0


def _valid_hex(value):
    return isinstance(value, str) and len(value) == 24 and all(ch in HEX_DIGITS for ch in value)


def _children(docs, key, value):
    """The documents whose key holds value, in their original order."""
    return [doc for doc in docs if doc.get(key) == value]


def _first(doc, *keys):
    """The value of the first key that is set; when none is, the rule or scene is skipped."""
    for key in keys:
        if doc.get(key) is not None:
            return doc[key]
    raise _Skip("missing " + " or ".join(keys))


def _as_text(value, fallback):
    text = str(value) if value else fallback
    if not text:
        raise _Skip("empty text")
    return text


def _clock_text(minutes):
    return "%02d:%02d" % (minutes // 60, minutes % 60)


def _window(doc):
    """Return (weekday, start time, end time or None) of one weekly interval; an interval never crosses midnight."""
    start = doc.get("start")
    end = doc.get("end")
    if not _is_int(start, 0, WEEK_MINUTES - 1) or not _is_int(end, 1, WEEK_MINUTES):
        raise _Skip("invalid time interval")
    if end <= start:
        raise _Skip("time interval ends before it starts")
    day = start // DAY_MINUTES
    if end > (day + 1) * DAY_MINUTES:
        raise _Skip("time interval crosses midnight")
    after = _clock_text(start - day * DAY_MINUTES)
    rest = end - day * DAY_MINUTES
    before = None if rest == DAY_MINUTES else _clock_text(rest)
    return DAY_NAMES[day], after, before


def _window_condition(window):
    weekday, after, before = window
    condition = {"condition": "time", "after": after, "weekday": [weekday]}
    if before is not None:
        condition["before"] = before
    return condition


def _window_trigger(window):
    weekday, after, _ = window
    return {"trigger": "time", "at": after, "weekday": [weekday]}


def _combine(items, any_mode):
    """One item stands alone; several are joined with or (any) or and (all)."""
    if len(items) == 1:
        return items[0]
    return {"condition": "or" if any_mode else "and", "conditions": items}


def _sensor_part(item):
    """Return (kind, body, any_mode) of one sensor ruleset: an edge becomes a trigger, a level a condition."""
    if item.get("trigger") != "sensor":
        raise _Skip("ruleset trigger {} not converted".format(item.get("trigger")))
    if item.get("enable") is False:
        raise _Skip("disabled ruleset not converted")
    compare = item.get("compare")
    if compare == 0:
        bound = "above"
    elif compare == 4:
        bound = "below"
    elif compare == 2:
        raise _Skip("equality comparison not supported")
    else:
        raise _Skip("unknown compare value {}".format(compare))
    limit = item.get("limit")
    if not _is_number(limit):
        raise _Skip("invalid limit")
    duration = item.get("duration") or 0
    if not _is_int(duration, 0, rules.MAX_DURATION):
        raise _Skip("invalid duration")
    entity = "sensor.old_" + str(_first(item, "sId"))
    any_mode = item.get("allorany") == "any"
    mode = item.get("edgeorlevel", "edge")
    if mode == "edge":
        body = {"trigger": "numeric_state", "entity_id": entity, bound: limit}
        if duration:
            body["for"] = {"minutes": duration}
        return "trigger", body, any_mode
    if mode == "level":
        if duration:
            raise _Skip("duration on a level condition not supported")
        return "condition", {"condition": "numeric_state", "entity_id": entity, bound: limit}, any_mode
    raise _Skip("unknown edge or level value {}".format(mode))


def _relay_action(doc):
    """Switch on or off a relay; a dimmer level (scene action) becomes a light with a brightness."""
    sensor = _first(doc, "sId")
    level = doc.get("dimmer_level")
    if level is not None:
        if not _is_int(level, 0, 100):
            raise _Skip("dimmer level outside 0 to 100")
        return {
            "action": "light.turn_on",
            "target": {"entity_id": ["light.old_" + str(sensor)]},
            "data": {"brightness": level},
        }
    target = {"entity_id": ["switch.old_" + str(sensor)]}
    if not doc.get("val"):
        return {"action": "switch.turn_off", "target": target}
    action = {"action": "switch.turn_on", "target": target}
    timer = doc.get("timer") or 0
    if timer:
        if not _is_int(timer, 1, MAX_MINUTES):
            raise _Skip("invalid timer")
        action["for"] = {"seconds": timer}
    return action


def _script_action(doc):
    text = doc.get("val")
    if not isinstance(text, str) or not text:
        raise _Skip("script action without text")
    sensor = _first(doc, "sId")
    return {"action": "script", "data": {"entity_id": "switch.old_" + str(sensor), "text": text}}


def _email_action(doc, alias):
    addr = doc.get("addr")
    if not isinstance(addr, list) or not addr or not all(isinstance(item, str) and item for item in addr):
        raise _Skip("e-mail action without address")
    data = {"addr": list(addr), "body": _as_text(doc.get("val"), alias)}
    minutes = doc.get("minute")
    if _is_int(minutes, 1, MAX_MINUTES):
        data["hold_minutes"] = minutes
    return {"action": "notify.email", "data": data}


def _event_action(doc, alias):
    data = {"key": EVENT_KEY, "msg": _as_text(doc.get("val"), alias)}
    if doc.get("alert") is True:
        data["level"] = 2
    minutes = doc.get("minute")
    if _is_int(minutes, 1, MAX_MINUTES):
        data["dedup_minutes"] = minutes
    return {"action": "mfi.event", "data": data}


def _url_action(doc, alias):
    url = doc.get("val")
    if not isinstance(url, str) or rules.URL_RE.fullmatch(url) is None:
        raise _Skip("url action without http or https address")
    return {"action": "http_post", "data": {"url": url, "payload": {"rule": alias}}}


def _scene_ref_action(doc):
    ref = _first(doc, "sceneId", "sId")
    return {"action": "scene.turn_on", "target": {"entity_id": ["scene.old_" + str(ref)]}}


def _rule_ref_action(doc):
    ref = _first(doc, "raId", "stateId")
    return {"action": "automation.trigger", "target": {"entity_id": ["automation.old_rule_" + str(ref)]}}


def _state_action(doc):
    ref = _first(doc, "stateId")
    service = "automation.turn_on" if doc.get("val") else "automation.turn_off"
    return {"action": service, "target": {"entity_id": ["automation.old_rule_" + str(ref)]}}


def _rule_action(doc, alias):
    kind = doc.get("type")
    if kind == "relaySwitch":
        return _relay_action(doc)
    if kind == "script":
        return _script_action(doc)
    if kind == "email":
        return _email_action(doc, alias)
    if kind == "event":
        return _event_action(doc, alias)
    if kind == "url":
        return _url_action(doc, alias)
    if kind == "scene":
        return _scene_ref_action(doc)
    if kind == "rule":
        return _rule_ref_action(doc)
    if kind == "state":
        return _state_action(doc)
    raise _Skip("unknown action type {}".format(kind))


def _scene_action(doc, alias):
    kind = doc.get("type")
    if kind == "relaySwitch":
        return _relay_action(doc)
    if kind == "script":
        return _script_action(doc)
    if kind == "url":
        return _url_action(doc, alias)
    raise _Skip("unknown scene action type {}".format(kind))


def _finish(auto_id, alias, triggers, conditions, actions, allow_script_action):
    """Build the automation in the format of rules.py. A script action without permission is kept switched off and noted."""
    auto = {"id": auto_id, "alias": alias, "triggers": triggers, "conditions": conditions, "actions": actions}
    notes = []
    if not allow_script_action and any(action.get("action") == "script" for action in actions):
        auto["enabled"] = False
        notes.append({"id": auto_id, "reason": SCRIPT_NOTE})
    return rules.normalize(auto), notes


def _rule_automation(auto_id, rule, docs, allow_script_action):
    rule_id = rule["_id"]
    alias = str(rule.get("label") or auto_id)
    triggers = []
    levels = []
    level_any = False
    for item in _children(docs["ruleset"], "rulesetId", rule_id):
        kind, body, any_mode = _sensor_part(item)
        if kind == "trigger":
            triggers.append(body)
        else:
            levels.append(body)
            level_any = level_any or any_mode
    windows = []
    for doc in _children(docs["rulestatecalendar"], "stateId", rule_id):
        if doc.get("trigger") != "time":
            raise _Skip("unknown interval trigger {}".format(doc.get("trigger")))
        windows.append(_window(doc))
    for doc in _children(docs["ruleschedule"], "rulesetId", rule_id):
        if doc.get("trigger") != "calendar":
            raise _Skip("unknown schedule trigger {}".format(doc.get("trigger")))
        # A string, not a list: rules.validate accepts one entity id for a calendar trigger.
        triggers.append({
            "trigger": "calendar",
            "entity_id": "calendar.old_" + str(_first(doc, "sId")),
            "event": "start",
        })
    conditions = []
    if levels:
        conditions.append(_combine(levels, level_any))
    if windows:
        # Weekly intervals are activity windows: any of them is enough.
        conditions.append(_combine([_window_condition(window) for window in windows], True))
    if not triggers:
        if not windows:
            raise _Skip("rule without trigger")
        for window in windows:
            triggers.append(_window_trigger(window))
    actions = [_rule_action(doc, alias) for doc in _children(docs["ruleaction"], "rulesetId", rule_id)]
    if not actions:
        raise _Skip("rule without action")
    return _finish(auto_id, alias, triggers, conditions, actions, allow_script_action)


def _scene_automation(auto_id, scene, docs, allow_script_action):
    alias = str(scene.get("label") or auto_id)
    actions = [_scene_action(doc, alias) for doc in _children(docs["sceneaction"], "sceneId", scene["_id"])]
    if not actions:
        raise _Skip("scene without action")
    return _finish(auto_id, alias, [], [], actions, allow_script_action)


def _convert_one(kind, doc, build, docs, allow_script_action, automations, skipped):
    """Convert one rule or scene: one automation, or one skipped entry with its reason."""
    doc_id = doc.get("_id")
    if not _valid_hex(doc_id):
        skipped.append({"id": "", "reason": "missing or invalid _id"})
        return
    auto_id = "old_%s_%s" % (kind, doc_id)
    try:
        auto, notes = build(auto_id, doc, docs, allow_script_action)
    except _Skip as exc:
        skipped.append({"id": auto_id, "reason": str(exc)})
        return
    except (ValueError, TypeError, KeyError) as exc:
        skipped.append({"id": auto_id, "reason": "conversion failed: " + str(exc)})
        return
    automations.append(auto)
    skipped.extend(notes)


def convert_rules(backup_docs, *, allow_script_action=False):
    """Convert the rules and scenes of a backup. Each rule or scene is one automation or one skipped entry.

    backup_docs maps a collection name to its list of documents; a missing collection is empty.
    A script action with allow_script_action False is kept switched off and a note is added to skipped;
    that automation is also counted as converted.
    """
    docs = {name: list(backup_docs.get(name) or []) for name in COLLECTIONS}
    automations = []
    skipped = []
    for doc in docs["rule"]:
        _convert_one("rule", doc, _rule_automation, docs, allow_script_action, automations, skipped)
    for doc in docs["scene"]:
        _convert_one("scene", doc, _scene_automation, docs, allow_script_action, automations, skipped)
    return {"automations": automations, "report": {"converted": len(automations), "skipped": skipped}}


def collect_rule_docs(docs):
    """Group a flat document list, read like migrate.import_backup, into one list per COLLECTIONS name."""
    grouped = {name: [] for name in COLLECTIONS}
    collection = None
    for doc in docs:
        if "__cmd" in doc:
            if doc["__cmd"] == "select":
                collection = doc.get("collection")
            continue
        if isinstance(collection, str) and collection in grouped:
            grouped[collection].append(doc)
    return grouped


MAX_BACKUP_BYTES = 256 * 1024 * 1024  # 256 MiB: enough for a controller backup, low enough to stop a gzip bomb


def _gunzip_limited(data, limit=MAX_BACKUP_BYTES):
    """Decompress gzip bytes, raising ValueError if the output grows past limit bytes (gzip-bomb guard)."""
    out = bytearray()
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as gz:
        while True:
            chunk = gz.read(65536)
            if not chunk:
                break
            out += chunk
            if len(out) > limit:
                raise ValueError("backup db.gz is too large")
    return out


def read_backup_documents(data):
    """Decrypt a .unf backup and return its BSON documents. Any failure is a ValueError."""
    try:
        usable = len(data) - len(data) % 16
        if usable == 0:
            raise ValueError("backup is too short")
        plain = crypto.aes128_decrypt(migrate.UNF_KEY, migrate.UNF_IV, data[:usable], unpad=False)
        entries = migrate._read_zip_entries(plain)
        if "db.gz" not in entries:
            raise ValueError("db.gz not found in backup")
        raw = _gunzip_limited(entries["db.gz"])
        return bson.read_bson_stream(io.BytesIO(raw))
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("cannot read backup: " + str(exc)) from exc


def store_automations(automations, data_dir, *, clock=time.time):
    """Merge the automations into automations.json by id, so a repeated import replaces and never duplicates.

    Returns the merged list. The file is copied first when it already exists.
    """
    settings = config.load_settings(data_dir)
    db = store.Store.open(settings["data_dir"])
    try:
        folder = db.data_dir
        astore = rules.AutomationStore(db)
        by_id = {}
        kept = []
        for auto in astore.load():
            if "id" in auto:
                by_id[auto["id"]] = auto
            else:
                kept.append(auto)
        for auto in automations:
            by_id[auto["id"]] = auto
        merged = kept + list(by_id.values())
        migrate._protected_step(
            folder / migrate.AUTOMATIONS_FILE,
            lambda: astore.save(merged),
            settings["backup_copies"],
            clock,
        )
        return merged
    finally:
        db.close()


def import_backup_rules(body, data_dir, *, allow_script_action=False, clock=time.time):
    """Read a backup, convert its rules and store them; return the report. Used by the route wiring."""
    docs = read_backup_documents(body)
    converted = convert_rules(collect_rule_docs(docs), allow_script_action=allow_script_action)
    store_automations(converted["automations"], data_dir, clock=clock)
    return converted["report"]
