"""Storage of mfi_server_next: sqlite3 databases and atomic JSON files. Standard library only."""
from __future__ import annotations

import contextlib
import json
import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path

STATE_DB = "state.sqlite3"
HISTORY_DB = "history.sqlite3"
DIR_MODE = 0o700
PRIVATE_FILE_MODE = 0o600
PUBLIC_FILE_MODE = 0o644


def _safe_name(name) -> None:
    """Reject a name that is not one plain file name inside the data folder."""
    if not isinstance(name, str) or name == "" or name in (".", "..") or os.path.basename(name) != name:
        raise ValueError(f"unsafe file name: {name!r}")


class Store:
    """Data folder of the server: state.sqlite3, history.sqlite3 and JSON files."""

    def __init__(self, data_dir: Path, state: sqlite3.Connection, history: sqlite3.Connection) -> None:
        self.data_dir = data_dir
        self._state = state
        self._history = history

    @classmethod
    def open(cls, data_dir) -> Store:
        """Create the folder with mode 0700 if missing and open both databases."""
        folder = Path(data_dir)
        os.makedirs(folder, mode=DIR_MODE, exist_ok=True)
        os.chmod(folder, DIR_MODE)
        state = sqlite3.connect(folder / STATE_DB)
        try:
            history = sqlite3.connect(folder / HISTORY_DB)
        except BaseException:
            state.close()
            raise
        try:
            os.chmod(folder / STATE_DB, PRIVATE_FILE_MODE)
            os.chmod(folder / HISTORY_DB, PRIVATE_FILE_MODE)
        except BaseException:
            history.close()
            state.close()
            raise
        return cls(folder, state, history)

    @contextlib.contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Yield the state connection: commit on a clean exit, roll back and re-raise on error."""
        try:
            yield self._state
            self._state.commit()
        except BaseException:
            self._state.rollback()
            raise

    def write_json(self, name: str, obj, *, private: bool = False) -> None:
        """Write obj to data_dir/name through a temporary file in the same folder, then replace."""
        _safe_name(name)
        final = self.data_dir / name
        tmp = self.data_dir / (name + ".tmp")
        text = json.dumps(obj, indent=2, sort_keys=True)
        mode = PRIVATE_FILE_MODE if private else PUBLIC_FILE_MODE
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
            try:
                os.fchmod(fd, mode)
            except BaseException:
                os.close(fd)
                raise
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, final)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    def read_json(self, name: str, default=None):
        """Return the parsed JSON of data_dir/name, or default when the file does not exist."""
        _safe_name(name)
        try:
            with open(self.data_dir / name, encoding="utf-8") as handle:
                return json.load(handle)
        except FileNotFoundError:
            return default
        except json.JSONDecodeError as exc:
            raise ValueError(f"{self.data_dir / name}: not valid JSON ({exc})") from exc

    def close(self) -> None:
        """Close both sqlite3 connections."""
        try:
            self._history.close()
        finally:
            self._state.close()
