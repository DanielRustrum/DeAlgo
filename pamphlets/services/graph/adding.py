"""Putting a new box or piece on the canvas."""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from ...models import (
    Channel,
    GraphNode,
    Playlist,
)
from ..scope import OwnerId
from .canvas import COLUMN_X, load, room_for_a_trigger
from .conditions import DEFAULT_SORT_BY, RULE, check_sort_key
from .cron import check_cron
from .errors import GraphError
from .names import store_name, tag_name
from .pieces import attach
from .units import DEFAULT_ALIVE, DEFAULT_CRON, DEFAULT_EVERY_MINUTES, clock_time
from .vocabulary import AUGMENTATIONS, STAMPS, TRIGGER_KINDS


def add_filter(session: Session, owner: OwnerId = None, *, label: str = "Filter",
               x: int = COLUMN_X["filter"], y: int = 40) -> GraphNode:
    """A new, empty Filter box."""
    node = GraphNode(owner_pk=owner, kind="filter", label=label or "Filter", x=x, y=y)
    session.add(node)
    session.flush()
    return node


def add_stamp(
    session: Session,
    owner: OwnerId = None,
    *,
    kind: str,
    marks: str = "",
    x: int | None = None,
    y: int = 40,
) -> GraphNode:
    """A box that marks what passes through it rather than narrowing it."""
    if kind not in STAMPS:
        raise GraphError(f"There is no {kind} box.")
    node = GraphNode(
        owner_pk=owner,
        kind=kind,
        marks=tag_name(marks) or None if kind == "tag" else None,
        x=COLUMN_X["filter"] if x is None else x,
        y=y,
    )
    session.add(node)
    session.flush()
    return node


def add_piece(
    session: Session,
    owner: OwnerId = None,
    *,
    kind: str,
    host: GraphNode | None = None,
    duration_minutes: int | None = None,
    cron: str | None = None,
    alive: tuple[str, str] | None = None,
    ref: str = "",
    settings: dict[str, str] | None = None,
    sort_by: str = "",
    newest_first: bool = True,
    side: str = "below",
    x: int = 0,
    y: int = 0,
) -> GraphNode:
    """An augmentation, slotted under a box if one was named — or, for a
    leaflet, beside another if that is the side it was dropped on.

    Its own position is kept for the moment it is unslotted: a piece that is
    attached is drawn under its host and does not use it, but a piece nobody
    has slotted anywhere has to be somewhere.

    A condition piece starts empty, which is a condition that narrows
    nothing: it is dropped on a box first and told what it means second, the
    same way a Tag box is dropped before it is named.
    """
    if kind not in AUGMENTATIONS:
        raise GraphError(f"There is no {kind} piece.")
    if kind == RULE and not ref:
        raise GraphError("A plugin condition has to say which one it is.")
    ends = alive or DEFAULT_ALIVE
    piece = GraphNode(
        owner_pk=owner,
        kind=kind,
        duration_minutes=duration_minutes if kind == "timer" else None,
        cron=(cron or DEFAULT_CRON) if kind == "reset" else None,
        alive_from=clock_time(ends[0]) if kind == "alive" else None,
        alive_to=clock_time(ends[1]) if kind == "alive" else None,
        plugin_ref=ref or None if kind == RULE else None,
        plugin_settings=(
            json.dumps(settings) if kind == RULE and settings else None
        ),
        sort_by=check_sort_key(sort_by or DEFAULT_SORT_BY) if kind == "order" else None,
        sort_dir=("desc" if newest_first else "asc") if kind == "order" else None,
        x=x,
        y=y,
    )
    session.add(piece)
    session.flush()
    if host is not None:
        # A piece has to exist before it can be slotted in — it is found by
        # id — so a refused drop has to take it away again. Otherwise saying
        # "that goes under a Sort" would leave the thing it refused lying on
        # the canvas, which is a refusal that did half of what was asked.
        try:
            attach(session, piece, host, owner, side=side)
        except GraphError:
            session.delete(piece)
            session.flush()
            raise
    return piece


def add_store(
    session: Session,
    owner: OwnerId = None,
    *,
    kind: str,
    repository: str = "",
    takes: int | None = None,
    x: int | None = None,
    y: int = 40,
) -> GraphNode:
    """A Deposit or a Withdraw box, both about one named repository.

    The name is what joins them: a Deposit and a Withdraw carrying the same
    name are two ends of one pile. It is filed lowercased, so a name typed
    two ways is still one repository.
    """
    if kind not in ("deposit", "withdraw"):
        raise GraphError(f"There is no {kind} box.")
    node = GraphNode(
        owner_pk=owner,
        kind=kind,
        repository=store_name(repository) or None,
        takes=takes if kind == "withdraw" else None,
        x=COLUMN_X[kind] if x is None else x,
        y=y,
    )
    session.add(node)
    session.flush()
    return node


def add_sort(
    session: Session,
    owner: OwnerId = None,
    *,
    label: str = "",
    x: int = COLUMN_X["sort"],
    y: int = 40,
) -> GraphNode:
    """A Sort box, which orders by whatever Order piece is slotted under it.

    It carries no key of its own: a box that ordered by something without
    saying so on the canvas was a box you had to open to read.
    """
    node = GraphNode(owner_pk=owner, kind="sort", label=label, x=x, y=y)
    session.add(node)
    session.flush()
    return node


def add_source(
    session: Session,
    owner: OwnerId = None,
    *,
    channel: Channel | None = None,
    source_kind: str = "",
    x: int = 0,
    y: int = 0,
) -> GraphNode:
    """A box for a channel — which may not have been named yet.

    A source box is dropped on the canvas first and told which source it is
    afterwards, by typing into it. Until then it stands for nothing, and
    everything that walks the graph skips it: an empty box cannot route
    anything, and saying so is better than refusing to make one.

    It does know which *kind* of somewhere it is for, because that is what
    was dragged out of the palette. That is the whole reason the box knows
    what to ask for: a Subreddit box asks for a subreddit.
    """
    node = GraphNode(
        owner_pk=owner,
        kind="source",
        channel_pk=channel.id if channel is not None else None,
        source_kind=(source_kind or "").strip() or None,
        x=x,
        y=y,
    )
    session.add(node)
    session.flush()
    return node


def attach_channel(
    session: Session, node: GraphNode, channel: Channel, owner: OwnerId = None
) -> GraphNode:
    """Say which channel an empty channel box stands for."""
    if node.kind != "source":
        raise GraphError("Only a channel node stands for a channel.")
    # The relationship, not only the key behind it: this node was loaded with
    # no channel, and setting the key alone leaves that stale until something
    # expires it — so the answer to this very request would still say empty.
    node.channel = channel
    node.channel_pk = channel.id
    node.label = ""  # the channel's own name takes over from the placeholder
    session.flush()
    return node


def add_feed(
    session: Session, playlist: Playlist, owner: OwnerId = None, *, x: int = 0, y: int = 0
) -> GraphNode:
    """A box for a feed somebody just made."""
    node = GraphNode(owner_pk=owner, kind="feed", playlist_pk=playlist.id, x=x, y=y)
    session.add(node)
    session.flush()
    return node


def add_trigger(
    session: Session,
    owner: OwnerId = None,
    *,
    trigger_kind: str = "pulse",
    label: str = "",
    every_minutes: int | None = None,
    cron: str | None = None,
    x: int | None = None,
    y: int | None = None,
) -> GraphNode:
    """Put a trigger box on the canvas, to the left of the channels.

    A pulse repeats on a gap; a schedule comes round at a time of day. Only
    the field that belongs to the kind is filled in, so a box changed from one
    to the other cannot carry a stale answer from the other shape.

    Its column is worked out from where the channels actually are rather than
    fixed, because a graph laid out before triggers existed has its channels
    hard against the left edge and a fixed column would land on top of them.
    """
    if trigger_kind not in TRIGGER_KINDS:
        raise GraphError(f"A trigger is a pulse or a schedule, not a {trigger_kind}.")

    # load() rather than nodes(): a trigger may be the first thing anyone adds,
    # and it is placed relative to the channel column, which has to exist.
    existing, _ = load(session, owner)
    if x is None or y is None:
        spot = room_for_a_trigger(session, existing)
        x = spot[0] if x is None else x
        y = spot[1] if y is None else y

    node = GraphNode(
        owner_pk=owner,
        kind="trigger",
        trigger_kind=trigger_kind,
        label=label,
        every_minutes=(
            (every_minutes or DEFAULT_EVERY_MINUTES) if trigger_kind == "pulse" else None
        ),
        cron=(check_cron(cron or DEFAULT_CRON) if trigger_kind == "schedule" else None),
        x=max(0, x),
        y=max(0, y),
    )
    session.add(node)
    session.flush()
    return node


def add_pamphlet(
    session: Session, owner: OwnerId = None, *, label: str = "", x: int = 0, y: int = 0
) -> GraphNode:
    """A Pamphlet box: a page under the Pamphlets tab, laid out by the
    leaflets slotted under it."""
    node = GraphNode(owner_pk=owner, kind="pamphlet", label=label.strip()[:120], x=x, y=y)
    session.add(node)
    session.flush()
    return node


def add_format(
    session: Session, owner: OwnerId = None, *, label: str = "", x: int = 0, y: int = 0
) -> GraphNode:
    """A Format box: reshapes the JSON wired into it into bars for a chart."""
    node = GraphNode(owner_pk=owner, kind="format", label=label.strip()[:120], x=x, y=y)
    session.add(node)
    session.flush()
    return node


def add_transform(
    session: Session, owner: OwnerId = None, *, label: str = "", x: int = 0, y: int = 0
) -> GraphNode:
    """A Transform box: turns items or data into data, as the piece under it says."""
    node = GraphNode(owner_pk=owner, kind="transform", label=label.strip()[:120], x=x, y=y)
    session.add(node)
    session.flush()
    return node


def add_text_box(
    session: Session, owner: OwnerId = None, *, label: str = "", x: int = 0, y: int = 0
) -> GraphNode:
    """A Text box: has a language model write from what comes in, for a Text leaflet."""
    node = GraphNode(owner_pk=owner, kind="text", label=label.strip()[:120], x=x, y=y)
    session.add(node)
    session.flush()
    return node
