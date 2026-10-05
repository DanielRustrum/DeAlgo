"""Updating a group from a newer copy of the file it was loaded from.

A group remembers the file it came from: its id, and a key for each box. A
newer copy of the same file updates the group in place — boxes the file
still has keep their history, channel and feed; boxes it adds are made;
boxes it dropped go — and a file for a different group is refused.
"""

from __future__ import annotations

import copy
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from dealgo.models import Channel, GraphEdge, GraphNode, Placement, Playlist, Video, utcnow
from dealgo.services import graph
from dealgo.services import playlists as playlist_service


def a_shared_group(db) -> dict:
    """A group somebody made and exported: a source, a filter with a
    condition slotted under it, and a feed, wired source → filter → feed."""
    with db.session_scope() as session:
        channel = Channel(channel_id="UCone", title="One")
        session.add(channel)
        session.flush()
        source = graph.add_source(session, channel=channel, x=100, y=100)
        middle = graph.add_filter(session, label="Long ones", x=300, y=100)
        longer = graph.add_piece(session, kind="longer-than", host=middle, x=300, y=160)
        longer.min_duration_sec = 600
        feed = graph.add_feed(session, playlist_service.create_generic(session, "Long reads"),
                              x=500, y=100)
        graph.connect(session, source, middle)
        graph.connect(session, middle, feed)
        group = graph.add_group(session, label="Shared", x=50, y=50, width=700, height=300)
        packed = graph.export_group(session, group.id)
        # The author's own copy is not what is being updated: take it away,
        # so the account below holds only what it loaded.
        for node in graph.nodes(session):
            session.delete(node)
        session.delete(channel)
        for playlist in session.scalars(select(Playlist)):
            session.delete(playlist)
    return packed


def load(db, packed, *, x=1000, y=1000, name="shared.json") -> int:
    with db.session_scope() as session:
        return graph.import_group(session, packed, x=x, y=y, file_name=name).id


def update(db, group_pk, packed, name="shared.json") -> graph.GroupUpdate:
    with db.session_scope() as session:
        return graph.update_group(session, group_pk, packed, file_name=name)


def entry(packed, kind):
    return next(node for node in packed["nodes"] if node["kind"] == kind)


def test_an_export_carries_an_id_and_a_key_per_box(db):
    packed = a_shared_group(db)
    assert packed["de_algo_group"] == 3 and packed["id"]
    keys = [node["key"] for node in packed["nodes"]]
    assert len(keys) == 4 and len(set(keys)) == 4


def test_a_loaded_group_remembers_its_file(db):
    group_pk = load(db, a_shared_group(db))
    with db.session_scope() as session:
        group = session.get(GraphNode, group_pk)
        assert group.imported_from == "shared.json" and group.imported_at is not None
        assert all(node.group_key for node in graph.inside(session, group))


def test_a_newer_copy_updates_what_is_there_in_place(db):
    packed = a_shared_group(db)
    group_pk = load(db, packed)
    with db.session_scope() as session:
        before = {n.kind: n.id for n in graph.inside(session, session.get(GraphNode, group_pk))}
        feed = session.get(GraphNode, before["feed"])
        # The account has been reading it: that must survive the update.
        video = Video(video_id="v1", channel_pk=session.scalar(select(Channel.id)),
                      title="Read me", published_at=utcnow(), status="added")
        session.add(video)
        session.flush()
        session.add(Placement(video_pk=video.id, playlist_pk=feed.playlist_pk,
                              playlist_item_id="generic-1"))
        playlist_pk = feed.playlist_pk

    newer = copy.deepcopy(packed)
    entry(newer, "longer-than")["value"] = 1200
    entry(newer, "filter")["label"] = "Longer ones"
    entry(newer, "feed")["title"] = "Long reads (weekly)"
    result = update(db, group_pk, newer)

    assert (result.updated, result.added, result.removed) == (4, 0, 0)
    with db.session_scope() as session:
        after = {n.kind: n for n in graph.inside(session, session.get(GraphNode, group_pk))}
        assert {kind: node.id for kind, node in after.items()} == before  # the same boxes
        assert after["longer-than"].min_duration_sec == 1200
        assert after["filter"].label == "Longer ones"
        feed_playlist = session.get(Playlist, playlist_pk)
        assert feed_playlist.title == "Long reads (weekly)"
        assert session.scalar(select(Placement).where(Placement.playlist_pk == playlist_pk))
        # Still wired, and the condition still slotted under its filter.
        assert len(graph.routes(session)) == 1
        assert after["longer-than"].attached_to == after["filter"].id


def test_boxes_the_file_adds_are_made_and_ones_it_drops_go(db):
    packed = a_shared_group(db)
    group_pk = load(db, packed)

    newer = copy.deepcopy(packed)
    ref = {node["kind"]: node["ref"] for node in newer["nodes"]}
    # The filter's condition is dropped, and a timer trigger is added and wired in.
    newer["nodes"] = [node for node in newer["nodes"] if node["kind"] != "longer-than"]
    newer["nodes"].append({"ref": 99, "key": "new-trigger", "kind": "trigger", "x": 10, "y": 200,
                           "label": "Hourly", "enabled": True, "trigger_kind": "pulse",
                           "every_minutes": 60})
    newer["wires"].append([99, ref["source"]])
    result = update(db, group_pk, newer)

    assert (result.added, result.removed) == (1, 1)
    with db.session_scope() as session:
        kinds = sorted(n.kind for n in graph.inside(session, session.get(GraphNode, group_pk)))
        assert kinds == ["feed", "filter", "source", "trigger"]
        trigger = session.scalar(select(GraphNode).where(GraphNode.kind == "trigger"))
        assert trigger.group_key == "new-trigger" and trigger.every_minutes == 60
        assert session.scalar(select(GraphEdge).where(GraphEdge.source_pk == trigger.id))


def test_a_feed_the_file_drops_keeps_everything_in_it(db):
    packed = a_shared_group(db)
    group_pk = load(db, packed)
    newer = copy.deepcopy(packed)
    newer["nodes"] = [node for node in newer["nodes"] if node["kind"] != "feed"]

    result = update(db, group_pk, newer)

    assert result.kept_feeds == ["Long reads"]
    assert "kept, with everything in them" in result.describe("Shared")
    with db.session_scope() as session:
        assert session.scalar(select(Playlist).where(Playlist.title == "Long reads"))
        assert not session.scalar(select(GraphNode).where(GraphNode.kind == "feed"))


def test_what_the_account_did_to_the_group_is_kept(db):
    packed = a_shared_group(db)
    group_pk = load(db, packed)
    with db.session_scope() as session:
        group = session.get(GraphNode, group_pk)
        source = next(n for n in graph.inside(session, group) if n.kind == "source")
        source.x += 40  # moved, but still inside
        moved_to = source.x
        # A box of its own, in the group, wired to one of the file's.
        mine = graph.add_trigger(session, trigger_kind="pulse", every_minutes=30,
                                 x=group.x + 20, y=group.y + 250)
        graph.connect(session, mine, source)
        mine_pk = mine.id

    update(db, group_pk, copy.deepcopy(packed))

    with db.session_scope() as session:
        source = session.scalar(select(GraphNode).where(GraphNode.kind == "source"))
        assert source.x == moved_to
        assert session.get(GraphNode, mine_pk) is not None
        assert session.scalar(select(GraphEdge).where(GraphEdge.source_pk == mine_pk))


def test_a_file_for_a_different_group_changes_nothing(db):
    packed = a_shared_group(db)
    group_pk = load(db, packed)
    other = copy.deepcopy(packed)
    other["id"] = "somebody-elses"
    other["name"] = "Other"
    entry(other, "filter")["label"] = "Changed"

    with pytest.raises(graph.GraphError, match="different group"):
        update(db, group_pk, other)
    with db.session_scope() as session:
        assert session.scalar(select(GraphNode).where(GraphNode.kind == "filter")).label == "Long ones"


def test_a_group_nobody_loaded_cannot_be_updated(db):
    with db.session_scope() as session:
        mine = graph.add_group(session, label="Mine", x=0, y=0).id
    with pytest.raises(graph.GraphError, match="not loaded from a file"):
        update(db, mine, {"de_algo_group": 3, "id": "x", "nodes": [], "wires": []})


def test_a_format_2_file_is_still_updatable_by_its_name_and_places(db):
    packed = a_shared_group(db)
    old = copy.deepcopy(packed)
    old["de_algo_group"] = 2
    del old["id"]
    for node in old["nodes"]:
        del node["key"]
    group_pk = load(db, old)

    newer = copy.deepcopy(old)
    entry(newer, "longer-than")["value"] = 900
    result = update(db, group_pk, newer)
    assert (result.updated, result.added) == (4, 0)


# -- through the canvas ----------------------------------------------------------------


@pytest.fixture
def client(db, monkeypatch):
    from dealgo import scheduler
    from dealgo.web import app as web_app

    monkeypatch.setattr(scheduler, "start", lambda: None)
    monkeypatch.setattr(scheduler, "shutdown", lambda: None)
    monkeypatch.setattr(scheduler, "next_run_time", lambda: None)
    monkeypatch.setattr(web_app, "init_db", lambda: None)
    with TestClient(web_app.app) as test_client:
        yield test_client


def test_the_canvas_loads_then_updates_a_group_from_its_file(client, db):
    packed = a_shared_group(db)
    loaded = client.post("/graph/groups", files={"file": ("shared.json", json.dumps(packed))},
                         data={"x": 0, "y": 0}).json()
    group = next(node for node in loaded["nodes"] if node["kind"] == "group")
    assert group["imported"]["from"] == "shared.json"

    newer = copy.deepcopy(packed)
    entry(newer, "filter")["label"] = "Renamed"
    answer = client.post(f"/graph/nodes/{group['id']}/update",
                         files={"file": ("shared-v2.json", json.dumps(newer))}).json()
    assert "is up to date with its file: 4 updated." in answer["said"]
    assert any(node["title"] == "Renamed" for node in answer["nodes"])
    again = next(node for node in answer["nodes"] if node["kind"] == "group")
    assert again["imported"]["from"] == "shared-v2.json"

    other = copy.deepcopy(packed)
    other["id"] = "elsewhere"
    refused = client.post(f"/graph/nodes/{group['id']}/update",
                          files={"file": ("x.json", json.dumps(other))})
    assert refused.status_code == 400 and "different group" in refused.json()["error"]


def test_a_group_of_ones_own_has_no_import_to_update_from(client, db):
    made = client.post("/graph/nodes", data={"kind": "group", "x": 0, "y": 0}).json()
    group = next(node for node in made["nodes"] if node["kind"] == "group")
    assert group["imported"] is None
