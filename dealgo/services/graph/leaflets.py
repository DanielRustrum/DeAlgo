"""Leaflets: the blocks a Pamphlet box lays its page out from.

A Pamphlet box is a page of its own, shown under the Pamphlets tab. What is
on it is whatever leaflets are slotted under it, and where each sits on the
page is where it sits on the canvas:

* A leaflet **below** another is the next thing down that column.
* A leaflet **beside** another starts the next column to its right.

So a Text leaflet under the box with two Feed leaflets side by side under it
is a heading across the page over two columns of cards. What the canvas
shows is the page; nothing else decides the layout.

Each kind keeps its few settings as JSON in one column (`GraphNode.leaflet`),
read and written only here.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from ...models import GraphNode
from .errors import GraphError

LEAFLET_KINDS: tuple[str, ...] = ("leaflet-feed", "leaflet-chart", "leaflet-text", "leaflet-link")

#: The two edges a leaflet can hang from.
SIDES = ("below", "beside")

#: What a Chart leaflet can draw: its name, and what it is called.
CHARTS: tuple[tuple[str, str], ...] = (
    ("watched-daily", "Watched each day"),
    ("arrived-daily", "Arrived each day"),
    ("filtered-daily", "Filtered out each day"),
    ("feeds-held", "What each feed holds"),
    ("counts", "The counts"),
)

#: Where a Link leaflet can go.
GOES: tuple[tuple[str, str], ...] = (
    ("focus", "Focus on a feed"),
    ("feed", "Open a feed"),
    ("url", "An address"),
)

#: How a Feed leaflet shows its feed: as stories, or as one tile like the shelf's.
SHAPES: tuple[tuple[str, str], ...] = (
    ("stories", "Stories"),
    ("tile", "A tile"),
)

#: The most a Feed leaflet shows, and the most days a chart covers.
MOST_ITEMS = 60
MOST_DAYS = 90

DEFAULTS: dict[str, dict[str, Any]] = {
    "leaflet-feed": {"title": "", "feed": None, "count": 8, "shape": "stories"},
    "leaflet-chart": {"title": "", "chart": "watched-daily", "days": 14},
    "leaflet-text": {"heading": "", "body": ""},
    "leaflet-link": {"label": "", "goes": "focus", "feed": None, "url": ""},
}


def is_leaflet(node: GraphNode) -> bool:
    return node.kind in LEAFLET_KINDS


def side_of(node: GraphNode) -> str:
    """Which edge a piece hangs from: only a leaflet ever hangs beside."""
    return "beside" if node.attached_side == "beside" else "below"


def settings(node: GraphNode) -> dict[str, Any]:
    """What this leaflet is set to, every setting its kind has filled in."""
    said: dict[str, Any] = dict(DEFAULTS.get(node.kind, {}))
    try:
        stored = json.loads(node.leaflet or "{}")
    except ValueError:
        stored = {}
    if isinstance(stored, dict):
        said.update({key: value for key, value in stored.items() if key in said})
    return said


def save(node: GraphNode, form: Mapping[str, str], feeds: set[int]) -> None:
    """Set a leaflet from the panel's fields, `leaflet_<setting>` each.

    `feeds` is every feed the account has, so a leaflet cannot be pointed at
    somebody else's. Raises `GraphError`, in words, for anything it cannot
    take; a field left out is left as it was.
    """
    said = settings(node)

    def given(name: str) -> str | None:
        value = form.get(f"leaflet_{name}")
        return None if value is None else str(value).strip()

    def number(name: str, least: int, most: int) -> None:
        value = given(name)
        if value is None or value == "":
            return
        if not value.isdigit():
            raise GraphError("That has to be a whole number.")
        said[name] = max(least, min(most, int(value)))

    def feed() -> None:
        value = given("feed")
        if value is None:
            return
        if value == "":
            said["feed"] = None
        elif value.isdigit() and int(value) in feeds:
            said["feed"] = int(value)
        else:
            raise GraphError("That feed is not one of yours.")

    def title() -> None:
        value = given("title")
        if value is not None:
            said["title"] = value[:120]

    if node.kind == "leaflet-feed":
        title()
        feed()
        number("count", 1, MOST_ITEMS)
        shape = given("shape")
        if shape is not None:
            if shape not in dict(SHAPES):
                raise GraphError("A feed shows as stories or as a tile.")
            said["shape"] = shape
    elif node.kind == "leaflet-chart":
        title()
        chart = given("chart")
        if chart is not None:
            if chart not in dict(CHARTS):
                raise GraphError("There is no chart of that kind.")
            said["chart"] = chart
        number("days", 2, MOST_DAYS)
    elif node.kind == "leaflet-text":
        if given("heading") is not None:
            said["heading"] = str(given("heading"))[:200]
        if given("body") is not None:
            said["body"] = str(given("body"))[:5000]
    elif node.kind == "leaflet-link":
        if given("label") is not None:
            said["label"] = str(given("label"))[:120]
        goes = given("goes")
        if goes is not None:
            if goes not in dict(GOES):
                raise GraphError("A link goes to a feed, Focus, or an address.")
            said["goes"] = goes
        feed()
        url = given("url")
        if url is not None:
            if url and urlparse(url).scheme not in ("http", "https"):
                raise GraphError("An address starts with http:// or https://.")
            said["url"] = url[:2000]
    else:
        raise GraphError(f"A {node.kind} box is not a leaflet.")
    node.leaflet = json.dumps(said, sort_keys=True)


def point_at(node: GraphNode, playlist_pk: int | None) -> None:
    """Show this feed — or none — as the wire into the leaflet says."""
    said = settings(node)
    said["feed"] = playlist_pk
    node.leaflet = json.dumps(said, sort_keys=True)


def words(node: GraphNode, feed_titles: Mapping[int, str]) -> str:
    """What a leaflet shows, said on the canvas."""
    said = settings(node)

    def feed_named() -> str:
        if said.get("feed") is None:
            return ""
        return feed_titles.get(int(said["feed"]), "a feed that has gone")

    if node.kind == "leaflet-feed":
        named = feed_named()
        if not named:
            return "wire a feed into it"
        return f"“{named}” as a tile" if said["shape"] == "tile" else f"{said['count']} from “{named}”"
    if node.kind == "leaflet-chart":
        chart = dict(CHARTS).get(str(said["chart"]), "a chart")
        daily = str(said["chart"]).endswith("-daily")
        return f"{chart}, {said['days']} days" if daily else chart
    if node.kind == "leaflet-text":
        heading = str(said["heading"]).strip()
        body = str(said["body"]).strip()
        if heading:
            return heading
        return (body[:40] + "…") if len(body) > 40 else (body or "open it and write something")
    if node.kind == "leaflet-link":
        goes = str(said["goes"])
        if goes == "url":
            return str(said["url"]) or "open it and give an address"
        named = feed_named()
        if goes == "focus":
            return f"Focus on “{named}”" if named else "Focus on everything"
        return f"open “{named}”" if named else "wire a feed into it"
    return ""


@dataclass
class Column:
    """One leaflet, and what hangs below it in its column: a row of its own,
    which is how a column can split into columns again."""

    leaflet: GraphNode
    below: list[Column] = field(default_factory=list)


def layout(all_nodes: list[GraphNode], pamphlet: GraphNode) -> list[Column]:
    """The page a Pamphlet box lays out, as the row at its top."""
    hanging: dict[tuple[int, str], GraphNode] = {}
    for node in sorted(all_nodes, key=lambda one: one.id):
        if is_leaflet(node) and node.attached_to is not None:
            hanging.setdefault((node.attached_to, side_of(node)), node)
    seen: set[int] = set()

    def row(first: GraphNode | None) -> list[Column]:
        columns: list[Column] = []
        walk = first
        while walk is not None and walk.id not in seen:
            seen.add(walk.id)
            column = Column(walk)
            columns.append(column)
            column.below = row(hanging.get((walk.id, "below")))
            walk = hanging.get((walk.id, "beside"))
        return columns

    return row(hanging.get((pamphlet.id, "below")))
