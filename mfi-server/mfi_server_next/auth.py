"""Accounts, roles, login sessions and login limits of the web API.

Standard library only. Passwords are stored as PBKDF2 hashes made by
mfi_server_next.crypto, in users.json with owner-only permissions. Passwords,
hashes and session tokens are never logged.
"""
from __future__ import annotations

import hmac
import secrets
import threading
import time
from collections.abc import Callable

from mfi_server_next import crypto
from mfi_server_next.store import Store

MIN_PASSWORD_LENGTH = 12
LIMIT_WINDOW_S = 60
MAX_FAILURES = 5
SESSION_TTL_S = 604800
TRUSTED_INGRESS_PEER = "172.30.32.2"
USERS_FILE = "users.json"
LEGACY_AUTH_FILE = "auth.json"
ROLE_ADMIN = "admin"
ROLE_READ_ONLY = "read_only"
ROLES = (ROLE_ADMIN, ROLE_READ_ONLY)
_DUMMY_PASSWORD_HASH = crypto.pbkdf2_hash("timing-equalizer", iterations=crypto.DEFAULT_ITERATIONS)


class LoginFailed(Exception):
    """Wrong username or password."""

    status = 401


class TooManyAttempts(Exception):
    """Too many failed logins from this address; try again later."""

    status = 429


class PermissionDenied(Exception):
    """The session is valid but its role may not do this."""

    status = 403


def password_problems(password: str, min_length: int = MIN_PASSWORD_LENGTH) -> list[str]:
    """Return the codes of the password rules the password breaks; an empty list means it is acceptable."""
    problems = []
    if len(password) < min_length:
        problems.append("too_short")
    if not any(ch.isupper() for ch in password):
        problems.append("no_upper")
    if not any(ch.islower() for ch in password):
        problems.append("no_lower")
    if not any(ch.isdigit() for ch in password):
        problems.append("no_digit")
    if not any(not ch.isalnum() for ch in password):
        problems.append("no_special")
    return problems


def trusted_ingress(peer_ip) -> bool:
    """Return True only for the address the Home Assistant ingress proxy connects from."""
    return isinstance(peer_ip, str) and peer_ip == TRUSTED_INGRESS_PEER


class Sessions:
    """Random session tokens; a token expires ttl_s seconds after it was created."""

    def __init__(self, clock: Callable[[], float], ttl_s: int = SESSION_TTL_S) -> None:
        self._clock = clock
        self._ttl_s = ttl_s
        self._sessions: dict[str, dict] = {}
        self._lock = threading.Lock()

    def create(self, username: str, role: str) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._sessions[token] = {"username": username, "role": role, "created": self._clock()}
        return token

    def check(self, token) -> dict | None:
        if not isinstance(token, str):
            return None
        candidate = token.encode("utf-8", "replace")
        with self._lock:
            match = None
            for stored in self._sessions:
                if hmac.compare_digest(stored.encode("utf-8"), candidate):
                    match = stored
            if match is None:
                return None
            entry = self._sessions[match]
            if self._clock() - entry["created"] > self._ttl_s:
                del self._sessions[match]
                return None
            return {"username": entry["username"], "role": entry["role"]}

    def drop(self, token) -> None:
        if not isinstance(token, str):
            return
        with self._lock:
            self._sessions.pop(token, None)


class LoginLimiter:
    """Counts failed logins per client address; an address is blocked after MAX_FAILURES in LIMIT_WINDOW_S."""

    def __init__(self, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, ip: str, now: float) -> list[float]:
        recent = [t for t in self._failures.get(ip, []) if now - t < LIMIT_WINDOW_S]
        if recent:
            self._failures[ip] = recent
        else:
            self._failures.pop(ip, None)
        return recent

    def failure(self, ip: str) -> None:
        with self._lock:
            now = self._clock()
            recent = self._prune(ip, now)
            recent.append(now)
            self._failures[ip] = recent

    def blocked(self, ip: str) -> bool:
        with self._lock:
            return len(self._prune(ip, self._clock())) >= MAX_FAILURES


class AuthManager:
    """Accounts with roles, login with rate limit, sessions and migration of the old single password."""

    def __init__(
        self,
        store: Store,
        *,
        clock: Callable[[], float] = time.monotonic,
        session_ttl_s: int = SESSION_TTL_S,
        min_password_length: int = MIN_PASSWORD_LENGTH,
    ) -> None:
        self._store = store
        self._min_password_length = min_password_length
        self._users: dict[str, dict[str, str]] = {}
        raw = store.read_json(USERS_FILE, {"users": {}})
        users = raw.get("users") if isinstance(raw, dict) else None
        if not isinstance(users, dict):
            raise ValueError(f"{USERS_FILE}: expected an object with a 'users' object")
        for username, entry in users.items():
            if not isinstance(entry, dict) or not isinstance(entry.get("password_hash"), str) or entry.get("role") not in ROLES:
                raise ValueError(f"{USERS_FILE}: invalid entry for user {username!r}")
            self._users[username] = {"password_hash": entry["password_hash"], "role": entry["role"]}
        self._sessions = Sessions(clock, session_ttl_s)
        self._limiter = LoginLimiter(clock)

    def _save(self, users: dict[str, dict[str, str]]) -> None:
        self._store.write_json(USERS_FILE, {"users": users}, private=True)
        self._users = users

    def _check_new_password(self, password: str) -> None:
        if not isinstance(password, str):
            raise ValueError("password must be a string")
        problems = password_problems(password, self._min_password_length)
        if problems:
            raise ValueError("password rules not met: " + ", ".join(problems))

    def add_user(self, username: str, password: str, role: str) -> None:
        if not isinstance(username, str) or username == "":
            raise ValueError("username must be a non-empty string")
        if username in self._users:
            raise ValueError(f"user {username!r} already exists")
        if role not in ROLES:
            raise ValueError("role must be one of: " + ", ".join(ROLES))
        self._check_new_password(password)
        users = dict(self._users)
        users[username] = {"password_hash": crypto.pbkdf2_hash(password), "role": role}
        self._save(users)

    def set_password(self, username: str, password: str) -> None:
        if username not in self._users:
            raise KeyError(username)
        self._check_new_password(password)
        users = dict(self._users)
        users[username] = {**self._users[username], "password_hash": crypto.pbkdf2_hash(password)}
        self._save(users)

    def verify(self, username: str, password: str) -> bool:
        entry = self._users.get(username)
        if entry is None:
            crypto.pbkdf2_verify(password, _DUMMY_PASSWORD_HASH)
            return False
        return crypto.pbkdf2_verify(password, entry["password_hash"])

    def role(self, username: str) -> str | None:
        entry = self._users.get(username)
        return None if entry is None else entry["role"]

    def login(self, username: str, password: str, peer_ip: str) -> str:
        if self._limiter.blocked(peer_ip):
            raise TooManyAttempts("too many failed logins from this address")
        if not self.verify(username, password):
            self._limiter.failure(peer_ip)
            raise LoginFailed("invalid username or password")
        return self._sessions.create(username, self._users[username]["role"])

    def check_session(self, token) -> dict | None:
        return self._sessions.check(token)

    def require_admin(self, token) -> dict:
        session = self.check_session(token)
        if session is None or session["role"] != ROLE_ADMIN:
            raise PermissionDenied("admin role required")
        return session

    def logout(self, token) -> None:
        self._sessions.drop(token)

    def migrate_from_legacy(self) -> bool:
        legacy = self._store.read_json(LEGACY_AUTH_FILE, None)
        if not isinstance(legacy, dict):
            return False
        value = legacy.get("password_hash")
        if not isinstance(value, str):
            return False
        if not value.startswith(crypto.PBKDF2_ALGORITHM + "$") or len(value.split("$")) != 4:
            return False
        if self._users:
            return False
        self._save({"admin": {"password_hash": value, "role": ROLE_ADMIN}})
        return True
