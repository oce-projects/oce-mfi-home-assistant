"""Password hashing, login sessions and the login rate limiter of mfi-server.

Standard library only. The password is stored as pbkdf2_sha256 with a random
salt in <data>/auth.json. Passwords and session tokens are never logged.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)

ALGORITHM = "pbkdf2_sha256"
DEFAULT_ITERATIONS = 600000
AUTH_FILE = "auth.json"
SESSION_TTL_S = 604800
LIMIT_WINDOW_S = 60
MAX_FAILURES = 5


def hash_password(password: str, salt: bytes | None = None, iterations: int = DEFAULT_ITERATIONS) -> str:
    """Return 'pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>' for the password."""
    if salt is None:
        salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{ALGORITHM}${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Return True only when the password matches the stored hash; malformed input gives False."""
    fields = stored.split("$")
    if len(fields) != 4 or fields[0] != ALGORITHM:
        return False
    try:
        iterations = int(fields[1])
        salt = bytes.fromhex(fields[2])
        expected = bytes.fromhex(fields[3])
    except ValueError:
        return False
    if iterations < 1:
        return False
    try:
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    except (ValueError, OverflowError):
        return False
    return hmac.compare_digest(digest, expected)


def load_password_hash(data_dir: Path) -> str | None:
    """Return the stored password hash, or None if auth.json is missing or malformed."""
    path = data_dir / AUTH_FILE
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("auth file is not valid JSON: %s", path)
        return None
    value = data.get("password_hash") if isinstance(data, dict) else None
    if not isinstance(value, str):
        logger.warning("auth file has no password_hash string: %s", path)
        return None
    return value


def save_password_hash(data_dir: Path, value: str) -> None:
    """Write the password hash to auth.json atomically with owner-only (0o600) permissions."""
    path = data_dir / AUTH_FILE
    temp = data_dir / (AUTH_FILE + ".tmp")
    text = json.dumps({"password_hash": value})
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except OSError:
        temp.unlink(missing_ok=True)
        raise


class Sessions:
    """Random session tokens with a creation time; a token expires after ttl_s seconds."""

    def __init__(self, clock: Callable[[], float], ttl_s: int = SESSION_TTL_S) -> None:
        self._clock = clock
        self._ttl_s = ttl_s
        self._tokens: dict[str, float] = {}

    def create(self) -> str:
        token = secrets.token_urlsafe(32)
        self._tokens[token] = self._clock()
        return token

    def valid(self, token: str) -> bool:
        created = self._tokens.get(token)
        if created is None:
            return False
        if self._clock() - created > self._ttl_s:
            self._tokens.pop(token, None)
            return False
        return True

    def drop(self, token: str) -> None:
        self._tokens.pop(token, None)


class LoginLimiter:
    """Counts failed logins per client address; an address is blocked after MAX_FAILURES in LIMIT_WINDOW_S."""

    def __init__(self, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._failures: dict[str, list[float]] = {}

    def _prune(self, ip: str, now: float) -> list[float]:
        recent = [t for t in self._failures.get(ip, []) if now - t < LIMIT_WINDOW_S]
        if recent:
            self._failures[ip] = recent
        else:
            self._failures.pop(ip, None)
        return recent

    def failure(self, ip: str) -> None:
        now = self._clock()
        recent = self._prune(ip, now)
        recent.append(now)
        self._failures[ip] = recent

    def blocked(self, ip: str) -> bool:
        now = self._clock()
        return len(self._prune(ip, now)) >= MAX_FAILURES
