"""Password hashing for the lightweight login (stdlib only, no deps).

Not a security showcase -- CLAUDE.md lists a full auth system as a non-goal --
just enough to tell users apart: a salted scrypt hash, constant-time verify. No
tokens or sessions; the frontend remembers the returned user id locally.
"""

from __future__ import annotations

import hashlib
import hmac
import os

_N = 2**14
_R = 8
_P = 1
_DKLEN = 32
_SALT_BYTES = 16
_PREFIX = "scrypt"


def hash_password(password: str) -> str:
    salt = os.urandom(_SALT_BYTES)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN)
    return f"{_PREFIX}${_N}${_R}${_P}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        prefix, n, r, p, salt_hex, hash_hex = stored.split("$")
        if prefix != _PREFIX:
            return False
        expected = bytes.fromhex(hash_hex)
        dk = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(dk, expected)
