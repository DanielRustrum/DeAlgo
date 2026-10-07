"""What a box or a piece does, said on the canvas in a few words."""

from __future__ import annotations

from ...models import (
    GraphNode,
)
from .conditions import CONDITION_KINDS, DEFAULT_SORT_BY, condition, sort_words
from .names import tag_name, tag_names
from .stamps import chooses, timer_minutes
from .units import (
    DEFAULT_CRON,
    DEFAULT_DURATION_MINUTES,
    DEFAULT_EVERY_MINUTES,
    clock_time,
    every_words,
    length_words,
)


def piece_note(piece: GraphNode, host: GraphNode | None) -> str:
    """What a piece does, said in the terms of what it is slotted into.

    A Timer says an amount and nothing about what it is an amount of: under
    a feed it is a sitting, under a Decay box it is how long you get with
    one item, under an Expire box it is how long that item stays. The piece
    carries the number; the box it is in is what the number means.
    """
    if piece.kind == "aggregation":
        from .. import algorithm

        return algorithm.words(piece, host)
    said = piece_words(piece)
    if piece.kind != "timer":
        return said

    if host is None:
        return said
    if host.kind == "decay":
        return f"{said} with each one"
    if host.kind == "expire":
        return f"gone {said} after it arrives"
    return f"{said} once you start reading"


def condition_words(piece: GraphNode) -> str:
    """What one condition piece narrows by, in its own words.

    A condition nobody has filled in yet says so rather than saying nothing:
    an empty "Title has" narrows nothing at all, and a piece that looked
    busy while doing nothing would be the worst of both.
    """
    spec = condition(piece.kind)
    if spec is None:
        return ""
    # An Order piece says its key and direction rather than a value.
    if piece.kind == "order":
        return sort_words(
            piece.sort_by or DEFAULT_SORT_BY, (piece.sort_dir or "desc") == "desc"
        )
    # Every other condition says its value, in its kind's words.
    value = getattr(piece, spec.column, None)
    if value is None or value == "":
        return "open it and say what"
    if piece.kind == "has-words":
        return f"title has “{value}”"
    if piece.kind == "lacks-words":
        return f"title lacks “{value}”"
    if piece.kind == "longer-than":
        return f"longer than {length_words(int(value))}"
    if piece.kind == "shorter-than":
        return f"shorter than {length_words(int(value))}"
    if piece.kind == "carrying":
        return f"tagged {tag_list_words(str(value))}"
    if piece.kind == "lacks-tag":
        return f"not tagged {tag_list_words(str(value))}"
    return f"{int(value)} per run"


def stamp_words(node: GraphNode, pieces: list[GraphNode]) -> str:
    """What a marking box does, in the words that belong to it.

    A Timer slotted under one says an amount and nothing about what it is an
    amount of; the box it is slotted into is what turns it into a sentence.
    """
    if node.kind == "tag" and chooses(node):
        from .. import tagging

        return tagging.words(node)
    if node.kind == "tag":
        named = tag_name(node.marks)
        return f"marks it “{named}”" if named else "open it and give it a tag"

    minutes = timer_minutes(pieces)
    watched = node.kind == "expire" and any(
        one.kind == "after-watch" and one.enabled for one in pieces
    )
    if minutes is None:
        if watched:
            return "gone once you watch it"
        if node.kind == "expire":
            return "slot a Timer or After watching under it to say when"
        return "slot a Timer under it to say how long"
    if node.kind == "decay":
        locked = any(one.kind == "lock" and one.enabled for one in pieces)
        return every_words(minutes) + " with each one" + (", no pausing" if locked else "")
    if watched:
        return "gone once you watch it, or " + every_words(minutes) + " after it arrives"
    return "gone " + every_words(minutes) + " after it arrives"


def piece_words(piece: GraphNode, window: int | None = None) -> str:
    """What one augmentation does, in the words that belong to it.

    A Timer reads differently depending on what it is slotted into — how
    long a sitting lasts, how long you get with one item, how long an item
    stays — so the host is asked for the sentence and this says the amount.
    """
    if piece.kind in CONDITION_KINDS:
        return condition_words(piece)
    if piece.kind == "lock":
        return "cannot be paused"
    if piece.kind == "aggregation":
        return "the algorithm of your own"
    if piece.kind == "count":
        return "how many come in, as one number"
    if piece.kind == "after-watch":
        return "once you watch it"
    if piece.kind == "alive":
        begins = clock_time(piece.alive_from)
        ends = clock_time(piece.alive_to)
        if not begins or not ends or begins == ends:
            return "any time of day"
        return f"only between {begins} and {ends}"
    if piece.kind == "timer":
        minutes = max(1, piece.duration_minutes or DEFAULT_DURATION_MINUTES)
        return every_words(minutes)
    held = window if window is not None else DEFAULT_DURATION_MINUTES
    return f"another {every_words(max(1, held))} on “{piece.cron or DEFAULT_CRON}”"


def window_words(node: GraphNode) -> str:
    """What a trigger opens, said the way it reads on a feed."""
    window = max(1, node.duration_minutes or DEFAULT_DURATION_MINUTES)
    if node.trigger_kind == "schedule":
        return f"open {window} min from “{node.cron or DEFAULT_CRON}”"
    gap = max(1, node.every_minutes or DEFAULT_EVERY_MINUTES)
    return f"open {window} min in every {every_words(gap)}"


def tag_list_words(raw: str) -> str:
    """Tags as a condition says them: “news”, or “news” or “long reads”."""
    return " or ".join(f"“{name}”" for name in tag_names(raw))
