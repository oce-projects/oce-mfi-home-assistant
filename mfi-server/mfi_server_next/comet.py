"""Comet buffer: holds the events pushed to the web page. Standard library only."""
import collections
import threading
import time


class CometBuffer:
    """Keeps the newest messages for the web page and lets a long poll wait for new ones."""

    def __init__(self, maxlen=200, clock=time.monotonic):
        self._clock = clock
        self._items = collections.deque(maxlen=maxlen)
        self._seq = 0
        self._cond = threading.Condition()

    def _newer(self, cursor):
        return [(seq, message) for seq, message in self._items if seq > cursor]

    def _has_newer(self, cursor):
        return bool(self._items) and self._items[-1][0] > cursor

    def append(self, message):
        with self._cond:
            self._seq += 1
            self._items.append((self._seq, message))
            self._cond.notify_all()
            return self._seq

    def read_after(self, cursor, *, timeout=0.0):
        with self._cond:
            if timeout > 0 and not self._has_newer(cursor):
                self._cond.wait_for(lambda: self._has_newer(cursor), timeout=timeout)
            newer = self._newer(cursor)
            if not newer:
                return cursor, []
            return newer[-1][0], [message for _, message in newer]

    def latest_cursor(self):
        with self._cond:
            return self._seq
