"""The Pamphlets tab: pages laid out on the canvas, by a Pamphlet box and its leaflets.

What is on a pamphlet is worked out when it is opened, the way the Feed page
is: a Feed leaflet shows what is in that feed now, a chart counts up to now.
Nothing is kept for a pamphlet but its layout, which is the canvas's.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db import get_settings, session_scope
from ...models import GraphNode, Playlist, utcnow
from ...services import graph as graph_service
from ...services import charting
from ...services import pamphlet_charts as charts
from ...services import playlists as playlist_service
from ...services import writing
from ...services.playlists import shelf as shelf_service
from ...services.scope import OwnerId, owned
from ..contexts import stats_context
from ..responses import owner_of, redirect, render
from ..templates import Context
from .feed import _section

router = APIRouter()


def _pamphlets(session: Session, owner: OwnerId) -> list[GraphNode]:
    return list(session.scalars(
        owned(select(GraphNode), GraphNode, owner)
        .where(GraphNode.kind == "pamphlet")
        .order_by(GraphNode.label, GraphNode.id)
    ))


@router.get("/pamphlets", response_class=HTMLResponse)
def pamphlets_page(request: Request, all: str = "") -> Response:
    """Every pamphlet as a tile. Always the list: the default is the app's
    front page, at its bare address, so this tab is how to reach the rest."""
    owner = owner_of(request)
    with session_scope() as session:
        found = _pamphlets(session, owner)
        chosen = get_settings(session, owner).default_pamphlet_pk
        all_nodes = graph_service.nodes(session, owner)
        tiles = [
            {
                "node": one,
                "leaflets": sum(
                    1 for piece in graph_service.pieces_under(all_nodes, one.id)
                    if piece.kind in graph_service.LEAFLET_KINDS
                ),
                "default": one.id == chosen,
            }
            for one in found
        ]
        return render(request, "pamphlets.html", {"tiles": tiles})


@router.get("/pamphlets/{node_pk}", response_class=HTMLResponse)
def pamphlet_page(request: Request, node_pk: int) -> Response:
    """One pamphlet, laid out as its leaflets are on the canvas."""
    owner = owner_of(request)
    with session_scope() as session:
        pamphlet = session.scalar(
            owned(select(GraphNode), GraphNode, owner)
            .where(GraphNode.id == node_pk, GraphNode.kind == "pamphlet")
        )
        if pamphlet is None:
            return redirect("/pamphlets", err="That pamphlet is not here.")
        return show_pamphlet(request, session, owner, pamphlet)


def default_pamphlet(session: Session, owner: OwnerId) -> GraphNode | None:
    """The pamphlet the app opens on, if one is chosen and still there."""
    chosen = get_settings(session, owner).default_pamphlet_pk
    if chosen is None:
        return None
    return session.scalar(
        owned(select(GraphNode), GraphNode, owner)
        .where(GraphNode.id == chosen, GraphNode.kind == "pamphlet")
    )


def show_pamphlet(request: Request, session: Session, owner: OwnerId, pamphlet: GraphNode) -> Response:
    """A pamphlet's page — at its own address, or at the front door."""
    rows = graph_service.leaflets.layout(graph_service.nodes(session, owner), pamphlet)
    shown: dict[int, Context] = {}
    _fill(session, owner, rows, shown)
    return render(request, "pamphlet.html", {
        "pamphlet": pamphlet,
        "rows": rows,
        "shown": shown,
        "is_default": get_settings(session, owner).default_pamphlet_pk == pamphlet.id,
        "others": len(_pamphlets(session, owner)) > 1,
        # The dateline, as a paper prints it.
        "today": utcnow().strftime("%A %-d %B %Y"),
        "waiting": sum(
            one["tile"].waiting if one.get("tile") else len(one.get("videos") or [])
            for one in shown.values()
        ),
    })


@router.post("/pamphlets/{node_pk}/default")
def choose_default(request: Request, node_pk: int) -> Response:
    """Make this the pamphlet the app opens on — at its bare address, and on
    the Pamphlets tab — or, if it already is, stop."""
    owner = owner_of(request)
    with session_scope() as session:
        pamphlet = session.scalar(
            owned(select(GraphNode), GraphNode, owner)
            .where(GraphNode.id == node_pk, GraphNode.kind == "pamphlet")
        )
        if pamphlet is None:
            return redirect("/pamphlets", err="That pamphlet is not here.")
        settings = get_settings(session, owner)
        if settings.default_pamphlet_pk == pamphlet.id:
            settings.default_pamphlet_pk = None
            said = "No pamphlet opens first now: the app opens on the list of them."
        else:
            settings.default_pamphlet_pk = pamphlet.id
            said = f"The app opens on “{pamphlet.title}”."
    return redirect(f"/pamphlets/{node_pk}", ok=said)


def _fill(
    session: Session, owner: OwnerId, row: list[graph_service.leaflets.Column],
    shown: dict[int, Context],
) -> None:
    """What every leaflet in a row shows, and every row below them."""
    for column in row:
        shown[column.leaflet.id] = _leaflet(session, owner, column.leaflet)
        _fill(session, owner, column.below, shown)


def _leaflet(session: Session, owner: OwnerId, node: GraphNode) -> Context:
    said: dict[str, Any] = graph_service.leaflets.settings(node)
    shown: Context = {"kind": node.kind, "on": node.enabled, **said}
    if node.kind == "leaflet-text":
        box = _writer(session, owner, node)
        if box is not None:
            # What a Text box last wrote, under the leaflet's own heading or
            # the box's name. Never written here: a page does not wait on a model.
            shown["heading"] = said.get("heading") or (box.title if box.label else "")
            shown["blocks"] = writing.blocks(box.written or "")
            shown["written_at"] = box.written_at
            shown["writing_error"] = writing.last_error(box)
        return shown
    if node.kind in ("leaflet-feed", "leaflet-link"):
        feed = _feed(session, owner, said.get("feed"))
        shown["playlist"] = feed
        if node.kind == "leaflet-feed" and feed is not None and said.get("shape") == "tile":
            shown["tile"] = shelf_service.tile_for(session, feed, owner)
        elif node.kind == "leaflet-feed" and feed is not None:
            windows = graph_service.consumption(session, owner)
            section = _section(
                session, feed, owner, windows.get(feed.id, []), now=utcnow(), sitting=False
            )
            shown["section"] = section
            shown["videos"] = section["videos"][: int(said["count"])]
    elif node.kind == "leaflet-chart":
        label, chart, counts = chart_for(session, owner, node, said)
        shown["chart_label"] = label
        shown["chart"] = chart
        if counts is not None:
            shown["counts"] = counts
    return shown


def _feed(session: Session, owner: OwnerId, pk: Any) -> Playlist | None:
    if not isinstance(pk, int):
        return None
    return next((one for one in playlist_service.list_playlists(session, owner) if one.id == pk), None)


def chart_for(
    session: Session, owner: OwnerId, node: GraphNode, said: Mapping[str, Any]
) -> tuple[str, charting.Chart | None, Context | None]:
    """A Chart leaflet's heading and chart, as its settings `said` say.

    With data wired in, the leaflet organises it — or, from a Format box,
    draws the bars that box shaped. With nothing wired in, one of the
    built-in counts. `said` is passed rather than read, so the canvas can
    preview settings not yet saved.
    """
    box = wired_into(session, owner, node)
    title = str(said.get("title") or "")
    kind = str(said.get("kind") or "column")
    if box is not None and box.kind == "format":
        spec = graph_service.formatting.settings(box)
        shaped = graph_service.formatting.shape(
            graph_service.formatting.data_into(session, box, owner), spec
        )
        chart = charting.from_bars(shaped.bars, kind, graph_service.formatting.words(box))
        chart.error = shaped.error if not shaped.bars else ""
        return title or (box.title if box.label else graph_service.formatting.words(box)), chart, None
    if box is not None:
        chart = charting.from_data(graph_service.formatting.data_out(session, box, owner), said)
        named = box.title if box.label and box.kind == "transform" else charting.words(said)
        return title or named, chart, None

    built = str(said.get("chart") or "watched-daily")
    named = title or dict(graph_service.leaflets.CHARTS).get(built, "")
    if built == "counts":
        return named, None, stats_context(session, owner)
    bars = (
        charts.feeds_held(session, owner) if built == "feeds-held"
        else charts.daily(session, owner, built, int(said.get("days") or 14))
    )
    if built == "feeds-held":
        return named, charting.from_bars(bars, kind, "waiting", "waiting"), None
    return named, charting.from_bars(bars, kind), None


def wired_into(session: Session, owner: OwnerId, chart: GraphNode) -> GraphNode | None:
    """What a Chart leaflet's data wire comes from, if anything."""
    for edge in graph_service.edges(session, owner, every=True):
        if edge.target_pk == chart.id and edge.carries == "data":
            return session.get(GraphNode, edge.source_pk)
    return None


def _writer(session: Session, owner: OwnerId, leaflet: GraphNode) -> GraphNode | None:
    """The Text box wired into a Text leaflet, if any."""
    for edge in graph_service.edges(session, owner, every=True):
        if edge.target_pk == leaflet.id and edge.carries == "page":
            box = session.get(GraphNode, edge.source_pk)
            if box is not None and box.kind == "text":
                return box
    return None
