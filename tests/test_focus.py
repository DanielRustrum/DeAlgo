"""Theater mode: playing the unwatched queue through, hands-free."""

from __future__ import annotations

import datetime as dt
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from dealgo.models import Channel, Placement, Playlist, Video, utcnow


@pytest.fixture
def client(db, monkeypatch):
    from dealgo import scheduler
    from dealgo.web import app as web_app

    monkeypatch.setattr(scheduler, "start", lambda: None)
    monkeypatch.setattr(scheduler, "shutdown", lambda: None)
    monkeypatch.setattr(scheduler, "next_run_time", lambda: None)
    monkeypatch.setattr(web_app, "init_db", lambda: None)

    with db.session_scope() as session:
        science = Playlist(playlist_id="PL_sci", title="Science", priority=0)
        music = Playlist(playlist_id="PL_mus", title="Music", priority=1)
        channel = Channel(channel_id="UCzzzzzzzzzzzzzzzzzzzzzz", title="A Channel")
        session.add_all([science, music, channel])
        session.flush()

        for index, (playlist, title, minutes, watched) in enumerate(
            [
                (science, "First science", 500, None),
                (science, "Second science", 300, None),
                (science, "Already seen", 400, utcnow()),
                (music, "A concert", 100, None),
            ],
            start=1,
        ):
            video = Video(
                video_id=f"v{index}",
                channel_pk=channel.id,
                title=title,
                published_at=utcnow() - dt.timedelta(minutes=minutes),
                status="added",
                watched_at=watched,
            )
            session.add(video)
            session.flush()
            session.add(
                Placement(video_pk=video.id, playlist_pk=playlist.id, playlist_item_id=f"i{index}")
            )

    with TestClient(web_app.app) as test_client:
        yield test_client


def queue_of(body: str) -> list[dict]:
    start = body.index('id="theater-queue">') + len('id="theater-queue">')
    return json.loads(body[start : body.index("</script>", start)])


def test_the_queue_is_unwatched_only_and_in_playlist_order(client):
    queue = queue_of(client.get("/watch").text)

    assert [item["title"] for item in queue] == ["First science", "Second science", "A concert"]
    assert all("Already seen" != item["title"] for item in queue)
    # Science before Music, because that is the fill order.
    assert queue[0]["playlist"] == "Science"
    assert queue[-1]["playlist"] == "Music"


def test_a_single_playlist_can_be_played_through(client, db):
    with db.session_scope() as session:
        music_id = session.scalar(select(Playlist).where(Playlist.title == "Music")).id

    queue = queue_of(client.get(f"/watch?playlist={music_id}").text)
    assert [item["title"] for item in queue] == ["A concert"]


def test_newest_first_is_honoured(client):
    queue = queue_of(client.get("/watch?order=newest").text)
    assert [item["title"] for item in queue][:2] == ["Second science", "First science"]


def test_finishing_a_video_marks_it_watched_and_hands_back_the_next(client, db):
    response = client.post("/watch/1/finished", data={"order": "oldest", "playlist": ""})
    payload = response.json()

    assert payload["next"]["title"] == "Second science"
    assert payload["remaining"] == 2
    with db.session_scope() as session:
        assert session.get(Video, 1).watched_at is not None


def test_skipping_leaves_it_unwatched_but_moves_on(client, db):
    payload = client.post("/watch/1/finished", data={"watched": "0"}).json()

    assert payload["next"]["title"] == "Second science"
    with db.session_scope() as session:
        assert session.get(Video, 1).watched_at is None
    # It is out of this sitting, so it cannot be handed back immediately.
    assert payload["next"]["id"] != 1


def test_the_queue_ends_cleanly(client, db):
    with db.session_scope() as session:
        for video in session.scalars(select(Video)):
            video.watched_at = utcnow()

    payload = client.post("/watch/1/finished").json()
    assert payload["next"] is None
    assert payload["remaining"] == 0

    body = client.get("/watch").text
    assert "Nothing unwatched to play" in body


def test_the_next_video_is_recomputed_not_replayed_from_the_page(client, db):
    """A queue left open must not resurrect something watched elsewhere."""
    queue = queue_of(client.get("/watch").text)
    assert queue[1]["title"] == "Second science"

    # Meanwhile, that video is watched from another tab.
    with db.session_scope() as session:
        session.get(Video, 2).watched_at = utcnow()

    payload = client.post("/watch/1/finished").json()
    assert payload["next"]["title"] == "A concert"


def test_a_video_in_two_playlists_only_queues_once(client, db):
    with db.session_scope() as session:
        music = session.scalar(select(Playlist).where(Playlist.title == "Music"))
        session.add(Placement(video_pk=1, playlist_pk=music.id, playlist_item_id="dup"))

    queue = queue_of(client.get("/watch").text)
    assert [item["id"] for item in queue].count(1) == 1


def test_playing_from_one_card_starts_there(client):
    queue = queue_of(client.get("/watch?start=2").text)
    assert queue[0]["title"] == "Second science"
    assert "First science" not in [item["title"] for item in queue]


def test_starting_from_an_already_watched_video_still_plays_it(client):
    queue = queue_of(client.get("/watch?start=3").text)
    assert queue[0]["title"] == "Already seen"
    assert queue[1]["title"] == "First science"


def test_the_page_loads_the_iframe_api_and_the_controls(client):
    body = client.get("/watch").text
    assert "https://www.youtube.com/iframe_api" in body
    assert "/static/theater.js" in body
    assert 'id="theater-player"' in body
    assert 'id="theater-next"' in body and 'id="theater-skip"' in body


def test_the_theater_player_keeps_fullscreen_and_refuses_pip(client):
    """Left to itself the IFrame API sets allow="…; picture-in-picture; …",
    which puts the pop-out button back over the fullscreen control. Supplying
    the iframe ourselves is what prevents that."""
    import re

    body = client.get("/watch").text
    frame = re.search(r'<iframe id="theater-player".*?</iframe>', body, re.S).group(0)

    assert "allowfullscreen" in frame
    assert "picture-in-picture" not in frame
    assert "enablejsapi=1" in frame  # the API can only attach with this set
    assert "youtube-nocookie.com/embed/" in frame


def test_finishing_an_unknown_video_is_refused(client):
    assert client.post("/watch/999/finished").status_code == 404


def test_the_feed_offers_a_way_in(client):
    body = client.get("/feed").text
    assert "/watch?order=oldest" in body
    assert "/watch?start=" in body


def test_the_page_offers_a_way_to_rebuild_a_stuck_player(client):
    """An embed that fails to load leaves a blank rectangle; Reload is the way
    out, and it must be a real page load — the API only initialises on one."""
    body = client.get("/watch").text

    assert 'id="theater-reload"' in body
    assert 'hx-boost="false"' in body
    # It comes back to the video you were on, not the start of the queue.
    assert "/watch?start=" in body


def test_reloading_lands_on_the_video_it_names(client, db):
    from dealgo.models import Video

    with db.session_scope() as session:
        second = session.get(Video, 2)
        second_id = second.id

    body = client.get(f"/watch?start={second_id}").text
    assert f'href="/watch?start={second_id}' in body
    assert "Second science" in body
