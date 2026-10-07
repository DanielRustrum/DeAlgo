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

from pamphlets.models import Channel, GraphNode, Placement, Video, utcnow
from pamphlets.services import graph
from pamphlets.services import pamphlet_charts as charts
from pamphlets.services import playlists as playlist_service
from pamphlets.services.graph import leaflets


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
        assert leaflets.words(feed, {}) == "wire a feed into it"
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
    from pamphlets import scheduler
    from pamphlets.web import app as web_app

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
    assert f'href="/focus?playlist={feed_pk}"' in page and "Read Science in Focus" in page
    # Set as a paper: a masthead with a dateline, the feed's items as stories.
    assert 'class="paper-title">Morning<' in page and "paper-dateline" in page
    assert 'class="story is-lead"' in page


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


# -- a feed wired onto a page ------------------------------------------------------


def test_a_feed_wired_into_a_leaflet_is_what_it_shows(db):
    with db.session_scope() as session:
        news = graph.add_feed(session, playlist_service.create_generic(session, "News"))
        sport = graph.add_feed(session, playlist_service.create_generic(session, "Sport"))
        pamphlet = graph.add_pamphlet(session)
        cards = leaflet(session, "feed", pamphlet)

        graph.connect(session, news, cards)
        assert leaflets.settings(cards)["feed"] == news.playlist_pk
        wire = next(one for one in graph.wires(session) if one["to"] == cards.id)
        assert wire["kind"] == "page"

        # One feed to a leaflet: a second wired in takes the first's place.
        graph.connect(session, sport, cards)
        assert [one["from"] for one in graph.wires(session) if one["to"] == cards.id] == [sport.id]
        assert leaflets.settings(cards)["feed"] == sport.playlist_pk

        graph.disconnect(session, int(wire_id(graph.wires(session), cards.id)))
        assert leaflets.settings(cards)["feed"] is None

        # A text leaflet shows no feed, and nothing but a feed goes into one.
        words = leaflet(session, "text", cards)
        with pytest.raises(graph.GraphError):
            graph.connect(session, news, words)
        with pytest.raises(graph.GraphError):
            graph.connect(session, pamphlet, cards)


def wire_id(wires, target):
    return next(one["id"] for one in wires if one["to"] == target).split(":")[1]


def test_leaflets_pointed_at_a_feed_before_wires_are_wired_to_it(db):
    from pamphlets.db.migrations import leaflets_are_wired_to_their_feeds

    with db.session_scope() as session:
        news = graph.add_feed(session, playlist_service.create_generic(session, "News"))
        cards = leaflet(session, "feed", graph.add_pamphlet(session))
        cards.leaflet = json.dumps({"feed": news.playlist_pk, "count": 4})
        cards_pk, news_pk = cards.id, news.id

    leaflets_are_wired_to_their_feeds()
    leaflets_are_wired_to_their_feeds()
    with db.session_scope() as session:
        wires = [one for one in graph.wires(session) if one["to"] == cards_pk]
        assert [(one["from"], one["kind"]) for one in wires] == [(news_pk, "page")]


# -- moving leaflets about ---------------------------------------------------------


def test_a_leaflet_moves_on_its_own_even_under_what_was_below_it(db):
    with db.session_scope() as session:
        pamphlet = graph.add_pamphlet(session)
        top = named(leaflet(session, "text", pamphlet), "top")
        middle = named(leaflet(session, "text", top), "middle")
        bottom = named(leaflet(session, "text", middle), "bottom")

        # Down past what was below it: the rest closes up, then it goes in.
        graph.attach(session, top, bottom)
        assert page_of(session, pamphlet) == [("middle", [("bottom", ["top"])])]

        # Beside something, and in between two that were beside each other.
        graph.attach(session, top, middle, side="beside")
        assert page_of(session, pamphlet) == [("middle", ["bottom"]), "top"]
        far = named(leaflet(session, "text", top, side="beside"), "far")
        graph.attach(session, bottom, top, side="beside")
        assert page_of(session, pamphlet) == ["middle", "top", "bottom", "far"]
        assert far.attached_to == bottom.id


def test_dragged_off_a_page_a_leaflet_lies_where_it_was_let_go(client, db):
    with db.session_scope() as session:
        pamphlet = graph.add_pamphlet(session)
        one = leaflet(session, "text", pamphlet)
        one_pk = one.id

    answer = client.post(f"/graph/nodes/{one_pk}/attach",
                         data={"under": "", "x": "640", "y": "-20"}).json()
    moved = next(node for node in answer["nodes"] if node["id"] == one_pk)
    assert moved["piece"]["under"] is None and (moved["x"], moved["y"]) == (640, -20)


def test_a_leaflet_goes_in_between_anywhere_on_a_page(db):
    with db.session_scope() as session:
        pamphlet = graph.add_pamphlet(session)
        top = named(leaflet(session, "text", pamphlet), "top")
        left = named(leaflet(session, "text", top), "left")
        named(leaflet(session, "text", left, side="beside"), "right")

        # Between the box and its first leaflet.
        named(leaflet(session, "text", pamphlet), "first")
        assert page_of(session, pamphlet) == [("first", [("top", ["left", "right"])])]

        # Between two stacked ones, and between two side by side.
        named(leaflet(session, "text", top), "under top")
        named(leaflet(session, "text", left, side="beside"), "middle")
        assert page_of(session, pamphlet) == [
            ("first", [("top", [("under top", ["left", "middle", "right"])])])
        ]

        # Before the first column of a row.
        named(leaflet(session, "text", left, side="before"), "leftmost")
        assert page_of(session, pamphlet) == [
            ("first", [("top", [("under top", ["leftmost", "left", "middle", "right"])])])
        ]

        # And one already on the page moved before another.
        right = session.scalar(select(GraphNode).where(GraphNode.label == "right"))
        graph.attach(session, right, left, side="before")
        assert page_of(session, pamphlet) == [
            ("first", [("top", [("under top", ["leftmost", "right", "left", "middle"])])])
        ]


def test_a_feed_leaflet_can_show_its_feed_as_a_tile(client, db):
    with db.session_scope() as session:
        feed = a_feed_with_one_item(session)
        box = graph.add_feed(session, feed)
        pamphlet = graph.add_pamphlet(session, label="Tiles")
        cards = leaflet(session, "feed", pamphlet)
        graph.connect(session, box, cards)
        leaflets.save(cards, {"leaflet_shape": "tile"}, set())
        assert leaflets.words(cards, {feed.id: "Science"}) == "“Science” as a tile"
        with pytest.raises(graph.GraphError, match="stories or as a tile"):
            leaflets.save(cards, {"leaflet_shape": "poster"}, set())
        pamphlet_pk, feed_pk = pamphlet.id, feed.id

    page = client.get(f"/pamphlets/{pamphlet_pk}").text
    assert 'class="paper-stack' in page and "A Science video" in page
    assert f'href="/feed/{feed_pk}"' in page and 'class="story' not in page


def test_the_bare_address_is_the_default_pamphlet_or_else_the_tab(client, db):
    # None chosen: the Pamphlets tab.
    first = client.get("/", follow_redirects=False)
    assert first.status_code == 303 and first.headers["location"] == "/pamphlets"

    with db.session_scope() as session:
        pamphlet = graph.add_pamphlet(session, label="Front Page")
        text = leaflet(session, "text", pamphlet)
        leaflets.save(text, {"leaflet_heading": "Hello there"}, set())
        pamphlet_pk = pamphlet.id
    client.post(f"/pamphlets/{pamphlet_pk}/default")

    # Chosen: shown at the bare address itself, with its tab lit.
    page = client.get("/", follow_redirects=False)
    assert page.status_code == 200
    assert "Hello there" in page.text and "Front Page" in page.text
    assert 'href="/pamphlets" class="active"' in page.text
    assert "★ The front page" in page.text

    # Gone: back to the tab.
    with db.session_scope() as session:
        graph.remove(session, pamphlet_pk)
    assert client.get("/", follow_redirects=False).headers["location"] == "/pamphlets"
