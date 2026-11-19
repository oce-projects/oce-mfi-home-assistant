"""AES-128-CBC and PBKDF2 password hashing, standard library only.

The AES-128 cipher is written from FIPS-197 in this file: the S-box is computed
from its definition, the key is expanded and CBC mode is applied. The logic
follows mfi_server/aes.py; this package does not import it.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from collections.abc import Sequence

BLOCK_SIZE = 16
KEY_SIZE = 16
ROUNDS = 10
DEFAULT_ITERATIONS = 600000
MAX_ITERATIONS = 10_000_000  # upper bound: a crafted stored hash must not pin the CPU.
PBKDF2_ALGORITHM = "pbkdf2_sha256"
PBKDF2_SALT_SIZE = 16
_HEX = re.compile(r"[0-9a-fA-F]*")


def _xtime(value: int) -> int:
    """Multiply by x (0x02) in GF(2^8) with the AES polynomial 0x11B."""
    value <<= 1
    if value & 0x100:
        value ^= 0x11B
    return value


def _gmul(a: int, b: int) -> int:
    """Multiply two elements of GF(2^8)."""
    result = 0
    while b:
        if b & 1:
            result ^= a
        a = _xtime(a)
        b >>= 1
    return result


def _make_sboxes() -> tuple[list[int], list[int]]:
    """Build the S-box and its inverse from the GF(2^8) inverse and the affine map."""
    inverse = [0] * 256
    for x in range(1, 256):
        for y in range(1, 256):
            if _gmul(x, y) == 1:
                inverse[x] = y
                break
    sbox = []
    for x in range(256):
        b = inverse[x]
        s = b
        for shift in range(1, 5):
            s ^= ((b << shift) | (b >> (8 - shift))) & 0xFF
        sbox.append(s ^ 0x63)
    inv_sbox = [0] * 256
    for x, s in enumerate(sbox):
        inv_sbox[s] = x
    return sbox, inv_sbox


_SBOX, _INV_SBOX = _make_sboxes()


def _make_rcon() -> list[int]:
    """Round constants: successive powers of x in GF(2^8), one per round."""
    values = []
    value = 1
    for _ in range(ROUNDS):
        values.append(value)
        value = _xtime(value)
    return values


_RCON = _make_rcon()


def _xor(a: Sequence[int], b: Sequence[int]) -> list[int]:
    return [x ^ y for x, y in zip(a, b)]


def _expand_key(key: bytes) -> tuple[bytes, ...]:
    """Expand a 16-byte key into 11 round keys of 16 bytes (44 words)."""
    words = [list(key[i:i + 4]) for i in range(0, KEY_SIZE, 4)]
    for i in range(4, 4 * (ROUNDS + 1)):
        temp = list(words[i - 1])
        if i % 4 == 0:
            temp = [_SBOX[b] for b in temp[1:] + temp[:1]]
            temp[0] ^= _RCON[i // 4 - 1]
        words.append(_xor(words[i - 4], temp))
    return tuple(
        bytes(b for word in words[4 * r:4 * r + 4] for b in word)
        for r in range(ROUNDS + 1)
    )


def _shift_rows(state: Sequence[int]) -> list[int]:
    return [state[r + 4 * ((c + r) % 4)] for c in range(4) for r in range(4)]


def _inv_shift_rows(state: Sequence[int]) -> list[int]:
    return [state[r + 4 * ((c - r) % 4)] for c in range(4) for r in range(4)]


def _mix_columns(state: Sequence[int]) -> list[int]:
    out: list[int] = []
    for c in range(4):
        a0, a1, a2, a3 = state[4 * c:4 * c + 4]
        out += [
            _gmul(a0, 2) ^ _gmul(a1, 3) ^ a2 ^ a3,
            a0 ^ _gmul(a1, 2) ^ _gmul(a2, 3) ^ a3,
            a0 ^ a1 ^ _gmul(a2, 2) ^ _gmul(a3, 3),
            _gmul(a0, 3) ^ a1 ^ a2 ^ _gmul(a3, 2),
        ]
    return out


def _inv_mix_columns(state: Sequence[int]) -> list[int]:
    out: list[int] = []
    for c in range(4):
        a0, a1, a2, a3 = state[4 * c:4 * c + 4]
        out += [
            _gmul(a0, 14) ^ _gmul(a1, 11) ^ _gmul(a2, 13) ^ _gmul(a3, 9),
            _gmul(a0, 9) ^ _gmul(a1, 14) ^ _gmul(a2, 11) ^ _gmul(a3, 13),
            _gmul(a0, 13) ^ _gmul(a1, 9) ^ _gmul(a2, 14) ^ _gmul(a3, 11),
            _gmul(a0, 11) ^ _gmul(a1, 13) ^ _gmul(a2, 9) ^ _gmul(a3, 14),
        ]
    return out


def _encrypt_state(round_keys: tuple[bytes, ...], block: Sequence[int]) -> bytes:
    state = _xor(block, round_keys[0])
    for r in range(1, ROUNDS):
        state = _mix_columns(_shift_rows([_SBOX[b] for b in state]))
        state = _xor(state, round_keys[r])
    state = _shift_rows([_SBOX[b] for b in state])
    return bytes(_xor(state, round_keys[ROUNDS]))


def _decrypt_state(round_keys: tuple[bytes, ...], block: Sequence[int]) -> bytes:
    state = _xor(block, round_keys[ROUNDS])
    for r in range(ROUNDS - 1, 0, -1):
        state = [_INV_SBOX[b] for b in _inv_shift_rows(state)]
        state = _inv_mix_columns(_xor(state, round_keys[r]))
    state = [_INV_SBOX[b] for b in _inv_shift_rows(state)]
    return bytes(_xor(state, round_keys[0]))


def _check_bytes(value: bytes, length: int, name: str) -> bytes:
    if not isinstance(value, (bytes, bytearray)) or len(value) != length:
        raise ValueError(f"{name} must be {length} bytes")
    return bytes(value)


def _check_data(data: bytes) -> bytes:
    if not isinstance(data, (bytes, bytearray)) or not data or len(data) % BLOCK_SIZE:
        raise ValueError("data must be a non-empty multiple of 16 bytes")
    return bytes(data)


def _pkcs7_pad(data: bytes) -> bytes:
    """Append from 1 to 16 bytes, each holding the number of bytes added."""
    count = BLOCK_SIZE - len(data) % BLOCK_SIZE
    return data + bytes([count]) * count


def _pkcs7_unpad(data: bytes) -> bytes:
    """Remove PKCS#7 padding, raising ValueError if it is not valid."""
    if not data:
        raise ValueError("invalid padding")
    count = data[-1]
    if count == 0 or count > BLOCK_SIZE or count > len(data) or data[-count:] != bytes([count]) * count:
        raise ValueError("invalid padding")
    return data[:-count]


def aes128_decrypt(key: bytes, iv: bytes, data: bytes, *, unpad: bool = True) -> bytes:
    """Decrypt AES-128-CBC. unpad=True removes PKCS#7 padding; unpad=False returns raw blocks."""
    round_keys = _expand_key(_check_bytes(key, KEY_SIZE, "key"))
    prev = _check_bytes(iv, BLOCK_SIZE, "iv")
    cipher = _check_data(data)
    out = bytearray()
    for i in range(0, len(cipher), BLOCK_SIZE):
        chunk = cipher[i:i + BLOCK_SIZE]
        out += bytes(_xor(_decrypt_state(round_keys, chunk), prev))
        prev = chunk
    plain = bytes(out)
    return _pkcs7_unpad(plain) if unpad else plain


def aes128_encrypt(key: bytes, iv: bytes, data: bytes, *, pad: bool = True) -> bytes:
    """Encrypt AES-128-CBC. pad=True adds PKCS#7 padding before encryption."""
    round_keys = _expand_key(_check_bytes(key, KEY_SIZE, "key"))
    prev = _check_bytes(iv, BLOCK_SIZE, "iv")
    if not isinstance(data, (bytes, bytearray)):
        raise ValueError("data must be bytes")
    plain = _check_data(_pkcs7_pad(bytes(data)) if pad else data)
    out = bytearray()
    for i in range(0, len(plain), BLOCK_SIZE):
        prev = _encrypt_state(round_keys, _xor(plain[i:i + BLOCK_SIZE], prev))
        out += prev
    return bytes(out)


def pbkdf2_hash(password: str, *, salt: bytes | None = None, iterations: int = DEFAULT_ITERATIONS) -> str:
    """Return 'pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>' for the password."""
    if iterations < 1:
        raise ValueError("iterations must be at least 1")
    if iterations > MAX_ITERATIONS:
        raise ValueError(f"iterations must not exceed {MAX_ITERATIONS}")
    if salt is None:
        salt = secrets.token_bytes(PBKDF2_SALT_SIZE)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{PBKDF2_ALGORITHM}${iterations}${salt.hex()}${digest.hex()}"


def pbkdf2_verify(password: str, stored: str) -> bool:
    """Return True only when the password matches the stored hash; malformed input gives False."""
    try:
        fields = stored.split("$")
        if len(fields) != 4 or fields[0] != PBKDF2_ALGORITHM:
            return False
        if not fields[1].isdigit():
            return False
        iterations = int(fields[1])
        if iterations < 1 or iterations > MAX_ITERATIONS or not _HEX.fullmatch(fields[2]) or not _HEX.fullmatch(fields[3]):
            return False
        salt = bytes.fromhex(fields[2])
        expected = bytes.fromhex(fields[3])
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    except (AttributeError, TypeError, ValueError, OverflowError):
        return False
    return hmac.compare_digest(digest, expected)
