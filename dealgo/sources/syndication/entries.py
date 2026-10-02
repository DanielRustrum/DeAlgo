"""What a feed is read into, whichever shape it was written in."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Item:
    """One entry, said the same way whatever the feed was written in."""

    #: Stable for this entry, for as long as the feed keeps saying it. The
    #: entry's own id where it has one, its link where it does not.
    guid: str
    title: str
    link: str | None
    published_at: dt.datetime | None
    summary: str | None = None
    thumbnail_url: str | None = None
    #: Every picture the entry carries, in the order it carried them. Reddit
    #: puts them in the post's own HTML; a plain blog often does too.
    images: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Feed:
    """A feed's title and its items, newest first."""

    title: str
    items: list[Item] = field(default_factory=list)
