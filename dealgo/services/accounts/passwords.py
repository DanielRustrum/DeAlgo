"""Passwords: scrypt with a salt each, compared in constant time."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from .errors import AccountError

# scrypt at the parameters OWASP suggests for interactive logins: ~16 MB of
# memory per attempt, which is the point — it is what makes guessing slow.
_SCRYPT_N = 2**14


_SCRYPT_R = 8


_SCRYPT_P = 1


_KEY_LENGTH = 32


_SALT_BYTES = 16


# Long enough that guessing is hopeless, short enough to type. The limit stops
# a very long password becoming a way to make the server do a lot of work.
MIN_PASSWORD_LENGTH = 8


MAX_PASSWORD_LENGTH = 1024


def hash_password(password: str, *, enforce_length: bool = True) -> str:
    """`scrypt$<salt>$<key>`, both hex. The salt is per password.

    The length rule is skipped only for the admin password, which comes from
    the environment: that is the operator's own decision, and refusing it
    would mean refusing to start. Everything else goes through the rule.
    """
    if enforce_length:
        check_password(password)
    elif not password:
        raise AccountError("A password is needed.")
    salt = secrets.token_bytes(_SALT_BYTES)
    key = _derive(password, salt)
    return f"scrypt${salt.hex()}${key.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time, and False rather than an exception for anything odd."""
    try:
        scheme, salt_hex, key_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(key_hex)
    except ValueError:
        return False
    if not password or len(password) > MAX_PASSWORD_LENGTH:
        return False
    return hmac.compare_digest(_derive(password, salt), expected)


def _derive(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_KEY_LENGTH,
        maxmem=64 * 1024 * 1024,
    )


def check_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AccountError(f"A password needs at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise AccountError("That password is longer than De-Algo will hash.")
