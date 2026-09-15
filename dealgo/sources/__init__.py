"""Where things come from.

De-Algo began as a YouTube tool and its polling was already an RSS reader:
YouTube publishes a per-channel Atom feed, which costs no quota and needs no
credentials. That turns out to be the common denominator for most of the web —
Reddit, Substack, Bluesky and every blog publish one too — so a source is no
longer "a YouTube channel" but "somewhere with a feed", and the kind only
decides how a reference becomes a URL and what an item links back to.

One thing does not generalise, and the app says so rather than pretending:
only a YouTube video can be put into a YouTube playlist. Everything else can
only fill a feed that lives inside De-Algo.
"""

from .kinds import (
    KINDS,
    SourceKind,
    UnknownSource,
    describe,
    item_url,
    looks_like_youtube,
    resolve,
)
from .syndication import Item, Feed, parse, fetch

__all__ = [
    "KINDS",
    "SourceKind",
    "UnknownSource",
    "describe",
    "looks_like_youtube",
    "resolve",
    "item_url",
    "Item",
    "Feed",
    "parse",
    "fetch",
]
