"""The canvas as a whole: loaded, drawn from an existing setup the first time,
and room found for new boxes.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ...models import (
    Channel,
    GraphEdge,
    GraphNode,
    Playlist,
)
from ..scope import OwnerId, owned
from .reading import edges, nodes

log = logging.getLogger(__name__)


# Where a newly laid-out graph puts things: sources on the left, feeds on the
# right, filters between them. Triggers are placed beside the channel they are
# added next to rather than in a column, so they fit a canvas already laid out.
COLUMN_X = {
    "trigger": 60, "source": 60, "filter": 420, "sort": 420, "feed": 780,
    "group": 40,
    # A deposit sits where a feed sits, since it ends a path; a withdraw sits
    # where a source sits, since it starts one.
    "deposit": 780, "withdraw": 60,
}


ROW_HEIGHT = 130


# Where the trigger column goes, and how much clear space a channel box needs
# to its left for one to fit beside it.
TRIGGER_COLUMN = 40


TRIGGER_GAP = 260


def load(session: Session, owner: OwnerId = None) -> tuple[list[GraphNode], list[GraphEdge]]:
    """The whole graph, built from the existing setup if it has none yet."""
    existing = nodes(session, owner)
    if not existing:
        existing = _lay_out_existing(session, owner)
    _add_missing(session, existing, owner)
    return nodes(session, owner), edges(session, owner)


def _lay_out_existing(session: Session, owner: OwnerId) -> list[GraphNode]:
    """Turn the channels, feeds and links already set up into a graph.

    Runs once, the first time the canvas is opened. Every existing link
    becomes a direct wire, so what someone sees the first time is what they
    already had.
    """
    channels = list(
        session.scalars(
            owned(select(Channel), Channel, owner)
            .options(selectinload(Channel.playlists))
            .order_by(Channel.priority, Channel.id)
        )
    )
    playlists = list(
        session.scalars(
            owned(select(Playlist), Playlist, owner).order_by(Playlist.priority, Playlist.id)
        )
    )
    if not channels and not playlists:
        return []

    made: dict[tuple[str, int], GraphNode] = {}
    for row, channel in enumerate(channels):
        made[("source", channel.id)] = _place(session, owner, "source", row, channel_pk=channel.id)
    for row, playlist in enumerate(playlists):
        made[("feed", playlist.id)] = _place(session, owner, "feed", row, playlist_pk=playlist.id)
    session.flush()

    # Every link a channel already had becomes a wire out of its box. The
    # wire is the truth now, so a setup that was never drawn has to be drawn
    # here or it would come out unwired.
    drawn = 0
    for channel in channels:
        start = made[("source", channel.id)]
        for playlist in channel.playlists:
            end = made.get(("feed", playlist.id))
            if end is None:
                continue
            session.add(GraphEdge(owner_pk=owner, source_pk=start.id, target_pk=end.id))
            drawn += 1
    session.flush()

    log.info(
        "laid out a graph from %d channel(s), %d feed(s) and %d link(s)",
        len(channels), len(playlists), drawn,
    )
    return nodes(session, owner)


def _add_missing(session: Session, existing: list[GraphNode], owner: OwnerId) -> None:
    """A channel or feed added since the graph was drawn gets a box of its own.

    Unwired, and off to one side: appearing already connected to something
    would be a guess about what someone meant.
    """
    have_channels = {node.channel_pk for node in existing if node.kind == "source"}
    have_feeds = {node.playlist_pk for node in existing if node.kind == "feed"}

    rows = sum(1 for node in existing if node.kind == "source")
    for channel in session.scalars(owned(select(Channel), Channel, owner).order_by(Channel.id)):
        if channel.id not in have_channels:
            _place(session, owner, "source", rows, channel_pk=channel.id)
            rows += 1

    rows = sum(1 for node in existing if node.kind == "feed")
    for playlist in session.scalars(owned(select(Playlist), Playlist, owner).order_by(Playlist.id)):
        if playlist.id not in have_feeds:
            _place(session, owner, "feed", rows, playlist_pk=playlist.id)
            rows += 1
    session.flush()


def _place(
    session: Session,
    owner: OwnerId,
    kind: str,
    row: int,
    *,
    channel_pk: int | None = None,
    playlist_pk: int | None = None,
    label: str = "",
) -> GraphNode:
    """A new box in its kind's column, at `row`, for a first lay-out."""
    node = GraphNode(
        owner_pk=owner,
        kind=kind,
        x=COLUMN_X[kind],
        y=40 + row * ROW_HEIGHT,
        channel_pk=channel_pk,
        playlist_pk=playlist_pk,
        label=label,
    )
    session.add(node)
    return node


def room_for_a_trigger(session: Session, existing: list[GraphNode]) -> tuple[int, int]:
    """A free spot in the trigger column: left of the channels, below the last.

    A graph laid out before triggers existed has its channels hard against the
    left edge, with no column to put one in. Rather than drop a box on top of
    them, everything slides right to make room — once, when the first trigger
    is added. Relative positions are kept, so the drawing is the same drawing,
    further along.
    """
    taken = [node for node in existing if node.kind == "trigger"]
    sources = [node for node in existing if node.kind == "source"]
    left = min((node.x for node in sources), default=COLUMN_X["source"])

    if not taken and left < TRIGGER_COLUMN + TRIGGER_GAP:
        shift = TRIGGER_COLUMN + TRIGGER_GAP - left
        for node in existing:
            node.x += shift
        session.flush()
        log.info("moved the canvas %dpx right to make room for a trigger column", shift)
        return TRIGGER_COLUMN, 40

    column = TRIGGER_COLUMN if not taken else min(node.x for node in taken)
    return column, 40 + len(taken) * ROW_HEIGHT
