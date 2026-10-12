"""Loading a .pam canvas file somebody else made, and Canvas boxes' sizes.

A loaded canvas comes in frozen. One whose boxes are from plugins this
install lacks is answered with which, and where each came from, before
anything is loaded — unless it is loaded anyway. A source keeps its kind
on the way through a file.
"""

from __future__ import annotations

import io
import json

from pamphlets.models import Channel, GraphNode
from pamphlets.services import graph
from pamphlets.services.graph import canvas_files
from tests.test_canvases import in_canvas
from tests.test_graph import build, canvas  # noqa: F401


def _a_canvas_with_a_reddit_source(session):
    room = graph.add_canvas(session, label="Room")
    reddit = Channel(channel_id="r/python", title="r/python", source_kind="reddit",
                     source_url="https://www.reddit.com/r/python/.rss")
    session.add(reddit)
    session.flush()
    with in_canvas(room.id):
        graph.add_source(session, channel=reddit, x=0, y=0)
        graph.add_piece(session, kind=graph.RULE, ref="reddit:self-posts", x=0, y=200)
    return room


def test_a_loaded_canvas_comes_in_frozen_with_its_sources_kinds(db):
    build(db, channels=(), feeds=())
    with db.session_scope() as session:
        room = _a_canvas_with_a_reddit_source(session)
        packed = json.loads(json.dumps(canvas_files.export_canvas(session, room.id)))
        assert [one["id"] for one in packed["plugins"]] == ["reddit"]
        source = next(entry for entry in packed["nodes"] if entry["kind"] == "source")
        assert source["source_kind"] == "reddit"

        # As another account's would: the channel is not here, so it is made.
        session.delete(session.query(Channel).filter_by(channel_id="r/python").one())
        for node in list(graph.nodes(session)):
            if node.kind == "source":
                session.delete(node)
        session.flush()
        loaded = canvas_files.import_canvas(session, packed)
        assert loaded.frozen
        made = session.query(Channel).filter_by(channel_id="r/python").one()
        assert (made.source_kind, made.source_url, made.enabled) == (
            "reddit", "https://www.reddit.com/r/python/.rss", False)
        assert canvas_files.missing_plugins(packed) == []


def _file_needing(plugin_id, origin="https://codeberg.org/someone/pamphlets-plugin-hn"):
    return {"pamphlets_canvas": 1, "name": "Theirs",
            "plugins": [{"id": plugin_id, "name": "Hacker News", "origin": origin, "ref": "v1"}],
            "nodes": [{"ref": 0, "kind": "filter", "label": "Keep", "x": 0, "y": 0}], "wires": []}


def test_a_file_needing_a_plugin_not_here_says_which_and_where_from(db):
    missing = canvas_files.missing_plugins(_file_needing("hackernews"))
    assert missing == [{"id": "hackernews", "name": "Hacker News", "paused": False,
                        "origin": "https://codeberg.org/someone/pamphlets-plugin-hn", "ref": "v1"}]
    # From an older file that names none: read off its boxes.
    old = {"pamphlets_canvas": 1, "name": "Old", "nodes": [
        {"ref": 0, "kind": "source", "channel_id": "x", "source_kind": "lobsters", "x": 0, "y": 0},
        {"ref": 1, "kind": "rule", "plugin_ref": "reddit:self-posts", "x": 0, "y": 0},
    ], "wires": []}
    assert [one["id"] for one in canvas_files.missing_plugins(old)] == ["lobsters"]


def test_loading_asks_first_then_loads_anyway_frozen(canvas, db):
    sent = json.dumps(_file_needing("hackernews")).encode()
    asked = canvas.post("/graph/groups", files={"file": ("theirs.pam", io.BytesIO(sent))})
    assert asked.status_code == 409
    assert asked.json()["missing"][0]["id"] == "hackernews" and asked.json()["can_install"] is True
    with db.session_scope() as session:
        assert not session.query(GraphNode).filter_by(kind="canvas").count()
    loaded = canvas.post("/graph/groups", data={"anyway": "1"},
                         files={"file": ("theirs.pam", io.BytesIO(sent))})
    assert loaded.status_code == 200
    room = next(node for node in loaded.json()["nodes"] if node["kind"] == "canvas")
    assert room["frozen"] is True


def test_a_canvas_box_is_resized_and_keeps_its_size_in_a_copy(canvas, db):
    with db.session_scope() as session:
        room = graph.add_canvas(session, label="Room")
        room_pk = room.id
    drawn = canvas.get("/api/graph").json()
    assert next(n for n in drawn["nodes"] if n["id"] == room_pk)["size"] == {"width": 220, "height": 104}
    assert canvas.post(f"/graph/nodes/{room_pk}/resize", data={"width": "400", "height": "50"}).json()["resized"]
    with db.session_scope() as session:
        room = session.get(GraphNode, room_pk)
        assert (room.width, room.height) == (400, 80)  # no smaller than it can be
        made = graph.clipboard.paste(session, graph.clipboard.copy(session, [room_pk]), x=0, y=500)
        assert (made[0].width, made[0].height) == (400, 80)


def test_feeds_on_a_service_whose_plugin_is_not_installed_say_so(monkeypatch):
    from pamphlets.web import templates

    monkeypatch.setattr(templates, "publishing_plugin", lambda: None)
    monkeypatch.setitem(templates.TEMPLATES.env.globals, "publishing_offline", lambda owner=None: {"feeds": 2, "stale": False})
    names = templates.publishing_names()
    assert (names["publisher"], names["installed"]) == ("its service", False)
    said = templates.TEMPLATES.env.get_template("_offline_banner.html").render(identity=None)
    assert "is not installed" in said and "/admin/plugins" in said
    assert ", ." not in said and "No  account" not in said
