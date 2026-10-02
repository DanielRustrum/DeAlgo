"""Every account and its setup, sealed into one file."""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ... import __version__
from ...db import get_settings
from ...models import OAuthToken, User
from .. import backup
from ..scope import OwnerId
from .sealing import FORMAT, FORMAT_VERSION, check_passphrase, seal

log = logging.getLogger(__name__)


def filename(now: dt.datetime | None = None) -> str:
    moment = now or dt.datetime.now(dt.timezone.utc)
    return f"de-algo-site-{moment:%Y-%m-%d}.dealgo"


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

    contents = {
        "format": FORMAT,
        "version": FORMAT_VERSION,
        "app_version": __version__,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "accounts": accounts,
    }
    log.info("site backup written: %d account(s)", len(accounts))
    return seal(contents, passphrase, accounts=len(accounts))
