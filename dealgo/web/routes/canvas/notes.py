"""The sentence under each box that says what it is doing."""

from __future__ import annotations

from .... import sources
from ....models import (
    GraphNode,
)
from ....plugins import registry
from ....services import graph as graph_service
from ...templates import Context
from .facts import orders


def node_note(
    node: GraphNode,
    opening: set[int] | None = None,
    store: Context | None = None,
    pieces: list[GraphNode] | None = None,
    host: GraphNode | None = None,
) -> str:
    """The line under the title: what this box is, in a few words."""
    if node.kind == "group":
        return "drag it to move everything in it"
    if node.kind == graph_service.RULE:
        return _rule_note(node)
    if node.kind in graph_service.AUGMENTATIONS:
        if node.attached_to is None:
            return "drop it on a box to slot it in"
        return graph_service.piece_note(node, host)
    if node.kind == "filter":
        return _filter_note(pieces or [])
    if node.kind == "sort":
        return _sort_note(pieces or [])
    if node.kind in graph_service.STAMPS:
        return graph_service.stamp_words(node, pieces or [])
    if node.kind in ("deposit", "withdraw"):
        return _store_note(node, store or {})
    if node.kind == "trigger":
        return _trigger_note(node, opening)
    if node.kind == "source":
        return _source_note(node)
    if node.kind == "feed":
        return _feed_note(node)
    count = len(node.overrides)
    return f"{count} rule{'s' if count != 1 else ''}" if count else "passes everything"


def _rule_note(node: GraphNode) -> str:
    """A condition a plugin declared. Its own words, since the host has none
    for it — it is the plugin that knows what it asks."""
    box = registry.current().augmentation(node.plugin_ref or "")
    if box is None:
        return "its plugin is switched off — it narrows nothing"
    return box.blurb or f"from {box.plugin}"


def _filter_note(pieces: list[GraphNode]) -> str:
    """Every condition under it, the app's own said in its own words and a
    plugin's said by the name that plugin gave it."""
    said: list[str] = []
    for one in pieces:
        if not one.enabled:
            continue
        if one.kind in graph_service.CONDITION_KINDS:
            said.append(graph_service.condition_words(one))
        elif one.kind == graph_service.RULE:
            said.append(one.title.lower())
    return " · ".join(said) if said else "slot a condition under it"


def _sort_note(pieces: list[GraphNode]) -> str:
    ordering = next((one for one in pieces if one.enabled and orders(one)), None)
    if ordering is None:
        return "slot an Order under it"
    if ordering.kind == graph_service.RULE:
        # A plugin's ordering works its own number out, so there is no key to
        # name — only which end of it comes first. Named by the plugin's own
        # label, which is the plugin's to choose.
        found = registry.current().augmentation(ordering.plugin_ref or "")
        named = (found.label if found is not None else ordering.title).lower()
        way = "first" if (ordering.sort_dir or "desc") == "desc" else "last"
        return f"{named} {way}"
    return graph_service.condition_words(ordering)


def _store_note(node: GraphNode, store: Context) -> str:
    name = str(store.get("name") or "")
    if not name:
        return "open it and give it a name"
    held = int(store.get("waiting") or 0)
    if node.kind == "deposit":
        return f"{held} waiting in {name}"
    how = "all of it" if not node.takes else f"{node.takes} at a time"
    return f"pulls {how} from {name}"


def _trigger_note(node: GraphNode, opening: set[int] | None) -> str:
    # Wired to a feed it opens a window, which is a different sentence from
    # the one about setting a channel off.
    if opening is not None and node.id in opening:
        return graph_service.window_words(node)
    if node.trigger_kind == "schedule":
        return node.cron or graph_service.DEFAULT_CRON
    every = node.every_minutes or graph_service.DEFAULT_EVERY_MINUTES
    return f"every {graph_service.every_words(every)}"


def _source_note(node: GraphNode) -> str:
    channel = node.channel
    if channel is None:
        return "open it and say where to watch"
    if not channel.is_youtube:
        # Nowhere else splits what it publishes into four kinds, so the line
        # says where it comes from, which is the useful fact instead.
        return f"everything from {sources.describe(channel.source_kind).label}"
    takes = [
        word
        for word, off in (("videos", channel.skip_videos), ("shorts", channel.skip_shorts),
                          ("live", channel.skip_live), ("posts", channel.skip_posts))
        if not off
    ]
    return "takes " + (", ".join(takes) if takes else "nothing")


def _feed_note(node: GraphNode) -> str:
    playlist = node.playlist
    if playlist is None:
        return "feed is gone"
    return "generic" if playlist.is_generic else "YouTube playlist"
