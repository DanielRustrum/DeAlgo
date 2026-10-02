"""A sync run, and the lines of its log."""

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
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, owner_column
from .times import utcnow


class SyncRun(Base):
    __tablename__ = "sync_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_pk: Mapped[Optional[int]] = owner_column()
    started_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, index=True)
    finished_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)
    trigger: Mapped[str] = mapped_column(String(16), default="manual")
    # A forced run polls every channel, ignoring their minimum gaps.
    forced: Mapped[bool] = mapped_column(Boolean, default=False)
    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    channels_checked: Mapped[int] = mapped_column(Integer, default=0)
    discovered: Mapped[int] = mapped_column(Integer, default=0)
    added: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    pruned: Mapped[int] = mapped_column(Integer, default=0)
    removed: Mapped[int] = mapped_column(Integer, default=0)
    quota_spent: Mapped[int] = mapped_column(Integer, default=0)
    stopped_on_quota: Mapped[bool] = mapped_column(Boolean, default=False)
    message: Mapped[Optional[str]] = mapped_column(Text)

    events: Mapped[list["RunEvent"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="RunEvent.seq"
    )

    # How a run came to happen. Kept as plain strings because they are written
    # into old rows too, and a column of names nobody can read is no worse
    # than an enum nobody can migrate.
    BY_HAND = ("manual", "cli", "pulse", "backfill", "test")

    @property
    def by_hand(self) -> bool:
        """Whether somebody started this, as against the clock starting it.

        The distinction people actually want from a log: "did I do this, or
        did it happen on its own?" — which is the first question asked of any
        line in it.
        """
        return self.trigger in self.BY_HAND

    @property
    def how(self) -> str:
        """What to call the thing that started it, in a word or two."""
        return {
            "pulse": "Run now",
            "backfill": "Backfill",
            "test": "Test",
            "manual": "By hand",
            "cli": "Command line",
            "scheduled": "On a schedule",
        }.get(self.trigger, self.trigger)

    @property
    def wrote_nothing(self) -> bool:
        """A trial: it went through the whole graph and kept none of it."""
        return self.trigger == "test"


class RunEvent(Base):
    """One line in the log of a run.

    Written as the run goes rather than summarised at the end, so a run that
    is still going can be read, and one that fell over says how far it got.

    The thing it is about is stored as text rather than as a foreign key: a
    log is a record of what happened, and deleting a channel should not
    quietly rewrite the history of the runs that polled it.
    """

    __tablename__ = "run_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_pk: Mapped[Optional[int]] = owner_column()
    run_pk: Mapped[int] = mapped_column(
        ForeignKey("sync_run.id", ondelete="CASCADE"), index=True
    )
    at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)
    #: Order within the run. Several lines can share a timestamp, and a log
    #: whose order depends on how fast the clock ticks is not a log.
    seq: Mapped[int] = mapped_column(Integer, default=0)
    #: "info", "warn" or "bad" — how much it wants looking at.
    level: Mapped[str] = mapped_column(String(8), default="info", index=True)
    #: Which part of the run this happened in.
    stage: Mapped[str] = mapped_column(String(16), default="polling")
    #: What it concerns — a channel, a feed, a box — by name.
    about: Mapped[Optional[str]] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text, default="")

    run: Mapped[SyncRun] = relationship(back_populates="events")
