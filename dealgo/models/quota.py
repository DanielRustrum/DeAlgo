"""What has been spent today against a service's daily allowance."""

from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base
from .times import utcnow


class AllowanceUsage(Base):
    """One day's spending against one plugin's service, for the whole install.

    A service that rations requests — YouTube's daily quota is the one there
    is — rations them per OAuth client, and the client is the admin's, set
    once on the plugin's card. So the ledger is the install's too: every
    account spends the same allowance, and each sees what is left of it.

    The day is the service's own (its `allowance.timezone`), since that is
    when the service starts counting again, wherever the server sits.
    """

    __tablename__ = "allowance_usage"
    __table_args__ = (UniqueConstraint("provider", "day", name="uq_allowance_usage_provider_day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: The plugin whose service this is, by id.
    provider: Mapped[str] = mapped_column(String(64), index=True)
    day: Mapped[str] = mapped_column(String(10))
    units: Mapped[int] = mapped_column(Integer, default=0)
    # Set when the service itself said the allowance is gone, which
    # overrides the count.
    exhausted_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
