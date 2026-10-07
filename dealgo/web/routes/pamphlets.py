"""The Pamphlets tab: pages laid out on the canvas, by a Pamphlet box and its leaflets.

What is on a pamphlet is worked out when it is opened, the way the Feed page
is: a Feed leaflet shows what is in that feed now, a chart counts up to now.
Nothing is kept for a pamphlet but its layout, which is the canvas's.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db import get_settings, session_scope
from ...models import GraphNode, Playlist, utcnow
from ...services import graph as graph_service
from ...services import pamphlet_charts as charts
from ...services import playlists as playlist_service
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
    """Every pamphlet as a tile — or, with one chosen as the default, that one."""
    owner = owner_of(request)
    with session_scope() as session:
        found = _pamphlets(session, owner)
        chosen = get_settings(session, owner).default_pamphlet_pk
        if not all and chosen is not None and any(one.id == chosen for one in found):
            return redirect(f"/pamphlets/{chosen}")
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
    """Make this the pamphlet the tab opens on, or, if it already is, stop."""
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
            said = "The Pamphlets tab shows them all again."
        else:
            settings.default_pamphlet_pk = pamphlet.id
            said = f"The Pamphlets tab opens on “{pamphlet.title}”."
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
    elif node.kind == "leaflet-chart" and (shaping := _shaping(session, owner, node)) is not None:
        # A Format box wired in: its bars, from the JSON wired into it.
        box, source = shaping
        spec = graph_service.formatting.settings(box)
        shaped = graph_service.formatting.shape(
            graph_service.formatting.data_for(session, source) if source is not None else None, spec
        )
        shown["chart_label"] = box.title if box.label else graph_service.formatting.words(box)
        shown["bars"] = shaped.bars
        shown["top"] = graph_service.formatting.scale(shaped.bars)
        shown["across"] = shaped.across
        shown["format_error"] = shaped.error
    elif node.kind == "leaflet-chart":
        chart = str(said["chart"])
        shown["chart_label"] = dict(graph_service.leaflets.CHARTS).get(chart, "")
        if chart == "counts":
            shown["counts"] = stats_context(session, owner)
        else:
            bars = (
                charts.feeds_held(session, owner) if chart == "feeds-held"
                else charts.daily(session, owner, chart, int(said["days"]))
            )
            shown["bars"] = bars
            shown["top"] = charts.scale(bars)
            shown["across"] = chart != "feeds-held"
    return shown


def _feed(session: Session, owner: OwnerId, pk: Any) -> Playlist | None:
    if not isinstance(pk, int):
        return None
    return next((one for one in playlist_service.list_playlists(session, owner) if one.id == pk), None)


def _shaping(
    session: Session, owner: OwnerId, chart: GraphNode
) -> tuple[GraphNode, GraphNode | None] | None:
    """The Format box wired into a chart, and the source wired into that."""
    wired = graph_service.edges(session, owner)
    by_id = {node.id: node for node in graph_service.nodes(session, owner)}
    box = next(
        (by_id[edge.source_pk] for edge in wired
         if edge.target_pk == chart.id and by_id.get(edge.source_pk) is not None
         and by_id[edge.source_pk].kind == "format"),
        None,
    )
    if box is None:
        return None
    source = next(
        (by_id[edge.source_pk] for edge in wired
         if edge.target_pk == box.id and by_id.get(edge.source_pk) is not None
         and by_id[edge.source_pk].kind == "source"),
        None,
    )
    return box, source
