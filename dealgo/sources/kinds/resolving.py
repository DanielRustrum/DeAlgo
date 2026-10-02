"""Working out what somebody typed, without asking anybody."""

from __future__ import annotations

from urllib.parse import urlparse

from .vocabulary import NEWSLETTER, RSS, Resolved, UnknownSource, describe


def resolve(reference: str, *, within: str = "") -> Resolved:
    """Work out what somebody has typed, without asking anybody.

    ``within`` is the kind whose box it was typed into. That box was dragged
    out on purpose, so its own kind is asked first and asked more generously:
    a bare "python" in a Subreddit box is r/python, which is not something
    anybody could conclude from the word alone.

    Without a kind — which now means an address pasted into the Sources page
    — every plugin is asked and a certain answer beats a guess: a Bluesky
    handle may be any domain, so "name.substack.com" is a newsletter rather
    than an account with an unusual name.
    """
    from ...plugins import registry

    typed = (reference or "").strip()
    if not typed:
        raise UnknownSource("Give it something to watch.")

    #: The two kinds the host owns itself. Everything else is a plugin's, and
    #: is asked of the plugin that offered it.
    if within and within not in (RSS.name, NEWSLETTER.name):
        said = registry.current().accept(within, typed)
        if said is not None:
            return Resolved(
                kind=said.kind,
                key=said.key,
                feed_url=said.feed_url,
                title=said.title,
                needs_host=said.needs_host,
            )
        raise UnknownSource(
            f"“{typed}” is not something {describe(within).label} recognises. "
            f"Try {describe(within).example}."
        )
    if within == NEWSLETTER.name:
        # A place, not a feed. Which feed it publishes is the site's to say,
        # and asking it is not this module's to do.
        from .. import newsletter

        site = newsletter.site_url(typed)
        if not site:
            raise UnknownSource(
                f"“{typed}” is not somewhere a newsletter could live. "
                f"Try {NEWSLETTER.example}."
            )
        return Resolved(
            kind=NEWSLETTER.name,
            key=site,
            feed_url="",
            title=(urlparse(site).hostname or site),
        )

    if within == RSS.name:
        # The box that takes an address takes an address, and whether it is
        # a feed is settled by reading it rather than by its spelling.
        url = typed if "://" in typed else f"https://{typed.lstrip('/')}"
        host = (urlparse(url).hostname or "").lower()
        if not host:
            raise UnknownSource(f"“{typed}” is not an address.")
        return Resolved(kind=RSS.name, key=url, feed_url=url, title=host)

    found = registry.current().recognise(typed)
    if found is not None:
        return Resolved(
            kind=found.kind,
            key=found.key,
            feed_url=found.feed_url,
            title=found.title,
            needs_host=found.needs_host,
        )

    # Nobody claimed it. An address is taken at its word — whether it is a
    # feed is settled by reading it, not by guessing from the spelling.
    if "://" in typed or typed.startswith("www."):
        url = typed if "://" in typed else f"https://{typed}"
        host = (urlparse(url).hostname or "").lower()
        return Resolved(kind=RSS.name, key=url, feed_url=url, title=host or url)

    raise UnknownSource(
        f"“{typed}” is not something this knows how to follow. Try r/name, a "
        "Bluesky handle, or the address of a feed."
    )
