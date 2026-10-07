"""What the on-device algorithm learns from, what it learned, and the switch for it.

Everything here stays on this install. Nothing is sent anywhere: the point
of an algorithm of one's own is that it answers to nobody else.
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, owner_column
from .times import utcnow


class Consumption(Base):
    """One time something was open in Focus mode, and how it went.

    What the algorithm learns from: whether it was opened at all (interest),
    how much of it was taken in (retention), and how often it was stopped
    and started again (engagement). Written when Focus moves on from an item,
    or when the page is left with one still open.
    """

    __tablename__ = "consumption"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_pk: Mapped[Optional[int]] = owner_column()
    video_pk: Mapped[int] = mapped_column(
        ForeignKey("video.id", ondelete="CASCADE"), index=True
    )
    at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, index=True)
    #: How long it was on screen, in seconds.
    seconds: Mapped[float] = mapped_column(Float, default=0.0)
    #: How far into a video it got, and how long the video is, in seconds;
    #: None for anything read rather than played.
    reached: Mapped[Optional[float]] = mapped_column(Float)
    duration: Mapped[Optional[float]] = mapped_column(Float)
    #: How many times it was paused and played again.
    pauses: Mapped[int] = mapped_column(Integer, default=0)
    #: Opened on purpose — its card was clicked — rather than reached in turn.
    clicked: Mapped[bool] = mapped_column(Boolean, default=False)
    #: Passed over with Skip, or played to the end / marked done.
    skipped: Mapped[bool] = mapped_column(Boolean, default=False)
    finished: Mapped[bool] = mapped_column(Boolean, default=False)


class AlgorithmModel(Base):
    """What the algorithm learned for one account, for one signal.

    A linear model over an item's features — its source, kind, tags, title
    words, length and when it went up — as weights by feature name, so what
    it leans towards can be read back and shown.
    """

    __tablename__ = "algorithm_model"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_pk: Mapped[Optional[int]] = owner_column()
    #: "interest", "retention" or "engagement".
    signal: Mapped[str] = mapped_column(String(16), index=True)
    #: {"bias": float, "weights": {feature: weight}} as JSON.
    weights: Mapped[str] = mapped_column(Text, default="{}")
    examples: Mapped[int] = mapped_column(Integer, default=0)
    #: How well it did on the examples held back from it: accuracy for
    #: interest, one minus mean error for the others. None if too few to tell.
    quality: Mapped[Optional[float]] = mapped_column(Float)
    trained_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow)


class SiteSetting(Base):
    """A setting for the whole install, the admin's: a name and a value."""

    __tablename__ = "site_setting"

    name: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
