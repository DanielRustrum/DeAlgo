"""Layout boxes: Relays, which a wire passes through, and Canvas nodes,
which are canvases inside the canvas, five deep at most.

A relay changes nothing about what is wired: everything that reads the
graph sees straight through it. A canvas keeps to itself — its boxes wire
only to each other — but every box inside it runs.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from pamphlets.models import CURRENT_INSIDE, GraphEdge, GraphNode, Playlist
from pamphlets.services import graph
from pamphlets.services.graph import formatting, insides, leaflets
from tests.test_format import ANSWER, a_rest_source, client  # noqa: F401
from tests.test_graph import build, canvas, node_for  # noqa: F401


def in_canvas(pk):
    """Work as if looking inside a Canvas node, as a request naming it would."""
    class Inside:
        def __enter__(self):
            self.token = CURRENT_INSIDE.set(pk)

        def __exit__(self, *_):
            CURRENT_INSIDE.reset(self.token)
    return Inside()


# -- relays ---------------------------------------------------------------------------


def test_a_path_through_relays_is_the_path_straight(db):
    build(db, channels=("UCone",), feeds=("PLone", "PLtwo"))
    with db.session_scope() as session:
        source = node_for(session, "source", "UCone")
        first, second = node_for(session, "feed", "PLone"), node_for(session, "feed", "PLtwo")
        for wire in list(session.scalars(select(GraphEdge))):
            session.delete(wire)
        session.flush()
        here, there = graph.add_relay(session), graph.add_relay(session)
        graph.connect(session, source, here)
        graph.connect(session, here, there)
        graph.connect(session, there, first)     # a relay passes on to as many as you like
        graph.connect(session, here, second)
        ends = sorted(route.playlist.playlist_id for route in graph.routes(session) if route.playlist)
        assert ends == ["PLone", "PLtwo"]
        # The canvas still draws the relays; nothing else sees them.
        drawn = graph.wires(session)
        assert sum(1 for wire in drawn if wire["to"] == here.id) == 1
        assert {wire["kind"] for wire in drawn} == {"edge"}
        # And the channel fills both, as a straight wire would.
        assert {p.playlist_id for p in source.channel.playlists} >= {"PLone", "PLtwo"}


def test_a_relay_passes_on_only_what_its_start_could(db):
    build(db, channels=("UCone",), feeds=("PLone",))
    with db.session_scope() as session:
        trigger = graph.add_trigger(session)
        feed = node_for(session, "feed", "PLone")
        relay = graph.add_relay(session)
        with pytest.raises(graph.GraphError, match="Wire something into this relay first"):
            graph.connect(session, relay, feed)
        graph.connect(session, trigger, relay)
        with pytest.raises(graph.GraphError, match="starts at a trigger"):
            graph.connect(session, relay, feed)
        graph.connect(session, relay, node_for(session, "source", "UCone"))
        assert graph.polling_plan(session)  # the trigger polls the source through it


def test_a_loop_through_a_relay_is_still_a_loop(db):
    build(db, channels=(), feeds=())
    with db.session_scope() as session:
        one, two = graph.add_filter(session), graph.add_filter(session)
        relay = graph.add_relay(session)
        graph.connect(session, one, two)
        graph.connect(session, two, relay)
        with pytest.raises(graph.GraphError, match="loop"):
            graph.connect(session, relay, one)


def test_data_and_feeds_pass_through_relays(db):
    with db.session_scope() as session:
        source = a_rest_source(session, ANSWER)
        pamphlet = graph.add_pamphlet(session, label="P")
        chart = graph.add_piece(session, kind="leaflet-bar", host=pamphlet)
        relay = graph.add_relay(session)
        graph.connect(session, source, relay)
        graph.connect(session, relay, chart)
        assert formatting.data_into(session, chart, None) == ANSWER

        playlist = Playlist(playlist_id="PLx", title="X")
        session.add(playlist)
        session.flush()
        feed = graph.add_feed(session, playlist)
        cards = graph.add_piece(session, kind="leaflet-feed", host=chart, side="beside")
        page = graph.add_relay(session)
        graph.connect(session, feed, page)
        assert [w for w in graph.wires(session) if w["to"] == page.id][0]["kind"] == "page"
        graph.connect(session, page, cards)
        assert leaflets.settings(cards)["feed"] == playlist.id

        # Taken out, the leaflet no longer shows the feed.
        graph.remove(session, page.id)
        assert leaflets.settings(cards)["feed"] is None


# -- canvases -------------------------------------------------------------------------


def test_a_canvas_holds_its_own_boxes_which_still_run(db):
    build(db, channels=("UCone",), feeds=("PLone",))
    with db.session_scope() as session:
        graph.load(session)
        room = graph.add_canvas(session, label="Ingest")
        with in_canvas(room.id):
            inner = graph.add_filter(session, label="Inside")
            relay = graph.add_relay(session)
        assert inner.inside_pk == room.id and relay.inside_pk == room.id
        source = node_for(session, "source", "UCone")
        with pytest.raises(graph.GraphError, match="keeps to itself"):
            graph.connect(session, source, inner)

        # Everything inside runs: a path drawn wholly inside is a path.
        with in_canvas(room.id):
            playlist = Playlist(playlist_id="PLin", title="In")
            session.add(playlist)
            session.flush()
            feed = graph.add_feed(session, playlist)
            channel_box = graph.add_source(session, channel=source.channel)
        graph.connect(session, channel_box, inner)
        graph.connect(session, inner, feed)
        assert "PLin" in [route.playlist.playlist_id for route in graph.routes(session) if route.playlist]


def test_canvases_go_five_deep(db):
    build(db, channels=(), feeds=())
    with db.session_scope() as session:
        holder = None
        for level in range(insides.MOST_DEPTH):
            with in_canvas(holder):
                holder = graph.add_canvas(session, label=f"Level {level + 1}").id
        with in_canvas(holder), pytest.raises(graph.GraphError, match="5 deep"):
            graph.add_canvas(session)
        by_id = {node.id: node for node in graph.nodes(session)}
        assert insides.depth(by_id, holder) == 5
        assert [step["title"] for step in insides.trail(session, None, holder)][:2] == ["Configuration", "Level 1"]


def test_the_canvas_shows_one_canvas_at_a_time_and_its_way_out(canvas, db):
    room = canvas.post("/graph/nodes", data={"kind": "canvas", "title": "Ingest"}).json()
    room_pk = next(node["id"] for node in room["nodes"] if node["kind"] == "canvas")
    inside = canvas.post(f"/graph/nodes?inside={room_pk}", data={"kind": "filter", "title": "In here"}).json()
    assert inside["inside"] == room_pk
    assert [node["title"] for node in inside["nodes"]] == ["In here"]
    assert [step["title"] for step in inside["trail"]] == ["Configuration", "Ingest"]

    top = canvas.get("/api/graph").json()
    assert "In here" not in [node["title"] for node in top["nodes"]]
    held = next(node for node in top["nodes"] if node["id"] == room_pk)
    assert held["note"].startswith("1 box inside")

    # Somebody else's number, or a box that is not a canvas, is the top.
    assert canvas.get("/api/graph?inside=99999").json()["inside"] is None

    # Taken away, it takes what is inside with it.
    canvas.post(f"/graph/nodes/{room_pk}/delete")
    with db.session_scope() as session:
        assert not [node for node in graph.nodes(session) if node.title == "In here"]


def test_a_group_surrounds_only_boxes_in_its_own_canvas(db):
    build(db, channels=(), feeds=())
    with db.session_scope() as session:
        group = graph.add_group(session, label="G", x=0, y=0, width=600, height=400)
        here = graph.add_filter(session, label="Here", x=100, y=100)
        room = graph.add_canvas(session, label="Room", x=800, y=0)
        with in_canvas(room.id):
            elsewhere = graph.add_filter(session, label="Elsewhere", x=100, y=100)
        from pamphlets.services.graph import groups
        assert [node.id for node in groups.inside(session, group)] == [here.id]
        graph.move_group(session, group.id, 50, 50)
        assert (elsewhere.x, elsewhere.y) == (100, 100)


# -- comments -------------------------------------------------------------------------


def test_a_comment_keeps_words_and_a_colour_and_is_wired_to_nothing(canvas, db):
    made = canvas.post("/graph/nodes", data={"kind": "comment", "title": "", "x": 40, "y": 60}).json()
    note = next(node for node in made["nodes"] if node["kind"] == "comment")
    assert note["comment"]["text"] == "" and note["comment"]["colour"] == "paper"
    assert note["size"] == {"width": 260, "height": 140}
    assert [one["name"] for one in note["comment"]["colours"]] == ["paper", "sage", "blush", "ochre", "sky"]

    saved = canvas.post(f"/graph/nodes/{note['id']}", data={
        "label": "", "comment_text": "Everything below\\nis for the morning.", "comment_colour": "sage",
    }).json()
    again = next(node for node in saved["nodes"] if node["id"] == note["id"])
    assert again["comment"] == {**again["comment"], "text": "Everything below\\nis for the morning.", "colour": "sage"}
    assert canvas.post(f"/graph/nodes/{note['id']}", data={"comment_colour": "neon"}).status_code == 400

    # Resized, down to a size of its own.
    canvas.post(f"/graph/nodes/{note['id']}/resize", data={"width": 10, "height": 10})
    with db.session_scope() as session:
        node = session.get(GraphNode, note["id"])
        assert (node.width, node.height) == graph.comments.LEAST
        source = node_for(session, "source", "One Channel")
        with pytest.raises(graph.GraphError):
            graph.connect(session, source, node)


def test_a_comment_travels_in_its_group(db):
    from pamphlets.services.graph import groups

    build(db, channels=(), feeds=())
    with db.session_scope() as session:
        group = graph.add_group(session, label="G", x=0, y=0, width=600, height=400)
        note = graph.add_comment(session, text="Read me first", x=20, y=20)
        graph.comments.save(note, {"comment_colour": "blush"})
        note.width, note.height = 300, 90
        packed = groups.export_group(session, group.id)
        loaded = groups.import_group(session, packed, x=1000, y=1000)
        copies = [node for node in graph.nodes(session) if node.kind == "comment" and node.id != note.id]
        assert len(copies) == 1 and loaded is not None
        assert graph.comments.settings(copies[0]) == {"text": "Read me first", "colour": "blush"}
        assert (copies[0].width, copies[0].height) == (300, 90)
