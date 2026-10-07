"""The Feed tab's shelf: every feed as a tile, favourites first, in your own order.

Where a feed sits is the account's arrangement and nothing else: starring and
moving change the shelf, never `priority`, which is the order feeds are filled
in when the quota runs short.
"""

from __future__ import annotations

import datetime as dt
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from pamphlets.models import Channel, Placement, Playlist, Video, utcnow
from pamphlets.services.playlists import shelf as shelf_service

TITLES = ["Alpha", "Bravo", "Charlie", "Delta"]


@pytest.fixture
def client(db, monkeypatch):
    from pamphlets import scheduler
    from pamphlets.web import app as web_app

    monkeypatch.setattr(scheduler, "start", lambda: None)
    monkeypatch.setattr(scheduler, "shutdown", lambda: None)
    monkeypatch.setattr(scheduler, "next_run_time", lambda: None)
    monkeypatch.setattr(web_app, "init_db", lambda: None)

    with db.session_scope() as session:
        channel = Channel(channel_id="UCzzzzzzzzzzzzzzzzzzzzzz", title="A Channel")
        session.add(channel)
        feeds = [
            # Fill order is the reverse of the shelf's, to show they are apart.
            Playlist(playlist_id=f"generic:{title}", title=title, priority=10 - index)
            for index, title in enumerate(TITLES)
        ]
        session.add_all(feeds)
        session.flush()
        # Charlie has the most waiting, and Bravo the latest arrival.
        for feed, waiting, minutes in ((feeds[2], 3, 300), (feeds[1], 1, 5), (feeds[0], 1, 900)):
            for n in range(waiting):
                video = Video(
                    video_id=f"{feed.title}-{n}", channel_pk=channel.id, title=f"{feed.title} {n}",
                    published_at=utcnow(), status="added",
                )
                session.add(video)
                session.flush()
                session.add(Placement(
                    video_pk=video.id, playlist_pk=feed.id, playlist_item_id=f"generic-{video.id}",
                    added_at=utcnow() - dt.timedelta(minutes=minutes),
                ))

    with TestClient(web_app.app) as test_client:
        yield test_client


def ids(db) -> dict[str, int]:
    with db.session_scope() as session:
        return {p.title: p.id for p in session.scalars(select(Playlist))}


def shelf_order(body: str) -> list[str]:
    """Every tile's title, in the order the shelf draws them."""
    return re.findall(r'<span class="tile-title">([^<]+)</span>', body)


def part(body: str, which: str) -> list[str]:
    """The titles in one part of the shelf: favourites, or the rest."""
    found = re.search(rf'data-shelf-part="{which}">(.*?)</ul>', body, re.S)
    return shelf_order(found.group(1)) if found else []


def test_the_shelf_starts_in_the_order_feeds_were_made(client):
    assert shelf_order(client.get("/feed").text) == TITLES


def test_a_star_puts_a_feed_at_the_top(client, db):
    feed = ids(db)["Charlie"]
    answer = client.post(f"/feeds/{feed}/favorite", data={"on": "1"}, headers={"HX-Request": "true"})

    assert part(answer.text, "favourites") == ["Charlie"]
    assert part(answer.text, "rest") == ["Alpha", "Bravo", "Delta"]
    assert "★ Favourites" in answer.text and "Everything else" in answer.text

    client.post(f"/feeds/{feed}/favorite", data={"on": "0"})
    assert part(client.get("/feed").text, "favourites") == []


def test_a_new_favourite_joins_the_end_of_the_favourites(client, db):
    feeds = ids(db)
    for title in ("Delta", "Alpha"):
        client.post(f"/feeds/{feeds[title]}/favorite", data={"on": "1"})
    assert part(client.get("/feed").text, "favourites") == ["Delta", "Alpha"]


def test_arrows_move_a_feed_within_its_part(client, db):
    feeds = ids(db)
    client.post(f"/feeds/{feeds['Delta']}/move", data={"where": "first"})
    assert shelf_order(client.get("/feed").text) == ["Delta", "Alpha", "Bravo", "Charlie"]

    client.post(f"/feeds/{feeds['Alpha']}/move", data={"where": "later"})
    assert shelf_order(client.get("/feed").text) == ["Delta", "Bravo", "Alpha", "Charlie"]

    client.post(f"/feeds/{feeds['Delta']}/move", data={"where": "last"})
    client.post(f"/feeds/{feeds['Bravo']}/move", data={"where": "earlier"})  # already first
    assert shelf_order(client.get("/feed").text) == ["Bravo", "Alpha", "Charlie", "Delta"]


def test_dragging_sends_the_whole_order(client, db):
    feeds = ids(db)
    order = ",".join(str(feeds[t]) for t in ["Charlie", "Alpha", "Delta", "Bravo"])
    answer = client.post("/feed/arrange", data={"order": order}, headers={"HX-Request": "true"})
    assert shelf_order(answer.text) == ["Charlie", "Alpha", "Delta", "Bravo"]


def test_an_arrangement_from_a_stale_page_loses_nothing(client, db):
    """A feed missing from the order keeps its place after those given, and an
    id that is not this account's (or nobody's) is ignored."""
    feeds = ids(db)
    order = f"{feeds['Delta']},999999,{feeds['Bravo']}"
    client.post("/feed/arrange", data={"order": order})
    assert shelf_order(client.get("/feed").text) == ["Delta", "Bravo", "Alpha", "Charlie"]


def test_arranging_never_touches_the_fill_order(client, db):
    feeds = ids(db)
    client.post(f"/feeds/{feeds['Alpha']}/favorite", data={"on": "1"})
    client.post(f"/feeds/{feeds['Delta']}/move", data={"where": "first"})
    with db.session_scope() as session:
        assert {p.title: p.priority for p in session.scalars(select(Playlist))} == {
            "Alpha": 10, "Bravo": 9, "Charlie": 8, "Delta": 7,
        }


@pytest.mark.parametrize("sort, expected", [
    ("name", ["Alpha", "Bravo", "Charlie", "Delta"]),
    ("waiting", ["Charlie", "Alpha", "Bravo", "Delta"]),
    ("recent", ["Bravo", "Charlie", "Alpha", "Delta"]),
])
def test_other_sorts_are_views_that_change_nothing(client, db, sort, expected):
    client.post(f"/feeds/{ids(db)['Delta']}/move", data={"where": "first"})
    assert shelf_order(client.get(f"/feed?sort={sort}").text) == expected
    # Your own order is still yours.
    assert shelf_order(client.get("/feed").text)[0] == "Delta"


def test_favourites_stay_on_top_whatever_the_sort(client, db):
    client.post(f"/feeds/{ids(db)['Delta']}/favorite", data={"on": "1"})
    assert shelf_order(client.get("/feed?sort=waiting").text)[0] == "Delta"


def test_a_tile_shows_what_is_waiting_and_its_latest_items(client, db):
    body = client.get("/feed").text
    charlie = re.search(r'<li class="feed-tile[^>]*data-feed="%d".*?</li>' % ids(db)["Charlie"],
                        body, re.S).group(0)
    assert 'class="tile-count"' in charlie and ">3<" in charlie
    assert "tile-mosaic-3" in charlie
    assert "last arrival" in charlie
    delta = re.search(r'<li class="feed-tile[^>]*data-feed="%d".*?</li>' % ids(db)["Delta"],
                      body, re.S).group(0)
    assert "Nothing yet" in delta and "tile-count" not in delta


def test_arranging_shows_handles_and_the_whole_shelf(client, db):
    with db.session_scope() as session:
        session.scalar(select(Playlist).where(Playlist.title == "Alpha")).tags = "news"

    body = client.get("/feed?arrange=1&tag=news&sort=name").text
    shelf = body.split('id="feed-shelf"', 1)[1]
    # Every feed, in your order, whatever filter was on.
    assert shelf_order(shelf) == TITLES
    assert 'draggable="true"' in shelf and 'class="tile-moves"' in shelf
    assert "/static/shelf.js" in body
    # And not otherwise.
    plain = client.get("/feed").text
    assert 'draggable="true"' not in plain and "tile-moves" not in plain


def test_the_star_is_on_the_feeds_own_page_too(client, db):
    feed = ids(db)["Bravo"]
    page = client.get(f"/feed/{feed}").text
    assert 'action="/feeds/%d/favorite"' % feed in page
    assert '<a href="/feed">Feeds</a>' in page  # the way back to the shelf

    star = client.post(f"/feeds/{feed}/favorite", data={"on": "1", "back": "feed"},
                       headers={"HX-Request": "true"})
    assert 'aria-pressed="true"' in star.text and "feed-shelf" not in star.text
    assert part(client.get("/feed").text, "favourites") == ["Bravo"]


def test_set_favorite_twice_is_harmless(db, client):
    with db.session_scope() as session:
        feed = session.scalar(select(Playlist).where(Playlist.title == "Alpha"))
        shelf_service.set_favorite(session, feed, True)
        shelf_service.set_favorite(session, feed, True)
        assert feed.favorite and feed.shelf_position == 0


def test_an_unknown_feed_cannot_be_starred_moved_or_opened(client):
    assert "err=" in client.post("/feeds/999999/favorite", follow_redirects=False).headers["location"]
    assert "err=" in client.post("/feeds/999999/move", data={"where": "first"},
                                 follow_redirects=False).headers["location"]
    assert "err=" in client.get("/feed/999999", follow_redirects=False).headers["location"]


def test_one_account_cannot_reach_anothers_feeds(db, monkeypatch):
    from fakes import use_config
    from pamphlets import config, scheduler
    from pamphlets.services import accounts
    from pamphlets.web import app as web_app

    secured = config.Config(**{**config.CONFIG.__dict__, "admin_user": "admin", "admin_password": "admin"})
    use_config(monkeypatch, secured)
    monkeypatch.setattr(scheduler, "start", lambda: None)
    monkeypatch.setattr(scheduler, "shutdown", lambda: None)
    monkeypatch.setattr(scheduler, "next_run_time", lambda: None)
    monkeypatch.setattr(web_app, "init_db", lambda: None)
    with db.session_scope() as session:
        admin = accounts.ensure_admin(session)
        accounts.create_user(session, "sam", "member-password")
        theirs = Playlist(playlist_id="generic:theirs", title="Theirs", owner_pk=admin.id)
        session.add(theirs)
        session.flush()
        theirs_id = theirs.id

    sam = TestClient(web_app.app)
    sam.post("/login", data={"username": "sam", "password": "member-password"})

    assert "err=" in sam.post(f"/feeds/{theirs_id}/favorite", follow_redirects=False).headers["location"]
    assert "err=" in sam.post(f"/feeds/{theirs_id}/move", data={"where": "last"},
                              follow_redirects=False).headers["location"]
    assert "err=" in sam.get(f"/feed/{theirs_id}", follow_redirects=False).headers["location"]
    sam.post("/feed/arrange", data={"order": str(theirs_id)})
    sam.post(f"/feeds/{theirs_id}/view", data={"show": "all"})
    assert "Theirs" not in sam.get("/feed").text

    with db.session_scope() as session:
        untouched = session.get(Playlist, theirs_id)
        assert not untouched.favorite and untouched.shelf_position == 0
        assert untouched.view_show == "unwatched"
