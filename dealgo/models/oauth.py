"""One account's sign-in to a plugin's service."""

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
    """One account's OAuth grant for one plugin's service. Each account
    connects its own, through the plugin that declared how (its `connect`)."""

    __tablename__ = "oauth_token"

    # One grant per account and service, so the primary key is its own.
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_pk: Mapped[Optional[int]] = owner_column()
    #: The plugin whose service granted it, by id.
    provider: Mapped[str] = mapped_column(String(64), default="", index=True)
    access_token: Mapped[str] = mapped_column(Text)
    refresh_token: Mapped[Optional[str]] = mapped_column(Text)
    expires_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)
    scope: Mapped[Optional[str]] = mapped_column(Text)
    account_title: Mapped[Optional[str]] = mapped_column(String(255))
    # Set when the service refuses to refresh it (revoked, or expired by the
    # service's own rules), so the page can say so rather than "connected".
    refresh_error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    def is_expired(self, skew_seconds: int = 60) -> bool:
        """Whether the access token has expired, or will within `skew_seconds`."""
        if self.expires_at is None:
            return True
        return utcnow() >= to_naive_utc(self.expires_at) - dt.timedelta(seconds=skew_seconds)
