"""The migration file itself: an envelope anyone can read, around contents only the
passphrase opens. scrypt stretches the passphrase; Fernet seals, and refuses a
file that has been altered.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import secrets
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from ... import __version__

FORMAT = "dealgo-site-backup"


FORMAT_VERSION = 1


# Deliberately heavier than a login: this runs once, by hand, and the file it
# guards holds every account's credentials.
_SCRYPT_N = 2**15


_SCRYPT_R = 8


_SCRYPT_P = 1


_SALT_BYTES = 16


MIN_PASSPHRASE = 12


class MigrationError(RuntimeError):
    """Something worth telling the admin about, in words."""


def _key_from(passphrase: str, salt: bytes) -> bytes:
    """Fernet wants 32 url-safe base64 bytes; scrypt makes the 32."""
    derived = hashlib.scrypt(
        passphrase.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=32,
        maxmem=128 * 1024 * 1024,
    )
    return base64.urlsafe_b64encode(derived)


def check_passphrase(passphrase: str) -> None:
    """Raise `MigrationError` if the passphrase is too short to protect the file."""
    if len(passphrase) < MIN_PASSPHRASE:
        raise MigrationError(
            f"Use at least {MIN_PASSPHRASE} characters: this file holds every account's "
            "credentials, and the passphrase is all that stands in front of it."
        )


def seal(contents: dict[str, Any], passphrase: str, *, accounts: int) -> bytes:
    """The file: the contents sealed with the passphrase, inside an envelope.

    The envelope is readable so a stranger can tell what the file is, what
    made it, and that they need a passphrase — without it giving anything up.
    """
    inner = json.dumps(contents, indent=2, sort_keys=True).encode("utf-8")
    salt = secrets.token_bytes(_SALT_BYTES)
    sealed = Fernet(_key_from(passphrase, salt)).encrypt(inner)
    envelope = {
        "format": FORMAT,
        "version": FORMAT_VERSION,
        "app_version": __version__,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "accounts": accounts,
        "kdf": {"name": "scrypt", "n": _SCRYPT_N, "r": _SCRYPT_R, "p": _SCRYPT_P,
                "salt": base64.b64encode(salt).decode("ascii")},
        "payload": sealed.decode("ascii"),
    }
    return json.dumps(envelope, indent=2).encode("utf-8")


def open_site_export(blob: bytes, passphrase: str) -> dict[str, Any]:
    """Decrypt and parse, or say plainly which of the two went wrong."""
    try:
        envelope = json.loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MigrationError("That file is not a Pamphlets site backup.") from exc
    if not isinstance(envelope, dict) or envelope.get("format") != FORMAT:
        raise MigrationError("That file is not a Pamphlets site backup.")
    if envelope.get("version") != FORMAT_VERSION:
        raise MigrationError(
            f"That backup is version {envelope.get('version')}; this Pamphlets reads "
            f"version {FORMAT_VERSION}."
        )

    kdf = envelope.get("kdf") or {}
    try:
        salt = base64.b64decode(kdf["salt"])
        sealed = str(envelope["payload"]).encode("ascii")
    except (KeyError, ValueError, TypeError) as exc:
        raise MigrationError("That backup is missing the parts needed to open it.") from exc

    try:
        opened = Fernet(_key_from(passphrase, salt)).decrypt(sealed)
    except InvalidToken as exc:
        # Fernet cannot tell a wrong passphrase from a tampered file, and
        # neither can this: both mean the contents cannot be trusted.
        raise MigrationError(
            "That passphrase does not open this file — or the file has been altered since it "
            "was written."
        ) from exc

    parsed: dict[str, Any] = json.loads(opened.decode("utf-8"))
    return parsed
