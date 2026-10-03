"""One account's settings."""

from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, owner_column
from .times import utcnow


class Settings(Base):
    """One account's configuration. Every account keeps its own."""

    __tablename__ = "settings"

    # No default any more: there is a row per account, not a singleton, and a
    # default of 1 meant every new one collided with the first.
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_pk: Mapped[Optional[int]] = owner_column()

    auto_sync: Mapped[bool] = mapped_column(Boolean, default=True)
    poll_interval_minutes: Mapped[int] = mapped_column(Integer, default=30)

    # New channels start with only this many of their recent uploads, so adding
    # a channel does not dump its last fifteen videos into the playlist.
    initial_backfill: Mapped[int] = mapped_column(Integer, default=3)
    # How long Focus mode holds a community post before moving on. A post has
    # no end of its own, so reading time is the only thing that can advance it.
    post_seconds: Mapped[int] = mapped_column(Integer, default=30)

    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
