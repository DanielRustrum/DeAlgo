"""Where things come from.

De-Algo began as a YouTube tool and its polling was already an RSS reader:
YouTube publishes a per-channel Atom feed, which costs no quota and needs no
credentials. That turns out to be the common denominator for most of the web —
Reddit, Substack, Bluesky and every blog publish one too — so a source is no
longer "a YouTube channel" but "somewhere with a feed".

Each of those is a plugin now. What is left in this package is the part that
cannot be one: reading a feed, waiting when a host asks us to, and RSS itself
as the floor under everything nobody claims.

One thing does not generalise, and the app says so rather than pretending:
only a YouTube video can be put into a YouTube playlist. Everything else can
only fill a feed that lives inside De-Algo.
"""

from .kinds import (
    NEWSLETTER,
    RSS,
    Resolved,
    SourceKind,
    UnknownSource,
    describe,
    home_url,
    item_url,
    all_kinds,
    resolve,
    suggest_mirror,
)
from .syndication import Item, Feed, parse, fetch
from . import embedded, items, kinds, newsletter, patience, syndication

__all__ = [
    # The modules themselves, so the reference documents each of them: an
    # `__all__` that named only what is re-exported here hid every one.
    "embedded",
    "items",
    "kinds",
    "newsletter",
    "patience",
    "syndication",
    "NEWSLETTER",
    "RSS",
    "Resolved",
    "SourceKind",
    "UnknownSource",
    "describe",
    "all_kinds",
    "resolve",
    "home_url",
    "item_url",
    "suggest_mirror",
    "Item",
    "Feed",
    "parse",
    "fetch",
]
