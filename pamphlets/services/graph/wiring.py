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
from . import leaflets, looks
from .vocabulary import DATA_TAKERS, WIRED_LEAFLETS, WIRING, carries_between


def connect(
    session: Session, source: GraphNode, target: GraphNode, owner: OwnerId = None,
    carries: str | None = None,
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
    if source.inside_pk != target.inside_pk:
        raise GraphError("A canvas keeps to itself: a box inside one is wired only to boxes beside it.")
    if "relay" in (source.kind, target.kind):
        return _through_relay(session, source, target, owner, carries)
    said = carries in WIRING
    carries = carries if carries is not None and said else carries_between(source.kind, target.kind)
    if not said and carries == "content" and only_data(source):
        carries = "data"
    if source.kind == "trigger":
        from .activations import is_activation

        # An Activation gives a signal to what it starts and its values, as
        # data, to anything that reads data. No other trigger gives data.
        if not said and is_activation(source) and target.kind not in WIRING["signal"]["trigger"]:
            carries = "data"
        if carries == "data" and not is_activation(source):
            raise GraphError("Only an Activation trigger gives data: the values it was set off with.")
    if only_data(source) and (
        carries == "content" or target.kind not in WIRING["data"].get(source.kind, ())
    ):
        raise GraphError(
            "A REST API gives data, not items: wire its { } port to an operation, "
            "a Transform or a Format box."
        )
    if target.kind not in WIRING[carries].get(source.kind, ()):
        if said and carries == "data":
            raise GraphError(f"A {source.kind} cannot give data to a {target.kind}.")
        raise GraphError(f"A {source.kind} cannot feed a {target.kind}.")

    fresh = carries == "content" and source.kind == "source" and target.kind == "feed"
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

    if _reaches(session, target, source, owner, carries):
        raise GraphError("That would make a loop, and nothing would ever come out of it.")

    existing = session.scalar(
        select(GraphEdge).where(
            GraphEdge.source_pk == source.id, GraphEdge.target_pk == target.id,
            GraphEdge.carries == carries,
        )
    )
    if existing is not None:
        return existing

    _make_room(session, target, carries)

    edge = GraphEdge(owner_pk=owner, source_pk=source.id, target_pk=target.id, carries=carries)
    session.add(edge)
    session.flush()
    if carries == "page" and target.kind in WIRED_LEAFLETS and source.playlist_pk is not None:
        leaflets.point_at(target, source.playlist_pk)
    if fresh and source.channel is not None and target.playlist is not None:
        refresh_membership(session, source.channel, owner)
        _bring_back_what_it_can_now_hold(session, source.channel, target.playlist, owner)
    return edge


def _make_room(session: Session, target: GraphNode, carries: str) -> None:
    """Take out what a new wire into `target` replaces, where it takes one thing in."""
    if target.kind in ("transform", "text", "relay"):
        # One thing in, of any kind: what it turns into data, writes about,
        # or passes on, is that.
        for older in session.scalars(select(GraphEdge).where(GraphEdge.target_pk == target.id)):
            session.delete(older)
        session.flush()
    elif (carries == "data" and target.kind in DATA_TAKERS) or carries == "page":
        # One thing in of this kind: a second wired in takes the first's place.
        for older in session.scalars(select(GraphEdge).where(
            GraphEdge.target_pk == target.id, GraphEdge.carries == carries,
        )):
            session.delete(older)
        session.flush()


def relay_origin(session: Session, relay: GraphNode, owner: OwnerId = None) -> tuple[GraphNode | None, str]:
    """Where what passes through a relay starts — back through any relays
    before it — and what it carries. (None, "") if nothing is wired in."""
    into = {edge.target_pk: edge for edge in edges(session, owner, every=True, raw=True)}
    node: GraphNode | None = relay
    carried = ""
    seen: set[int] = set()
    while node is not None and node.kind == "relay":
        if node.id in seen:
            return None, ""
        seen.add(node.id)
        wire = into.get(node.id)
        if wire is None:
            return None, ""
        carried = wire.carries
        node = session.get(GraphNode, wire.source_pk)
    return node, carried


def relay_ends(session: Session, relay: GraphNode, owner: OwnerId = None) -> list[GraphNode]:
    """The boxes a relay passes on to — through any relays after it."""
    onward: dict[int, list[int]] = {}
    for edge in edges(session, owner, every=True, raw=True):
        onward.setdefault(edge.source_pk, []).append(edge.target_pk)
    found: list[GraphNode] = []
    seen: set[int] = set()
    waiting = [relay.id]
    while waiting:
        at = waiting.pop()
        if at in seen:
            continue
        seen.add(at)
        for target_pk in onward.get(at, []):
            target = session.get(GraphNode, target_pk)
            if target is None:
                continue
            if target.kind == "relay":
                waiting.append(target.id)
            else:
                found.append(target)
    return found


def _gives(source: GraphNode, carries: str | None) -> str:
    """What a box sends down a wire drawn from it into a relay: what its port
    said, or else the one thing it gives."""
    if carries in WIRING:
        return str(carries)
    if source.kind == "trigger":
        return "signal"
    if only_data(source) or source.kind in ("format", "transform"):
        return "data"
    if source.kind in ("feed", "text"):
        return "page"
    return "content"


def _through_relay(
    session: Session, source: GraphNode, target: GraphNode, owner: OwnerId, carries: str | None,
) -> GraphEdge:
    """A wire into or out of a Relay. A relay passes on what comes into it,
    unchanged: so a wire out of one is allowed where a wire straight from
    where that starts would be, and a wire into one that already passes
    things on must still suit them."""
    if source.kind == "relay":
        origin, carried = relay_origin(session, source, owner)
        if origin is None:
            raise GraphError("Wire something into this relay first: it passes on what comes into it.")
    else:
        origin, carried = source, _gives(source, carries)
        if not WIRING.get(carried, {}).get(source.kind) or (only_data(source) and carried != "data"):
            raise GraphError(f"A {source.kind} has nothing to pass on that way.")
    ends = [target] if target.kind != "relay" else relay_ends(session, target, owner)
    for end in ends:
        if end.kind not in WIRING[carried].get(origin.kind, ()):
            raise GraphError(
                f"What comes through here starts at a {origin.kind}, and a {origin.kind} cannot feed a {end.kind}."
            )
    if _reaches(session, target, source, owner, carried):
        raise GraphError("That would make a loop, and nothing would ever come out of it.")
    existing = session.scalar(select(GraphEdge).where(
        GraphEdge.source_pk == source.id, GraphEdge.target_pk == target.id, GraphEdge.carries == carried,
    ))
    if existing is not None:
        return existing
    _make_room(session, target, carried)
    edge = GraphEdge(owner_pk=owner, source_pk=source.id, target_pk=target.id, carries=carried)
    session.add(edge)
    session.flush()
    # What follows from the wire, as if it went straight from where it starts.
    if carried == "page" and origin.playlist_pk is not None:
        for end in ends:
            if end.kind in WIRED_LEAFLETS:
                leaflets.point_at(end, origin.playlist_pk)
    if origin.kind == "source" and origin.channel is not None:
        refresh_membership(session, origin.channel, owner)
    return edge


def after_relay_change(session: Session, origin: GraphNode | None, ends: list[GraphNode], owner: OwnerId) -> None:
    """Put right what a relay's wires said, once one of them has gone: the
    feeds a source fills, and the feed a leaflet shows."""
    for end in ends:
        if end.kind in WIRED_LEAFLETS and not any(
            edge.target_pk == end.id and edge.carries == "page" for edge in edges(session, owner, every=True)
        ):
            leaflets.point_at(end, None)
    if origin is not None and origin.kind == "source" and origin.channel is not None:
        refresh_membership(session, origin.channel, owner)


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
    # As drawn: relays and all.
    _, all_edges = load(session, owner, every=True, raw=True)

    def kind_of(edge: GraphEdge) -> str:
        # The canvas draws paths alike, signal or items; page and data
        # wires each their own way.
        return edge.carries if edge.carries in ("page", "data") else "edge"

    return [
        {
            "id": f"edge:{edge.id}",
            "from": edge.source_pk,
            "to": edge.target_pk,
            "kind": kind_of(edge),
            "route": looks.route_of(edge),
            "colour": looks.colour_of(edge),
            "bend": looks.bend_of(edge),
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
    end = session.get(GraphNode, edge.target_pk)
    was_page = edge.carries == "page"
    if (start is not None and start.kind == "relay") or (end is not None and end.kind == "relay"):
        # Through a relay: what it changes is where it starts and where it ends.
        origin = relay_origin(session, start, owner)[0] if start is not None and start.kind == "relay" else start
        ends = relay_ends(session, end, owner) if end is not None and end.kind == "relay" else [end] if end else []
        session.delete(edge)
        session.flush()
        after_relay_change(session, origin, [one for one in ends if one is not None], owner)
        return True
    session.delete(edge)
    session.flush()
    if was_page and end is not None and end.kind in WIRED_LEAFLETS:
        leaflets.point_at(end, None)
    if channel is not None:
        refresh_membership(session, channel, owner)
    return True


def still_drawn(session: Session, pk: int, what: str) -> bool:
    """Whether any node still stands for this channel or playlist."""
    column = GraphNode.channel_pk if what == "channel" else GraphNode.playlist_pk
    return session.scalar(select(GraphNode.id).where(column == pk).limit(1)) is not None


def _reaches(
    session: Session, start: GraphNode, goal: GraphNode, owner: OwnerId, carries: str = "content"
) -> bool:
    """Whether `goal` is already downstream of `start` — a loop in waiting.

    Along wires of the same kind: items and data are separate flows, and a
    data wire back up a path makes no loop in it."""
    # Depth-first along the wires from `start`, looking for `goal`.
    # As drawn, relays and all: a loop through a relay is still a loop.
    out: dict[int, list[int]] = {}
    for edge in edges(session, owner, every=True, raw=True):
        if edge.carries == carries:
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


def only_data(node: GraphNode) -> bool:
    """Whether a box gives data and no items: a REST API source does — what
    an API answers is numbers and records, read through Format or Transform."""
    if node.kind != "source":
        return False
    kind = node.channel.source_kind if node.channel is not None else node.source_kind
    return kind == "rest"
