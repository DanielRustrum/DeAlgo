"""Which plugins' boxes a canvas offers.

A Canvas node can offer only some installed plugins' boxes inside it. Its
palette hides the rest, and a box of a plugin it leaves out is refused there
— dropped, pasted or moved in. A canvas inside it offers no more than it.
"""

from __future__ import annotations

import json

import pytest

from pamphlets.models import Channel, GraphNode
from pamphlets.services import graph
from pamphlets.services.graph import allowing
from tests.test_canvases import in_canvas
from tests.test_graph import build, canvas  # noqa: F401


def test_a_canvas_offering_some_plugins_refuses_the_others(db):
    build(db, channels=(), feeds=())
    with db.session_scope() as session:
        room = graph.add_canvas(session, label="Room")
        allowing.set_allowed(room, ["reddit"])
        with in_canvas(room.id):
            graph.add_source(session, source_kind="reddit")
            # The app's own boxes go anywhere.
            graph.add_source(session, source_kind="rss")
            graph.add_filter(session, label="Keep")
            with pytest.raises(graph.GraphError, match="YouTube"):
                graph.add_source(session, source_kind="youtube")
            with pytest.raises(graph.GraphError, match="YouTube"):
                graph.add_piece(session, kind=graph.RULE, ref="youtube:no-shorts")
            graph.add_piece(session, kind=graph.RULE, ref="reddit:self-posts")
        # Outside it, everything still is.
        graph.add_source(session, source_kind="youtube")


def test_a_canvas_inside_offers_no_more_than_the_one_around_it(db):
    build(db, channels=(), feeds=())
    with db.session_scope() as session:
        outer = graph.add_canvas(session, label="Outer")
        allowing.set_allowed(outer, ["reddit", "youtube"])
        with in_canvas(outer.id):
            inner = graph.add_canvas(session, label="Inner")
        allowing.set_allowed(inner, ["youtube", "bluesky"])
        assert allowing.allowed_in(session, inner.id) == {"youtube"}
        # Every one offered again, the inner canvas still has the outer's limit.
        allowing.set_allowed(inner, None)
        assert allowing.allowed_in(session, inner.id) == {"reddit", "youtube"}


def test_ticking_every_plugin_is_the_same_as_saying_nothing(db):
    build(db, channels=(), feeds=())
    with db.session_scope() as session:
        room = graph.add_canvas(session, label="Room")
        allowing.set_allowed(room, [one.id for one in allowing.offered()])
        assert room.plugins is None
        allowing.set_allowed(room, ["reddit", "not-installed"])
        assert json.loads(room.plugins) == ["reddit"]


def test_a_paste_or_a_cut_of_a_plugin_s_box_is_refused_whole(db):
    build(db, channels=(), feeds=())
    with db.session_scope() as session:
        channel = Channel(channel_id="UCx", title="X", source_kind="youtube")
        session.add(channel)
        session.flush()
        tube = graph.add_source(session, channel=channel, x=0, y=0)
        keep = graph.add_filter(session, label="Keep", x=300, y=0)
        room = graph.add_canvas(session, label="Room")
        allowing.set_allowed(room, ["reddit"])
        clip = graph.clipboard.copy(session, [keep.id, tube.id])
        before = len(graph.nodes(session))
        with in_canvas(room.id):
            with pytest.raises(graph.GraphError, match="YouTube"):
                graph.clipboard.paste(session, clip, x=0, y=0)
            assert len(graph.nodes(session)) == before  # not half of it
            with pytest.raises(graph.GraphError, match="YouTube"):
                graph.clipboard.move(session, [tube.id], x=0, y=0)
            assert tube.inside_pk is None


def test_the_canvas_says_its_plugins_through_its_api(canvas, db):
    with db.session_scope() as session:
        room = graph.add_canvas(session, label="Room")
        room_pk = room.id
    answer = canvas.post(f"/graph/nodes/{room_pk}/plugins", data={"plugin": ["reddit", "bluesky"]}).json()
    rows = {one["id"]: one for one in next(n for n in answer["nodes"] if n["id"] == room_pk)["plugins"]}
    assert rows["reddit"]["offered"] and not rows["youtube"]["offered"]
    inside = canvas.get(f"/api/graph?inside={room_pk}").json()
    assert inside["plugins"] == ["bluesky", "reddit"]
    assert canvas.get("/api/graph").json()["plugins"] is None
    canvas.post(f"/graph/nodes/{room_pk}/plugins", data={"every": "1"})
    with db.session_scope() as session:
        assert session.get(GraphNode, room_pk).plugins is None


def test_the_palette_marks_each_plugin_s_rows(canvas):
    page = canvas.get("/channels").text
    assert 'data-plugin="youtube"' in page and 'data-palette-no-plugins' in page


def test_a_refused_box_is_said_why_not_failed(canvas, db):
    with db.session_scope() as session:
        room = graph.add_canvas(session, label="Room")
        allowing.set_allowed(room, ["reddit"])
        session.add(Channel(channel_id="UCx", title="X", source_kind="youtube"))
        room_pk = room.id
    dropped = canvas.post(f"/graph/nodes?inside={room_pk}", data={"kind": "source", "source_kind": "youtube"})
    assert dropped.status_code == 400 and "YouTube" in dropped.json()["error"]
    # An empty box of an offered kind cannot be pointed at a watched source of another.
    with db.session_scope() as session:
        with in_canvas(room_pk):
            empty = graph.add_source(session, source_kind="reddit")
        watched = session.query(Channel).filter_by(channel_id="UCx").one()
        empty_pk, watched_pk = empty.id, watched.id
    pointed = canvas.post(f"/graph/nodes/{empty_pk}", data={"source_pk": str(watched_pk)})
    assert pointed.status_code == 400 and "YouTube" in pointed.json()["error"]
