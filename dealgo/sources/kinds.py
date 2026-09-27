"""What a reference turns out to be, asked of the plugins that know.

This used to hold a regex per site. It holds none now: every kind of
somewhere — YouTube, Reddit, Bluesky, Substack — is a plugin, and this asks
them in turn. What is left here is the part that cannot be a plugin:

* **RSS**, the floor. Anything with no plugin to claim it is taken at its
  word as the address of a feed, which is what it most often is. It is not a
  peer of the others; it is what they are all built on.
* **Newsletter**, which is the floor said the way somebody thinks of it. A
  newsletter is known by where it lives rather than by where its feed is, and
  every platform puts that feed somewhere slightly different — so this one
  kind resolves to a site and has its feed found by reading it. Not a plugin
  because it belongs to no service: Substack, Ghost, beehiiv and a WordPress
  with an email list are all the same answer to "which newsletter".
* **the vocabulary** — ``Resolved``, ``SourceKind``, ``UnknownSource`` — so
  the rest of the app talks about sources without knowing a plugin exists.

Nothing here makes a request. A plugin says where a feed is by the shape of
what was typed; reading it is the host's business, and so are rate limits —
which is why a Newsletter resolves with no feed address at all and says so,
rather than fetching one from in here.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


class UnknownSource(ValueError):
    """What was typed does not look like anything this knows how to poll."""


@dataclass(frozen=True)
class Resolved:
    """What a reference turned out to be."""

    kind: str
    #: What identifies it within its kind — a subreddit's name, a handle, a
    #: URL. Stored as the channel's id, and unique per account.
    key: str
    feed_url: str
    title: str
    #: True when the plugin knows what this is but cannot finish alone. The
    #: one case is a YouTube handle, which needs this account's Google
    #: connection — not something a plugin is ever handed.
    needs_host: bool = False

    @property
    def needs_finding(self) -> bool:
        """Whether where its feed lives still has to be worked out.

        A blank feed address is not a missing answer, it is the answer: this
        is a place rather than a feed, and which feed it publishes is settled
        by asking it. Nothing in this module asks anything, so it says so and
        leaves it to the half that is allowed to make requests.
        """
        return not self.feed_url


@dataclass(frozen=True)
class SourceKind:
    name: str
    label: str
    #: What to type, said the way somebody would say it.
    example: str
    #: Only YouTube videos can be put into a YouTube playlist. Everything
    #: else can only fill a feed that lives inside De-Algo.
    playlistable: bool = False
    #: Which plugin offers it, or "" for the one kind that is not a plugin.
    plugin: str = ""
    #: What its box is called on the canvas. You drag out the kind you want,
    #: so the box has to say which kind that is.
    noun: str = ""
    #: The line under that name in the palette.
    blurb: str = ""


#: The floor. Not a plugin, because every plugin's parsing is built on it and
#: because something has to catch an address nobody claims.
RSS = SourceKind(
    "rss", "RSS", "the address of any feed", plugin="",
    noun="Feed address",
    blurb="Any RSS or Atom feed, by its address. The one that fits everything else.",
)


#: A newsletter, known the way somebody knows one: by where it lives. Its
#: feed is found by reading the site rather than guessed from the spelling,
#: because every platform puts it somewhere slightly different and nobody
#: should have to know which one theirs is on.
NEWSLETTER = SourceKind(
    "newsletter", "Newsletter", "platformer.news, or wherever it lives",
    plugin="",
    noun="Newsletter",
    blurb="A newsletter by where it lives. Its feed is found by asking the site.",
)


def all_kinds() -> tuple[SourceKind, ...]:
    """Every kind of somewhere that can be watched, plugins first.

    Not called `kinds`, which is this module's own name: `from ..sources
    import kinds` then gives back the function rather than the module, and
    the mistake reads perfectly until something is called on it.

    Asked rather than listed, so a plugin dropped in the folder shows up on
    the Sources page without anything here being edited.
    """
    from ..plugins import registry

    offered = tuple(
        SourceKind(
            name=kind.kind,
            label=kind.label,
            example=kind.example,
            playlistable=kind.playlistable,
            plugin=kind.plugin,
            noun=kind.noun,
            blurb=kind.blurb,
        )
        for kind in registry.current().source_kinds()
    )
    return offered + (NEWSLETTER, RSS)


def describe(kind: str) -> SourceKind:
    """What a kind is called, falling back rather than failing.

    A row stored by a plugin that has since been removed still has to draw:
    the item is in a feed, and "reddit" is a better label than a stack trace.
    """
    for known in all_kinds():
        if known.name == kind:
            return known
    return SourceKind(kind, kind.title(), "")


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
    from ..plugins import registry

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
        from . import newsletter

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


def item_url(kind: str, key: str, link: str | None) -> str | None:
    """Where an item lives. The link the feed gave, unless its plugin knows
    better — YouTube items are addressed by a video id and are built
    elsewhere."""
    from ..plugins import registry

    return registry.current().item_url(kind, key, link)


def home_url(kind: str, key: str) -> str | None:
    """Where the source itself lives. Its plugin's to say.

    Except a newsletter's, which is the one kind whose key *is* where it
    lives — that is how one is named, and there is no plugin to ask.
    """
    if kind == NEWSLETTER.name:
        return key or None
    from ..plugins import registry

    return registry.current().home(kind, key)


def feed_url(kind: str, key: str) -> str | None:
    """Where to poll, for a source stored before its address was.

    Asked of the plugin that owns the kind rather than built here: a feed
    address is part of knowing a service, and the host stopped knowing any.
    """
    from ..plugins import registry

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
    from ..plugins import registry

    return registry.current().mirror(kind, key)
