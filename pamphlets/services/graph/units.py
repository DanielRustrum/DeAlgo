"""Amounts of time and times of day, as the canvas asks for them and says them."""

from __future__ import annotations

import datetime as dt

#: What an Alive piece allows when nobody has said. All day, so a piece just
#: dropped in changes nothing until it is told to.
DEFAULT_ALIVE = ("00:00", "00:00")


# What a trigger means if it is wired up without anything being chosen.
DEFAULT_EVERY_MINUTES = 60


DEFAULT_CRON = "0 9 * * *"  # every day at 09:00 UTC


# How long a window stays open when nobody has said.
DEFAULT_DURATION_MINUTES = 30


# What a pulse's gap can be said in. Stored as minutes whichever is chosen —
# one number in the database, so nothing has to know which unit it was typed
# in. A month is thirty days here, and says so where it is offered: there is
# no honest fixed number of minutes in a month.
EVERY_UNITS: tuple[tuple[str, int, str], ...] = (
    ("minutes", 1, "minutes"),
    ("hours", 60, "hours"),
    ("days", 1440, "days"),
    ("weeks", 10080, "weeks"),
    ("months", 43200, "months (30 days)"),
)


def split_every(minutes: int) -> tuple[int, str]:
    """A gap in minutes as an amount and the largest unit it divides into.

    120 reads back as 2 hours and 90 as 90 minutes: the unit it was typed in
    is not stored, so the one that comes back is the one that needs no
    fraction to say.
    """
    for name, size, _ in reversed(EVERY_UNITS):
        if minutes >= size and minutes % size == 0:
            return minutes // size, name
    return max(1, minutes), "minutes"


def every_minutes_from(amount: int, unit: str) -> int:
    """An amount and a unit as the minutes to store.

    Zero survives, because zero means something: every run there is. Anything
    negative is nonsense and becomes the smallest gap the unit can express.
    """
    size = next((size for name, size, _ in EVERY_UNITS if name == unit), 1)
    if amount == 0:
        return 0
    return max(1, amount) * size


def every_words(minutes: int) -> str:
    """A gap said the way it was most likely meant."""
    if minutes == 0:
        return "run"  # reads as "every run", which is what it means
    amount, unit = split_every(minutes)
    return f"{amount} {unit[:-1] if amount == 1 else unit}"


#: How a length of video is asked for, and what each unit is in seconds.
#: Short units, because "longer than" is usually about minutes rather than
#: about days, which is what the other unit list is for.
LENGTH_UNITS: tuple[tuple[str, int], ...] = (
    ("seconds", 1), ("minutes", 60), ("hours", 3600),
)


def seconds_from(amount: int, unit: str) -> int:
    """An amount and a unit as the seconds to store."""
    size = next((size for name, size in LENGTH_UNITS if name == unit), 1)
    return max(1, amount) * size


def split_length(seconds: int) -> tuple[int, str]:
    """The seconds back as the largest unit they divide into evenly."""
    for name, size in reversed(LENGTH_UNITS):
        if seconds >= size and seconds % size == 0:
            return seconds // size, name
    return seconds, "seconds"


def as_aware(when: dt.datetime) -> dt.datetime:
    """Stored instants are naive UTC; APScheduler wants them to say so."""
    return when if when.tzinfo is not None else when.replace(tzinfo=dt.timezone.utc)


def clock_time(raw: str | None) -> str:
    """A time of day as "HH:MM", or "" if that is not what it is.

    Forgiving about what is typed and strict about what is stored: "9",
    "9:5", "09.05" and "0905" all become "09:05", because a field asking for
    a time should take a time however somebody writes one down.
    """
    said = "".join((raw or "").split())
    if not said:
        return ""
    for mark in (":", ".", "h"):
        said = said.replace(mark, ":")
    hours, _, minutes = said.partition(":")
    if not minutes and len(hours) == 4 and hours.isdigit():
        hours, minutes = hours[:2], hours[2:]   # "0905"
    if not hours.isdigit() or (minutes and not minutes.isdigit()):
        return ""
    hour, minute = int(hours), int(minutes or 0)
    if hour > 23 or minute > 59:
        return ""
    return f"{hour:02d}:{minute:02d}"


def minutes_of(said: str | None) -> int | None:
    """A stored "HH:MM" as minutes since midnight."""
    tidy = clock_time(said)
    if not tidy:
        return None
    hours, _, minutes = tidy.partition(":")
    return int(hours) * 60 + int(minutes)


def length_words(seconds: int) -> str:
    """A stretch of a video, said the way somebody would say it out loud."""
    if seconds < 60:
        return f"{seconds}s"
    return every_words(max(1, round(seconds / 60)))
