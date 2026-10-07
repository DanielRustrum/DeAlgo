"""Format boxes: a source's JSON reshaped into bars for a Chart leaflet.

A REST API source gives its last whole answer; any other source its items
written out as JSON. The box finds the rows, labels each bar by a path in
them, and measures it — counting rows, or adding up, averaging… a number.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from dealgo.models import Channel, GraphNode, Video, utcnow
from dealgo.services import graph
from dealgo.services import playlists as playlist_service
from dealgo.services.graph import formatting
from tests.test_rest_source import serve

ANSWER = {"data": {"children": [
    {"data": {"author": "ana", "score": 10, "created_utc": 1759500000, "flair": ["news", "tech"]}},
    {"data": {"author": "ben", "score": 4, "created_utc": 1759500000 + 86400, "flair": ["news"]}},
    {"data": {"author": "ana", "score": 6, "created_utc": 1759500000 + 86400, "flair": []}},
    {"data": {"author": "cy", "score": "2", "created_utc": 1759500000 + 2 * 86400}},
]}}


def spec(**said):
    return {**formatting.DEFAULTS, **said}


def bars(shaped):
    return [(bar.label, bar.value) for bar in shaped.bars]


# -- reshaping ---------------------------------------------------------------------


def test_it_counts_rows_by_a_label_found_in_them():
    shaped = formatting.shape(ANSWER, spec(label="data.author"))
    assert shaped.rows_path == "data.children" and shaped.rows == 4
    assert bars(shaped) == [("ana", 2), ("ben", 1), ("cy", 1)]
    assert "data.author" in shaped.fields and "data.score" in shaped.fields
    assert not shaped.across


def test_it_adds_up_averages_and_reads_numbers_written_as_text():
    added = formatting.shape(ANSWER, spec(label="data.author", value="data.score", combine="sum"))
    assert bars(added) == [("ana", 16), ("ben", 4), ("cy", 2)]
    averaged = formatting.shape(ANSWER, spec(label="data.author", value="data.score",
                                             combine="average", sort="label-asc"))
    assert bars(averaged) == [("ana", 8), ("ben", 4), ("cy", 2)]


def test_dates_are_grouped_and_drawn_across_in_order():
    shaped = formatting.shape(ANSWER, spec(label="data.created_utc", group="day", sort="label-asc"))
    assert [bar.value for bar in shaped.bars] == [1, 2, 1]
    assert shaped.across
    assert shaped.bars[0].long.startswith("Fri 3 Oct")


def test_a_list_gives_a_bar_for_each_thing_in_it():
    shaped = formatting.shape(ANSWER, spec(label="data.flair"))
    assert bars(shaped) == [("news", 2), ("tech", 1)]


def test_it_says_what_is_missing():
    assert "Nothing has come in yet" in formatting.shape(None, spec(label="x")).error
    assert "labels each bar" in formatting.shape(ANSWER, spec()).error
    assert "No row had" in formatting.shape(ANSWER, spec(label="nowhere")).error
    assert "does not lead to a list" in formatting.shape(ANSWER, spec(rows="data", label="x")).error


def test_its_settings_are_checked(db):
    with db.session_scope() as session:
        box = graph.add_format(session)
        formatting.save(box, {"format_label": "data.author", "format_limit": "500"})
        assert formatting.settings(box)["limit"] == formatting.MOST_BARS
        with pytest.raises(graph.GraphError, match="number to add up"):
            formatting.save(box, {"format_combine": "sum", "format_value": ""})
        with pytest.raises(graph.GraphError):
            formatting.save(box, {"format_group": "fortnight"})
        assert formatting.words(box) == "count of data.author"


# -- what comes in, and where it goes --------------------------------------------------


def a_rest_source(session, answer=None, url="https://api.example/list"):
    channel = Channel(channel_id=url, title="An API", source_kind="rest",
                      source_url=url, enabled=True)
    if answer is not None:
        channel.raw_snapshot = json.dumps(answer)
    session.add(channel)
    session.flush()
    return graph.add_source(session, channel=channel)


def test_a_media_source_gives_its_items_as_json(db):
    with db.session_scope() as session:
        channel = Channel(channel_id="UCone", title="One")
        session.add(channel)
        session.flush()
        for n in range(3):
            session.add(Video(video_id=f"v{n}", channel_pk=channel.id, title=f"V{n}",
                              status="added", duration_sec=60 * (n + 1),
                              published_at=utcnow() - dt.timedelta(days=n),
                              watched_at=utcnow() if n == 0 else None))
        source = graph.add_source(session, channel=channel)
        data = formatting.data_for(session, source)

    assert [row["title"] for row in data] == ["V0", "V1", "V2"]
    assert data[0]["watched"] is True and data[0]["source"] == "One"
    shaped = formatting.shape(data, spec(label="watched", value="duration", combine="sum",
                                         sort="label-asc"))
    assert bars(shaped) == [("no", 300), ("yes", 60)]


def test_a_source_wires_into_a_format_box_and_that_into_a_chart(db):
    with db.session_scope() as session:
        source = a_rest_source(session, ANSWER)
        box = graph.add_format(session)
        chart = graph.add_piece(session, kind="leaflet-chart", host=graph.add_pamphlet(session))
        graph.connect(session, source, box)
        graph.connect(session, box, chart)
        kinds = {(wire["from"], wire["to"]): wire["kind"] for wire in graph.wires(session)}
        assert kinds[(source.id, box.id)] == "data" and kinds[(box.id, chart.id)] == "data"

        # Nothing else goes in or out of one, and it is on no path.
        feed = graph.add_feed(session, playlist_service.create_generic(session, "F"))
        with pytest.raises(graph.GraphError):
            graph.connect(session, box, feed)
        with pytest.raises(graph.GraphError):
            graph.connect(session, feed, box)
        assert graph.routes(session) == []

        # One source into a box: a second takes the first's place.
        other = a_rest_source(session, url="https://api.example/other")
        graph.connect(session, other, box)
        assert [w["from"] for w in graph.wires(session) if w["to"] == box.id] == [other.id]


def test_a_rest_source_keeps_its_answer_when_it_is_polled(db, monkeypatch):
    from dealgo.services import sync as sync_service

    serve(monkeypatch, {"items": [{"title": "One", "url": "https://example.com/1"}],
                        "stats": {"users": 12}})
    with db.session_scope() as session:
        db.get_settings(session).initial_backfill = 10
        source = a_rest_source(session)
        graph.connect(session, source, graph.add_format(session))

    sync_service.run_sync("manual", force=True)
    with db.session_scope() as session:
        kept = session.scalar(select(Channel)).raw_snapshot
        assert kept and json.loads(kept)["stats"] == {"users": 12}


# -- on the page and the canvas ----------------------------------------------------


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


def test_a_chart_leaflet_draws_what_its_format_box_shapes(client, db):
    with db.session_scope() as session:
        source = a_rest_source(session, ANSWER)
        box = graph.add_format(session, label="Posts by author")
        formatting.save(box, {"format_label": "data.author", "format_value": "data.score",
                              "format_combine": "sum"})
        pamphlet = graph.add_pamphlet(session, label="Stats")
        chart = graph.add_piece(session, kind="leaflet-chart", host=pamphlet)
        graph.connect(session, source, box)
        graph.connect(session, box, chart)
        pamphlet_pk = pamphlet.id

    page = client.get(f"/pamphlets/{pamphlet_pk}").text
    assert "Posts by author" in page
    assert "ana · 16" in page and "ben · 4" in page


def test_the_canvas_makes_tries_and_saves_a_format_box(client, db):
    with db.session_scope() as session:
        source_pk = a_rest_source(session, ANSWER).id

    made = client.post("/graph/nodes", data={"kind": "format", "title": ""}).json()
    box = next(node for node in made["nodes"] if node["kind"] == "format")
    assert box["format"]["settings"]["combine"] == "count"
    client.post("/graph/connect", data={"source": source_pk, "target": box["id"]})

    tried = client.post(f"/graph/nodes/{box['id']}/format/try",
                        data={"format_label": "data.author", "format_limit": "2"}).json()
    assert tried["rows"] == 4 and tried["rows_path"] == "data.children"
    assert tried["bars"] == [{"label": "ana", "value": "2"}, {"label": "ben", "value": "1"}]
    assert "data.score" in tried["fields"]

    saved = client.post(f"/graph/nodes/{box['id']}", data={
        "label": "", "format_label": "data.author", "format_group": "none",
    }).json()
    assert next(n for n in saved["nodes"] if n["id"] == box["id"])["note"] == "count of data.author"
    refused = client.post(f"/graph/nodes/{box['id']}", data={"format_combine": "sum"})
    assert refused.status_code == 400


def test_a_format_box_travels_in_a_group(db):
    with db.session_scope() as session:
        box = graph.add_format(session, x=100, y=100)
        formatting.save(box, {"format_label": "data.author", "format_group": "none"})
        group = graph.add_group(session, label="G", x=0, y=0, width=600, height=400)
        packed = graph.export_group(session, group.id)
        loaded = graph.import_group(session, json.loads(json.dumps(packed)), x=2000, y=0,
                                    file_name="g.json")
        copy = next(node for node in graph.inside(session, loaded) if node.kind == "format")
        assert formatting.settings(copy)["label"] == "data.author"
        assert session.scalars(select(GraphNode).where(GraphNode.kind == "format")).all()
