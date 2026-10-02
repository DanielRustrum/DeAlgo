"""The whole graph as the canvas draws it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from ....services import channels as channel_service
from ....services import graph as graph_service
from ....services.scope import OwnerId

if TYPE_CHECKING:
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
    nodes, _ = graph_service.load(session, owner)
    plan = graph_service.polling_plan(session, owner)
    facts = channel_facts(session, owner)
    windows = graph_service.consumption(session, owner)
    opening = {node.id for wired in windows.values() for node in wired}
    # What each empty source box is waiting to be told, worked out once per
    # node because the title and the form both want it.
    asking = {
        node.id: asks_for(node) for node in nodes if node.kind == "source"
    }
    # The same, for the two ends of a repository: the count is wanted on the
    # box and in its panel, and counting it twice per box would be two
    # queries each for one answer.
    stores = {
        node.id: store_facts(session, node, owner)
        for node in nodes
        if node.kind in ("deposit", "withdraw")
    }
    # What is slotted under each box that reads pieces, since what those
    # boxes do is whatever their pieces say. A Filter narrows by nothing at
    # all until something is slotted under it.
    slotted = {
        node.id: graph_service.pieces_under(nodes, node.id)
        for node in nodes
        if node.kind in graph_service.SLOTTED
    }
    # And what each piece is slotted into, since a Timer says an amount and
    # the box it is in is what the amount means.
    hosts = {
        node.id: graph_service.host_of(nodes, node)
        for node in nodes
        if node.kind in graph_service.AUGMENTATIONS
    }
    return {
        "nodes": [
            {
                "id": node.id,
                "kind": node.kind,
                # An empty source box is named after the kind it was dragged
                # out as — "New Subreddit". Said here rather than on the model
                # because the pretty name is the plugin's and the model must
                # be readable without asking which plugins are loaded.
                "title": box_title(node, asking.get(node.id)),
                "x": node.x,
                "y": node.y,
                "detail": (
                    f"/channels/{node.channel_pk}" if node.kind == "source" and node.channel_pk
                    else f"/feeds/{node.playlist_pk}" if node.kind == "feed" and node.playlist_pk
                    else None
                ),
                "note": node_note(
                    node, opening, stores.get(node.id), slotted.get(node.id),
                    hosts.get(node.id),
                ),
                "enabled": is_on(node),
                "size": (
                    None
                    if node.kind != "group"
                    else {
                        "width": node.width or graph_service.GROUP_SIZE[0],
                        "height": node.height or graph_service.GROUP_SIZE[1],
                    }
                ),
                "polled": how_polled(node, plan) if node.kind == "source" else None,
                "plugin": (
                    plugin_facts(node) if node.kind == graph_service.RULE else None
                ),
                "channel": facts.get(node.channel_pk or 0) if node.kind == "source" else None,
                # Which kind of somewhere an empty box is for, and what to
                # type into it. Sent per box rather than looked up in the
                # browser, because the palette is the only other place that
                # knows and a second copy would be a second thing to keep up.
                "asks": asking.get(node.id) if node.kind == "source" else None,
                "store": stores.get(node.id),
                "stamp": (
                    {"marks": graph_service.tag_name(node.marks)}
                    if node.kind in graph_service.STAMPS
                    else None
                ),
                # An augmentation: what it is slotted under, and what it says.
                # Drawn under its host rather than at its own position, so the
                # canvas needs to know which box that is.
                "piece": (
                    {
                        "under": node.attached_to,
                        "minutes": node.duration_minutes or graph_service.DEFAULT_DURATION_MINUTES,
                        "cron": node.cron or graph_service.DEFAULT_CRON,
                        "from": graph_service.clock_time(node.alive_from),
                        "to": graph_service.clock_time(node.alive_to),
                        # An amount and a unit, so a Timer can say days as
                        # readily as minutes without anybody counting.
                        "every": every_words_for(node),
                        # Which boxes it may be slotted under, so dragging one
                        # already on the canvas lights up the same places the
                        # palette promised and the drop will accept.
                        "hosts": ",".join(
                            graph_service.hosts_for(node.kind, node.plugin_ref or "")
                        ),
                    }
                    if node.kind in graph_service.AUGMENTATIONS
                    else None
                ),
                # A condition piece: what it narrows by, and how to ask for
                # it. Sent per piece rather than looked up in the browser,
                # so the canvas has one way of drawing every condition.
                "condition": condition_facts(node),
                "feed": (
                    feed_facts(node, windows.get(node.playlist_pk or 0, []))
                    if node.kind == "feed"
                    else None
                ),
                "sort": (
                    None
                    if not orders(node)
                    else {
                        "by": node.sort_by or graph_service.DEFAULT_SORT_BY,
                        "desc": (node.sort_dir or "desc") == "desc",
                        # Each key carries its own two ends, so the canvas
                        # can say "Longest first" rather than "Most first".
                        "keys": [
                            {"name": name, "label": label, "first": first, "last": last}
                            for name, label, first, last in graph_service.SORT_KEYS
                        ],
                    }
                ),
                "trigger": (
                    None
                    if node.kind != "trigger"
                    else {
                        "kind": node.trigger_kind or "pulse",
                        "every_minutes": node.every_minutes,
                        # The same gap said as an amount and a unit, so the
                        # canvas can offer "2 hours" rather than "120".
                        "every": every_parts(node),
                        "cron": node.cron,
                        "next": next_firing(node),
                        "duration": node.duration_minutes,
                        # A trigger wired to a feed opens a window rather than
                        # setting something off, and is asked different things.
                        "opens": node.id in opening,
                        "last_fired": node.last_fired_at.isoformat() if node.last_fired_at else None,
                    }
                ),
            }
            for node in nodes
        ],
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
