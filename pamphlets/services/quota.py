"""Keeping count against a service's daily allowance.

Some services ration requests: YouTube gives each OAuth client so many units
a day and refuses the rest. Which service, how many, when its day starts and
what a refusal for running out looks like are the plugin's — its
`connect.allowance` (registry/connect.py) — and the limits are its settings
for everyone, so the admin can change them on its card.

The service gives no way to read what is left, so this keeps its own ledger:
every request is charged what the plugin says it costs, against a counter for
the service's current day. One ledger for the install, because the client is
the install's and every account spends the same allowance.

The ledger is pessimistic — a request is charged whether or not it did what
was asked — so writes stop slightly early rather than discovering the limit by
being refused halfway through a playlist.

Every function here is about the plugin that publishes unless told which.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AllowanceUsage, utcnow
from ..plugins.registry.connect import Allowance
from . import connections, plugin_settings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class QuotaState:
    """A service's allowance for today: what is spent, what is allowed, when it resets."""

    day: str
    used: int
    budget: int
    reserve: int
    exhausted: bool
    resets_at: dt.datetime
    #: False for a service with no allowance at all, which nothing is held to.
    limited: bool = True
    #: What the service calls one: "units".
    unit: str = "units"

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


def _allowance(provider: str) -> Allowance | None:
    """The allowance a plugin declared, if it is working and declared one."""
    plugin = connections.connecting(provider) if provider else None
    return plugin.connect.allowance if plugin is not None and plugin.connect else None


def _zone(provider: str) -> ZoneInfo:
    """The time zone the service's day starts in."""
    allowance = _allowance(provider)
    return ZoneInfo(allowance.timezone if allowance else "UTC")


def _amount(provider: str, what: str) -> int:
    """The daily budget or the reserve: a number, or one of the plugin's settings."""
    allowance = _allowance(provider)
    plugin = connections.connecting(provider)
    if allowance is None or plugin is None:
        return 0
    said = getattr(allowance, what)
    if said.lstrip("-").isdigit():
        return max(0, int(said))
    declared = plugin.settings.named("app", said)
    if declared is None:
        return 0
    value = declared.read(plugin_settings.app_value(provider, said))
    return max(0, int(value)) if isinstance(value, (int, float)) else 0


def _which(provider: str | None) -> str:
    """The plugin asked about: the one named, or the one that publishes."""
    return provider if provider is not None else connections.publisher_id()


def quota_day(now: dt.datetime | None = None, *, provider: str | None = None) -> str:
    """The service's day that `now` falls in, as an ISO date in its own time zone."""
    moment = now or dt.datetime.now(dt.timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    return moment.astimezone(_zone(_which(provider))).date().isoformat()


def next_reset(now: dt.datetime | None = None, *, provider: str | None = None) -> dt.datetime:
    """When the allowance next refreshes, in UTC."""
    zone = _zone(_which(provider))
    moment = now or dt.datetime.now(dt.timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    local = moment.astimezone(zone)
    tomorrow = (local + dt.timedelta(days=1)).date()
    midnight = dt.datetime.combine(tomorrow, dt.time.min, tzinfo=zone)
    return midnight.astimezone(dt.timezone.utc)


def _row(session: Session, provider: str) -> AllowanceUsage:
    """The ledger row for the service's today, made on first use."""
    day = quota_day(provider=provider)
    row = session.scalar(
        select(AllowanceUsage)
        .where(AllowanceUsage.provider == provider)
        .where(AllowanceUsage.day == day)
    )
    if row is None:
        row = AllowanceUsage(provider=provider, day=day, units=0)
        session.add(row)
        session.flush()
    return row


def state(session: Session, provider: str | None = None) -> QuotaState:
    """The allowance as it stands now."""
    which = _which(provider)
    allowance = _allowance(which)
    if allowance is None:
        # Counted all the same, but held to nothing.
        row = _row(session, which) if which else None
        return QuotaState(
            day=row.day if row else quota_day(provider=which), used=row.units if row else 0,
            budget=0, reserve=0, exhausted=False,
            resets_at=next_reset(provider=which), limited=False,
        )
    row = _row(session, which)
    return QuotaState(
        day=row.day,
        used=row.units,
        budget=_amount(which, "daily"),
        reserve=_amount(which, "reserve"),
        exhausted=row.exhausted_at is not None,
        resets_at=next_reset(provider=which),
        unit=allowance.unit,
    )


def spend(session: Session, units: int, provider: str | None = None) -> None:
    """Charge units to today's ledger. Nothing for zero or less.

    Counted even for a service with no allowance: what was spent is worth
    knowing whether or not anything is held to it.
    """
    which = _which(provider)
    if units <= 0 or not which:
        return
    row = _row(session, which)
    row.units += units
    row.updated_at = utcnow()
    session.flush()


def mark_exhausted(session: Session, provider: str | None = None) -> None:
    """The service said no. Believe it over our own arithmetic."""
    which = _which(provider)
    if _allowance(which) is None:
        return
    row = _row(session, which)
    if row.exhausted_at is None:
        row.exhausted_at = utcnow()
        log.warning("%s reports its daily allowance is spent; pausing writes until reset", which)
    # Keep the ledger honest for the rest of the day.
    row.units = max(row.units, _amount(which, "daily") or row.units)
    session.flush()


def can_afford(
    session: Session, units: int, *, use_reserve: bool = False, provider: str | None = None
) -> bool:
    """Whether `units` can be spent now.

    Syncing keeps the reserve back; `use_reserve=True` lets a manual action
    dip into it. A service with no allowance can always afford it.
    """
    current = state(session, provider)
    if not current.limited:
        return True
    if current.exhausted:
        return False
    available = current.remaining if use_reserve else current.spendable
    return available >= units


def meter(session: Session, provider: str | None = None) -> Callable[[int], None]:
    """A callback each request is charged through."""

    def record(units: int) -> None:
        """Charge one request's units, logging rather than raising if it fails."""
        try:
            spend(session, units, provider)
        except Exception:  # pragma: no cover - accounting must never break a sync
            log.exception("could not record allowance spend")

    return record


def describe_reset(now: dt.datetime | None = None, *, provider: str | None = None) -> str:
    """When the allowance resets, said as "in 3h 05m" or "in 12 min"."""
    resets_at = next_reset(now, provider=provider)
    delta = resets_at - (now or dt.datetime.now(dt.timezone.utc))
    hours = int(delta.total_seconds() // 3600)
    minutes = int((delta.total_seconds() % 3600) // 60)
    if hours:
        return f"in {hours}h {minutes:02d}m"
    return f"in {minutes} min"
