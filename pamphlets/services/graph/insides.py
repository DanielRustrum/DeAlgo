"""Canvas nodes: canvases inside the canvas, five deep at most.

A Canvas node is a box that is a canvas of its own: double-clicked, the
canvas shows what is inside it, with a trail back out. What is inside is
kept apart — its boxes wire only to each other — but nothing about it is
asleep: every box inside runs, as every box outside does.

Each box says which Canvas node it is inside (`GraphNode.inside_pk`; None
for the top of the canvas). The canvas being looked at is the one a request
names (`CURRENT_INSIDE`), and a box made while it is set is made there.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ...models import CURRENT_INSIDE, GraphNode
from ..scope import OwnerId
from .errors import GraphError
from .reading import nodes

#: How many canvases deep a canvas can be: the top, then five more.
MOST_DEPTH = 5


def depth(by_id: dict[int, GraphNode], inside: int | None) -> int:
    """How many canvases deep a canvas is: the top is 0."""
    level = 0
    seen: set[int] = set()
    while inside is not None and inside not in seen and level <= MOST_DEPTH + 1:
        seen.add(inside)
        level += 1
        holder = by_id.get(inside)
        inside = holder.inside_pk if holder is not None else None
    return level


def current(session: Session, owner: OwnerId = None) -> int | None:
    """The canvas being looked at — if the request named one that is the
    account's own Canvas node. Anything else is the top."""
    wanted = CURRENT_INSIDE.get()
    if wanted is None:
        return None
    node = session.get(GraphNode, wanted)
    if node is None or node.kind != "canvas" or node.owner_pk != owner:
        return None
    return wanted


def trail(session: Session, owner: OwnerId, inside: int | None) -> list[dict[str, object]]:
    """The way back out: the top, then each canvas down to this one."""
    by_id = {node.id: node for node in nodes(session, owner)}
    found: list[dict[str, object]] = []
    seen: set[int] = set()
    while inside is not None and inside not in seen:
        seen.add(inside)
        holder = by_id.get(inside)
        if holder is None:
            break
        found.append({"id": holder.id, "title": holder.title})
        inside = holder.inside_pk
    found.append({"id": None, "title": "Configuration"})
    return list(reversed(found))


def everything_inside(all_nodes: list[GraphNode], canvas_pk: int) -> list[GraphNode]:
    """Every box inside a Canvas node, and inside the canvases inside it."""
    found: list[GraphNode] = []
    holders = {canvas_pk}
    while holders:
        within = [node for node in all_nodes if node.inside_pk in holders]
        found.extend(within)
        holders = {node.id for node in within if node.kind == "canvas"}
    return found


def add_canvas(
    session: Session, owner: OwnerId = None, *, label: str = "", x: int = 0, y: int = 0
) -> GraphNode:
    """A Canvas node, in the canvas being looked at — if that is not already
    as deep as canvases go."""
    inside = current(session, owner)
    by_id = {node.id: node for node in nodes(session, owner)}
    if depth(by_id, inside) >= MOST_DEPTH:
        raise GraphError(f"Canvases go {MOST_DEPTH} deep, and this is the deepest: there is no room for another inside it.")
    node = GraphNode(owner_pk=owner, kind="canvas", label=label.strip()[:120], x=x, y=y, inside_pk=inside)
    session.add(node)
    session.flush()
    return node


def add_relay(session: Session, owner: OwnerId = None, *, x: int = 0, y: int = 0) -> GraphNode:
    """A Relay: a point a wire passes through, to be drawn round other boxes."""
    node = GraphNode(owner_pk=owner, kind="relay", label="", x=x, y=y, inside_pk=current(session, owner))
    session.add(node)
    session.flush()
    return node
