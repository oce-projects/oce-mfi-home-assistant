"""Event log: records the device and server events and sends the e-mail notifications. Standard library only."""
from __future__ import annotations

import logging
import smtplib
import ssl
import time
from collections.abc import Callable
from email.message import EmailMessage

EVENT_TABLE = "event"
ACTIONEVENT_TABLE = "actionevent"
EMAIL_FAILED_KEY = "EVT_EMAIL_FAILED"
EMAIL_FAILED_DEDUP_MINUTES = 5
DEFAULT_RETENTION_DAYS = 30
DEFAULT_TIMEOUT = 10
DAY_SECONDS = 86400
EVENT_FIELDS = ("id", "ts", "device", "key", "level", "msg")
NOTIFY_ACTION = "notify.email"


def _scrub(text: str, secret: object) -> str:
    """Replace the secret (a password) in a text, so it never reaches a log or a row."""
    if secret:
        return text.replace(str(secret), "[redacted]")
    return text


class EventLog:
    """Keeps the events in the state database and sends the e-mail notifications."""

    def __init__(
        self,
        store,
        *,
        now: Callable[[], float] = time.time,
        retention_days: int = DEFAULT_RETENTION_DAYS,
        smtp_factory=None,
        logger=None,
    ) -> None:
        self._store = store
        self._now = now
        self._retention_days = retention_days
        self._smtp_factory = smtp_factory
        self._logger = logger or logging.getLogger(__name__)
        self._last_email: dict[str, float] = {}
        with store.transaction() as conn:
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {EVENT_TABLE} ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "ts INTEGER NOT NULL, "
                "device TEXT, "
                "key TEXT NOT NULL, "
                "level INTEGER NOT NULL DEFAULT 0, "
                "msg TEXT NOT NULL)"
            )
            conn.execute(
                f"CREATE TABLE IF NOT EXISTS {ACTIONEVENT_TABLE} ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "ts INTEGER NOT NULL, "
                "action TEXT NOT NULL, "
                "addr TEXT, "
                "result TEXT NOT NULL, "
                "detail TEXT)"
            )

    def record(self, *, key: str, msg: str, device: str | None = None, level: int = 0, dedup_minutes: int = 0) -> bool:
        """Store one event. Return False, and store nothing, when the same event was stored within dedup_minutes."""
        ts = int(self._now())
        with self._store.transaction() as conn:
            if dedup_minutes > 0:
                row = conn.execute(
                    f"SELECT ts FROM {EVENT_TABLE} WHERE device IS ? AND key = ? AND msg = ? "
                    "ORDER BY ts DESC, id DESC LIMIT 1",
                    (device, key, msg),
                ).fetchone()
                if row is not None and ts - row[0] < dedup_minutes * 60:
                    return False
            conn.execute(
                f"INSERT INTO {EVENT_TABLE} (ts, device, key, level, msg) VALUES (?, ?, ?, ?, ?)",
                (ts, device, key, level, msg),
            )
        return True

    def list_events(self, *, device=None, since=None, until=None, limit: int = 1000) -> list[dict]:
        """Return the events, newest first. Each filter applies only when it is not None."""
        limit = max(0, limit)
        clauses: list[str] = []
        params: list = []
        if device is not None:
            clauses.append("device = ?")
            params.append(device)
        if since is not None:
            clauses.append("ts >= ?")
            params.append(since)
        if until is not None:
            clauses.append("ts <= ?")
            params.append(until)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        with self._store.transaction() as conn:
            rows = conn.execute(
                f"SELECT id, ts, device, key, level, msg FROM {EVENT_TABLE}{where} "
                "ORDER BY ts DESC, id DESC LIMIT ?",
                params,
            ).fetchall()
        return [dict(zip(EVENT_FIELDS, row)) for row in rows]

    def prune(self, max_age_seconds: int | None = None) -> int:
        """Delete the events older than max_age_seconds (default: retention_days). Return the rows removed."""
        if max_age_seconds is None:
            max_age_seconds = self._retention_days * DAY_SECONDS
        cutoff = int(self._now()) - max_age_seconds
        with self._store.transaction() as conn:
            cursor = conn.execute(f"DELETE FROM {EVENT_TABLE} WHERE ts < ?", (cutoff,))
            removed = cursor.rowcount
            conn.execute(f"DELETE FROM {ACTIONEVENT_TABLE} WHERE ts < ?", (cutoff,))
            return removed

    def notify_email(self, settings, addr, subject, body, *, key=None, hold_minutes=0) -> bool:
        """Send one e-mail. Return False when it is held, disabled or failed; a failure is recorded as an event.

        The password is passed only to login(). It never goes into a log line, an event or an actionevent row.
        """
        now = self._now()
        addr = list(addr) if addr is not None else []
        if any(("\r" in value or "\n" in value) for value in addr) or "\r" in subject or "\n" in subject:
            detail = "rejected: newline in recipient or subject"
            self._logger.error("e-mail notification %s", detail)
            self.record(key=EMAIL_FAILED_KEY, msg="e-mail notification " + detail, level=2,
                        dedup_minutes=EMAIL_FAILED_DEDUP_MINUTES)
            self._log_action(addr, "error", detail)
            return False
        if key is not None and hold_minutes > 0:
            last = self._last_email.get(key)
            if last is not None and now - last < hold_minutes * 60:
                self._log_action(addr, "held")
                return False
        if not settings or not settings.get("host"):
            self._log_action(addr, "disabled")
            return False
        factory = self._smtp_factory or smtplib.SMTP
        try:
            msg = EmailMessage()
            msg["From"] = settings["from_addr"]
            msg["To"] = ", ".join(addr)
            msg["Subject"] = subject
            msg.set_content(body)
            with factory(settings["host"], settings["port"], timeout=settings.get("timeout", DEFAULT_TIMEOUT)) as smtp:
                if settings.get("use_tls"):
                    smtp.starttls(context=ssl.create_default_context())
                if settings.get("user"):
                    smtp.login(settings["user"], settings["password"])
                smtp.send_message(msg)
        except Exception as exc:
            detail = _scrub(str(exc) or type(exc).__name__, settings.get("password"))
            self._logger.error("e-mail notification failed: %s", detail)
            self.record(key=EMAIL_FAILED_KEY, msg="e-mail notification failed: " + detail, level=2,
                        dedup_minutes=EMAIL_FAILED_DEDUP_MINUTES)
            self._log_action(addr, "error", detail)
            if key is not None and hold_minutes > 0:
                self._last_email[key] = now
            return False
        if key is not None:
            self._last_email[key] = now
        self._log_action(addr, "sent")
        return True

    def _log_action(self, addr, result: str, detail: str | None = None) -> None:
        """Write one row of the actionevent table for an e-mail action."""
        with self._store.transaction() as conn:
            conn.execute(
                f"INSERT INTO {ACTIONEVENT_TABLE} (ts, action, addr, result, detail) VALUES (?, ?, ?, ?, ?)",
                (int(self._now()), NOTIFY_ACTION, ", ".join(addr), result, detail),
            )
