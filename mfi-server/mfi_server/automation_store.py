"""Automation archive of mfi-server: automations.json with the automations.

One record per automation, in the Home Assistant format (see automation_model).
A missing file is an empty archive. A damaged file raises ValueError and is
never rewritten. Writes go to a temporary file first, then replace the old file.
Standard library only.
"""
from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path

from mfi_server import automation_model, yaml_lite

SCHEMA = 1
FILE_NAME = "automations.json"


def _checked(obj: object) -> tuple[dict, list[str]]:
    """Return the normalized automation and its problems; a value that is not a mapping has no normalized form."""
    if not isinstance(obj, dict):
        return {}, ["not a mapping"]
    clean = automation_model.normalize(obj)
    return clean, automation_model.validate(clean)


class AutomationStore:
    """automations.json in data_dir: loaded at start, rewritten on every change."""

    def __init__(self, data_dir: Path) -> None:
        data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = data_dir / FILE_NAME
        self._lock = threading.RLock()
        self._automations: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except UnicodeDecodeError as exc:
            raise ValueError(f"{self.path}: not UTF-8 text") from exc
        except json.JSONDecodeError as exc:
            raise ValueError(f"{self.path}: not valid JSON ({exc})") from exc
        except OSError as exc:
            raise ValueError(f"{self.path}: cannot be read") from exc
        if not isinstance(raw, dict):
            raise ValueError(f"{self.path}: the top level must be a JSON object")
        schema = raw.get("schema")
        if type(schema) is not int or schema != SCHEMA:
            raise ValueError(f"{self.path}: schema must be {SCHEMA}")
        automations = raw.get("automations")
        if not isinstance(automations, list):
            raise ValueError(f"{self.path}: automations must be a list")
        loaded: dict[str, dict] = {}
        for index, item in enumerate(automations):
            clean, errors = _checked(item)
            if errors:
                raise ValueError(f"{self.path}: automation {index}: {errors[0]}")
            if clean["id"] in loaded:
                raise ValueError(f"{self.path}: duplicate automation {clean['id']}")
            loaded[clean["id"]] = clean
        self._automations = loaded

    def _write(self) -> None:
        """Write the whole archive to a temporary file, then replace the old one."""
        tmp = self.path.with_name(FILE_NAME + ".tmp")
        automations = [self._automations[key] for key in sorted(self._automations)]
        text = json.dumps({"schema": SCHEMA, "automations": automations}, indent=2, sort_keys=True)
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise

    def _commit(self, changed: dict[str, dict]) -> None:
        """Write the changed archive; on failure the previous one stays in memory and on disk."""
        previous = self._automations
        self._automations = changed
        try:
            self._write()
        except Exception:
            self._automations = previous
            raise

    def list(self) -> list[dict]:
        """Return normalized copies of all automations, ordered by id."""
        with self._lock:
            return [copy.deepcopy(self._automations[key]) for key in sorted(self._automations)]

    def get(self, id: str) -> dict | None:
        """Return a copy of one automation, or None if it is unknown."""
        with self._lock:
            record = self._automations.get(id)
            return None if record is None else copy.deepcopy(record)

    def put(self, obj: dict) -> None:
        """Normalize and validate one automation, then store and write it. Raises ValueError with the error list."""
        clean, errors = _checked(obj)
        if errors:
            raise ValueError(errors)
        with self._lock:
            changed = dict(self._automations)
            changed[clean["id"]] = clean
            self._commit(changed)

    def delete(self, id: str) -> None:
        """Remove one automation and write the archive. Raises KeyError when the id is unknown."""
        with self._lock:
            if id not in self._automations:
                raise KeyError(id)
            changed = dict(self._automations)
            del changed[id]
            self._commit(changed)

    def import_yaml(self, text: str) -> list[str]:
        """Store every automation of a YAML list (or of one mapping) and return the ids.

        Nothing is stored when one automation is invalid; the ValueError lists every problem.
        """
        try:
            data = yaml_lite.loads(text)
        except yaml_lite.YamlError as exc:
            raise ValueError([str(exc)]) from exc
        if data is None:
            raise ValueError(["document is empty"])
        if isinstance(data, dict):
            items = [data]
        elif isinstance(data, list):
            items = data
        else:
            raise ValueError(["top level must be a mapping or a list of mappings"])
        imported: list[dict] = []
        errors: list[str] = []
        seen: set[str] = set()
        for index, item in enumerate(items):
            prefix = f"[{index}] " if isinstance(data, list) else ""
            clean, problems = _checked(item)
            errors.extend(prefix + problem for problem in problems)
            if problems:
                continue
            if clean["id"] in seen:
                errors.append(f"{prefix}id: duplicate in this import")
                continue
            seen.add(clean["id"])
            imported.append(clean)
        if errors:
            raise ValueError(errors)
        with self._lock:
            changed = dict(self._automations)
            for clean in imported:
                changed[clean["id"]] = clean
            self._commit(changed)
        return [clean["id"] for clean in imported]
