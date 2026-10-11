"""Copy, cut and paste on the canvas.

Copy then paste makes the boxes again, with their pieces and the wires
between them; a source or feed box is another box for the same channel or
feed. Cut then paste moves the boxes themselves, into this canvas or
another. Nothing cut is lost unless it is pasted somewhere it cannot go.
"""

from __future__ import annotations

import json

import pytest

from pamphlets.models import GraphNode
from pamphlets.services import graph
from tests.test_canvases import in_canvas
from tests.test_graph import build, canvas, narrow, node_for  # noqa: F401


def test_a_copy_pastes_as_new_boxes_with_their_pieces_and_wires(db):
    build(db, channels=("UCone",), feeds=("PLone",))
    with db.session_scope() as session:
        source, feed = node_for(session, "source", "UCone"), node_for(session, "feed", "PLone")
        keep = graph.add_filter(session, label="Keep", x=300, y=100)
        narrow(session, keep, "has-words", "cats")
        graph.connect(session, source, keep)
        graph.connect(session, keep, feed)
        clip = graph.clipboard.copy(session, [source.id, keep.id, feed.id])
        made = graph.clipboard.paste(session, json.loads(json.dumps(clip)), x=1000, y=1000)

        boxes = [node for node in made if node.attached_to is None]
        assert sorted(node.kind for node in boxes) == ["feed", "filter", "source"]
        # The same channel and feed: a second box for each, nothing new behind them.
        assert {node.channel_pk for node in boxes if node.kind == "source"} == {source.channel_pk}
        assert {node.playlist_pk for node in boxes if node.kind == "feed"} == {feed.playlist_pk}
        # The piece came under its copy, and the wires between the copies.
        new_filter = next(node for node in boxes if node.kind == "filter")
        assert [piece.kind for piece in made if piece.attached_to == new_filter.id] == ["has-words"]
        made_ids = {node.id for node in made}
        between = [w for w in graph.wires(session) if w["from"] in made_ids and w["to"] in made_ids]
        assert len(between) == 2
        # Placed from the top-left of what was copied.
        assert min(node.x for node in boxes) == 1000


def test_a_copied_group_comes_with_what_it_surrounds(db):
    build(db, channels=(), feeds=())
    with db.session_scope() as session:
        group = graph.add_group(session, label="G", x=0, y=0, width=500, height=300)
        graph.add_comment(session, text="Inside", x=40, y=40)
        made = graph.clipboard.paste(session, graph.clipboard.copy(session, [group.id]), x=700, y=0)
        assert sorted(node.kind for node in made) == ["comment", "group"]


def test_a_cut_moves_the_boxes_themselves_into_another_canvas(db):
    build(db, channels=("UCone",), feeds=("PLone",))
    with db.session_scope() as session:
        source, feed = node_for(session, "source", "UCone"), node_for(session, "feed", "PLone")
        keep = graph.add_filter(session, label="Keep", x=300, y=100)
        graph.connect(session, source, keep)
        graph.connect(session, keep, feed)
        room = graph.add_canvas(session, label="Room")
        with in_canvas(room.id):
            moved = graph.clipboard.move(session, [keep.id, feed.id], x=50, y=60)
        assert {node.id for node in moved} == {keep.id, feed.id}
        assert keep.inside_pk == room.id and feed.inside_pk == room.id
        # The wire between them came; the one from the source left behind went.
        wires = graph.wires(session)
        assert [(w["from"], w["to"]) for w in wires if w["to"] == keep.id] == []
        assert [(w["from"], w["to"]) for w in wires if w["from"] == keep.id] == [(keep.id, feed.id)]
        assert (min(keep.x, feed.x), min(keep.y, feed.y)) == (50, 60)

        # Within the one canvas, a cut and paste is only a move: wires stay.
        with in_canvas(room.id):
            graph.clipboard.move(session, [keep.id], x=400, y=400)
        assert any(w["from"] == keep.id for w in graph.wires(session))


def test_a_canvas_cannot_be_moved_inside_itself(db):
    build(db, channels=(), feeds=())
    with db.session_scope() as session:
        outer = graph.add_canvas(session, label="Outer")
        with in_canvas(outer.id):
            inner = graph.add_canvas(session, label="Inner")
        with in_canvas(inner.id), pytest.raises(graph.GraphError, match="inside itself"):
            graph.clipboard.move(session, [outer.id])


def test_the_canvas_copies_and_pastes_through_its_api(canvas, db):
    top = canvas.get("/api/graph").json()
    feed = next(node for node in top["nodes"] if node["kind"] == "feed")
    copied = canvas.post("/graph/copy", data={"nodes": str(feed["id"])}).json()
    assert copied["count"] == 1
    pasted = canvas.post("/graph/paste", data={"clip": json.dumps(copied["clip"]), "x": 600, "y": 400}).json()
    assert len(pasted["pasted"]) == 1 and pasted["pasted"][0] != feed["id"]
    assert sum(1 for node in pasted["nodes"] if node["kind"] == "feed") == 2

    moved = canvas.post("/graph/paste", data={"cut": str(feed["id"]), "x": 900, "y": 50}).json()
    assert moved["pasted"] == [feed["id"]]
    with db.session_scope() as session:
        assert (session.get(GraphNode, feed["id"]).x, session.get(GraphNode, feed["id"]).y) == (900, 50)
    assert canvas.post("/graph/paste", data={"clip": "nonsense"}).status_code == 400


def test_an_empty_source_box_copies_as_an_empty_box_of_its_kind(db):
    build(db, channels=(), feeds=())
    with db.session_scope() as session:
        empty = graph.add_source(session, source_kind="rest", x=10, y=10)
        made = graph.clipboard.paste(session, graph.clipboard.copy(session, [empty.id]), x=500, y=500)
        assert [(node.kind, node.channel_pk, node.source_kind) for node in made] == [("source", None, "rest")]
