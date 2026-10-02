"""What a Filter narrows by and what a Sort orders by, as pieces."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ...models import (
    CONDITION_LABELS,
    GraphNode,
)
from .errors import GraphError


@dataclass(frozen=True)
class Condition:
    """One thing a Filter or a Sort box can be told, as a piece.

    A rule used to be a field in a box's popover, which meant a box said
    "Filter" and you had to open it to find out what it filtered. A piece
    says what it is on the canvas, and a box narrowing three ways is three
    pieces rather than one form filled in three places.

    Each keeps its value in the column that rule always used, so nothing is
    stored twice and a box from before this converts into pieces rather than
    being read two ways.

    Only what is true of any item at all is here. Anything that is a fact
    about one service — whether a video is a Short, how many have watched it —
    belongs to the plugin that knows what those words mean, and is offered as
    a piece under that plugin's box instead. See `RULE`.
    """

    kind: str
    label: str
    blurb: str
    #: Which box it goes under: a Filter narrows, a Sort orders.
    under: str
    #: The column it writes, which is the same column that rule lived in when
    #: it was a field on the box.
    column: str
    #: How the panel asks for it, and what to call the field.
    field: str
    asks: str


CONDITIONS: tuple[Condition, ...] = (
    Condition(
        "has-words", CONDITION_LABELS["has-words"], "Only what matches this.", "filter",
        "title_include", "text", "Words, or /a regex/",
    ),
    Condition(
        "lacks-words", CONDITION_LABELS["lacks-words"], "Holds anything that matches this.", "filter",
        "title_exclude", "text", "Words, or /a regex/",
    ),
    Condition(
        "longer-than", CONDITION_LABELS["longer-than"], "Holds anything shorter.", "filter",
        "min_duration_sec", "duration", "How long",
    ),
    Condition(
        "shorter-than", CONDITION_LABELS["shorter-than"], "Holds anything longer.", "filter",
        "max_duration_sec", "duration", "How long",
    ),
    Condition(
        "carrying", CONDITION_LABELS["carrying"], "Only what a Tag box earlier put a mark on.",
        "filter", "tagged", "text", "This tag",
    ),
    Condition(
        "at-most", CONDITION_LABELS["at-most"], "How many may get through in one run.", "filter",
        "max_per_run", "number", "Per run",
    ),
    Condition(
        "order", CONDITION_LABELS["order"], "What to put the batch in order by.", "sort",
        "sort_by", "order", "By",
    ),
)


CONDITION_KINDS: tuple[str, ...] = tuple(one.kind for one in CONDITIONS)


#: A condition that belongs to a plugin rather than to the host. One kind
#: rather than one per condition, because which conditions exist depends on
#: which plugins are loaded and the host cannot have a column for each: which
#: one this piece is lives in `plugin_ref`, exactly as it did when the same
#: thing was a box of its own.
RULE = "rule"


def condition(kind: str) -> Condition | None:
    """The condition of this kind, or None."""
    return next((one for one in CONDITIONS if one.kind == kind), None)


def conditions_for(kind: str) -> tuple[Condition, ...]:
    """The pieces that may be slotted under a box of this kind."""
    return tuple(one for one in CONDITIONS if one.under == kind)


def filter_rules(pieces: list[GraphNode]) -> dict[str, Any]:
    """What the condition pieces under a Filter box narrow by.

    `pieces` comes nearest-first, and the one nearest the box has the last
    word — the same rule a filter nearest a feed already lives by. So they
    are read from the far end back.
    """
    said: dict[str, Any] = {}
    for piece in reversed(pieces):
        if piece.kind in CONDITION_KINDS and piece.enabled:
            said.update(piece.overrides)
    return said


# What a sort box can order a batch by: the name it is stored under, what it
# is called, and the two ends of it. "Most first" means something different
# for a duration than for a date, so each key brings its own words rather than
# leaving the reader to work out which end "most" is.
SORT_KEYS: tuple[tuple[str, str, str, str], ...] = (
    ("published", "When it went up", "Newest first", "Oldest first"),
    ("duration", "How long it is", "Longest first", "Shortest first"),
    ("views", "How many have watched it", "Most watched first", "Least watched first"),
    ("likes", "How many liked it", "Most liked first", "Least liked first"),
    ("title", "Its title", "Z to A", "A to Z"),
)


def sort_words(key: str, falling: bool) -> str:
    """What this box does, in the words that belong to what it sorts by."""
    for name, _, first, last in SORT_KEYS:
        if name == key:
            return first if falling else last
    return "Newest first" if falling else "Oldest first"


DEFAULT_SORT_BY = "published"


# What a filter file is allowed to set, so a stray key cannot reach a column
# that has nothing to do with filtering. A format-1 file's rules are read
# against this before being unpacked into pieces.
FILTER_RULES = tuple(one.column for one in CONDITIONS if one.under == "filter")


def check_sort_key(key: str) -> str:
    """The key, if a Sort can order by it; raises `GraphError` if not."""
    known = {name for name, _, _, _ in SORT_KEYS}
    if key not in known:
        raise GraphError(f"There is nothing to sort by called “{key}”.")
    return key
