"""The whole instance, encrypted, for moving it to another machine.

This is the other half of the backup story, and deliberately a different thing
from the per-account file:

* **A per-account backup** (services/backup.py) is the shape of one account's
  setup — its feeds and channels — in plain JSON, with no credentials in it,
  meant to be read, kept and restored by the person it belongs to.
* **This** is every account and every setup at once: who the accounts are,
  what each of them watches, and how each of them is configured. It exists to
  stand the same instance up somewhere else.

**No secrets travel in it.** Not password hashes, not Google grants, not API
keys. A migration file is a thing that gets copied between machines, emailed to
oneself and left in a Downloads folder, and a credential that has been through
all that is a credential to be rotated anyway. So the accounts come across and
the passwords do not: the admin sets a new one for each from the Admin page,
and each account reconnects its own Google when it next signs in.

It is still encrypted, because everyone's usernames and everything they watch
is nobody else's business. The passphrase the admin chooses is stretched with
scrypt (the same function passwords use here) and handed to Fernet, which is
authenticated: a file that has been altered fails to open rather than restoring
something subtly wrong. The salt travels in the clear beside the ciphertext,
as it must.

Losing the passphrase means losing the file. There is no recovery, by design.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import logging
import secrets
from dataclasses import dataclass, field
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import __version__
from ..db import get_settings
from ..models import Channel, OAuthToken, Placement, Playlist, User, Video
from . import backup
from .scope import OwnerId

log = logging.getLogger(__name__)

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


# What a restored account has instead of a password. Nothing hashes to it, so
# it cannot be signed in to until the admin sets one — which is the point.
NO_PASSWORD = "none"


@dataclass
class SiteSummary:
    accounts: int = 0
    feeds: int = 0
    channels: int = 0
    notes: list[str] = field(default_factory=list)


def filename(now: dt.datetime | None = None) -> str:
    moment = now or dt.datetime.now(dt.timezone.utc)
    return f"de-algo-site-{moment:%Y-%m-%d}.dealgo"


# -- the passphrase --------------------------------------------------------


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
    if len(passphrase) < MIN_PASSPHRASE:
        raise MigrationError(
            f"Use at least {MIN_PASSPHRASE} characters: this file holds every account's "
            "credentials, and the passphrase is all that stands in front of it."
        )


# -- writing ---------------------------------------------------------------


def _account_payload(session: Session, user: User | None) -> dict[str, Any]:
    """One account: who they are, and everything of theirs."""
    owner: OwnerId = user.id if user else None
    settings = get_settings(session, owner)
    token = session.scalar(
        select(OAuthToken).where(
            OAuthToken.owner_pk.is_(None) if owner is None else OAuthToken.owner_pk == owner
        )
    )

    payload: dict[str, Any] = {
        # Who the account is, and nothing that would let anyone be them.
        "username": user.username if user else None,
        "is_admin": bool(user.is_admin) if user else False,
        "enabled": bool(user.enabled) if user else True,
        # The same shape a per-account backup uses, so one reader serves both.
        "setup": backup.build_export(session, owner),
        "settings": {
            "auto_sync": settings.auto_sync,
            "poll_interval_minutes": settings.poll_interval_minutes,
            "initial_backfill": settings.initial_backfill,
            "shorts_max_seconds": settings.shorts_max_seconds,
            "post_seconds": settings.post_seconds,
            "daily_quota": settings.daily_quota,
            "quota_reserve": settings.quota_reserve,
            "hide_tour": settings.hide_tour,
            "hide_open_notice": settings.hide_open_notice,
            "hide_connect_notice": settings.hide_connect_notice,
            # No client_id, client_secret or api_key. They are credentials,
            # and this file is meant to be moved around.
        },
        # Recorded so a restore can say who will need to reconnect, without
        # carrying anything that would let it reconnect for them.
        "had_google": token is not None,
    }
    return payload


def build_site_export(session: Session, passphrase: str) -> bytes:
    """The whole instance, encrypted, as bytes to hand to a browser."""
    check_passphrase(passphrase)

    users = list(session.scalars(select(User).order_by(User.username)))
    accounts = [_account_payload(session, user) for user in users]

    # Anything still belonging to the implicit owner — an instance that has
    # never had sign-in switched on is entirely this.
    unowned = _account_payload(session, None)
    if unowned["setup"]["feeds"] or unowned["setup"]["channels"]:
        accounts.append(unowned)

    inner = json.dumps(
        {
            "format": FORMAT,
            "version": FORMAT_VERSION,
            "app_version": __version__,
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "accounts": accounts,
        },
        indent=2,
        sort_keys=True,
    ).encode("utf-8")

    salt = secrets.token_bytes(_SALT_BYTES)
    sealed = Fernet(_key_from(passphrase, salt)).encrypt(inner)

    # The envelope is readable so a stranger can tell what the file is, what
    # made it, and that they need a passphrase — without it giving anything up.
    envelope = {
        "format": FORMAT,
        "version": FORMAT_VERSION,
        "app_version": __version__,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "accounts": len(accounts),
        "kdf": {"name": "scrypt", "n": _SCRYPT_N, "r": _SCRYPT_R, "p": _SCRYPT_P,
                "salt": base64.b64encode(salt).decode("ascii")},
        "payload": sealed.decode("ascii"),
    }
    log.info("site backup written: %d account(s)", len(accounts))
    return json.dumps(envelope, indent=2).encode("utf-8")


# -- reading ---------------------------------------------------------------


def open_site_export(blob: bytes, passphrase: str) -> dict[str, Any]:
    """Decrypt and parse, or say plainly which of the two went wrong."""
    try:
        envelope = json.loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MigrationError("That file is not a De-Algo site backup.") from exc
    if not isinstance(envelope, dict) or envelope.get("format") != FORMAT:
        raise MigrationError("That file is not a De-Algo site backup.")
    if envelope.get("version") != FORMAT_VERSION:
        raise MigrationError(
            f"That backup is version {envelope.get('version')}; this De-Algo reads "
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


def restore_site(session: Session, blob: bytes, passphrase: str) -> SiteSummary:
    """Put a site backup onto this instance.

    Merges rather than replaces: accounts that are not here are created, and
    each account's feeds and channels are restored into its own space. Nothing
    already here is deleted, so restoring onto a running instance adds to it
    rather than wiping it — which is the safe way round when the other way is
    unrecoverable.

    The accounts arrive without passwords and without Google connections,
    because the file carries neither. The summary says who needs what.
    """
    from . import accounts as accounts_service

    opened = open_site_export(blob, passphrase)
    summary = SiteSummary()
    needs_password: list[str] = []
    needs_google: list[str] = []

    for payload in opened.get("accounts", []):
        username = payload.get("username")
        owner: OwnerId = None

        if username:
            user = accounts_service.find(session, username)
            if user is None:
                user = User(
                    username=accounts_service.normalize_username(username),
                    # No password came across, and nothing hashes to this, so
                    # the account exists and cannot be signed in to until the
                    # admin sets one.
                    password_hash=NO_PASSWORD,
                    is_admin=False,   # the admin is the environment's, not a file's
                    enabled=bool(payload.get("enabled", True)),
                )
                session.add(user)
                session.flush()
                summary.accounts += 1
                needs_password.append(user.username)
            else:
                summary.notes.append(f"{user.username} was already here; its setup was merged.")
            owner = user.id
            if payload.get("had_google"):
                needs_google.append(user.username)

        _restore_settings(session, payload.get("settings") or {}, owner)

        setup = payload.get("setup") or {}
        if setup:
            restored = backup.restore(session, setup, owner)
            summary.feeds += restored.feeds
            summary.channels += restored.channels

    # Say what is still missing, by name. A restore that looks complete and is
    # not is worse than one that tells you what is left to do.
    if needs_password:
        summary.notes.append(
            f"Set a password for {', '.join(sorted(needs_password))} before they can sign in."
        )
    if needs_google:
        summary.notes.append(
            f"{', '.join(sorted(needs_google))} had a Google account connected and will need to "
            "connect it again."
        )

    session.flush()
    log.info("site backup restored: %d new account(s)", summary.accounts)
    return summary


def _restore_settings(session: Session, values: dict[str, Any], owner: OwnerId) -> None:
    settings = get_settings(session, owner)
    for name, value in values.items():
        if hasattr(settings, name) and name not in {"id", "owner_pk"}:
            setattr(settings, name, value)
    session.flush()
