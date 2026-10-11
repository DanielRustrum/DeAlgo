"""Reading the canvas: its boxes, its wires, and the channel behind a source box."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ...models import (
    Channel,
    GraphEdge,
    GraphNode,
)
from ..scope import OwnerId, owned


def channels_of(session: Session, node: GraphNode, owner: OwnerId = None) -> list[Channel]:
    """Which channel a source node stands for, if it stands for one yet.

    A list rather than one, because every caller walks it and an empty box
    standing for nothing is the ordinary case rather than an error.
    """
    if node.kind != "source":
        return []
    return [node.channel] if node.channel is not None else []


def nodes(session: Session, owner: OwnerId = None) -> list[GraphNode]:
    """Every box and piece on the account's canvas, with channels and feeds loaded."""
    return list(
        session.scalars(
            owned(select(GraphNode), GraphNode, owner)
            .options(selectinload(GraphNode.channel), selectinload(GraphNode.playlist))
            .order_by(GraphNode.id)
        )
    )


#: The wires that are paths: items, and the signals that start them. Data
#: and page wires are drawn and kept, but nothing is routed down them.
FLOW = ("content", "signal")


def edges(
    session: Session, owner: OwnerId = None, *, every: bool = False, raw: bool = False,
) -> list[GraphEdge]:
    """The wires on the account's canvas that are paths — or, with `every`,
    every wire, data and page wires among them.

    Relays are seen through: a wire into a Relay and on out of it is one wire,
    from where it starts to where it ends, carrying what went in. Only the
    canvas, drawing them, asks for the wires as drawn (`raw`)."""
    found = list(session.scalars(owned(select(GraphEdge), GraphEdge, owner).order_by(GraphEdge.id)))
    if not raw:
        relays = set(session.scalars(
            owned(select(GraphNode.id), GraphNode, owner).where(GraphNode.kind == "relay")
        ))
        found = through_relays(found, relays)
    if not every:
        found = [edge for edge in found if edge.carries in FLOW]
    return found


def through_relays(found: list[GraphEdge], relays: set[int]) -> list[GraphEdge]:
    """The wires with every Relay taken out of the middle of them: each wire
    into a relay followed on, through any relays after it, to every box it
    reaches. A relay nothing is wired into passes nothing on; a ring of relays
    goes nowhere. What comes out is new wires, never saved — each keeps the
    first wire's id, for ordering, and what it carries."""
    if not relays:
        return found
    onward: dict[int, list[GraphEdge]] = {}
    for edge in found:
        onward.setdefault(edge.source_pk, []).append(edge)
    seen_through: list[GraphEdge] = []
    for edge in found:
        if edge.source_pk in relays:
            continue
        if edge.target_pk not in relays:
            seen_through.append(edge)
            continue
        waiting = [(edge.target_pk, {edge.target_pk})]
        while waiting:
            relay, passed = waiting.pop()
            for nxt in onward.get(relay, []):
                if nxt.target_pk in relays:
                    if nxt.target_pk not in passed:
                        waiting.append((nxt.target_pk, passed | {nxt.target_pk}))
                    continue
                seen_through.append(GraphEdge(
                    id=edge.id, owner_pk=edge.owner_pk, source_pk=edge.source_pk,
                    target_pk=nxt.target_pk, carries=edge.carries,
                ))
    return sorted(seen_through, key=lambda one: one.id)
