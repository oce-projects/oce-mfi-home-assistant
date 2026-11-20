"""Alarms: raising and storing the alarms of the monitors. Implemented in EPIC-08. Standard library only."""
import time

ALARM_TABLE = "alarm"
ALARMDEF_TABLE = "alarmdef"
SYSTEM_ALERT_KEY = "EVT_SystemAlert"
ALARM_FIELDS = (
    "id", "ts", "key", "device", "msg", "level", "occurs", "archived", "active", "handled_by", "handled_ts",
)
STARTUP_DEFS = (
    {"key": "EVT_AP_DiscoveredPending", "repeat": 0, "auto_close": 1, "level": 0, "system": 1},
    {"key": "EVT_AP_RediscoveredPending", "repeat": 0, "auto_close": 1, "level": 0, "system": 1},
    {"key": "EVT_AP_Lost_Contact", "repeat": 1, "auto_close": 1, "level": 1, "system": 0},
    {"key": "EVT_WU_AssocPending", "repeat": 0, "auto_close": 1, "level": 0, "system": 0},
    {"key": "EVT_WG_AssocPending", "repeat": 0, "auto_close": 1, "level": 0, "system": 0},
    {"key": "EVT_AD_UpdateAvailable", "repeat": 0, "auto_close": 0, "level": 0, "system": 1},
)
ALARMDEF_SCHEMA = (
    f"CREATE TABLE IF NOT EXISTS {ALARMDEF_TABLE} ("
    "key TEXT PRIMARY KEY, "
    "repeat INTEGER NOT NULL DEFAULT 0, "
    "auto_close INTEGER NOT NULL DEFAULT 0, "
    "level INTEGER NOT NULL DEFAULT 0, "
    "system INTEGER NOT NULL DEFAULT 0)"
)
ALARM_SCHEMA = (
    f"CREATE TABLE IF NOT EXISTS {ALARM_TABLE} ("
    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
    "ts INTEGER NOT NULL, "
    "key TEXT NOT NULL, "
    "device TEXT, "
    "msg TEXT NOT NULL, "
    "level INTEGER NOT NULL DEFAULT 0, "
    "occurs INTEGER NOT NULL DEFAULT 1, "
    "archived INTEGER NOT NULL DEFAULT 0, "
    "active INTEGER NOT NULL DEFAULT 1, "
    "handled_by TEXT, "
    "handled_ts INTEGER)"
)
OPEN_ALARM_SQL = (
    f"SELECT id FROM {ALARM_TABLE} WHERE key = ? AND device IS ? AND active = 1 AND archived = 0 "
    "ORDER BY id DESC LIMIT 1"
)


def _definition(conn, key):
    """Return (level, auto_close) of the definition of key, or None when there is none."""
    return conn.execute(
        f"SELECT level, auto_close FROM {ALARMDEF_TABLE} WHERE key = ?", (key,)
    ).fetchone()


class AlarmStore:
    """Keeps the alarm definitions and the raised alarms. Implemented in EPIC-08."""

    def __init__(self, store, event_log=None, *, now=time.time):
        self._store = store
        self._event_log = event_log
        self._now = now
        with store.transaction() as conn:
            conn.execute(ALARMDEF_SCHEMA)
            conn.execute(ALARM_SCHEMA)
        self.ensure_definitions()

    def ensure_definitions(self) -> int:
        """Insert the startup definitions that are missing. Return how many rows this call inserted."""
        inserted = 0
        with self._store.transaction() as conn:
            for item in STARTUP_DEFS:
                cursor = conn.execute(
                    f"INSERT OR IGNORE INTO {ALARMDEF_TABLE} (key, repeat, auto_close, level, system) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (item["key"], item["repeat"], item["auto_close"], item["level"], item["system"]),
                )
                inserted += cursor.rowcount
        return inserted

    def add_definition(self, key, *, repeat=0, auto_close=0, level=0, system=0) -> None:
        """Insert or replace the definition of key."""
        with self._store.transaction() as conn:
            conn.execute(
                f"INSERT OR REPLACE INTO {ALARMDEF_TABLE} (key, repeat, auto_close, level, system) "
                "VALUES (?, ?, ?, ?, ?)",
                (key, int(repeat), int(auto_close), int(level), int(system)),
            )

    def raise_alarm(self, key, *, device=None, msg=None, level=None) -> int:
        """Raise one alarm. An open alarm with the same key and device is counted again, not duplicated."""
        ts = int(self._now())
        with self._store.transaction() as conn:
            open_row = conn.execute(OPEN_ALARM_SQL, (key, device)).fetchone()
            if open_row is not None:
                conn.execute(
                    f"UPDATE {ALARM_TABLE} SET occurs = occurs + 1, ts = ? WHERE id = ?",
                    (ts, open_row[0]),
                )
                return open_row[0]
            if level is None:
                definition = _definition(conn, key)
                level = definition[0] if definition is not None else 0
            if msg is None:
                msg = key
            cursor = conn.execute(
                f"INSERT INTO {ALARM_TABLE} (ts, key, device, msg, level, occurs, archived, active) "
                "VALUES (?, ?, ?, ?, ?, 1, 0, 1)",
                (ts, key, device, msg, level),
            )
            alarm_id = cursor.lastrowid
        if self._event_log is not None:
            self._event_log.record(key=key, msg=msg, device=device, level=level)
        return alarm_id

    def clear(self, key, *, device=None) -> bool:
        """Close the open alarm of key and device when its definition has auto_close. Return True if closed."""
        with self._store.transaction() as conn:
            open_row = conn.execute(OPEN_ALARM_SQL, (key, device)).fetchone()
            if open_row is None:
                return False
            definition = _definition(conn, key)
            if definition is None or definition[1] != 1:
                return False
            conn.execute(f"UPDATE {ALARM_TABLE} SET active = 0 WHERE id = ?", (open_row[0],))
            return True

    def acknowledge(self, alarm_id, *, by=None) -> bool:
        """Record who handled the alarm and when. Return True when one row changed."""
        with self._store.transaction() as conn:
            cursor = conn.execute(
                f"UPDATE {ALARM_TABLE} SET handled_by = ?, handled_ts = ? WHERE id = ?",
                (by, int(self._now()), alarm_id),
            )
            return cursor.rowcount == 1

    def archive(self, alarm_id) -> bool:
        """Move the alarm to the archive. Return True when one row changed."""
        with self._store.transaction() as conn:
            cursor = conn.execute(f"UPDATE {ALARM_TABLE} SET archived = 1 WHERE id = ?", (alarm_id,))
            return cursor.rowcount == 1

    def create_system_alert(self, msg, *, key=SYSTEM_ALERT_KEY, level=2) -> int:
        """Raise a system alarm (no device) for the rule action 'Create System Alert'."""
        with self._store.transaction() as conn:
            known = _definition(conn, key) is not None
        if not known:
            self.add_definition(key, system=1)
        return self.raise_alarm(key, device=None, msg=msg, level=level)

    def list_alarms(self, *, archived=None, active=None, device=None, limit=1000) -> list[dict]:
        """Return the alarms, newest first. Each filter applies only when it is not None."""
        clauses: list[str] = []
        params: list = []
        if archived is not None:
            clauses.append("archived = ?")
            params.append(int(archived))
        if active is not None:
            clauses.append("active = ?")
            params.append(int(active))
        if device is not None:
            clauses.append("device = ?")
            params.append(device)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(max(0, int(limit)))
        with self._store.transaction() as conn:
            rows = conn.execute(
                f"SELECT {', '.join(ALARM_FIELDS)} FROM {ALARM_TABLE}{where} ORDER BY ts DESC, id DESC LIMIT ?",
                params,
            ).fetchall()
        return [dict(zip(ALARM_FIELDS, row)) for row in rows]
