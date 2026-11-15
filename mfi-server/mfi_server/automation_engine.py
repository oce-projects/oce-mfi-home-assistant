"""Automation engine of mfi-server: runs automations in the Home Assistant format.

Standard library only, and no thread of its own: the caller calls tick() once a
second and entity_changed() whenever the value of an entity changes. The time is
read only from the arguments and from clock(), so the engine is deterministic.
Each execution is a generator that yields ('delay', seconds) and returns its
result. A lock makes the public methods safe to call from the tick thread and
from the measurement listener.
"""
from __future__ import annotations

import copy
import threading
import time
from collections import deque
from collections.abc import Callable, Generator
from itertools import count

from mfi_server.automation_model import WEEKDAYS, normalize, parse_duration

TRACE_LIMIT = 5
TIME_KINDS = ("time", "time_pattern")
DAY_SECONDS = 86400


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


def _step(trace: dict, path: str, result: str) -> None:
    trace["steps"].append({"path": path, "result": result})


def _fail(trace: dict, path: str, message: str) -> str:
    """Record the failed step and the message of the run; return the 'error' result."""
    _step(trace, path, "error")
    trace["message"] = message
    return "error"


def _second_of_day(local: time.struct_time) -> int:
    return local.tm_hour * 3600 + local.tm_min * 60 + local.tm_sec


def _clock_seconds(text: str) -> int:
    """Seconds since midnight of 'HH:MM' or 'HH:MM:SS'; automation_model has already checked the text."""
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


def _time_due(item: dict, local: time.struct_time) -> bool:
    """True when the local clock matches a time or a time_pattern trigger."""
    if item["trigger"] == "time":
        return _second_of_day(local) == _clock_seconds(item["at"])
    has_hm = "hours" in item or "minutes" in item
    specs = (
        (item.get("hours", "*"), local.tm_hour),
        (item.get("minutes", "*"), local.tm_min),
        (item.get("seconds", 0 if has_hm else "*"), local.tm_sec),
    )
    return all(_pattern_matches(spec, value) for spec, value in specs)


class AutomationEngine:
    """Runs the automations: triggers, conditions, actions, delays, modes and traces."""

    def __init__(
        self,
        entities: Callable[[str], object],
        set_output: Callable[[str, int, int], None],
        resolve: Callable[[str], tuple[str, int] | None],
        clock: Callable[[], float],
        *,
        localtime: Callable[[float], time.struct_time] = time.localtime,
    ) -> None:
        self._entities = entities
        self._set_output = set_output
        self._resolve = resolve
        self._clock = clock
        self._localtime = localtime
        self._lock = threading.RLock()
        self._automations: dict[str, _Automation] = {}
        self._ids = count(1)
        self._now = 0.0

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
                for index, item in enumerate(auto.obj.get("triggers", [])):
                    if item.get("entity_id") != entity_id:
                        continue
                    if item.get("trigger") == "state":
                        self._state_event(auto, index, item, old, new)
                    elif item.get("trigger") == "numeric_state":
                        self._numeric_event(auto, index, item, old, new)

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
            return copy.deepcopy(list(self._automations[automation_id].traces))

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
        for index, item in enumerate(auto.obj.get("triggers", [])):
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
        run = _Run(self._body(auto.obj, trace), trace)
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
        """Run an execution until it waits for a delay or ends."""
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

    def _body(self, obj: dict, trace: dict) -> Generator:
        """The whole execution: the automation conditions first, then the actions."""
        if not self._all(obj.get("conditions", [])):
            _step(trace, "conditions", "condition_false")
            return "condition_false"
        status = yield from self._sequence(obj.get("actions", []), "actions", trace)
        return "finished" if status == "ok" else status

    def _sequence(self, items: list, base: str, trace: dict) -> Generator:
        for index, item in enumerate(items):
            status = yield from self._action(item, f"{base}[{index}]", trace)
            if status != "ok":
                return status
        return "ok"

    def _action(self, item: dict, path: str, trace: dict) -> Generator:
        """Run one step. Returns 'ok', 'condition_false' or 'error'; a delay suspends the run."""
        if "action" in item:
            return self._switch(item, path, trace)
        if "delay" in item:
            yield ("delay", parse_duration(item["delay"]))
            _step(trace, path, "ok")
            return "ok"
        if "if" in item:
            branch = "then" if self._all(item["if"]) else "else"
            _step(trace, path, branch)
            return (yield from self._sequence(item.get(branch, []), f"{path}.{branch}", trace))
        if "choose" in item:
            return (yield from self._choose(item, path, trace))
        if self._condition(item):
            _step(trace, path, "ok")
            return "ok"
        _step(trace, path, "condition_false")
        return "condition_false"

    def _choose(self, item: dict, path: str, trace: dict) -> Generator:
        for index, branch in enumerate(item["choose"]):
            if self._all(branch["conditions"]):
                _step(trace, path, f"choose[{index}]")
                return (yield from self._sequence(branch["sequence"], f"{path}.choose[{index}].sequence", trace))
        if "default" not in item:
            _step(trace, path, "none")
            return "ok"
        _step(trace, path, "default")
        return (yield from self._sequence(item["default"], f"{path}.default", trace))

    def _switch(self, item: dict, path: str, trace: dict) -> str:
        """Set the output of each entity of a switch action; return the result of the step."""
        service = item["action"]
        entity_ids = item["target"]["entity_id"]
        if not isinstance(entity_ids, list):
            entity_ids = [entity_ids]
        try:
            for entity_id in entity_ids:
                located = self._resolve(entity_id)
                if located is None:
                    return _fail(trace, path, f"unknown entity {entity_id}")
                mac, port = located
                if service == "switch.toggle":
                    value = 0 if self._entities(entity_id) == "on" else 1
                else:
                    value = 1 if service == "switch.turn_on" else 0
                self._set_output(mac, port, value)
        except Exception as exc:
            return _fail(trace, path, str(exc) or type(exc).__name__)
        _step(trace, path, "ok")
        return "ok"

    def _all(self, conditions: list) -> bool:
        return all(self._condition(item) for item in conditions)

    def _condition(self, item: dict) -> bool:
        kind = item["condition"]
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
        return not any(self._condition(child) for child in item["conditions"])

    def _time_ok(self, item: dict) -> bool:
        """True when the local time of the tick is on a listed weekday and inside the window.

        'after' is inclusive and 'before' is exclusive; with after later than before the window crosses midnight.
        """
        local = self._localtime(self._now)
        if "weekday" in item and WEEKDAYS[local.tm_wday] not in item["weekday"]:
            return False
        if "after" not in item and "before" not in item:
            return True
        now_s = _second_of_day(local)
        after = _clock_seconds(item["after"]) if "after" in item else 0
        before = _clock_seconds(item["before"]) if "before" in item else DAY_SECONDS
        if after <= before:
            return after <= now_s < before
        return now_s >= after or now_s < before
