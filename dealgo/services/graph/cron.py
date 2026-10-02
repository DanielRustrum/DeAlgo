"""Cron expressions, read the way everybody else reads them."""

from __future__ import annotations

import datetime as dt

from apscheduler.triggers.cron import CronTrigger

from .errors import GraphError

# Cron counts weekdays from Sunday; APScheduler counts them from Monday, and
# reads its own names unambiguously. So the day-of-week field is expanded to
# names before it is handed over — otherwise "0 9 * * 1" would quietly mean
# Tuesday here and Monday everywhere else somebody has ever written cron.
CRON_DAYS = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")


CRON_DAY_NUMBERS = {name: number for number, name in enumerate(CRON_DAYS)}


def cron_trigger(expression: str) -> CronTrigger:
    """An APScheduler trigger that fires when cron says it would.

    APScheduler is already a dependency and already parses these, so there is
    no second dialect to keep in step — only the weekday numbering to correct.
    """
    fields = expression.split()
    if len(fields) != 5:
        raise GraphError(
            "A cron expression has five fields: minute, hour, day, month, weekday. "
            "“0 9 * * *” is every day at nine."
        )
    minute, hour, day, month, weekday = fields
    try:
        return CronTrigger(
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=_weekdays(weekday),
            timezone=dt.timezone.utc,
        )
    except (ValueError, KeyError) as exc:
        raise GraphError(f"“{expression}” is not a cron expression: {exc}") from exc


def _weekdays(field: str) -> str:
    """A cron weekday field as APScheduler day names.

    Expanded rather than shifted: a step like ``*/2`` counts from a different
    day in each dialect, and there are only seven values to write out.
    """
    if field == "*":
        return "*"

    wanted: set[int] = set()
    # Each comma-separated part is a day, a range `a-b`, or `*`, with an optional `/step`.
    for part in field.split(","):
        step = 1
        if "/" in part:
            part, _, raw_step = part.partition("/")
            if not raw_step.isdigit() or int(raw_step) < 1:
                raise GraphError(f"“{field}” is not a weekday: {raw_step!r} is not a step.")
            step = int(raw_step)
        first, last = (part, part) if "-" not in part.strip("-") else part.split("-", 1)
        if part == "*":
            first, last = "0", "6"
        wanted.update(range(_weekday(first), _weekday(last) + 1, step))

    # Written back as names, which APScheduler cannot misnumber.
    if not wanted:
        raise GraphError(f"“{field}” names no weekday.")
    return ",".join(CRON_DAYS[day] for day in sorted(wanted))


def _weekday(token: str) -> int:
    """One weekday, counted from Sunday as cron counts them."""
    wanted = token.strip().lower()
    if wanted.isdigit():
        number = int(wanted)
        if number > 7:
            raise GraphError(f"“{token}” is not a weekday: cron counts 0 to 7.")
        return 0 if number == 7 else number  # both 0 and 7 are Sunday
    if wanted[:3] in CRON_DAY_NUMBERS:
        return CRON_DAY_NUMBERS[wanted[:3]]
    raise GraphError(f"“{token}” is not a weekday.")


def check_cron(expression: str) -> str:
    """A cron expression, tidied — or a complaint about it in words."""
    wanted = " ".join(expression.split())
    if not wanted:
        raise GraphError("Give the schedule a cron expression, such as 0 9 * * *.")
    cron_trigger(wanted)
    return wanted
