"""Reading a feed, whichever of the two shapes it is written in.

RSS 2.0 and Atom are different enough to need separate readers and similar
enough that one set of fields covers both. Everything here is parsing: nothing
knows what a Reddit post or a YouTube video is, only what a feed entry is.
"""

from __future__ import annotations

from .entries import Feed, Item
from .feed import fetch, parse
from .pictures import declared_width, pictures_in

__all__ = [
    "declared_width",
    "Feed",
    "fetch",
    "Item",
    "parse",
    "pictures_in",
]
