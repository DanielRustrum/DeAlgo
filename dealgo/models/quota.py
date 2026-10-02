"""What one account spent against the YouTube quota on one day."""

from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy import (
    DateTime,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, owned_unique, owner_column
from .times import utcnow


class QuotaUsage(Base):
    """What De-Algo has spent against the YouTube API today.

    One row per quota day, which Google resets at midnight Pacific — so the day
    key is a Pacific date, not a local or UTC one.
    """

    __tablename__ = "quota_usage"
    # Each account spends against its own Google project, so each keeps its
    # own ledger for the day.
    __table_args__ = (owned_unique("quota_usage", "day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_pk: Mapped[Optional[int]] = owner_column()
    day: Mapped[str] = mapped_column(String(10), index=True)
    units: Mapped[int] = mapped_column(Integer, default=0)
    # Set when YouTube itself said the quota is gone, which overrides our count.
    exhausted_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
