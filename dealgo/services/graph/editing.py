"""Renaming, moving and removing what is on the canvas."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...models import (
    GraphNode,
)
from ..scope import OwnerId, owned
from .errors import GraphError
from .pieces import close_up, pieces_under
from .reading import nodes
from .vocabulary import AUGMENTATIONS
from .wiring import refresh_membership, still_drawn


def rename(session: Session, node_pk: int, name: str, owner: OwnerId = None) -> GraphNode:
    """Rename a box, and the thing behind it if this is its only box.

    A box that stands for a channel or a feed writes the new name through, so
    the rest of the app agrees with the canvas. The sync engine only fills in
    a channel's title when it is blank, so a rename is not undone by the next
    poll.

    Only while it is the only box for that thing, though. A channel may be
    drawn twice — two boxes, wired down two paths that filter differently —
    and writing through would then rename the other box as well. Two boxes
    that rename each other are one box in two places, which is the opposite
    of why you drew the second.
    """
    node = session.scalar(owned(select(GraphNode), GraphNode, owner).where(GraphNode.id == node_pk))
    if node is None:
        raise GraphError("That node is not here.")

    wanted = " ".join(name.split())
    node.label = wanted
    if wanted and stands_alone(session, node, owner):
        if node.kind == "source" and node.channel is not None:
            node.channel.title = wanted
        elif node.kind == "feed" and node.playlist is not None:
            node.playlist.title = wanted
    session.flush()
    return node


def stands_alone(session: Session, node: GraphNode, owner: OwnerId = None) -> bool:
    """Whether this is the only box on the canvas for the thing behind it.

    Which decides what a box is allowed to write through to that thing: with
    one box the canvas and the channel are the same thing said twice, and
    with two they are not.
    """
    if node.kind == "source" and node.channel_pk is not None:
        column, wanted = GraphNode.channel_pk, node.channel_pk
    elif node.kind == "feed" and node.playlist_pk is not None:
        column, wanted = GraphNode.playlist_pk, node.playlist_pk
    else:
        return False
    others = session.scalar(
        owned(select(func.count()).select_from(GraphNode), GraphNode, owner).where(
            column == wanted, GraphNode.id != node.id
        )
    )
    return not others


def move(session: Session, node_pk: int, x: int, y: int, owner: OwnerId = None) -> bool:
    """Put a box at new coordinates. False if it is not here."""
    node = session.scalar(owned(select(GraphNode), GraphNode, owner).where(GraphNode.id == node_pk))
    if node is None:
        return False
    node.x, node.y = int(x), int(y)
    session.flush()
    return True


def remove(session: Session, node_pk: int, owner: OwnerId = None) -> bool:
    """Take a box off the canvas, and the thing behind it with it.

    The canvas is the whole of the configuration now, so this is the only
    place a channel or a feed can be removed — there is no list to do it from
    any more. What that costs is spelled out where it is pressed, not here.
    """
    node = session.scalar(owned(select(GraphNode), GraphNode, owner).where(GraphNode.id == node_pk))
    if node is None:
        return False

    channel, playlist = node.channel, node.playlist

    if node.kind in AUGMENTATIONS:
        # The chain closes up behind it. The column carries a cascade on a
        # database built from scratch, which would take everything below it
        # as well — silently deleting a Reset because a Timer above it was
        # removed.
        close_up(session, node)
    else:
        # A box's pieces describe that box, so they go with it rather than
        # being left on the canvas slotted into nothing. Said here rather
        # than left to the cascade, which a column added to an existing
        # database does not carry.
        # Deepest first: a piece's own pieces cascade with it on a database
        # built from scratch, and deleting them after would find them gone.
        for piece in reversed(pieces_under(nodes(session, owner), node.id)):
            session.delete(piece)
            session.flush()

    session.delete(node)
    session.flush()

    # The wires went with it, so which feeds that channel fills has changed.
    if node.kind == "source" and channel is not None:
        refresh_membership(session, channel, owner)

    # Only if nothing else is still drawn around it. A channel may have two
    # nodes, and taking one off the canvas is rearranging the drawing rather
    # than saying goodbye to the channel.
    if node.kind == "source" and channel is not None and not still_drawn(session, channel.id, "channel"):
        session.delete(channel)
    elif node.kind == "feed" and playlist is not None and not still_drawn(session, playlist.id, "playlist"):
        session.delete(playlist)
    session.flush()
    return True
