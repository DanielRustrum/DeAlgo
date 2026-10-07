"""A REST API as a source: any JSON endpoint that answers with a list of things."""

from __future__ import annotations

import datetime as dt
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from dealgo import outgoing, sources
from dealgo.models import Channel, GraphNode
from dealgo.services import graph
from dealgo.services import playlists as playlist_service
from dealgo.sources import rest

REDDITISH = {"kind": "Listing", "data": {"children": [
    {"kind": "t3", "data": {"id": "abc", "title": "Hello &amp; world",
                            "url": "https://example.com/a", "created_utc": 1759500000,
                            "thumbnail": "https://i.example/t.jpg",
                            "selftext": "<b>Some</b> text"}},
    {"kind": "t3", "data": {"id": "def", "title": "Second", "url": "https://example.com/b",
                            "created_utc": 1759600000}},
]}}


def serve(monkeypatch, answer, *, status=200, seen=None, headers=None):
    """Stand in for the network: every request gets `answer`."""
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        body = answer if isinstance(answer, (str, bytes)) else json.dumps(answer)
        return httpx.Response(status, content=body, headers=headers or {
            "content-type": "application/json"})

    monkeypatch.setattr(outgoing, "client", lambda: httpx.Client(
        transport=httpx.MockTransport(handler), follow_redirects=True))


# -- reading an answer ---------------------------------------------------------------


def test_the_list_and_its_fields_are_found_without_being_told():
    found = rest.parse(REDDITISH, rest.Mapping(), base="https://api.example/r/x.json")
    assert found.paths["items"] == "data.children"
    assert found.paths["title"] == "data.title" and found.paths["published"] == "data.created_utc"
    first = found.feed.items[0]  # newest first
    assert first.title == "Second"
    second = found.feed.items[1]
    assert second.title == "Hello & world"
    assert second.summary == "Some text"
    assert second.thumbnail_url == "https://i.example/t.jpg"
    assert second.published_at == dt.datetime.fromtimestamp(1759500000, tz=dt.timezone.utc)


def test_paths_given_are_used_as_given():
    answer = {"payload": {"rows": [{"headline": {"main": "Told"},
                                    "web": "/story/1", "at": "2026-10-01T09:00:00Z"}]}}
    mapping = rest.Mapping(items="payload.rows", title="headline.main", link="web",
                           published="at")
    found = rest.parse(answer, mapping, base="https://news.example/api/v2/rows")
    item = found.feed.items[0]
    assert item.title == "Told"
    assert item.link == "https://news.example/story/1"  # made whole against the endpoint
    assert item.published_at == dt.datetime(2026, 10, 1, 9, tzinfo=dt.timezone.utc)


@pytest.mark.parametrize("value, expected", [
    ("2026-10-01T09:00:00Z", dt.datetime(2026, 10, 1, 9, tzinfo=dt.timezone.utc)),
    ("Wed, 01 Oct 2026 09:00:00 +0000", dt.datetime(2026, 10, 1, 9, tzinfo=dt.timezone.utc)),
    (1790845200, dt.datetime(2026, 10, 1, 9, tzinfo=dt.timezone.utc)),
    (1790845200000, dt.datetime(2026, 10, 1, 9, tzinfo=dt.timezone.utc)),
    ("1790845200", dt.datetime(2026, 10, 1, 9, tzinfo=dt.timezone.utc)),
    ("not a date", None),
])
def test_dates_are_read_however_apis_write_them(value, expected):
    found = rest.parse([{"title": "x", "published": value}], rest.Mapping())
    assert found.feed.items[0].published_at == expected


def test_a_wordpress_style_rendered_title_is_read():
    found = rest.parse([{"id": 7, "title": {"rendered": "A <em>post</em>"},
                         "link": "https://blog.example/p"}], rest.Mapping())
    assert found.feed.items[0].title == "A post" and found.feed.items[0].guid == "7"


@pytest.mark.parametrize("answer, mapping, said", [
    ({"count": 3}, rest.Mapping(), "No list of items"),
    ({"rows": [{"x": 1}]}, rest.Mapping(), "nothing in it had a title or a link"),
    ({"rows": []}, rest.Mapping(items="rows"), "no list of items at"),
    ({"rows": 3}, rest.Mapping(items="rows"), "does not lead to a list"),
])
def test_an_answer_that_cannot_be_read_says_why(answer, mapping, said):
    with pytest.raises(rest.RestError, match=said):
        rest.parse(answer, mapping)


def test_only_web_links_are_kept():
    found = rest.parse([{"title": "x", "url": "javascript:alert(1)"}], rest.Mapping())
    assert found.feed.items[0].link is None


# -- the request -----------------------------------------------------------------------


def test_the_key_header_is_sent(monkeypatch):
    seen: list[httpx.Request] = []
    serve(monkeypatch, REDDITISH, seen=seen)
    mapping = rest.Mapping(header_name="Authorization", header_value="Bearer s3cret")
    with outgoing.client() as http:
        rest.fetch("https://api.example/list", mapping, http)
    assert seen[0].headers["authorization"] == "Bearer s3cret"
    assert seen[0].headers["accept"] == "application/json"


def test_with_a_key_a_redirect_is_refused_not_followed(monkeypatch):
    seen: list[httpx.Request] = []
    serve(monkeypatch, "", status=302, seen=seen,
          headers={"location": "https://elsewhere.example/steal"})
    mapping = rest.Mapping(header_name="X-API-Key", header_value="s3cret")
    with outgoing.client() as http, pytest.raises(rest.RestError, match="redirect"):
        rest.fetch("https://api.example/list", mapping, http)
    assert [str(r.url) for r in seen] == ["https://api.example/list"]


def test_an_answer_that_is_not_json_says_what_it_is(monkeypatch):
    serve(monkeypatch, "<html></html>", headers={"content-type": "text/html; charset=utf-8"})
    with outgoing.client() as http, pytest.raises(rest.RestError, match="text/html"):
        rest.fetch("https://api.example/list", rest.Mapping(), http)


def test_a_mapping_keeps_its_secret_out_of_what_it_shows():
    mapping = rest.Mapping(items="data", header_name="X-Key", header_value="s3cret")
    assert "s3cret" not in json.dumps(mapping.public())
    again = rest.Mapping.loads(mapping.dumps())
    assert again == mapping
    # A blank value from the page means "unchanged", for the same header.
    kept = rest.Mapping(header_name="X-Key").with_header_kept(mapping)
    assert kept.header_value == "s3cret"
    assert rest.Mapping(header_name="Other").with_header_kept(mapping).header_value == ""


# -- as a source ----------------------------------------------------------------------


def test_a_rest_box_takes_an_address():
    found = sources.resolve("api.example/v1/items", within="rest")
    assert (found.kind, found.key, found.feed_url) == (
        "rest", "https://api.example/v1/items", "https://api.example/v1/items")
    with pytest.raises(sources.UnknownSource):
        sources.resolve("ftp://nope", within="rest")
    assert "rest" in {kind.name for kind in sources.all_kinds()}


def test_it_is_read_on_a_run_and_its_answer_kept(db, monkeypatch):
    """A REST source gives data, not items: read on a run, and its whole
    answer kept for what its data wire goes to."""
    from dealgo.services import sync as sync_service

    serve(monkeypatch, REDDITISH)
    with db.session_scope() as session:
        db.get_settings(session).initial_backfill = 10
        channel = Channel(channel_id="https://api.example/list", title="An API",
                          source_kind="rest", source_url="https://api.example/list",
                          enabled=True)
        session.add(channel)
        session.flush()
        source = graph.add_source(session, channel=channel)
        graph.connect(session, source, graph.add_format(session))
        # Never into a feed: an API's answer is data.
        feed = graph.add_feed(session, playlist_service.create_generic(session, "From the API"))
        with pytest.raises(graph.GraphError, match="gives data, not items"):
            graph.connect(session, source, feed)

    sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        channel = session.scalar(select(Channel))
        assert channel.last_error in (None, "")
        assert json.loads(channel.raw_snapshot or "{}") == REDDITISH


def test_an_unreadable_api_is_said_on_the_source(db, monkeypatch):
    from dealgo.services import sync as sync_service

    serve(monkeypatch, {"count": 0})
    with db.session_scope() as session:
        channel = Channel(channel_id="https://api.example/x", title="Empty", source_kind="rest",
                          source_url="https://api.example/x", enabled=True)
        session.add(channel)
        session.flush()
        graph.connect(session, graph.add_source(session, channel=channel),
                      graph.add_format(session))

    sync_service.run_sync("manual", force=True)
    with db.session_scope() as session:
        assert "No list of items" in (session.scalar(select(Channel)).last_error or "")


# -- on the canvas -----------------------------------------------------------------------


@pytest.fixture
def canvas(db, monkeypatch):
    from dealgo import scheduler
    from dealgo.web import app as web_app

    monkeypatch.setattr(scheduler, "start", lambda: None)
    monkeypatch.setattr(scheduler, "shutdown", lambda: None)
    monkeypatch.setattr(scheduler, "next_run_time", lambda: None)
    monkeypatch.setattr(web_app, "init_db", lambda: None)
    with TestClient(web_app.app) as client:
        yield client


def rest_box(canvas, monkeypatch, answer=REDDITISH) -> dict:
    """A REST box on the canvas, pointed at an API that answers `answer`."""
    serve(monkeypatch, answer)
    made = canvas.post("/graph/nodes", data={"kind": "source", "source_kind": "rest"}).json()
    box = next(n for n in made["nodes"] if n["kind"] == "source")
    pointed = canvas.post(f"/graph/nodes/{box['id']}",
                          data={"handle": "https://api.example/list"}).json()
    return next(n for n in pointed["nodes"] if n["kind"] == "source")


def test_a_rest_box_is_added_and_shows_its_mapping(canvas, monkeypatch):
    box = rest_box(canvas, monkeypatch)
    assert box["channel"]["rest"] == {
        "items": "", "id": "", "title": "", "link": "", "published": "", "image": "",
        "summary": "", "header_name": "", "has_key": False, "error": "",
    }


def test_an_api_that_wants_a_key_can_still_be_added_and_then_given_one(canvas, monkeypatch):
    serve(monkeypatch, {"error": "unauthorised"}, status=401)
    made = canvas.post("/graph/nodes", data={"kind": "source", "source_kind": "rest"}).json()
    box = next(n for n in made["nodes"] if n["kind"] == "source")
    pointed = canvas.post(f"/graph/nodes/{box['id']}",
                          data={"handle": "https://api.example/private"})
    assert pointed.status_code == 200
    assert next(n for n in pointed.json()["nodes"] if n["kind"] == "source")["detail"]


def test_try_it_reads_with_the_fields_as_they_stand_and_saves_nothing(canvas, monkeypatch, db):
    box = rest_box(canvas, monkeypatch)
    tried = canvas.post(f"/graph/nodes/{box['id']}/rest/try",
                        data={"rest_items": "data.children", "rest_title": "data.id"}).json()
    assert tried["count"] == 2
    assert tried["paths"]["link"] == "data.url"  # guessed, and said
    assert [one["title"] for one in tried["items"]] == ["def", "abc"]
    with db.session_scope() as session:
        assert session.scalar(select(Channel).where(Channel.source_kind == "rest")
                              ).source_options is None


def test_saving_keeps_the_mapping_and_never_shows_the_key(canvas, monkeypatch, db):
    box = rest_box(canvas, monkeypatch)
    saved = canvas.post(f"/graph/nodes/{box['id']}", data={
        "box_form": "1", "active": "1", "rest_items": "data.children",
        "rest_header_name": "Authorization", "rest_header_value": "Bearer s3cret",
    })
    assert saved.status_code == 200
    assert "s3cret" not in saved.text
    shown = next(n for n in saved.json()["nodes"] if n["kind"] == "source")["channel"]["rest"]
    assert shown["items"] == "data.children" and shown["has_key"] is True

    # Saved again with the key field left empty: the key is kept.
    canvas.post(f"/graph/nodes/{box['id']}", data={
        "box_form": "1", "active": "1", "rest_header_name": "Authorization"})
    with db.session_scope() as session:
        kept = rest.Mapping.loads(session.scalar(select(Channel)).source_options)
        assert kept.header_value == "Bearer s3cret"
    assert "s3cret" not in canvas.get("/api/graph").text

    # And it can be stopped.
    canvas.post(f"/graph/nodes/{box['id']}", data={
        "box_form": "1", "active": "1", "rest_header_name": "Authorization",
        "rest_header_clear": "1"})
    with db.session_scope() as session:
        assert rest.Mapping.loads(session.scalar(select(Channel)).source_options).header_name == ""


@pytest.mark.parametrize("data, said", [
    ({"rest_url": "ftp://x"}, "web address"),
    ({"rest_header_name": "Bad Name", "rest_header_value": "x"}, "not a header name"),
    ({"rest_header_name": "X-Key"}, "Give the X-Key header a value"),
])
def test_fields_that_cannot_be_used_are_refused(canvas, monkeypatch, data, said):
    box = rest_box(canvas, monkeypatch)
    answer = canvas.post(f"/graph/nodes/{box['id']}", data={"box_form": "1", **data})
    assert answer.status_code == 400 and said in answer.json()["error"]


def test_try_it_is_only_for_rest_boxes(canvas, monkeypatch, db):
    with db.session_scope() as session:
        channel = Channel(channel_id="UCx", title="x")
        session.add(channel)
        session.flush()
        node = graph.add_source(session, channel=channel).id
    assert canvas.post(f"/graph/nodes/{node}/rest/try").status_code == 404


def test_the_palette_offers_a_rest_api_box(canvas):
    page = canvas.get("/channels").text
    assert 'data-source-kind="rest"' in page and "<strong>REST API</strong>" in page


def test_an_empty_rest_box_asks_for_an_api_address(canvas):
    made = canvas.post("/graph/nodes", data={"kind": "source", "source_kind": "rest"}).json()
    asks = next(n for n in made["nodes"] if n["kind"] == "source")["asks"]
    assert asks["kind"] == "rest" and asks["known"] is True
    assert asks["label"] == "REST API" and "JSON API" in asks["example"]
