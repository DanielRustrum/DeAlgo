"""What a Chart leaflet draws: counts of what happened, day by day or feed by feed.

Each answer is one series of bars — a label and a number each — so the page
draws every chart the same way. Days are UTC days, as every other date the
app keeps is UTC, and a day with nothing in it is a bar of nothing rather
than a missing bar: a gap in the axis reads as a gap in the record.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from ..models import Placement, Playlist, Video, utcnow
from .scope import OwnerId, belongs_to


@dataclass(frozen=True)
class Bar:
    label: str
    #: Said in full on hover and in the table: "Tue 6 Oct" or a feed's name.
    long: str
    value: int


def daily(session: Session, owner: OwnerId, chart: str, days: int) -> list[Bar]:
    """One bar per day, the last `days` of them ending today."""
    today = utcnow().date()
    first = today - dt.timedelta(days=days - 1)
    since = dt.datetime.combine(first, dt.time())
    counted: dict[dt.date, int] = {}
    when: ColumnElement[dt.datetime]
    if chart == "watched-daily":
        when = Video.watched_at  # type: ignore[assignment]
        statement = select(func.date(when), func.count(Video.id)).where(
            belongs_to(Video, owner), when.is_not(None), when >= since
        )
    elif chart == "filtered-daily":
        when = func.coalesce(Video.processed_at, Video.discovered_at)
        statement = select(func.date(when), func.count(Video.id)).where(
            belongs_to(Video, owner), Video.status == "skipped", when >= since
        )
    else:  # arrived-daily: landed in a feed
        when = Placement.added_at  # type: ignore[assignment]
        statement = (
            select(func.date(when), func.count(Placement.id))
            .join(Video, Video.id == Placement.video_pk)
            .where(belongs_to(Video, owner), when.is_not(None), when >= since)
        )
    for day, count in session.execute(statement.group_by(func.date(when))):
        if day:
            counted[dt.date.fromisoformat(str(day))] = int(count)
    bars = []
    for offset in range(days):
        day = first + dt.timedelta(days=offset)
        bars.append(Bar(
            label=day.strftime("%-d"),
            long=day.strftime("%a %-d %b"),
            value=counted.get(day, 0),
        ))
    return bars


def feeds_held(session: Session, owner: OwnerId) -> list[Bar]:
    """One bar per feed: how many unwatched items it holds, most first."""
    rows = session.execute(
        select(Playlist.title, Playlist.playlist_id, func.count(Placement.id))
        .join(Placement, Placement.playlist_pk == Playlist.id)
        .join(Video, Video.id == Placement.video_pk)
        .where(
            belongs_to(Playlist, owner),
            Placement.playlist_item_id.is_not(None),
            Video.watched_at.is_(None),
        )
        .group_by(Playlist.id)
    )
    bars = [
        Bar(label=title or ident, long=title or ident, value=int(count))
        for title, ident, count in rows
    ]
    return sorted(bars, key=lambda one: (-one.value, one.label.lower()))


def scale(bars: list[Bar]) -> int:
    """The top of the axis: the biggest bar rounded up to a readable number."""
    most = max((one.value for one in bars), default=0)
    if most <= 4:
        return 4
    step = 10 ** (len(str(most)) - 1)
    for nice in (1, 2, 2.5, 5, 10):
        top = int(nice * step)
        if top >= most:
            return top
    return most
