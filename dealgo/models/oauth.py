"""One account's Google grant."""

from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy import (
    DateTime,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, owner_column
from .times import to_naive_utc, utcnow


class OAuthToken(Base):
    """One account's Google OAuth grant. Every account connects its own."""

    __tablename__ = "oauth_token"

    # One grant per account, so the primary key is its own, not a fixed 1.
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_pk: Mapped[Optional[int]] = owner_column()
    access_token: Mapped[str] = mapped_column(Text)
    refresh_token: Mapped[Optional[str]] = mapped_column(Text)
    expires_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)
    scope: Mapped[Optional[str]] = mapped_column(Text)
    account_title: Mapped[Optional[str]] = mapped_column(String(255))
    # Set when Google refuses to refresh (revoked, or the weekly expiry that
    # applies while the consent screen is still in Testing).
    refresh_error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    def is_expired(self, skew_seconds: int = 60) -> bool:
        if self.expires_at is None:
            return True
        return utcnow() >= to_naive_utc(self.expires_at) - dt.timedelta(seconds=skew_seconds)
