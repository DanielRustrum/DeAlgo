"""Tracking what De-Algo has spent against the YouTube Data API.

Google gives no way to read the remaining allowance, so De-Algo keeps its own
ledger: every request has a published cost, and each one is added to a counter
for the current quota day. The day is a Pacific one, because that is when
Google resets the allowance regardless of where the server sits.

The ledger is deliberately pessimistic — a request is charged whether or not it
did what was asked — so De-Algo stops slightly early rather than discovering the
limit by being refused mid-playlist.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_settings
from ..models import QuotaUsage, utcnow
from .scope import OwnerId, owned

log = logging.getLogger(__name__)

# Google resets Data API quota at midnight Pacific.
QUOTA_TZ = ZoneInfo("America/Los_Angeles")


def quota_day(now: dt.datetime | None = None) -> str:
    """The quota day `now` falls in, as an ISO date in Pacific time."""
    moment = now or dt.datetime.now(dt.timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    return moment.astimezone(QUOTA_TZ).date().isoformat()


def next_reset(now: dt.datetime | None = None) -> dt.datetime:
    """When the allowance next refreshes, in UTC."""
    moment = now or dt.datetime.now(dt.timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    local = moment.astimezone(QUOTA_TZ)
    tomorrow = (local + dt.timedelta(days=1)).date()
    midnight = dt.datetime.combine(tomorrow, dt.time.min, tzinfo=QUOTA_TZ)
    return midnight.astimezone(dt.timezone.utc)


@dataclass(frozen=True)
class QuotaState:
    """One account's quota for today: what is spent, what is allowed, when it resets."""

    day: str
    used: int
    budget: int
    reserve: int
    exhausted: bool
    resets_at: dt.datetime

    @property
    def remaining(self) -> int:
        """Units left before the daily budget, reserve included."""
        return max(0, self.budget - self.used)

    @property
    def spendable(self) -> int:
        """What syncing may use, holding the reserve back for manual actions."""
        if self.exhausted:
            return 0
        return max(0, self.remaining - self.reserve)

    @property
    def percent_used(self) -> int:
        """How much of the budget is spent, 0–100; 100 when there is no budget."""
        return min(100, round(self.used * 100 / self.budget)) if self.budget else 100


def _row(session: Session, owner: OwnerId = None, day: str | None = None) -> QuotaUsage:
    """The owner's ledger row for a day (today by default), made on first use."""
    day = day or quota_day()
    row = session.scalar(
        owned(select(QuotaUsage), QuotaUsage, owner).where(QuotaUsage.day == day)
    )
    if row is None:
        row = QuotaUsage(day=day, units=0, owner_pk=owner)
        session.add(row)
        session.flush()
    return row


def state(session: Session, owner: OwnerId = None) -> QuotaState:
    """The owner's quota as it stands now."""
    settings = get_settings(session, owner)
    row = _row(session, owner)
    return QuotaState(
        day=row.day,
        used=row.units,
        budget=max(0, settings.daily_quota or 0),
        reserve=max(0, settings.quota_reserve or 0),
        exhausted=row.exhausted_at is not None,
        resets_at=next_reset(),
    )


def spend(session: Session, units: int, owner: OwnerId = None) -> None:
    """Charge units to the owner's ledger for today. Nothing for zero or less."""
    if units <= 0:
        return
    row = _row(session, owner)
    row.units += units
    row.updated_at = utcnow()
    session.flush()


def mark_exhausted(session: Session, owner: OwnerId = None) -> None:
    """YouTube said no. Believe it over our own arithmetic."""
    row = _row(session, owner)
    if row.exhausted_at is None:
        row.exhausted_at = utcnow()
        log.warning("YouTube reports the daily quota is exhausted; pausing writes until reset")
    settings = get_settings(session, owner)
    # Keep the ledger honest for the rest of the day.
    row.units = max(row.units, settings.daily_quota or row.units)
    session.flush()


def can_afford(
    session: Session, units: int, *, use_reserve: bool = False, owner: OwnerId = None
) -> bool:
    """Whether the owner can spend `units` now.

    Syncing keeps the reserve back; `use_reserve=True` lets a manual action dip into it.
    """
    current = state(session, owner)
    if current.exhausted:
        return False
    available = current.remaining if use_reserve else current.spendable
    return available >= units


def meter(session: Session, owner: OwnerId = None) -> Callable[[int], None]:
    """A callback the API client charges each request against.

    Each account brings its own Google project, so each keeps its own ledger.
    """

    def record(units: int) -> None:
        """Charge one request's units, logging rather than raising if it fails."""
        try:
            spend(session, units, owner)
        except Exception:  # pragma: no cover - accounting must never break a sync
            log.exception("could not record quota spend")

    return record


def describe_reset(now: dt.datetime | None = None) -> str:
    """When the quota resets, said as "in 3h 05m" or "in 12 min"."""
    resets_at = next_reset(now)
    delta = resets_at - (now or dt.datetime.now(dt.timezone.utc))
    hours = int(delta.total_seconds() // 3600)
    minutes = int((delta.total_seconds() % 3600) // 60)
    if hours:
        return f"in {hours}h {minutes:02d}m"
    return f"in {minutes} min"
