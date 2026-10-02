"""How times are stored: naive UTC, made aware again at the edges."""

from __future__ import annotations

import datetime as dt
from typing import overload


def utcnow() -> dt.datetime:
    """Naive UTC — SQLite has no timezone-aware storage, so UTC is the only
    convention in the database and awareness is added back at the edges."""
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


@overload
def to_naive_utc(value: dt.datetime) -> dt.datetime: ...


@overload
def to_naive_utc(value: None) -> None: ...


def to_naive_utc(value: dt.datetime | None) -> dt.datetime | None:
    """Drop a timestamp to naive UTC, which is how every column stores one.

    Overloaded so a caller that has already ruled out None keeps a plain
    datetime, rather than having to assert what it just checked.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(dt.timezone.utc).replace(tzinfo=None)
