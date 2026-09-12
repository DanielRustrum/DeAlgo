"""The Configuration canvas: what is wired to what.

The graph is the truth about routing. A video leaves a source node, follows
wires, and lands in every feed node it can reach — narrowed on the way by any
filter node it passes through.

Two rules make it comprehensible:

* **A channel's own filters are the default.** They apply on every path out of
  that channel, exactly as they did before there was a graph.
* **A filter node overrides, it does not replace.** Anything it leaves unset
  stays whatever the channel said. So a channel can take Shorts everywhere
  except down one particular wire, without its settings being duplicated.

Existing setups are turned into a graph the first time one is asked for, so
nobody has to build theirs again.

Wires have one home each, which is what keeps the canvas and the rest of the
app from disagreeing:

* **Source to feed** is the link that already existed — a row in
  ``channel_playlist``. Drawing one on the canvas writes that, so a channel's
  own page shows it too.
* **Anything touching a filter node** is a ``GraphEdge``, because there was
  nowhere else for it to live.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..models import Channel, GraphEdge, GraphNode, Playlist
from .scope import OwnerId, owned

log = logging.getLogger(__name__)

KINDS = ("source", "filter", "feed")

# Which wires make sense. Sources start paths, feeds end them, filters sit in
# between — and nothing runs backwards.
ALLOWED: dict[str, tuple[str, ...]] = {
    "source": ("filter", "feed"),
    "filter": ("filter", "feed"),
    "feed": (),
}

# Where a newly laid-out graph puts things: sources on the left, feeds on the
# right, filters between them.
COLUMN_X = {"source": 60, "filter": 420, "feed": 780}
ROW_HEIGHT = 130


class GraphError(RuntimeError):
    """Something the person drawing it should be told."""


@dataclass
class Route:
    """One path from a channel to a feed, and what narrows it."""

    channel: Channel
    playlist: Playlist
    filters: list[GraphNode] = field(default_factory=list)

    def effective(self) -> dict[str, Any]:
        """The channel's filters with each filter node laid over the top.

        Later nodes win, so a path can narrow twice and the last word is the
        one nearest the feed.
        """
        settings: dict[str, Any] = {
            "skip_videos": self.channel.skip_videos,
            "skip_shorts": self.channel.skip_shorts,
            "skip_live": self.channel.skip_live,
            "skip_posts": self.channel.skip_posts,
            "title_include": self.channel.title_include,
            "title_exclude": self.channel.title_exclude,
            "min_duration_sec": self.channel.min_duration_sec,
            "max_duration_sec": self.channel.max_duration_sec,
            "max_per_run": self.channel.max_per_run,
        }
        for node in self.filters:
            settings.update(node.overrides)
        return settings


# -- reading ---------------------------------------------------------------


def nodes(session: Session, owner: OwnerId = None) -> list[GraphNode]:
    return list(
        session.scalars(
            owned(select(GraphNode), GraphNode, owner)
            .options(selectinload(GraphNode.channel), selectinload(GraphNode.playlist))
            .order_by(GraphNode.id)
        )
    )


def edges(session: Session, owner: OwnerId = None) -> list[GraphEdge]:
    return list(
        session.scalars(owned(select(GraphEdge), GraphEdge, owner).order_by(GraphEdge.id))
    )


def load(session: Session, owner: OwnerId = None) -> tuple[list[GraphNode], list[GraphEdge]]:
    """The whole graph, built from the existing setup if it has none yet."""
    existing = nodes(session, owner)
    if not existing:
        existing = _lay_out_existing(session, owner)
    _add_missing(session, existing, owner)
    return nodes(session, owner), edges(session, owner)


def routes(session: Session, owner: OwnerId = None) -> list[Route]:
    """Every channel-to-feed path in the graph, with what narrows each.

    This is what the sync engine asks instead of reading a channel's targets:
    the same channel can reach two feeds down two paths that filter
    differently, which a list of targets cannot express.
    """
    all_nodes, all_edges = load(session, owner)
    by_id = {node.id: node for node in all_nodes}
    out: dict[int, list[int]] = {}
    for edge in all_edges:
        out.setdefault(edge.source_pk, []).append(edge.target_pk)

    feed_node_for = {node.playlist_pk: node for node in all_nodes if node.kind == "feed"}

    found: list[Route] = []
    for node in all_nodes:
        if node.kind != "source" or node.channel is None:
            continue
        # The direct wires: the channel-to-feed links, unfiltered by anything
        # but the channel itself.
        for playlist in node.channel.playlists:
            if playlist.id in feed_node_for:
                found.append(Route(channel=node.channel, playlist=playlist))
        # And the paths that go through filter nodes.
        _walk(node, by_id, out, node.channel, [], set(), found)
    return found


def _walk(
    node: GraphNode,
    by_id: dict[int, GraphNode],
    out: dict[int, list[int]],
    channel: Channel,
    carried: list[GraphNode],
    seen: set[int],
    found: list[Route],
) -> None:
    """Depth-first from a source, collecting filters until a feed is reached.

    `seen` is per path, not global: two paths may legitimately pass through the
    same filter node, and only a loop is a problem.
    """
    if node.id in seen:
        return
    seen = seen | {node.id}

    for target_id in out.get(node.id, []):
        target = by_id.get(target_id)
        if target is None:
            continue
        if target.kind == "feed":
            if target.playlist is not None:
                found.append(Route(channel=channel, playlist=target.playlist, filters=list(carried)))
        elif target.kind == "filter":
            _walk(target, by_id, out, channel, carried + [target], seen, found)


# -- building it from what is already there --------------------------------


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

    # No edges to write: a direct wire is the channel-to-feed link, which is
    # already there. Laying out the boxes is the whole job.
    log.info("laid out a graph from %d channel(s) and %d feed(s)", len(channels), len(playlists))
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


# -- changing it -----------------------------------------------------------


def connect(
    session: Session, source: GraphNode, target: GraphNode, owner: OwnerId = None
) -> GraphEdge | None:
    """Wire one box to another, refusing what would not make sense.

    Returns the edge it made, or None for a source-to-feed wire — that one is
    a channel-to-feed link rather than an edge, so that the channel's own page
    and the canvas are looking at the same thing.
    """
    if source.id == target.id:
        raise GraphError("A box cannot feed itself.")
    if target.kind not in ALLOWED.get(source.kind, ()):
        raise GraphError(f"A {source.kind} cannot feed a {target.kind}.")

    if source.kind == "source" and target.kind == "feed":
        if source.channel is None or target.playlist is None:
            raise GraphError("That box no longer has anything behind it.")
        if target.playlist not in source.channel.playlists:
            source.channel.playlists.append(target.playlist)
            session.flush()
        return None

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
    return edge


def unlink(session: Session, source: GraphNode, target: GraphNode) -> bool:
    """Take out a source-to-feed wire, which is a link rather than an edge."""
    if source.channel is None or target.playlist is None:
        return False
    if target.playlist in source.channel.playlists:
        source.channel.playlists.remove(target.playlist)
        session.flush()
        return True
    return False


def wires(session: Session, owner: OwnerId = None) -> list[dict[str, Any]]:
    """Every wire, of both kinds, in the one shape the canvas draws from."""
    all_nodes, all_edges = load(session, owner)
    feed_node_for = {node.playlist_pk: node for node in all_nodes if node.kind == "feed"}

    drawn: list[dict[str, Any]] = []
    for node in all_nodes:
        if node.kind == "source" and node.channel is not None:
            for playlist in node.channel.playlists:
                target = feed_node_for.get(playlist.id)
                if target is not None:
                    drawn.append({"id": f"link:{node.id}:{target.id}", "from": node.id,
                                  "to": target.id, "kind": "link"})
    for edge in all_edges:
        drawn.append({"id": f"edge:{edge.id}", "from": edge.source_pk,
                      "to": edge.target_pk, "kind": "edge"})
    return drawn


def disconnect(session: Session, edge_pk: int, owner: OwnerId = None) -> bool:
    edge = session.scalar(owned(select(GraphEdge), GraphEdge, owner).where(GraphEdge.id == edge_pk))
    if edge is None:
        return False
    session.delete(edge)
    session.flush()
    return True


def _reaches(session: Session, start: GraphNode, goal: GraphNode, owner: OwnerId) -> bool:
    """Whether `goal` is already downstream of `start` — a loop in waiting."""
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


def add_filter(session: Session, owner: OwnerId = None, *, label: str = "Filter",
               x: int = COLUMN_X["filter"], y: int = 40) -> GraphNode:
    node = GraphNode(owner_pk=owner, kind="filter", label=label or "Filter", x=x, y=y)
    session.add(node)
    session.flush()
    return node


def move(session: Session, node_pk: int, x: int, y: int, owner: OwnerId = None) -> bool:
    node = session.scalar(owned(select(GraphNode), GraphNode, owner).where(GraphNode.id == node_pk))
    if node is None:
        return False
    node.x, node.y = int(x), int(y)
    session.flush()
    return True


def remove(session: Session, node_pk: int, owner: OwnerId = None) -> bool:
    """Only filter nodes. A source or feed box stands for a channel or a feed,
    and deleting one of those is not something to do by pressing backspace on
    a canvas."""
    node = session.scalar(owned(select(GraphNode), GraphNode, owner).where(GraphNode.id == node_pk))
    if node is None:
        return False
    if node.kind != "filter":
        raise GraphError(
            "That box stands for a channel or a feed. Remove it from its own page, where the "
            "consequences are spelled out."
        )
    session.delete(node)
    session.flush()
    return True
