"""Accounts and the browsers signed in to them."""

from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .times import to_naive_utc, utcnow


class User(Base):
    """Someone who may sign in.

    The admin comes from the environment and is recreated from it on every
    start; everyone else is created here by the admin. A password is stored
    only as a scrypt hash with its own salt — see services/accounts.py.
    """

    __tablename__ = "user"
    __table_args__ = (UniqueConstraint("username", name="uq_user_username"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    # Admins manage accounts and the site's own settings. Everyone else uses
    # the feeds without being able to reach the credentials behind them.
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    # A disabled account keeps its history but cannot sign in, and its live
    # sessions are dropped the moment it is switched off.
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    last_seen_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)

    sessions: Mapped[list["LoginSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class LoginSession(Base):
    """One signed-in browser.

    Sessions live here rather than in a signed cookie so that disabling an
    account, or signing out everywhere, takes effect at once. Only a hash of
    the token is stored: the cookie is the secret, and a copy of this table is
    not enough to impersonate anyone.
    """

    __tablename__ = "login_session"
    __table_args__ = (UniqueConstraint("token_hash", name="uq_session_token"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), index=True)
    user_pk: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime, index=True)
    last_used_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)
    # Enough to recognise a session in the list, and nothing identifying.
    agent: Mapped[Optional[str]] = mapped_column(String(255))

    user: Mapped[User] = relationship(back_populates="sessions")

    @property
    def expired(self) -> bool:
        """Whether this session has passed its expiry."""
        return utcnow() >= to_naive_utc(self.expires_at)
