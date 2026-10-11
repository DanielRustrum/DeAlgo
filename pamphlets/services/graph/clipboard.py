"""Copy, cut and paste on the canvas.

**Copy** packs the picked boxes as a group's file packs them — each one's
settings, the pieces slotted under it, what a picked group surrounds, and
the wires between them — and **paste** makes them again in the canvas being
looked at. A source or a feed box pasted in the account it was copied from
is another box for the same channel or feed, as drawing one twice is: a copy
never duplicates a feed, or what it has collected.

**Cut** is a move, finished by pasting: nothing is taken away until then,
and pasting moves the boxes themselves — their history, their feeds and the
wires between them with them — to where they are pasted, in this canvas or
another. Wires to boxes left behind go, if the boxes go to another canvas:
a canvas keeps to itself.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import Channel, GraphEdge, GraphNode, Playlist
from ..scope import OwnerId, owned
from . import groups, insides
from .errors import GraphError
from .pieces import pieces_under
from .reading import nodes

#: What a copy says it is, so a paste can tell one from anything else.
CLIP_FORMAT = 1


def gather(session: Session, picked_ids: list[int], owner: OwnerId = None) -> list[GraphNode]:
    """The picked boxes, and what goes with each: the pieces slotted under
    it, and — for a group — whatever it surrounds, and their pieces."""
    every = nodes(session, owner)
    by_id = {node.id: node for node in every}
    found: dict[int, GraphNode] = {}

    def take(node: GraphNode) -> None:
        if node.id in found:
            return
        found[node.id] = node
        for piece in pieces_under(every, node.id):
            found.setdefault(piece.id, piece)

    for pk in picked_ids:
        node = by_id.get(pk)
        if node is None:
            continue
        take(node)
        if node.kind == "group":
            for inner in groups.inside(session, node, owner):
                take(inner)
    return list(found.values())


def _corner(carried: list[GraphNode]) -> tuple[int, int]:
    """The top-left of what is carried — its boxes, not the pieces hanging
    off them, which are placed from their boxes."""
    boxes = [node for node in carried if node.attached_to is None] or carried
    return min(node.x for node in boxes), min(node.y for node in boxes)


def copy(session: Session, picked_ids: list[int], owner: OwnerId = None) -> dict[str, Any]:
    """The picked boxes, packed to be pasted."""
    carried = gather(session, picked_ids, owner)
    if not carried:
        raise GraphError("Nothing is picked to copy.")
    left, top = _corner(carried)
    packed, wires = groups.pack_nodes(session, carried, left, top, owner)
    for entry, node in zip(packed, carried):
        # Which box it was, so an undo can put wires back to what it became.
        entry["was"] = node.id
        # In the same account, the same channel and feed, not new ones.
        if node.kind == "source" and node.channel_pk is not None:
            entry["channel_pk"] = node.channel_pk
        if node.kind == "feed" and node.playlist_pk is not None:
            entry["feed_pk"] = node.playlist_pk
        if node.kind == "group":
            entry["width"], entry["height"] = node.width, node.height
    return {"pamphlets_clip": CLIP_FORMAT, "nodes": packed, "wires": wires}


def paste(
    session: Session, clip: Any, owner: OwnerId = None, *, x: int = 40, y: int = 40,
    copied_from: dict[int, int] | None = None,
) -> list[GraphNode]:
    """Make what was copied again, its top-left at `x`, `y`, in the canvas
    being looked at. Says which boxes it made — and, into `copied_from`,
    which box each is a copy of, as the copy said."""
    if not isinstance(clip, dict) or clip.get("pamphlets_clip") != CLIP_FORMAT:
        raise GraphError("That is not something copied from the canvas.")
    made: dict[int, GraphNode] = {}
    for entry in clip.get("nodes") or []:
        if not isinstance(entry, dict):
            continue
        at = (x + int(entry.get("x") or 0), y + int(entry.get("y") or 0))
        node = _same_thing(session, entry, owner, at) or groups.unpack(session, entry, owner, at=at)
        if node is None:
            continue
        groups.apply(session, node, entry, owner)
        if copied_from is not None and isinstance(entry.get("was"), int):
            copied_from[entry["was"]] = node.id
        made[int(entry.get("ref", -1))] = node
    session.flush()
    groups.slot_and_wire(session, clip, made, owner)
    session.flush()
    return list(made.values())


def _same_thing(
    session: Session, entry: dict[str, Any], owner: OwnerId, at: tuple[int, int],
) -> GraphNode | None:
    """Another box for the channel or feed the copied one stood for, if this
    account still has it."""
    from .adding import add_feed, add_source

    if entry.get("kind") == "source" and isinstance(entry.get("channel_pk"), int):
        channel = session.scalar(owned(select(Channel), Channel, owner).where(Channel.id == entry["channel_pk"]))
        if channel is not None:
            return add_source(session, owner, channel=channel, x=at[0], y=at[1])
    if entry.get("kind") == "feed" and isinstance(entry.get("feed_pk"), int):
        playlist = session.scalar(owned(select(Playlist), Playlist, owner).where(Playlist.id == entry["feed_pk"]))
        if playlist is not None:
            return add_feed(session, playlist, owner, x=at[0], y=at[1])
    return None


def move(session: Session, picked_ids: list[int], owner: OwnerId = None, *, x: int = 40, y: int = 40) -> list[GraphNode]:
    """Finish a cut: move the picked boxes, and what goes with them, to the
    canvas being looked at, their top-left at `x`, `y`. Says which it moved."""
    carried = gather(session, picked_ids, owner)
    if not carried:
        raise GraphError("What was cut is no longer there.")
    target = insides.current(session, owner)
    every = nodes(session, owner)
    by_id = {node.id: node for node in every}
    moving = {node.id for node in carried}

    # A canvas cannot go inside itself, nor take its insides deeper than five.
    for node in carried:
        if node.kind != "canvas":
            continue
        within = insides.everything_inside(every, node.id)
        if target == node.id or target in {inner.id for inner in within}:
            raise GraphError("A canvas cannot go inside itself.")
        # How many levels it holds below its own inside.
        below = max((insides.depth(by_id, inner.id) - insides.depth(by_id, node.id)
                     for inner in within if inner.kind == "canvas"), default=0)
        if insides.depth(by_id, target) + 1 + below > insides.MOST_DEPTH:
            raise GraphError(f"Canvases go {insides.MOST_DEPTH} deep: that one would go deeper.")

    # Into another canvas, wires to boxes left behind go: a canvas keeps to
    # itself. Taken out the way taking each out would, so the feeds a source
    # fills and the feed a leaflet shows are put right.
    from .wiring import disconnect

    if any(node.inside_pk != target for node in carried):
        for edge in list(session.scalars(owned(select(GraphEdge), GraphEdge, owner))):
            if (edge.source_pk in moving) != (edge.target_pk in moving):
                disconnect(session, edge.id, owner)

    left, top = _corner(carried)
    for node in carried:
        node.x = x + (node.x - left)
        node.y = y + (node.y - top)
        node.inside_pk = target
    session.flush()
    return carried
