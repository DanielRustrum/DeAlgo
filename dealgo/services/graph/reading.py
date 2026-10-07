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


def edges(session: Session, owner: OwnerId = None, *, every: bool = False) -> list[GraphEdge]:
    """The wires on the account's canvas that are paths — or, with `every`,
    every wire, data and page wires among them."""
    statement = owned(select(GraphEdge), GraphEdge, owner).order_by(GraphEdge.id)
    if not every:
        statement = statement.where(GraphEdge.carries.in_(FLOW))
    return list(session.scalars(statement))
