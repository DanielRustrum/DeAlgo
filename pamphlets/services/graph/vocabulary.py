"""The kinds of box, what may be wired to what, and the error the canvas speaks in."""

from __future__ import annotations

from .conditions import CONDITION_KINDS, RULE
from .leaflets import LEAFLET_KINDS

#: The box kinds that read what is slotted under them. A feed reads a Timer
#: as a sitting and a Reset as when it comes back; a Decay reads a Timer as
#: time with one item and a Lock as "and you cannot pause it"; an Expire
#: reads a Timer as a lifetime, counted from arrival or, with an After
#: watching piece, from when the item is watched. A Filter reads conditions — the app's own and
#: whatever ones the plugins declared — and a Sort reads an Order.
#: Every other kind ignores a piece entirely, which is why only these are
#: drawn with somewhere for one to go.
SLOTTED = ("feed", "decay", "expire", "filter", "sort", "pamphlet", "transform")


#: The boxes that mark what goes through them. On a path like a filter, but
#: they turn nothing away — what they do shows up after the item has landed.
STAMPS = ("decay", "expire", "tag")


#: The leaflets a feed can be wired into: what they show is that feed's.
WIRED_LEAFLETS = ("leaflet-feed", "leaflet-link")

#: What takes one wire in only — a second wired in replaces the first: a
#: leaflet shows one feed, a Format box reshapes one source, a chart draws
#: one Format box's bars.
ONE_INPUT = WIRED_LEAFLETS + ("format", "leaflet-chart")


#: What a Transform box can be told to do, one augmentation each. It turns
#: what comes in — items or data — into data, as these say.
TRANSFORMS: tuple[str, ...] = ("count",)


#: The augmentations, as against the boxes. An augmentation is not on any
#: path and has no wires: it is slotted under a box and changes what that box
#: does. Kept in one tuple so "is this an augmentation" is one question asked
#: in one place.
#:
#: Called a piece throughout the code, which is what one of them is on the
#: canvas — it is drawn with a tab and a notch and interlocks with whatever it
#: is slotted into. "Augmentation" is what the kind of thing is called;
#: "piece" is what one looks like.
AUGMENTATIONS: tuple[str, ...] = (
    ("timer", "reset", "alive", "lock", "after-watch") + CONDITION_KINDS + (RULE,)
    + LEAFLET_KINDS + TRANSFORMS + ("aggregation",)
)


#: What each box is called where one is named out loud.
BOX_NAMES: dict[str, str] = {
    "feed": "Feed", "filter": "Filter", "sort": "Sort",
    "decay": "Decay", "expire": "Expire", "pamphlet": "Pamphlet", "format": "Format",
    "transform": "Transform", "text": "Text",
}


# What a group starts out as, and the least it can be shrunk to.
GROUP_SIZE = (520, 300)


GROUP_LEAST = (200, 140)


TRIGGER_KINDS = ("schedule", "pulse")


# Which wires make sense. Triggers feed channels, sources start paths, feeds
# end them, filters and sorts sit in between — and nothing runs backwards.
MIDDLE = ("filter", "sort", "decay", "expire", "tag")

#: Where items may also go, off the end of a path: a Transform box, which
#: turns them into data. No path runs through one.
INTO_TRANSFORM = ("transform", "text")


#: Where a path may end: a feed, or a repository to be pulled from later.
ENDS = ("feed", "deposit")


ALLOWED: dict[str, tuple[str, ...]] = {
    # A group is not on any path: it surrounds, it does not carry.
    "group": (),
    # A page of its own, laid out by the leaflets slotted under it. Nothing
    # runs through it: what it shows, it reads when the page is opened.
    "pamphlet": (),
    **{kind: () for kind in LEAFLET_KINDS},
    # Into a channel it says when to poll; into a feed it says when that feed
    # may be read; into a withdraw it says when to pull. A trigger carries no
    # content any of those ways.
    # A feed used to take one too, on a second input, to say when it could
    # be read. That is a Timer and a Reset slotted under it now: it is a
    # property of the feed rather than something arriving along a wire.
    "trigger": ("source", "withdraw"),
    "source": MIDDLE + ENDS + INTO_TRANSFORM,
    "format": (),
    # A Transform takes items as well as data, and gives out data only.
    "transform": (),
    # A Text box takes items or data and gives out words, onto a page.
    "text": (),
    **{kind: () for kind in TRANSFORMS},
    "aggregation": (),
    "filter": MIDDLE + ENDS + INTO_TRANSFORM,
    "sort": MIDDLE + ENDS + INTO_TRANSFORM,
    # A withdraw stands where a source stands: it starts a path, and what
    # comes out of it has already been through whatever filtered it on the
    # way in.
    "withdraw": MIDDLE + ENDS + INTO_TRANSFORM,
    "feed": (),
    # The end of the line. What is in it comes out through a Withdraw box,
    # which is a path of its own rather than a continuation of this one.
    "deposit": (),
    # A piece is slotted, not wired. Nothing runs into or out of one.
    "timer": (),
    "reset": (),
    "alive": (),
    "lock": (),
    "after-watch": (),
    "has-words": (),
    "lacks-words": (),
    "longer-than": (),
    "shorter-than": (),
    "carrying": (),
    "lacks-tag": (),
    "at-most": (),
    "order": (),
    "rule": (),
    # They mark what passes and pass it on, so they sit where a filter sits.
    "decay": MIDDLE + ENDS + INTO_TRANSFORM,
    "expire": MIDDLE + ENDS + INTO_TRANSFORM,
    "tag": MIDDLE + ENDS + INTO_TRANSFORM,
}


#: The boxes data passes through on its way to a Format box, each doing to
#: it what it does to items: a Filter keeps rows, a Sort orders them…
DATA_OPS = ("filter", "sort", "tag", "decay", "expire")

#: Where data may go from each box: through the operations, into a Format
#: box, and from a Format box into a Chart leaflet. A repository gives what
#: is waiting in it.
_ONWARD = DATA_OPS + ("format", "transform", "text", "leaflet-chart")

DATA_ALLOWED: dict[str, tuple[str, ...]] = {
    "source": _ONWARD,
    **{kind: _ONWARD for kind in DATA_OPS},
    "deposit": _ONWARD,
    "withdraw": _ONWARD,
    "format": ("leaflet-chart",),
    # What a Transform gives — a count, say — can go on, be shaped, or be
    # shown on a page as it is.
    "transform": _ONWARD,
}

#: What may be wired to what, by what the wire carries.
WIRING: dict[str, dict[str, tuple[str, ...]]] = {
    "signal": {"trigger": ALLOWED["trigger"]},
    "content": {kind: targets for kind, targets in ALLOWED.items() if kind != "trigger"},
    # A feed is where a path ends — but what is in it can be shown on a
    # pamphlet's page, down a wire of its own kind into a leaflet.
    "page": {"feed": WIRED_LEAFLETS, "text": ("leaflet-text",)},
    "data": DATA_ALLOWED,
}

#: Boxes a data wire may come into. Each takes one: a second replaces it.
DATA_TAKERS = DATA_OPS + ("format", "leaflet-chart", "transform", "text")


def carries_between(source_kind: str, target_kind: str) -> str:
    """What a wire between two kinds of box carries, when nobody said: the
    kind there is only one of between them, items before data."""
    if source_kind == "trigger":
        return "signal"
    if target_kind in WIRING["page"].get(source_kind, ()):
        return "page"
    if target_kind in WIRING["content"].get(source_kind, ()):
        return "content"
    return "data"
