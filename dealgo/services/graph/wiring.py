"""Drawing and removing wires, and what follows from them."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...plugins.publisher import names
from ...models import (
    Channel,
    GraphEdge,
    GraphNode,
    Playlist,
    Video,
)
from ..scope import OwnerId, owned
from .canvas import load
from .errors import GraphError
from .reading import edges, nodes
from .vocabulary import ALLOWED


def connect(
    session: Session, source: GraphNode, target: GraphNode, owner: OwnerId = None
) -> GraphEdge | None:
    """Wire one box to another, refusing what would not make sense.

    Every wire is an edge, including a source's. It used to be stored as a
    link between the *channel* and the feed, which meant two boxes for one
    channel could not be told apart: wiring either drew a wire from both, and
    unwiring either unwired both. A wire belongs to the box it was drawn
    from, so that a second box is a second box.
    """
    if source.id == target.id:
        raise GraphError("A node cannot feed itself.")
    if target.kind not in ALLOWED.get(source.kind, ()):
        raise GraphError(f"A {source.kind} cannot feed a {target.kind}.")

    fresh = source.kind == "source" and target.kind == "feed"
    if fresh:
        if source.channel is None or target.playlist is None:
            raise GraphError("That node no longer has anything behind it.")
        # A wire that could never carry anything, refused where it is drawn
        # rather than discovered sixty skipped items later.
        if not source.channel.publishable and not target.playlist.is_generic:
            publisher = names().publisher
            raise GraphError(
                f"{target.playlist.title} is a {publisher} playlist, and a {publisher} playlist "
                f"holds {publisher} items only. Wire this one to a feed that lives here — "
                "make a new feed and keep it generic."
            )

    if _reaches(session, target, source, owner):
        raise GraphError("That would make a loop, and nothing would ever come out of it.")

    existing = session.scalar(
        select(GraphEdge).where(
            GraphEdge.source_pk == source.id, GraphEdge.target_pk == target.id
        )
    )
    if existing is not None:
        return existing

    edge = GraphEdge(owner_pk=owner, source_pk=source.id, target_pk=target.id)
    session.add(edge)
    session.flush()
    if fresh and source.channel is not None and target.playlist is not None:
        refresh_membership(session, source.channel, owner)
        _bring_back_what_it_can_now_hold(session, source.channel, target.playlist, owner)
    return edge


def _bring_back_what_it_can_now_hold(
    session: Session, channel: Channel, playlist: Playlist, owner: OwnerId = None
) -> int:
    """Requeue items this source had nowhere to put.

    A source the publishing service cannot hold, wired only to its playlists, has every
    item turned away. Giving it a feed that can hold them should fill that
    feed, not leave the backlog stranded and wait for the next new post —
    the same courtesy turning a filter off already gets.
    """
    from .. import sync as sync_service

    # Only a feed here can take what a published playlist turned away, and only an unpublishable source
    # was turned away.
    if not playlist.is_generic or channel.publishable:
        return 0

    stranded = list(
        session.scalars(
            owned(select(Video), Video, owner).where(
                Video.channel_pk == channel.id,
                Video.status == "skipped",
                Video.reason == sync_service.WRONG_KIND_OF_FEED,
            )
        )
    )
    for video in stranded:
        video.status = "pending"
        video.reason = None
        video.attempts = 0
        video.processed_at = None
    session.flush()
    return len(stranded)


def refresh_membership(
    session: Session, channel: Channel, owner: OwnerId = None
) -> None:
    """Work out again which feeds this channel fills, from the wires drawn.

    ``channel.playlists`` is what the rest of the app reads — the feed page,
    the backup, the sync engine — and it is now a view of the canvas rather
    than a thing anybody edits. One writer, so the two cannot disagree.

    Only the wires straight from a box to a feed count, which is what the
    pairing has always meant: a path that goes through a filter is a path,
    and `routes` is what asks about those.
    """
    # Feed boxes by the feed they stand for, and this channel's own source boxes.
    by_playlist = {
        node.playlist_pk: node
        for node in nodes(session, owner)
        if node.kind == "feed" and node.playlist_pk
    }
    mine = [
        node.id
        for node in nodes(session, owner)
        if node.kind == "source" and node.channel_pk == channel.id
    ]
    if not mine:
        channel.playlists = []
        session.flush()
        return

    # The feeds wired straight from any of those boxes.
    wired = {
        edge.target_pk
        for edge in edges(session, owner)
        if edge.source_pk in mine
    }
    feeds = [
        node.playlist
        for playlist_pk, node in by_playlist.items()
        if node.id in wired and node.playlist is not None
    ]
    channel.playlists = feeds
    session.flush()


def wires(session: Session, owner: OwnerId = None) -> list[dict[str, Any]]:
    """Every wire, in the one shape the canvas draws from.

    One kind now. A source's wire used to be synthesised from its channel's
    feeds, which is why two boxes for one channel showed the same wires.
    """
    _, all_edges = load(session, owner)

    return [
        {
            "id": f"edge:{edge.id}",
            "from": edge.source_pk,
            "to": edge.target_pk,
            "kind": "edge",
        }
        for edge in all_edges
    ]


def disconnect(session: Session, edge_pk: int, owner: OwnerId = None) -> bool:
    """Remove a wire, and work out again which feeds its source fills."""
    edge = session.scalar(owned(select(GraphEdge), GraphEdge, owner).where(GraphEdge.id == edge_pk))
    if edge is None:
        return False
    # Held before the row goes: afterwards there is nothing to ask which
    # channel's feeds have just changed.
    start = session.get(GraphNode, edge.source_pk)
    channel = start.channel if start is not None and start.kind == "source" else None
    session.delete(edge)
    session.flush()
    if channel is not None:
        refresh_membership(session, channel, owner)
    return True


def still_drawn(session: Session, pk: int, what: str) -> bool:
    """Whether any node still stands for this channel or playlist."""
    column = GraphNode.channel_pk if what == "channel" else GraphNode.playlist_pk
    return session.scalar(select(GraphNode.id).where(column == pk).limit(1)) is not None


def _reaches(session: Session, start: GraphNode, goal: GraphNode, owner: OwnerId) -> bool:
    """Whether `goal` is already downstream of `start` — a loop in waiting."""
    # Depth-first along the wires from `start`, looking for `goal`.
    out: dict[int, list[int]] = {}
    for edge in edges(session, owner):
        out.setdefault(edge.source_pk, []).append(edge.target_pk)

    seen: set[int] = set()
    stack = [start.id]
    while stack:
        current = stack.pop()
        if current == goal.id:
            return True
        if current in seen:
            continue
        seen.add(current)
        stack.extend(out.get(current, []))
    return False
