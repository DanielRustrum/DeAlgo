"""One account's settings."""

from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Integer,
    String,
    Text,
    text,
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
    # The pamphlet the Pamphlets tab opens on, a Pamphlet box's id. Not a
    # foreign key: the box can go, and the tab then shows them all.
    default_pamphlet_pk: Mapped[Optional[int]] = mapped_column(Integer)

    # The model a Text box writes with: which kind of service, which model,
    # where (for a server of one's own, or a proxy), and its key. The key is
    # a secret: never sent back to a page, and never in a backup.
    ai_provider: Mapped[Optional[str]] = mapped_column(String(16))
    ai_model: Mapped[Optional[str]] = mapped_column(String(120))
    ai_base_url: Mapped[Optional[str]] = mapped_column(Text)
    ai_key: Mapped[Optional[str]] = mapped_column(Text)

    # The algorithm of one's own: whether Focus mode remembers how things are
    # watched, so it can learn; how far back it learns from; how many
    # examples it needs before it says anything; and how often it learns again.
    algorithm_on: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("1"))
    algorithm_days: Mapped[int] = mapped_column(Integer, default=90, server_default=text("90"))
    algorithm_min: Mapped[int] = mapped_column(Integer, default=20, server_default=text("20"))
    algorithm_every: Mapped[str] = mapped_column(String(8), default="daily", server_default=text("'daily'"))

    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
