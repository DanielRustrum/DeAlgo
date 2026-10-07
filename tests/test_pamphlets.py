"""Pamphlets: a page laid out on the canvas by a Pamphlet box and its leaflets.

A leaflet below another is the next thing down its column; beside another
is the next column. The page is the canvas's layout, so most of what is
tested here is that the tree the canvas holds is the page the tab shows.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from dealgo.models import Channel, GraphNode, Placement, Video, utcnow
from dealgo.services import graph
from dealgo.services import pamphlet_charts as charts
from dealgo.services import playlists as playlist_service
from dealgo.services.graph import leaflets


def leaflet(session, kind, host=None, side="below"):
    return graph.add_piece(session, kind=f"leaflet-{kind}", host=host, side=side)


def shape(row):
    """A layout as names: each column its leaflet's label and what is below it."""
    return [
        (column.leaflet.label, shape(column.below)) if column.below else column.leaflet.label
        for column in row
    ]


def page_of(session, pamphlet):
    return shape(leaflets.layout(graph.nodes(session), pamphlet))


def named(node, label):
    node.label = label
    return node


# -- the layout --------------------------------------------------------------------


def test_below_is_a_column_and_beside_is_the_next_one(db):
    """A heading across the page, over two columns of feeds."""
    with db.session_scope() as session:
        pamphlet = graph.add_pamphlet(session, label="Morning")
        heading = named(leaflet(session, "text", pamphlet), "heading")
        left = named(leaflet(session, "feed", heading), "left")
        named(leaflet(session, "feed", left, side="beside"), "right")
        named(leaflet(session, "chart", left), "under left")

        assert page_of(session, pamphlet) == [
            ("heading", [("left", ["under left"]), "right"]),
        ]


def test_a_leaflet_dropped_on_a_taken_edge_goes_between(db):
    with db.session_scope() as session:
        pamphlet = graph.add_pamphlet(session)
        first = named(leaflet(session, "text", pamphlet), "first")
        named(leaflet(session, "text", first, side="beside"), "far")
        named(leaflet(session, "text", pamphlet), "new top")
        named(leaflet(session, "text", first, side="beside"), "middle")

        assert page_of(session, pamphlet) == [("new top", ["first", "middle", "far"])]


def test_only_a_leaflet_has_a_side_to_go_beside(db):
    with db.session_scope() as session:
        pamphlet = graph.add_pamphlet(session)
        with pytest.raises(graph.GraphError, match="beside another leaflet"):
            leaflet(session, "text", pamphlet, side="beside")
        # And a leaflet goes nowhere but a pamphlet.
        feed = graph.add_feed(session, playlist_service.create_generic(session, "News"))
        with pytest.raises(graph.GraphError, match="Pamphlet"):
            leaflet(session, "text", feed)


def test_taking_one_out_closes_the_page_up(db):
    with db.session_scope() as session:
        pamphlet = graph.add_pamphlet(session)
        top = named(leaflet(session, "text", pamphlet), "top")
        middle = named(leaflet(session, "text", top), "middle")
        named(leaflet(session, "text", middle), "bottom")
        named(leaflet(session, "text", middle, side="beside"), "side")
        graph.remove(session, middle.id)

        # What was below moves up; what was beside stays beside it.
        assert page_of(session, pamphlet) == [("top", ["bottom", "side"])]

        graph.remove(session, pamphlet.id)
        assert not session.scalars(select(GraphNode).where(GraphNode.kind.like("leaflet-%"))).all()


# -- what a leaflet is set to ------------------------------------------------------


def test_a_leaflet_takes_only_what_makes_sense(db):
    with db.session_scope() as session:
        mine = playlist_service.create_generic(session, "Mine")
        feed = leaflet(session, "feed")
        leaflets.save(feed, {"leaflet_feed": str(mine.id), "leaflet_count": "500"}, {mine.id})
        assert leaflets.settings(feed)["feed"] == mine.id
        assert leaflets.settings(feed)["count"] == leaflets.MOST_ITEMS
        with pytest.raises(graph.GraphError, match="not one of yours"):
            leaflets.save(feed, {"leaflet_feed": "9999"}, {mine.id})

        link = leaflet(session, "link")
        with pytest.raises(graph.GraphError, match="http"):
            leaflets.save(link, {"leaflet_goes": "url", "leaflet_url": "javascript:alert(1)"}, set())
        chart = leaflet(session, "chart")
        with pytest.raises(graph.GraphError, match="no chart"):
            leaflets.save(chart, {"leaflet_chart": "pie"}, set())


def test_a_leaflet_says_what_it_shows(db):
    with db.session_scope() as session:
        feed = leaflet(session, "feed")
        assert leaflets.words(feed, {}) == "open it and pick a feed"
        leaflets.save(feed, {"leaflet_feed": "7", "leaflet_count": "5"}, {7})
        assert leaflets.words(feed, {7: "News"}) == "5 from “News”"
        link = leaflet(session, "link")
        assert leaflets.words(link, {}) == "Focus on everything"


# -- charts ------------------------------------------------------------------------


def test_a_daily_chart_has_a_bar_for_every_day(db):
    with db.session_scope() as session:
        channel = Channel(channel_id="UCone", title="One")
        session.add(channel)
        session.flush()
        for n, days_ago in enumerate((0, 0, 2)):
            session.add(Video(video_id=f"v{n}", channel_pk=channel.id, title=f"V{n}",
                              status="added", watched_at=utcnow() - dt.timedelta(days=days_ago)))
        session.flush()
        bars = charts.daily(session, None, "watched-daily", 7)

    assert len(bars) == 7
    assert [one.value for one in bars] == [0, 0, 0, 0, 1, 0, 2]
    assert charts.scale(bars) == 4


def test_the_scale_rounds_up_to_a_readable_number():
    bar = charts.Bar
    assert charts.scale([bar("a", "a", 37)]) == 50
    assert charts.scale([bar("a", "a", 120)]) == 200


# -- the tab -----------------------------------------------------------------------


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


def a_feed_with_one_item(session, title="Science"):
    channel = Channel(channel_id=f"UC{title}", title=title)
    session.add(channel)
    session.flush()
    feed = playlist_service.create_generic(session, title)
    video = Video(video_id=f"{title}-1", channel_pk=channel.id, title=f"A {title} video",
                  status="added", published_at=utcnow())
    session.add(video)
    session.flush()
    session.add(Placement(video_pk=video.id, playlist_pk=feed.id,
                          playlist_item_id=f"generic-{title}", added_at=utcnow()))
    return feed


def test_a_pamphlet_page_shows_every_leaflet(client, db):
    with db.session_scope() as session:
        feed = a_feed_with_one_item(session)
        pamphlet = graph.add_pamphlet(session, label="Morning")
        text = leaflet(session, "text", pamphlet)
        leaflets.save(text, {"leaflet_heading": "Good morning", "leaflet_body": "One.\n\nTwo."}, set())
        cards = leaflet(session, "feed", text)
        leaflets.save(cards, {"leaflet_feed": str(feed.id)}, {feed.id})
        chart = leaflet(session, "chart", cards, side="beside")
        leaflets.save(chart, {"leaflet_chart": "feeds-held"}, set())
        link = leaflet(session, "link", chart)
        leaflets.save(link, {"leaflet_goes": "focus", "leaflet_feed": str(feed.id)}, {feed.id})
        pamphlet_pk, feed_pk = pamphlet.id, feed.id

    page = client.get(f"/pamphlets/{pamphlet_pk}").text
    assert "Good morning" in page and "<p class=\"leaflet-words\">Two.</p>" in page
    assert "pamphlet-row is-columns" in page
    assert "A Science video" in page  # the feed's card
    assert "What each feed holds" in page and "Science · 1 waiting" in page
    assert f'href="/focus?playlist={feed_pk}"' in page and "Focus on Science" in page


def test_the_tab_opens_on_the_default_once_one_is_chosen(client, db):
    with db.session_scope() as session:
        first = graph.add_pamphlet(session, label="First").id
        graph.add_pamphlet(session, label="Second")

    listed = client.get("/pamphlets").text
    assert "First" in listed and "Second" in listed

    client.post(f"/pamphlets/{first}/default")
    opened = client.get("/pamphlets", follow_redirects=False)
    assert opened.status_code == 303 and opened.headers["location"] == f"/pamphlets/{first}"
    # Every one is still a click away.
    assert "Second" in client.get("/pamphlets?all=1").text

    # Pressed again, it stops being the default.
    client.post(f"/pamphlets/{first}/default")
    assert client.get("/pamphlets", follow_redirects=False).status_code == 200


def test_the_canvas_builds_a_pamphlet(client, db):
    with db.session_scope() as session:
        feed_pk = playlist_service.create_generic(session, "News").id

    made = client.post("/graph/nodes", data={"kind": "pamphlet", "title": "Mine"}).json()
    pamphlet = next(node for node in made["nodes"] if node["kind"] == "pamphlet")
    assert pamphlet["detail"] == f"/pamphlets/{pamphlet['id']}"
    assert pamphlet["note"] == "slot leaflets under it to lay out its page"

    top = client.post("/graph/nodes", data={
        "kind": "leaflet-feed", "attach_to": str(pamphlet["id"]),
    }).json()
    first = next(node for node in top["nodes"] if node["kind"] == "leaflet-feed")
    beside = client.post("/graph/nodes", data={
        "kind": "leaflet-text", "attach_to": str(first["id"]), "side": "beside",
    }).json()
    text = next(node for node in beside["nodes"] if node["kind"] == "leaflet-text")
    assert text["piece"]["side"] == "beside" and text["piece"]["under"] == first["id"]
    assert first["leaflet"]["feeds"] == [{"id": feed_pk, "title": "News"}]

    saved = client.post(f"/graph/nodes/{first['id']}", data={
        "label": "", "leaflet_feed": str(feed_pk), "leaflet_count": "4",
    }).json()
    assert next(n for n in saved["nodes"] if n["id"] == first["id"])["note"] == "4 from “News”"
    refused = client.post(f"/graph/nodes/{first['id']}", data={"leaflet_feed": "9999"})
    assert refused.status_code == 400


# -- given away in a group ---------------------------------------------------------


def test_a_group_carries_its_pamphlet_laid_out_and_pointed_at_its_feed(db):
    with db.session_scope() as session:
        feed_box = graph.add_feed(
            session, playlist_service.create_generic(session, "Shared feed"), x=400, y=100
        )
        pamphlet = graph.add_pamphlet(session, label="Shared page", x=100, y=100)
        cards = leaflet(session, "feed", pamphlet)
        leaflets.save(cards, {"leaflet_feed": str(feed_box.playlist_pk)}, {feed_box.playlist_pk})
        leaflet(session, "text", cards, side="beside")
        group = graph.add_group(session, label="G", x=0, y=0, width=900, height=600)
        packed = graph.export_group(session, group.id)

    entries = {entry["kind"]: entry for entry in packed["nodes"]}
    assert entries["leaflet-text"]["side"] == "beside"
    assert "feed" not in entries["leaflet-feed"]["leaflet"]
    assert entries["leaflet-feed"]["feed_ref"] == entries["feed"]["ref"]

    with db.session_scope() as session:
        loaded = graph.import_group(session, json.loads(json.dumps(packed)), x=2000, y=0,
                                    file_name="g.json")
        inside = graph.inside(session, loaded)
        copy = next(node for node in inside if node.kind == "pamphlet")
        new_feed = next(node for node in inside if node.kind == "feed")
        row = leaflets.layout(graph.nodes(session), copy)
        assert [column.leaflet.kind for column in row] == ["leaflet-feed", "leaflet-text"]
        assert leaflets.settings(row[0].leaflet)["feed"] == new_feed.playlist_pk
