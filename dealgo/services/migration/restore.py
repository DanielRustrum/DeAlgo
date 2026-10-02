"""Standing a migration file's accounts up here."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from ...db import get_settings
from ...models import User
from .. import backup
from ..scope import OwnerId
from .sealing import open_site_export

log = logging.getLogger(__name__)


# What a restored account has instead of a password. Nothing hashes to it, so
# it cannot be signed in to until the admin sets one — which is the point.
NO_PASSWORD = "none"


@dataclass
class SiteSummary:
    """What a migration restore made, counted, and what the admin must do next."""

    accounts: int = 0
    feeds: int = 0
    channels: int = 0
    notes: list[str] = field(default_factory=list)


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
    from .. import accounts as accounts_service

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
    """Lay a migrated account's settings over its own."""
    settings = get_settings(session, owner)
    for name, value in values.items():
        if hasattr(settings, name) and name not in {"id", "owner_pk"}:
            setattr(settings, name, value)
    session.flush()
