"""How the rest of the app talks about sources without knowing a plugin exists."""

from __future__ import annotations

from dataclasses import dataclass


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
    from ...plugins import registry

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
