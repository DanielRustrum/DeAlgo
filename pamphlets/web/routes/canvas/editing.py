"""Adding, moving, wiring, slotting and removing boxes."""

from __future__ import annotations

import json

from typing import TYPE_CHECKING

from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .... import sources
from ....db import session_scope
from ....models import (
    GraphEdge,
    GraphNode,
)
from ....plugins import registry
from ....services import graph as graph_service
from ....services import playlists as playlist_service
from ....services.scope import OwnerId, owned
from ...responses import owner_of

if TYPE_CHECKING:
    pass
from .payload import graph_payload

router = APIRouter()


@router.get("/api/graph")
def graph_state(request: Request) -> JSONResponse:
    """The whole canvas, for the browser to draw."""
    owner = owner_of(request)
    with session_scope() as session:
        return JSONResponse(graph_payload(session, owner))


@router.post("/graph/nodes/{node_pk}/move")
def graph_move(
    request: Request,
    node_pk: int,
    x: int = Form(0),
    y: int = Form(0),
    carries: str = Form(""),
) -> JSONResponse:
    """Where a node was dragged to.

    ``carries`` says this is a group, which moves everything it surrounds by
    the same amount — one call rather than one per node inside it, so a group
    of ten cannot half-move.
    """
    owner = owner_of(request)
    with session_scope() as session:
        if carries == "1":
            try:
                went = graph_service.move_group(session, node_pk, x, y, owner)
            except graph_service.GraphError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)
            return JSONResponse({"moved": True, "carried": len(went)})
        moved = graph_service.move(session, node_pk, x, y, owner)
    return JSONResponse({"moved": moved})


@router.post("/graph/connect")
def graph_connect(
    request: Request, source: int = Form(...), target: int = Form(...), carries: str = Form(""),
) -> JSONResponse:
    """Draw a wire from one box to another, if it is allowed."""
    owner = owner_of(request)
    with session_scope() as session:
        nodes = {node.id: node for node in graph_service.nodes(session, owner)}
        first, second = nodes.get(source), nodes.get(target)
        if first is None or second is None:
            return JSONResponse({"error": "That node is no longer there."}, status_code=404)
        try:
            graph_service.connect(session, first, second, owner, carries=carries or None)
        except graph_service.GraphError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(graph_payload(session, owner))


@router.post("/graph/disconnect")
def graph_disconnect(request: Request, wire: str = Form(...)) -> JSONResponse:
    """Take out one wire. There is only one kind of wire now."""
    owner = owner_of(request)
    with session_scope() as session:
        kind, _, rest = wire.partition(":")
        if kind == "edge" and rest.isdigit():
            graph_service.disconnect(session, int(rest), owner)
        return JSONResponse(graph_payload(session, owner))


def _picked(text: str) -> list[int]:
    """Box ids, as a form sends them: "3,7,12"."""
    return [int(one) for one in text.split(",") if one.strip().isdigit()]


@router.post("/graph/copy")
def graph_copy(request: Request, nodes: str = Form("")) -> JSONResponse:
    """The picked boxes, packed to be pasted — kept by the browser, so a copy
    can be pasted into another canvas, or after leaving the tab."""
    owner = owner_of(request)
    with session_scope() as session:
        try:
            clip = graph_service.clipboard.copy(session, _picked(nodes), owner)
        except graph_service.GraphError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse({"clip": clip, "count": sum(1 for one in clip["nodes"] if "under" not in one)})


@router.post("/graph/paste")
def graph_paste(
    request: Request, clip: str = Form(""), cut: str = Form(""), x: int = Form(40), y: int = Form(40),
) -> JSONResponse:
    """Paste here: what was copied, made again — or what was cut, moved."""
    owner = owner_of(request)
    copied_from: dict[int, int] = {}
    with session_scope() as session:
        try:
            if cut:
                placed = graph_service.clipboard.move(session, _picked(cut), owner, x=x, y=y)
            else:
                try:
                    given = json.loads(clip)
                except ValueError:
                    given = None
                placed = graph_service.clipboard.paste(session, given, owner, x=x, y=y, copied_from=copied_from)
        except graph_service.GraphError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        answer = graph_payload(session, owner)
        # What landed, for the browser to pick: the boxes, not their pieces.
        answer["pasted"] = [node.id for node in placed if node.attached_to is None]
        # Which box each copy is of, for an undo to put wires back.
        answer["made"] = {str(was): now for was, now in copied_from.items()}
        return JSONResponse(answer)


@router.post("/graph/nodes")
def graph_add_node(
    request: Request,
    kind: str = Form(...),
    title: str = Form(""),
    plugin_node: str = Form(""),
    source_kind: str = Form(""),
    attach_to: str = Form(""),
    side: str = Form("below"),
    x: int = Form(0),
    y: int = Form(0),
) -> JSONResponse:
    """Put a new box on the canvas wherever it was dropped.

    Every kind comes through here, because every kind is dragged out of the
    same palette. A channel box arrives empty and is told which channel it is
    afterwards; a feed box makes its feed at once, since a name is all one
    needs.
    """
    owner = owner_of(request)
    with session_scope() as session:
        refused: JSONResponse | None = None
        if kind == "source":
            refused = _add_source_box(session, owner, source_kind, x=x, y=y)
        elif kind == "feed":
            refused = _add_feed_box(session, owner, title, x=x, y=y)
        elif kind == "filter":
            graph_service.add_filter(session, owner, label=title.strip() or "Filter", x=x, y=y)
        elif kind == "sort":
            graph_service.add_sort(session, owner, label=title.strip(), x=x, y=y)
        elif kind in graph_service.STAMPS:
            graph_service.add_stamp(
                session, owner, kind=kind, marks=title.strip(), x=x, y=y
            )
        elif kind in graph_service.AUGMENTATIONS:
            refused = _add_piece_box(
                session, owner, kind, plugin_node, attach_to, side=side, x=x, y=y
            )
        elif kind in ("deposit", "withdraw"):
            graph_service.add_store(
                session, owner, kind=kind, repository=title.strip(), x=x, y=y
            )
        elif kind == "group":
            graph_service.add_group(session, owner, label=title.strip(), x=x, y=y)
        elif kind == "canvas":
            try:
                graph_service.add_canvas(session, owner, label=title.strip(), x=x, y=y)
            except graph_service.GraphError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)
        elif kind == "relay":
            graph_service.add_relay(session, owner, x=x, y=y)
        elif kind == "comment":
            graph_service.add_comment(session, owner, text=title, x=x, y=y)
        elif kind == "pamphlet":
            graph_service.add_pamphlet(session, owner, label=title.strip(), x=x, y=y)
        elif kind == "format":
            graph_service.add_format(session, owner, label=title.strip(), x=x, y=y)
        elif kind == "transform":
            graph_service.add_transform(session, owner, label=title.strip(), x=x, y=y)
        elif kind == "text":
            graph_service.add_text_box(session, owner, label=title.strip(), x=x, y=y)
        elif kind in graph_service.TRIGGER_KINDS:
            graph_service.add_trigger(
                session, owner, trigger_kind=kind, label=title.strip(), x=x, y=y
            )
        else:
            return JSONResponse({"error": f"There is no {kind} node."}, status_code=400)
        if refused is not None:
            return refused
        return JSONResponse(graph_payload(session, owner))


def _add_source_box(
    session: Session, owner: OwnerId, source_kind: str, *, x: int, y: int
) -> JSONResponse | None:
    """An empty source box of one kind, told which source it is afterwards."""
    wanted = source_kind.strip()
    if not wanted or wanted not in {known.name for known in sources.all_kinds()}:
        return JSONResponse(
            {"error": "There is no source of that kind. Its plugin may be off."},
            status_code=400,
        )
    graph_service.add_source(session, owner, source_kind=wanted, x=x, y=y)
    return None


def _add_feed_box(
    session: Session, owner: OwnerId, title: str, *, x: int, y: int
) -> JSONResponse | None:
    """A feed box makes its feed at once, since a name is all one needs."""
    try:
        playlist = playlist_service.create_generic(session, title.strip() or "New feed", owner)
    except playlist_service.PlaylistError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    graph_service.add_feed(session, playlist, owner, x=x, y=y)
    return None


def _add_piece_box(
    session: Session,
    owner: OwnerId,
    kind: str,
    plugin_node: str,
    attach_to: str,
    *,
    side: str = "below",
    x: int,
    y: int,
) -> JSONResponse | None:
    """A piece, slotted under whatever it was dropped on.

    Without a host it is a piece lying on the canvas, which is a thing you can
    pick up and put somewhere rather than a thing that was refused.
    """
    host = (
        session.scalar(
            owned(select(GraphNode), GraphNode, owner).where(GraphNode.id == int(attach_to))
        )
        if attach_to.strip().isdigit()
        else None
    )
    asked: dict[str, str] = {}
    ref = ""
    if kind == graph_service.RULE:
        box = registry.current().augmentation(plugin_node.strip())
        if box is None:
            return JSONResponse(
                {"error": "That condition's plugin is not loaded."},
                status_code=400,
            )
        ref = box.ref
        asked = {one.name: one.default for one in box.fields if one.default}
    try:
        graph_service.add_piece(
            session, owner, kind=kind, host=host, ref=ref, settings=asked, side=side, x=x, y=y,
        )
    except graph_service.GraphError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return None


@router.post("/graph/nodes/{node_pk}/attach")
def graph_attach(
    request: Request, node_pk: int, under: str = Form(""), side: str = Form("below"),
    x: str = Form(""), y: str = Form(""),
) -> JSONResponse:
    """Slot a piece that is already on the canvas into a box, or take it out.

    The other way a piece gets slotted in. Dragging one out of the palette
    onto a slot is the first; this is for the one already lying there, which
    otherwise could only be deleted and dragged out again.
    """
    owner = owner_of(request)
    with session_scope() as session:
        piece = session.scalar(
            owned(select(GraphNode), GraphNode, owner).where(GraphNode.id == node_pk)
        )
        if piece is None:
            return JSONResponse({"error": "That node is not here."}, status_code=404)

        wanted = under.strip()
        if not wanted:
            graph_service.detach(session, piece)
            # Taken out by being dragged off: it lies where it was let go.
            if x.lstrip("-").isdigit() and y.lstrip("-").isdigit():
                piece.x, piece.y = int(x), int(y)
            return JSONResponse(graph_payload(session, owner))

        host = session.scalar(
            owned(select(GraphNode), GraphNode, owner).where(GraphNode.id == int(wanted))
            if wanted.isdigit()
            else select(GraphNode).where(GraphNode.id == -1)
        )
        if host is None:
            return JSONResponse({"error": "That box is not here."}, status_code=404)
        try:
            graph_service.attach(session, piece, host, owner, side=side)
        except graph_service.GraphError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(graph_payload(session, owner))


@router.post("/graph/nodes/{node_pk}/resize")
def graph_resize(
    request: Request, node_pk: int, width: int = Form(0), height: int = Form(0)
) -> JSONResponse:
    """Resize a group box."""
    owner = owner_of(request)
    with session_scope() as session:
        return JSONResponse({"resized": graph_service.resize(session, node_pk, width, height, owner)})


@router.post("/graph/nodes/{node_pk}/fold")
def graph_fold(request: Request, node_pk: int, folded: str = Form("1")) -> JSONResponse:
    """Fold a group up to its name, or open it out. A lock holds where a
    group is, not whether it is folded: this works either way."""
    owner = owner_of(request)
    with session_scope() as session:
        node = session.scalar(owned(select(GraphNode), GraphNode, owner).where(GraphNode.id == node_pk))
        if node is None or node.kind != "group":
            return JSONResponse({"error": "Only a group folds."}, status_code=400)
        graph_service.looks.save(node, {"look_collapsed": "1" if folded == "1" else "0"})
        return JSONResponse(graph_payload(session, owner))


@router.post("/graph/wires/{edge_pk}/route")
def graph_route(request: Request, edge_pk: int, route: str = Form("curve")) -> JSONResponse:
    """Draw a wire another way: a curve, straight, square, or round the boxes."""
    owner = owner_of(request)
    with session_scope() as session:
        edge = session.scalar(owned(select(GraphEdge), GraphEdge, owner).where(GraphEdge.id == edge_pk))
        if edge is None:
            return JSONResponse({"error": "That wire is no longer there."}, status_code=404)
        try:
            graph_service.looks.set_route(edge, route)
        except graph_service.GraphError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(graph_payload(session, owner))


@router.post("/graph/nodes/{node_pk}/lock")
def graph_lock(request: Request, node_pk: int, locked: str = Form("1")) -> JSONResponse:
    """Hold a group in place, or let it go again."""
    owner = owner_of(request)
    with session_scope() as session:
        if not graph_service.lock(session, node_pk, locked == "1", owner):
            return JSONResponse({"error": "That is not a group."}, status_code=404)
        return JSONResponse(graph_payload(session, owner))


@router.post("/graph/nodes/{node_pk}/delete")
def graph_remove(request: Request, node_pk: int) -> JSONResponse:
    """Remove a box, and its channel or feed if no other box stands for it."""
    owner = owner_of(request)
    with session_scope() as session:
        try:
            gone = graph_service.remove(session, node_pk, owner)
        except graph_service.GraphError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        if not gone:
            return JSONResponse({"error": "That node is not here."}, status_code=404)
        return JSONResponse(graph_payload(session, owner))
