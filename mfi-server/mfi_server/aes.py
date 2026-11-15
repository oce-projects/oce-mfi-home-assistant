"""AES-128 block cipher and CBC mode in pure Python, written from FIPS-197.

The S-box is computed from its definition (inverse in GF(2^8), then the affine
transform), so no table is copied. Only the standard library is used.
Checked by the official vectors in tests/test_aes.py.
"""
from __future__ import annotations

import functools
import logging
from collections.abc import Sequence

logger = logging.getLogger(__name__)

BLOCK_SIZE = 16
KEY_SIZE = 16
ROUNDS = 10
INVALID_PADDING = "invalid padding"


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


@functools.lru_cache(maxsize=256)
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


def _cbc_setup(key: bytes, iv: bytes, data: bytes) -> tuple[tuple[bytes, ...], bytes, bytes]:
    round_keys = _expand_key(_check_bytes(key, KEY_SIZE, "key"))
    iv = _check_bytes(iv, BLOCK_SIZE, "iv")
    if not isinstance(data, (bytes, bytearray)) or not data or len(data) % BLOCK_SIZE:
        raise ValueError("data must be a non-empty multiple of 16 bytes")
    return round_keys, iv, bytes(data)


def encrypt_block(key: bytes, block: bytes) -> bytes:
    """Encrypt one 16-byte block with a 16-byte key."""
    round_keys = _expand_key(_check_bytes(key, KEY_SIZE, "key"))
    return _encrypt_state(round_keys, _check_bytes(block, BLOCK_SIZE, "block"))


def decrypt_block(key: bytes, block: bytes) -> bytes:
    """Decrypt one 16-byte block with a 16-byte key."""
    round_keys = _expand_key(_check_bytes(key, KEY_SIZE, "key"))
    return _decrypt_state(round_keys, _check_bytes(block, BLOCK_SIZE, "block"))


def encrypt_cbc(key: bytes, iv: bytes, data: bytes) -> bytes:
    """Encrypt whole blocks in CBC mode. No padding is added."""
    round_keys, prev, data = _cbc_setup(key, iv, data)
    out = bytearray()
    for i in range(0, len(data), BLOCK_SIZE):
        prev = _encrypt_state(round_keys, _xor(data[i:i + BLOCK_SIZE], prev))
        out += prev
    return bytes(out)


def decrypt_cbc(key: bytes, iv: bytes, data: bytes) -> bytes:
    """Decrypt whole blocks in CBC mode. No padding is removed."""
    round_keys, prev, data = _cbc_setup(key, iv, data)
    out = bytearray()
    for i in range(0, len(data), BLOCK_SIZE):
        chunk = data[i:i + BLOCK_SIZE]
        out += bytes(_xor(_decrypt_state(round_keys, chunk), prev))
        prev = chunk
    return bytes(out)


def pkcs7_pad(data: bytes) -> bytes:
    """Append from 1 to 16 bytes, each holding the number of bytes added."""
    count = BLOCK_SIZE - len(data) % BLOCK_SIZE
    return bytes(data) + bytes([count]) * count


def pkcs7_unpad(data: bytes) -> bytes:
    """Remove PKCS#7 padding, raising ValueError if it is not valid."""
    if not isinstance(data, (bytes, bytearray)) or not data or len(data) % BLOCK_SIZE:
        raise ValueError(INVALID_PADDING)
    count = data[-1]
    if count == 0 or count > BLOCK_SIZE or data[-count:] != bytes([count]) * count:
        raise ValueError(INVALID_PADDING)
    return bytes(data[:-count])
