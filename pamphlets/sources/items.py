"""One thing a source published, said the same way whatever the source is.

This used to live in ``youtube/feeds.py``, because for a long time every item
was a YouTube video and the YouTube reader was the only one there was. It is
not YouTube's shape any more: a subreddit's post, a newsletter's article and
an upload all arrive here, and the fields that only some of them have are the
ones that say so.

Nothing here parses anything. ``syndication`` reads the feed — it has a real
XML parser, which a plugin does not — and the source's own plugin says what
is particular about what came back.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Entry:
    """One item, before anything has decided what to do with it."""

    #: What this item is filed under, and what makes it the same item next
    #: time. A video id where the source has one; a hash of the feed's own
    #: guid where it does not.
    id: str
    title: str
    published_at: dt.datetime | None
    thumbnail_url: str | None = None
    #: What its source's plugin said about it, for its `classify` to weigh
    #: later — "shorts", for a YouTube entry linking to /shorts/.
    hint: str = ""
    #: "video" for something with a player, "post" for a community post,
    #: "link" for an item that lives somewhere else entirely.
    kind: str = "link"
    link: str | None = None
    summary: str | None = None
    #: Every picture the item carries, in the order it carried them.
    images: tuple[str, ...] = ()


@dataclass(frozen=True)
class Batch:
    """What one poll of one source brought back."""

    key: str
    title: str
    entries: list[Entry] = field(default_factory=list)


def newest_first(entries: list[Entry]) -> list[Entry]:
    """Oldest last, and anything undated last of all — an item with no time
    on it is not new, it is unknown."""
    return sorted(
        entries,
        key=lambda entry: entry.published_at or dt.datetime.min.replace(tzinfo=dt.timezone.utc),
        reverse=True,
    )
