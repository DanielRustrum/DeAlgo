"""The Feed page: what is in each playlist, laid out to watch."""

from __future__ import annotations

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

    import datetime as dt

    with db.session_scope() as session:
        science = Playlist(playlist_id="PL_sci", title="Science", priority=0)
        music = Playlist(playlist_id="PL_mus", title="Music", priority=1)
        channel = Channel(channel_id="UCzzzzzzzzzzzzzzzzzzzzzz", title="A Channel")
        session.add_all([science, music, channel])
        session.flush()

        for index, (playlist, title, minutes, watched) in enumerate(
            [
                (science, "Old science video", 500, None),
                (science, "New science video", 50, None),
                (science, "Seen already", 200, utcnow()),
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
                Placement(
                    video_pk=video.id, playlist_pk=playlist.id, playlist_item_id=f"item-{index}"
                )
            )

    with TestClient(web_app.app) as test_client:
        yield test_client


def order_of(body: str) -> list[str]:
    import re

    return re.findall(r"watch\?v=(v\d)", body)[::2]  # each card links its video twice


def test_the_feed_is_a_tab(client):
    assert '<a href="/feed"' in client.get("/").text
    assert client.get("/feed").status_code == 200


def test_videos_are_grouped_under_their_playlist(client):
    body = client.get("/feed").text
    assert "Science" in body and "Music" in body
    # The section header links to the playlist on YouTube.
    assert "playlist?list=PL_sci" in body
    assert "playlist?list=PL_mus" in body
    # Science comes first because it is first in the fill order.
    assert body.index("PL_sci") < body.index("PL_mus")


def test_watched_videos_are_hidden_by_default(client):
    body = client.get("/feed").text
    assert "Seen already" not in body
    # …and the count says what is being held back.
    assert "2 of 3" in body

    everything = client.get("/feed?show=all").text
    assert "Seen already" in everything
    assert "card-watched" in everything


def test_oldest_first_by_default_and_newest_on_request(client):
    assert order_of(client.get("/feed").text)[:2] == ["v1", "v2"]
    assert order_of(client.get("/feed?order=newest").text)[:2] == ["v2", "v1"]


def test_one_playlist_can_be_singled_out(client, db):
    with db.session_scope() as session:
        music = session.scalar(select(Playlist).where(Playlist.title == "Music"))
        music_id = music.id

    body = client.get(f"/feed?playlist={music_id}").text
    assert "A concert" in body
    assert "Old science video" not in body


def test_a_caught_up_playlist_says_so(client, db):
    with db.session_scope() as session:
        for video in session.scalars(select(Video)):
            video.watched_at = utcnow()

    body = client.get("/feed").text
    assert "All 3 watched" in body
    assert "All 1 watched" in body


def test_the_player_is_embedded_rather_than_linking_away(client):
    card = client.get("/feed").text
    assert "/partials/player/1" in card

    player = client.get("/partials/player/1", headers={"HX-Request": "true"}).text
    assert "youtube-nocookie.com/embed/v1" in player
    assert "autoplay=1" in player
    assert "<html" not in player.lower()
    assert "allowfullscreen" in player


def test_the_player_does_not_ask_for_picture_in_picture(client):
    """The browser floats its pop-out button over YouTube's fullscreen control.

    Fullscreen is a separate permission and must survive.
    """
    player = client.get("/partials/player/1", headers={"HX-Request": "true"}).text
    assert "picture-in-picture" not in player
    assert "allowfullscreen" in player


def test_marking_watched_from_the_feed_returns_a_card(client, db):
    response = client.post(
        "/videos/1/watched", data={"view": "feed"}, headers={"HX-Request": "true"}
    )
    assert response.status_code == 200
    assert 'id="feed-card-1"' in response.text
    assert "card-watched" in response.text
    assert "<tr" not in response.text
    with db.session_scope() as session:
        assert session.get(Video, 1).watched_at is not None


def test_the_videos_page_still_gets_a_table_row(client):
    response = client.post("/videos/1/watched", headers={"HX-Request": "true"})
    assert response.text.strip().startswith('<tr id="video-1"')


def test_a_video_removed_from_a_playlist_leaves_the_feed(client, db):
    assert "Old science video" in client.get("/feed").text

    with db.session_scope() as session:
        placement = session.scalar(select(Placement).where(Placement.video_pk == 1))
        placement.playlist_item_id = None  # as a watched-removal would leave it

    assert "Old science video" not in client.get("/feed").text
