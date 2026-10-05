"""The kinds of box, what may be wired to what, and the error the canvas speaks in."""

from __future__ import annotations

from .conditions import CONDITION_KINDS, RULE

#: The box kinds that read what is slotted under them. A feed reads a Timer
#: as a sitting and a Reset as when it comes back; a Decay reads a Timer as
#: time with one item and a Lock as "and you cannot pause it"; an Expire
#: reads a Timer as a lifetime, counted from arrival or, with an After
#: watching piece, from when the item is watched. A Filter reads conditions — the app's own and
#: whatever ones the plugins declared — and a Sort reads an Order.
#: Every other kind ignores a piece entirely, which is why only these are
#: drawn with somewhere for one to go.
SLOTTED = ("feed", "decay", "expire", "filter", "sort")


#: The boxes that mark what goes through them. On a path like a filter, but
#: they turn nothing away — what they do shows up after the item has landed.
STAMPS = ("decay", "expire", "tag")


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
)


#: What each box is called where one is named out loud.
BOX_NAMES: dict[str, str] = {
    "feed": "Feed", "filter": "Filter", "sort": "Sort",
    "decay": "Decay", "expire": "Expire",
}


# What a group starts out as, and the least it can be shrunk to.
GROUP_SIZE = (520, 300)


GROUP_LEAST = (200, 140)


TRIGGER_KINDS = ("schedule", "pulse")


# Which wires make sense. Triggers feed channels, sources start paths, feeds
# end them, filters and sorts sit in between — and nothing runs backwards.
MIDDLE = ("filter", "sort", "decay", "expire", "tag")


#: Where a path may end: a feed, or a repository to be pulled from later.
ENDS = ("feed", "deposit")


ALLOWED: dict[str, tuple[str, ...]] = {
    # A group is not on any path: it surrounds, it does not carry.
    "group": (),
    # Into a channel it says when to poll; into a feed it says when that feed
    # may be read; into a withdraw it says when to pull. A trigger carries no
    # content any of those ways.
    # A feed used to take one too, on a second input, to say when it could
    # be read. That is a Timer and a Reset slotted under it now: it is a
    # property of the feed rather than something arriving along a wire.
    "trigger": ("source", "withdraw"),
    "source": MIDDLE + ENDS,
    "filter": MIDDLE + ENDS,
    "sort": MIDDLE + ENDS,
    # A withdraw stands where a source stands: it starts a path, and what
    # comes out of it has already been through whatever filtered it on the
    # way in.
    "withdraw": MIDDLE + ENDS,
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
    "decay": MIDDLE + ENDS,
    "expire": MIDDLE + ENDS,
    "tag": MIDDLE + ENDS,
}
