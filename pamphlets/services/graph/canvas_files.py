"""A Canvas box as a file to hand somebody else: a `.pam` file.

Everything inside the canvas travels — each box's settings, the pieces
slotted under it, its comments and relays, the canvases inside it and
everything inside those — with the wires between, drawn as they were.
Positions are each canvas's own, so they come back where they were.

Loaded, a `.pam` file is a new Canvas box, in the canvas it is loaded into,
with all of that inside it. Nothing already here is changed: channels it
names are matched by their id or made, and feeds are made, as a group's
file does (groups.py, whose packing this shares).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import CURRENT_INSIDE, GraphNode
from ..scope import OwnerId, owned
from . import allowing, groups, insides
from .errors import GraphError
from .reading import nodes

#: What a canvas file says it is, and which shape it is in.
FORMAT = "pamphlets_canvas"
VERSION = 1
#: What a canvas file is called.
SUFFIX = ".pam"


def export_canvas(session: Session, node_pk: int, owner: OwnerId = None) -> dict[str, Any]:
    """A Canvas box, and everything inside it, as a file."""
    canvas = session.scalar(owned(select(GraphNode), GraphNode, owner).where(GraphNode.id == node_pk))
    if canvas is None or canvas.kind != "canvas":
        raise GraphError("Only a Canvas box is saved as a file: put what you want to hand on inside one.")
    carried = insides.everything_inside(nodes(session, owner), canvas.id)
    packed, wires = groups.pack_nodes(session, carried, 0, 0, owner)
    refs = {node.id: index for index, node in enumerate(carried)}
    for entry, node in zip(packed, carried):
        # Which canvas inside it this box is in: None for the canvas itself.
        held = node.inside_pk
        entry["inside"] = refs.get(held) if held is not None and held != canvas.id else None
    return {FORMAT: VERSION, "name": canvas.title, "nodes": packed, "wires": wires}


def is_canvas_file(payload: Any) -> bool:
    return isinstance(payload, dict) and FORMAT in payload


def _levels(entries: list[dict[str, Any]]) -> int:
    """How many canvases deep the file goes below its own canvas."""
    by_ref = {entry.get("ref"): entry for entry in entries}
    deepest = 0
    for entry in entries:
        if entry.get("kind") != "canvas":
            continue
        level, at, seen = 1, entry.get("inside"), set()
        while at is not None and at not in seen and at in by_ref:
            seen.add(at)
            level += 1
            at = by_ref[at].get("inside")
        deepest = max(deepest, level)
    return deepest


def import_canvas(
    session: Session, payload: Any, owner: OwnerId = None, *, x: int = 40, y: int = 40,
) -> GraphNode:
    """Load a canvas file as a new Canvas box, in the canvas being worked in."""
    if not is_canvas_file(payload):
        raise GraphError("That is not a Pamphlets canvas file.")
    if payload.get(FORMAT) != VERSION:
        raise GraphError(f"That canvas file is version {payload.get(FORMAT)!r}; this Pamphlets reads version {VERSION}.")
    entries = [entry for entry in payload.get("nodes") or [] if isinstance(entry, dict)]
    here = insides.current(session, owner)
    by_id = {node.id: node for node in nodes(session, owner)}
    if insides.depth(by_id, here) + 1 + _levels(entries) > insides.MOST_DEPTH:
        raise GraphError(f"Canvases go {insides.MOST_DEPTH} deep, and this file would go deeper here.")

    allowing.check_entries(session, here, entries, owner)
    canvas = insides.add_canvas(session, owner, label=str(payload.get("name") or "Canvas")[:120], x=x, y=y)
    made: dict[int, GraphNode] = {}
    # A canvas's boxes are made once the canvas they go in is: round again
    # while anything is still waiting for its canvas.
    waiting = entries
    while waiting:
        later = []
        for entry in waiting:
            inside = entry.get("inside")
            if inside is not None and inside not in made:
                later.append(entry)
                continue
            holder = canvas.id if inside is None else made[inside].id
            token = CURRENT_INSIDE.set(holder)
            try:
                node = groups.unpack(
                    session, entry, owner, at=(int(entry.get("x") or 0), int(entry.get("y") or 0)),
                )
                if node is not None:
                    node.inside_pk = holder
                    groups.apply(session, node, entry, owner)
                    made[int(entry.get("ref", -1))] = node
            finally:
                CURRENT_INSIDE.reset(token)
        if len(later) == len(waiting):
            break  # waiting on a canvas the file never makes
        waiting = later
    session.flush()
    groups.slot_and_wire(session, payload, made, owner)
    session.flush()
    return canvas
