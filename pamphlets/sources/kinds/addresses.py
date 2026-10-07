"""Where a source's items, home page, feed and mirror are, by kind."""

from __future__ import annotations

from .vocabulary import NEWSLETTER


def item_url(kind: str, key: str, link: str | None, item_kind: str = "video") -> str | None:
    """Where an item lives. The link the feed gave, unless its plugin knows
    better — an item addressed by an id rather than a link is the plugin's
    to build an address for."""
    from ...plugins import registry

    return registry.current().item_url(kind, key, link, item_kind)


def home_url(kind: str, key: str) -> str | None:
    """Where the source itself lives. Its plugin's to say.

    Except a newsletter's, which is the one kind whose key *is* where it
    lives — that is how one is named, and there is no plugin to ask.
    """
    if kind == NEWSLETTER.name:
        return key or None
    from ...plugins import registry

    return registry.current().home(kind, key)


def feed_url(kind: str, key: str) -> str | None:
    """Where to poll, for a source stored before its address was.

    Asked of the plugin that owns the kind rather than built here: a feed
    address is part of knowing a service, and the host stopped knowing any.
    """
    from ...plugins import registry

    found = registry.current().kind(kind)
    if found is None:
        return None
    said = registry.current().recognise(key)
    return said.feed_url if said is not None and said.kind == kind and said.feed_url else None


def suggest_mirror(kind: str, key: str) -> str | None:
    """A second address for the same feed, where the plugin offers one.

    Only the kinds that actually ration a reader have anything to say here.
    A suggestion nobody needs is a field somebody has to think about for no
    reason.
    """
    from ...plugins import registry

    return registry.current().mirror(kind, key)
