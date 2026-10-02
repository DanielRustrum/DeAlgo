"""The rows every account has exactly one of, made on first use."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import OAuthToken, Settings


def get_settings(session: Session, owner: int | None = None) -> Settings:
    """This account's settings, made on first use.

    Every account keeps its own — the poll interval, the backfill, the quota
    and the Google credentials all belong to whoever set them. `owner=None` is
    the implicit account, which is what everything is while sign-in is off.
    """
    settings = session.scalar(
        select(Settings).where(
            Settings.owner_pk.is_(None) if owner is None else Settings.owner_pk == owner
        )
    )
    if settings is None:
        settings = Settings(owner_pk=owner)
        session.add(settings)
        session.flush()
    return settings


def get_token(session: Session, owner: int | None = None) -> OAuthToken | None:
    """This account's Google grant. Each connects their own."""
    return session.scalar(
        select(OAuthToken).where(
            OAuthToken.owner_pk.is_(None) if owner is None else OAuthToken.owner_pk == owner
        )
    )
