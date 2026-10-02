"""The whole graph as the canvas draws it."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from ....models import GraphNode
from ....services import channels as channel_service
from ....services import graph as graph_service
from ....services.scope import OwnerId
from ...templates import Context
from .facts import (
    asks_for,
    box_title,
    channel_facts,
    condition_facts,
    every_parts,
    every_words_for,
    feed_facts,
    how_polled,
    is_on,
    next_firing,
    orders,
    plugin_facts,
    store_facts,
)
from .notes import node_note


def graph_payload(session: Session, owner: OwnerId) -> Context:
    """The whole canvas as JSON: what the browser draws from."""
    canvas = _Canvas.read(session, owner)
    return {
        "nodes": [_node(node, canvas) for node in canvas.nodes],
        "wires": graph_service.wires(session, owner),
        # What is already watched, for a source node to be pointed at rather
        # than told again. Sent once for the whole canvas: every empty source
        # node offers the same list, narrowed in the browser to its own kind.
        "sources": [
            {
                "id": channel.id,
                "title": channel.title or channel.channel_id,
                "kind": channel.source_kind,
            }
            for channel in channel_service.list_channels(session, owner)
        ],
    }


@dataclass
class _Canvas:
    """Everything about the canvas that is read once and asked of many boxes."""

    nodes: list[GraphNode]
    plan: dict[int, list[graph_service.When]]
    facts: dict[int, Context]
    windows: dict[int, list[GraphNode]]
    #: Boxes whose reading window a piece under a feed opens.
    opening: set[int]
    #: What each empty source box is waiting to be told, worked out once per
    #: node because the title and the form both want it.
    asking: dict[int, Any]
    #: The same, for the two ends of a repository: the count is wanted on the
    #: box and in its panel, and counting it twice per box would be two
    #: queries each for one answer.
    stores: dict[int, Context]
    #: What is slotted under each box that reads pieces, since what those
    #: boxes do is whatever their pieces say. A Filter narrows by nothing at
    #: all until something is slotted under it.
    slotted: dict[int, list[GraphNode]]
    #: And what each piece is slotted into, since a Timer says an amount and
    #: the box it is in is what the amount means.
    hosts: dict[int, GraphNode | None]

    @classmethod
    def read(cls, session: Session, owner: OwnerId) -> _Canvas:
        """Read everything once for the whole canvas."""
        nodes, _ = graph_service.load(session, owner)
        windows = graph_service.consumption(session, owner)
        return cls(
            nodes=nodes,
            plan=graph_service.polling_plan(session, owner),
            facts=channel_facts(session, owner),
            windows=windows,
            opening={node.id for wired in windows.values() for node in wired},
            asking={node.id: asks_for(node) for node in nodes if node.kind == "source"},
            stores={
                node.id: store_facts(session, node, owner)
                for node in nodes
                if node.kind in ("deposit", "withdraw")
            },
            slotted={
                node.id: graph_service.pieces_under(nodes, node.id)
                for node in nodes
                if node.kind in graph_service.SLOTTED
            },
            hosts={
                node.id: graph_service.host_of(nodes, node)
                for node in nodes
                if node.kind in graph_service.AUGMENTATIONS
            },
        )


def _node(node: GraphNode, canvas: _Canvas) -> Context:
    """One box or piece, as the canvas draws it."""
    return {
        "id": node.id,
        "kind": node.kind,
        # An empty source box is named after the kind it was dragged out as —
        # "New Subreddit". Said here rather than on the model because the
        # pretty name is the plugin's and the model must be readable without
        # asking which plugins are loaded.
        "title": box_title(node, canvas.asking.get(node.id)),
        "x": node.x,
        "y": node.y,
        "detail": (
            f"/channels/{node.channel_pk}" if node.kind == "source" and node.channel_pk
            else f"/feeds/{node.playlist_pk}" if node.kind == "feed" and node.playlist_pk
            else None
        ),
        "note": node_note(
            node, canvas.opening, canvas.stores.get(node.id), canvas.slotted.get(node.id),
            canvas.hosts.get(node.id),
        ),
        "enabled": is_on(node),
        "size": _size(node),
        "polled": how_polled(node, canvas.plan) if node.kind == "source" else None,
        "plugin": plugin_facts(node) if node.kind == graph_service.RULE else None,
        "channel": canvas.facts.get(node.channel_pk or 0) if node.kind == "source" else None,
        # Which kind of somewhere an empty box is for, and what to type into
        # it. Sent per box rather than looked up in the browser, because the
        # palette is the only other place that knows and a second copy would
        # be a second thing to keep up.
        "asks": canvas.asking.get(node.id) if node.kind == "source" else None,
        "store": canvas.stores.get(node.id),
        "stamp": (
            {"marks": graph_service.tag_name(node.marks)}
            if node.kind in graph_service.STAMPS
            else None
        ),
        "piece": _piece(node),
        # A condition piece: what it narrows by, and how to ask for it. Sent
        # per piece rather than looked up in the browser, so the canvas has
        # one way of drawing every condition.
        "condition": condition_facts(node),
        "feed": (
            feed_facts(node, canvas.windows.get(node.playlist_pk or 0, []))
            if node.kind == "feed"
            else None
        ),
        "sort": _sort(node),
        "trigger": _trigger(node, canvas.opening),
    }


def _size(node: GraphNode) -> Context | None:
    """A group's size, or None for any other box."""
    if node.kind != "group":
        return None
    return {
        "width": node.width or graph_service.GROUP_SIZE[0],
        "height": node.height or graph_service.GROUP_SIZE[1],
    }


def _piece(node: GraphNode) -> Context | None:
    """An augmentation: what it is slotted under, and what it says.

    Drawn under its host rather than at its own position, so the canvas needs
    to know which box that is.
    """
    if node.kind not in graph_service.AUGMENTATIONS:
        return None
    return {
        "under": node.attached_to,
        "minutes": node.duration_minutes or graph_service.DEFAULT_DURATION_MINUTES,
        "cron": node.cron or graph_service.DEFAULT_CRON,
        "from": graph_service.clock_time(node.alive_from),
        "to": graph_service.clock_time(node.alive_to),
        # An amount and a unit, so a Timer can say days as readily as minutes
        # without anybody counting.
        "every": every_words_for(node),
        # Which boxes it may be slotted under, so dragging one already on the
        # canvas lights up the same places the palette promised and the drop
        # will accept.
        "hosts": ",".join(graph_service.hosts_for(node.kind, node.plugin_ref or "")),
    }


def _sort(node: GraphNode) -> Context | None:
    """What a Sort box orders by, and the keys it could order by; None if it orders nothing."""
    if not orders(node):
        return None
    return {
        "by": node.sort_by or graph_service.DEFAULT_SORT_BY,
        "desc": (node.sort_dir or "desc") == "desc",
        # Each key carries its own two ends, so the canvas can say "Longest
        # first" rather than "Most first".
        "keys": [
            {"name": name, "label": label, "first": first, "last": last}
            for name, label, first, last in graph_service.SORT_KEYS
        ],
    }


def _trigger(node: GraphNode, opening: set[int]) -> Context | None:
    """A trigger's schedule and next firing, or None for any other box."""
    if node.kind != "trigger":
        return None
    return {
        "kind": node.trigger_kind or "pulse",
        "every_minutes": node.every_minutes,
        # The same gap said as an amount and a unit, so the canvas can offer
        # "2 hours" rather than "120".
        "every": every_parts(node),
        "cron": node.cron,
        "next": next_firing(node),
        "duration": node.duration_minutes,
        # A trigger wired to a feed opens a window rather than setting
        # something off, and is asked different things.
        "opens": node.id in opening,
        "last_fired": node.last_fired_at.isoformat() if node.last_fired_at else None,
    }
