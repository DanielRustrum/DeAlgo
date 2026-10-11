"""How layout looks: wires drawn four ways, relays facing any way, groups
in the theme's colours and folded up — and a Canvas box saved as a .pam
file with all of it inside."""

from __future__ import annotations

import json

import pytest

from pamphlets.models import GraphEdge, GraphNode
from pamphlets.services import graph
from pamphlets.services.graph import canvas_files, looks
from tests.test_canvases import in_canvas
from tests.test_graph import build, canvas, only  # noqa: F401


def test_a_wire_is_drawn_the_way_it_was_told(canvas, db):
    with db.session_scope() as session:
        one, two = graph.add_filter(session), graph.add_filter(session)
        edge = graph.connect(session, one, two)
        edge_pk = edge.id
    drawn = canvas.post(f"/graph/wires/{edge_pk}/route", data={"route": "astar"}).json()
    assert next(w for w in drawn["wires"] if w["id"] == f"edge:{edge_pk}")["route"] == "astar"
    canvas.post(f"/graph/wires/{edge_pk}/route", data={"route": "curve"})
    with db.session_scope() as session:
        assert session.get(GraphEdge, edge_pk).route is None  # the usual way is no way at all
    assert canvas.post(f"/graph/wires/{edge_pk}/route", data={"route": "zigzag"}).status_code == 400


def test_a_relay_faces_any_way(canvas):
    relay = only(canvas.post("/graph/nodes", data={"kind": "relay"}).json(), "relay")
    assert relay["relay"]["faces"] == "right"
    saved = canvas.post(f"/graph/nodes/{relay['id']}", data={"label": "", "look_faces": "down"}).json()
    assert only(saved, "relay")["relay"]["faces"] == "down"
    assert canvas.post(f"/graph/nodes/{relay['id']}", data={"look_faces": "sideways"}).status_code == 400


def test_a_group_has_a_colour_and_folds_locked_or_not(canvas):
    group = only(canvas.post("/graph/nodes", data={"kind": "group"}).json(), "group")
    assert group["look"]["colour"] == "paper" and group["look"]["collapsed"] is False
    saved = canvas.post(f"/graph/nodes/{group['id']}", data={"label": "", "look_colour": "sky"}).json()
    assert only(saved, "group")["look"]["colour"] == "sky"

    canvas.post(f"/graph/nodes/{group['id']}/lock", data={"locked": "1"})
    folded = canvas.post(f"/graph/nodes/{group['id']}/fold", data={"folded": "1"}).json()
    assert only(folded, "group")["look"]["collapsed"] is True and only(folded, "group")["locked"] is True
    opened = canvas.post(f"/graph/nodes/{group['id']}/fold", data={"folded": "0"}).json()
    assert only(opened, "group")["look"]["collapsed"] is False


def test_a_canvas_file_carries_everything_inside_it_and_loads_as_a_canvas(db):
    build(db, channels=(), feeds=())
    with db.session_scope() as session:
        room = graph.add_canvas(session, label="Room")
        with in_canvas(room.id):
            first = graph.add_filter(session, label="First", x=10, y=20)
            relay = graph.add_relay(session, x=200, y=20)
            looks.save(relay, {"look_faces": "up"})
            second = graph.add_sort(session, label="Second", x=400, y=20)
            graph.connect(session, first, relay)
            looks.set_route(graph.connect(session, relay, second), "square")
            band = graph.add_group(session, label="Band", x=0, y=200, width=500, height=200)
            looks.save(band, {"look_colour": "sage", "look_collapsed": "1"})
            note = graph.add_comment(session, text="Hello", x=20, y=240)
            words = graph.add_text_box(session, label="Writer", x=600, y=20)
            graph.add_transform(session, label="Counter", x=600, y=200)
            deeper = graph.add_canvas(session, label="Deeper", x=0, y=500)
        with in_canvas(deeper.id):
            graph.add_filter(session, label="Deepest")
        from pamphlets.services import writing
        writing.save(words, {"writing_instructions": "Sum it up."})

        packed = json.loads(json.dumps(canvas_files.export_canvas(session, room.id)))
        loaded = canvas_files.import_canvas(session, packed, x=900, y=900)

        inside = [node for node in graph.nodes(session) if node.inside_pk == loaded.id]
        by_title = {node.title: node for node in inside}
        assert {"First", "Relay", "Second", "Band", "Comment", "Writer", "Counter", "Deeper"} <= set(by_title)
        assert looks.look(by_title["Relay"])["faces"] == "up"
        assert looks.look(by_title["Band"]) == {"colour": "sage", "collapsed": True}
        assert (by_title["First"].x, by_title["First"].y) == (10, 20)
        assert graph.comments.settings(by_title["Comment"])["text"] == "Hello"
        assert writing.settings(by_title["Writer"])["instructions"] == "Sum it up."
        deepest = [node for node in graph.nodes(session) if node.inside_pk == by_title["Deeper"].id]
        assert [node.title for node in deepest] == ["Deepest"]
        # The wires came, through the relay, the second drawn square.
        routes = {(edge.source_pk, edge.target_pk): edge.route
                  for edge in graph.edges(session, every=True, raw=True)}
        assert routes[(by_title["First"].id, by_title["Relay"].id)] is None
        assert routes[(by_title["Relay"].id, by_title["Second"].id)] == "square"


def test_a_canvas_file_that_would_go_too_deep_is_refused(db):
    build(db, channels=(), feeds=())
    with db.session_scope() as session:
        holder = None
        for level in range(4):
            with in_canvas(holder):
                holder = graph.add_canvas(session, label=f"L{level}").id
        file = {"pamphlets_canvas": 1, "name": "Deep", "nodes": [
            {"ref": 0, "kind": "canvas", "x": 0, "y": 0, "inside": None},
        ], "wires": []}
        with in_canvas(holder), pytest.raises(graph.GraphError, match="deep"):
            canvas_files.import_canvas(session, file)
