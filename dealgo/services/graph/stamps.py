"""What Decay, Expire and Tag boxes leave on an item that passes them."""

from __future__ import annotations

from typing import Any

from ...models import (
    GraphNode,
)
from .names import tag_name
from .units import DEFAULT_DURATION_MINUTES, every_words


def stamped_seconds(stamps: list[GraphNode], pieces_for: Any) -> int | None:
    """How long a Decay box on this path gives you with an item, in seconds.

    The shortest of them where several disagree: a Decay box is a limit, and
    two limits mean the tighter one. None when no Decay box said anything,
    which leaves the account's own setting alone.
    """
    shortest: int | None = None
    for node in stamps:
        if node.kind != "decay" or not node.enabled:
            continue
        minutes = timer_minutes(pieces_for(node))
        if minutes is None:
            continue
        seconds = max(1, minutes * 60)
        shortest = seconds if shortest is None else min(shortest, seconds)
    return shortest


def stamped_locked(stamps: list[GraphNode], pieces_for: Any) -> bool:
    """Whether any Decay box on this path was told its time cannot be held.

    A Lock piece under it. Any one of them saying so is enough: a stretch
    that can be paused somewhere else is not a stretch you cannot pause.
    """
    for node in stamps:
        if node.kind != "decay" or not node.enabled:
            continue
        if any(one.kind == "lock" and one.enabled for one in pieces_for(node)):
            return True
    return False


def _after_watch(node: GraphNode, pieces_for: Any) -> bool:
    """Whether an Expire box counts from the watching rather than the arrival."""
    return any(one.kind == "after-watch" and one.enabled for one in pieces_for(node))


def stamped_life(
    stamps: list[GraphNode], pieces_for: Any, *, after_watch: bool = False
) -> int | None:
    """How long an Expire box on this path lets an item stay, in minutes.

    The shortest again, and for the same reason. Two clocks, asked for
    apart: from when it arrives (the plain box), and from when it is watched
    (one with an After watching piece). A path may have both, and an item
    goes at whichever comes round first.
    """
    shortest: int | None = None
    for node in stamps:
        if node.kind != "expire" or not node.enabled:
            continue
        if _after_watch(node, pieces_for) != after_watch:
            continue
        minutes = timer_minutes(pieces_for(node))
        if minutes is None:
            continue
        shortest = minutes if shortest is None else min(shortest, minutes)
    return shortest


def stamp_marks(stamps: list[GraphNode], pieces_for: Any) -> list[str]:
    """What these boxes would leave on an item, said the way they say it.

    The same words the boxes themselves carry, so a trial and the canvas
    agree about what is going to happen — and the same words a card shows
    afterwards, so it is recognisable when it gets there.
    """
    said = [f"“{one}”" for one in stamped_tags(stamps)]

    seconds = stamped_seconds(stamps, pieces_for)
    if seconds is not None:
        spoken = f"{seconds}s" if seconds < 60 else f"{round(seconds / 60)} min"
        said.append(spoken + (" · no pause" if stamped_locked(stamps, pieces_for) else ""))

    minutes = stamped_life(stamps, pieces_for)
    if minutes is not None:
        said.append(f"gone {every_words(minutes)} after it arrives")
    watched = stamped_life(stamps, pieces_for, after_watch=True)
    if watched is not None:
        said.append(f"gone {every_words(watched)} after you watch it")
    return said


def stamped_tags(stamps: list[GraphNode]) -> list[str]:
    """Every tag the boxes on this path put on what passes."""
    found: list[str] = []
    for node in stamps:
        if node.kind != "tag" or not node.enabled:
            continue
        named = tag_name(node.marks)
        if named and named not in found:
            found.append(named)
    return found


def timer_minutes(pieces: list[GraphNode]) -> int | None:
    """What the Timer slotted under a box says, in minutes.

    The nearest one, the same rule a Timer under a feed lives by. None when
    there is no Timer: a Decay or Expire box with nothing slotted into it
    has been put on the canvas and not yet told anything.
    """
    for piece in pieces:
        if piece.kind == "timer" and piece.enabled:
            return max(1, piece.duration_minutes or DEFAULT_DURATION_MINUTES)
    return None
