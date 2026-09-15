"""Focus mode: playing the unwatched queue through, hands-free."""

from __future__ import annotations

import datetime as dt
import json

import pathlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from dealgo.db import get_settings
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
    start = body.index('id="focus-queue">') + len('id="focus-queue">')
    return json.loads(body[start : body.index("</script>", start)])


def test_the_queue_is_unwatched_only_and_in_playlist_order(client):
    queue = queue_of(client.get("/focus").text)

    assert [item["title"] for item in queue] == ["First science", "Second science", "A concert"]
    assert all("Already seen" != item["title"] for item in queue)
    # Science before Music, because that is the fill order.
    assert queue[0]["playlist"] == "Science"
    assert queue[-1]["playlist"] == "Music"


def test_a_single_playlist_can_be_played_through(client, db):
    with db.session_scope() as session:
        music_id = session.scalar(select(Playlist).where(Playlist.title == "Music")).id

    queue = queue_of(client.get(f"/focus?playlist={music_id}").text)
    assert [item["title"] for item in queue] == ["A concert"]


def test_newest_first_is_honoured(client):
    queue = queue_of(client.get("/focus?order=newest").text)
    assert [item["title"] for item in queue][:2] == ["Second science", "First science"]


def test_finishing_a_video_marks_it_watched_and_hands_back_the_next(client, db):
    response = client.post("/focus/1/finished", data={"order": "oldest", "playlist": ""})
    payload = response.json()

    assert payload["next"]["title"] == "Second science"
    assert payload["remaining"] == 2
    with db.session_scope() as session:
        assert session.get(Video, 1).watched_at is not None


def test_skipping_leaves_it_unwatched_but_moves_on(client, db):
    payload = client.post("/focus/1/finished", data={"watched": "0"}).json()

    assert payload["next"]["title"] == "Second science"
    with db.session_scope() as session:
        assert session.get(Video, 1).watched_at is None
    # It is out of this sitting, so it cannot be handed back immediately.
    assert payload["next"]["id"] != 1


def test_the_queue_ends_cleanly(client, db):
    with db.session_scope() as session:
        for video in session.scalars(select(Video)):
            video.watched_at = utcnow()

    payload = client.post("/focus/1/finished").json()
    assert payload["next"] is None
    assert payload["remaining"] == 0

    body = client.get("/focus").text
    assert "Nothing unwatched" in body


def test_the_next_video_is_recomputed_not_replayed_from_the_page(client, db):
    """A queue left open must not resurrect something watched elsewhere."""
    queue = queue_of(client.get("/focus").text)
    assert queue[1]["title"] == "Second science"

    # Meanwhile, that video is watched from another tab.
    with db.session_scope() as session:
        session.get(Video, 2).watched_at = utcnow()

    payload = client.post("/focus/1/finished").json()
    assert payload["next"]["title"] == "A concert"


def test_a_video_in_two_playlists_only_queues_once(client, db):
    with db.session_scope() as session:
        music = session.scalar(select(Playlist).where(Playlist.title == "Music"))
        session.add(Placement(video_pk=1, playlist_pk=music.id, playlist_item_id="dup"))

    queue = queue_of(client.get("/focus").text)
    assert [item["id"] for item in queue].count(1) == 1


def test_playing_from_one_card_starts_there(client):
    queue = queue_of(client.get("/focus?start=2").text)
    assert queue[0]["title"] == "Second science"
    assert "First science" not in [item["title"] for item in queue]


def test_starting_from_an_already_watched_video_still_plays_it(client):
    queue = queue_of(client.get("/focus?start=3").text)
    assert queue[0]["title"] == "Already seen"
    assert queue[1]["title"] == "First science"


def test_the_page_loads_its_script_and_the_controls(client):
    body = client.get("/focus").text
    assert "/static/focus.js" in body
    assert 'id="focus-player"' in body
    assert 'id="focus-next"' in body and 'id="focus-skip"' in body


def test_the_iframe_api_is_left_to_the_script(client):
    """A script tag in the page is inserted by htmx on a boosted navigation,
    where `defer` orders nothing — so it could run before the ready callback
    exists and the player would never attach."""
    assert "iframe_api" not in client.get("/focus").text


def test_the_focus_player_keeps_fullscreen_and_refuses_pip(client):
    """Left to itself the IFrame API sets allow="…; picture-in-picture; …",
    which puts the pop-out button back over the fullscreen control. Supplying
    the iframe ourselves is what prevents that."""
    import re

    body = client.get("/focus").text
    frame = re.search(r'<iframe id="focus-player".*?</iframe>', body, re.S).group(0)

    assert "allowfullscreen" in frame
    assert "picture-in-picture" not in frame
    assert "enablejsapi=1" in frame  # the API can only attach with this set
    assert "youtube-nocookie.com/embed/" in frame


def test_finishing_an_unknown_video_is_refused(client):
    assert client.post("/focus/999/finished").status_code == 404


def test_the_feed_offers_a_way_in(client):
    body = client.get("/feed").text
    assert "/focus?order=oldest" in body
    assert "/focus?start=" in body


def test_the_page_offers_a_way_to_rebuild_a_stuck_player(client):
    """An embed that fails to load leaves a blank rectangle; Reload is the way
    out, and it must be a real page load — the API only initialises on one."""
    body = client.get("/focus").text

    assert 'id="focus-reload"' in body
    assert 'hx-boost="false"' in body
    # It comes back to the video you were on, not the start of the queue.
    assert "/focus?start=" in body


def test_reloading_lands_on_the_video_it_names(client, db):
    from dealgo.models import Video

    with db.session_scope() as session:
        second = session.get(Video, 2)
        second_id = second.id

    body = client.get(f"/focus?start={second_id}").text
    assert f'href="/focus?start={second_id}' in body
    assert "Second science" in body


# -- community posts -------------------------------------------------------


def make_post(db, *, body="Something written", images=("https://i.test/a.jpg",), watched=None):
    """Put a post in the first feed, the way a sync would."""
    import json as _json

    from dealgo.models import Channel, Placement, Playlist, Video

    with db.session_scope() as session:
        channel = session.scalar(select(Channel))
        playlist = session.scalar(select(Playlist))
        post = Video(
            video_id="Ugk1",
            channel_pk=channel.id,
            kind="post",
            title=body.splitlines()[0][:80],
            body=body,
            images=_json.dumps(list(images)) if images else None,
            thumbnail_url=images[0] if images else None,
            published_at=utcnow(),
            status="added",
            watched_at=watched,
        )
        session.add(post)
        session.flush()
        session.add(
            Placement(
                video_pk=post.id,
                playlist_pk=playlist.id,
                playlist_item_id=f"generic-{playlist.id}-{post.id}",
                added_at=utcnow(),
            )
        )
        return post.id


def test_a_post_is_shown_as_tiles_and_words(client, db):
    post_id = make_post(db, body="Back on Friday", images=("https://i.test/a.jpg", "https://i.test/b.jpg"))

    body = client.get(f"/focus?start={post_id}").text

    assert "focus-tiles" in body
    assert body.count("focus-tile\"") == 2      # one tile per image
    assert "Back on Friday" in body
    assert "https://i.test/b.jpg" in body


def test_the_post_is_readable_before_the_script_runs(client, db):
    """Server-rendered, not filled in by JavaScript: the words are in the HTML."""
    post_id = make_post(db, body="Read me without JS")

    body = client.get(f"/focus?start={post_id}").text
    words = body.split('id="focus-words"', 1)[1]

    assert "Read me without JS" in words.split("</div>", 1)[0]


def test_opening_on_a_post_hides_the_player_and_shows_the_timer(client, db):
    post_id = make_post(db)

    body = client.get(f"/focus?start={post_id}").text
    stage = body.split('id="focus-stage"', 1)[1].split(">", 1)[0]
    timer = body.split('id="focus-timer"', 1)[1].split(">", 1)[0]

    assert "hidden" in stage
    assert "hidden" not in timer


def test_opening_on_a_post_does_not_autoplay_a_video_underneath(client, db):
    """The player is still there for what comes next, but it must be silent
    while something is being read."""
    post_id = make_post(db)

    body = client.get(f"/focus?start={post_id}").text

    assert "autoplay=0" in body
    assert "autoplay=1" not in body


# -- items from somewhere other than YouTube --------------------------------


def make_link(db, *, title="An article", body="Some words", link="https://example.com/a"):
    """Put an item from a feed elsewhere in the first feed, as a sync would."""
    from dealgo.models import Channel, Placement, Playlist, Video

    with db.session_scope() as session:
        channel = Channel(
            channel_id="r/python", title="r/python", source_kind="reddit",
            source_url="https://www.reddit.com/r/python/.rss",
        )
        session.add(channel)
        playlist = session.scalar(select(Playlist))
        session.flush()
        item = Video(
            video_id="item-abc",
            channel_pk=channel.id,
            kind="link",
            title=title,
            body=body,
            link=link,
            published_at=utcnow(),
            status="added",
        )
        session.add(item)
        session.flush()
        session.add(
            Placement(
                video_pk=item.id,
                playlist_pk=playlist.id,
                playlist_item_id=f"generic-{playlist.id}-{item.id}",
                added_at=utcnow(),
            )
        )
        return item.id


def test_an_item_from_a_feed_is_read_rather_than_played(client, db):
    """It has no player and no end of its own, which is the same shape as a
    community post — so it gets the reader and the timer, not the stage."""
    item_id = make_link(db)

    body = client.get(f"/focus?start={item_id}").text
    stage = body.split('id="focus-stage"', 1)[1].split(">", 1)[0]
    timer = body.split('id="focus-timer"', 1)[1].split(">", 1)[0]

    assert "hidden" in stage
    assert "hidden" not in timer
    assert "Some words" in body


def test_the_way_out_of_an_item_says_where_it_goes(client, db):
    """"Open the post on YouTube" would be a lie about a Reddit thread."""
    item_id = make_link(db, link="https://reddit.com/r/python/comments/abc")

    body = client.get(f"/focus?start={item_id}").text

    assert "Open it on Reddit" in body
    assert "https://reddit.com/r/python/comments/abc" in body


def test_an_item_from_a_feed_does_not_autoplay_underneath(client, db):
    item_id = make_link(db)

    body = client.get(f"/focus?start={item_id}").text

    assert "autoplay=0" in body
    assert "autoplay=1" not in body


def test_a_video_first_still_autoplays(client):
    body = client.get("/focus").text
    assert "autoplay=1" in body


def test_the_timer_comes_from_settings(client, db):
    from dealgo.models import Settings

    post_id = make_post(db)
    with db.session_scope() as session:
        get_settings(session).post_seconds = 45

    body = client.get(f"/focus?start={post_id}").text

    assert 'data-post-seconds="45"' in body
    assert "45s" in body


def test_a_queue_of_only_posts_loads_no_player_at_all(client, db):
    from dealgo.models import Video

    with db.session_scope() as session:
        for video in session.scalars(select(Video)):
            video.watched_at = utcnow()
    make_post(db)

    body = client.get("/focus").text

    assert "focus-post" in body
    assert "focus-player" not in body   # nothing to play, so no player at all


def test_the_old_theater_address_still_works(client, db):
    """Bookmarks and open tabs outlive a rename."""
    response = client.get("/watch?order=newest", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/focus?order=newest")


# These read the TypeScript, not the compiled JavaScript: the source is what
# anyone edits, and the compiler decides how the output reads.
FOCUS_TS = pathlib.Path("dealgo/web/ts/focus.ts")


def test_advancing_works_without_the_iframe_api():
    """The reported failure: the button posted, the title changed, and the
    video carried on playing, because the player was never attached and
    loadVideoById had nothing to call. Advancing must not depend on it."""
    body = FOCUS_TS.read_text().split("function showFocusVideo", 1)[1].split("\n}", 1)[0]

    # With no player, the iframe itself is pointed at the next video.
    assert "elements.frame.src = focusEmbedUrl(item.video_id)" in body


def test_the_player_is_built_however_the_api_turns_up():
    """YT calls onYouTubeIframeAPIReady once per document, so a second boosted
    visit never gets that callback at all."""
    script = FOCUS_TS.read_text()

    assert "function buildFocusPlayer" in script
    assert "if (sitting.player || !sitting.elements.frame || !api || !api.Player) return;" in script
    assert "setInterval" in script.split("function awaitYouTubeApi", 1)[1]   # polled too


# -- the sitting keeps its place -------------------------------------------


def queue_ids(client, path="/focus"):
    """The whole queue the page is showing: the one it opened on, then the
    up-next rows. Reload names the current item, which is the only place the
    page prints it."""
    import re

    body = client.get(path).text
    current = re.search(r'id="focus-reload"[^>]*?/focus\?start=(\d+)', body, re.S)
    rows = [int(n) for n in re.findall(r'data-video="(\d+)"', body)]
    return ([int(current.group(1))] if current else []) + rows


def test_advancing_continues_from_where_the_sitting_is(client, db):
    """The reported bug: opening Focus part-way down a feed and finishing that
    item handed back the first item of the whole queue instead of the next one,
    so the up-next list described a sitting that was not happening."""
    order = queue_ids(client)
    assert len(order) >= 3
    start, expected = order[1], order[2]

    response = client.post(
        f"/focus/{start}/finished",
        data={"order": "oldest", "playlist": "", "watched": "1"},
    )

    assert response.json()["next"]["id"] == expected


def test_the_page_and_the_server_agree_on_what_is_next(client, db):
    """Whatever the list promises is what the next advance delivers."""
    order = queue_ids(client)
    start = order[0]
    promised = queue_ids(client, f"/focus?start={start}")[1]   # [0] is playing now

    served = client.post(
        f"/focus/{start}/finished",
        data={"order": "oldest", "playlist": "", "watched": "1"},
    ).json()

    assert served["next"]["id"] == promised


def test_the_up_next_list_travels_with_each_advance(client, db):
    """The list is rebuilt from the server's queue rather than by deleting
    rows, so the two cannot drift apart."""
    order = queue_ids(client)

    payload = client.post(
        f"/focus/{order[0]}/finished",
        data={"order": "oldest", "playlist": "", "watched": "1"},
    ).json()

    assert [item["id"] for item in payload["upcoming"]] == order[2:]
    assert payload["remaining"] == len(order) - 1


def test_something_skipped_stays_out_of_the_sitting(client, db):
    """Skip means "not this one now". Rebuilding the queue each time used to
    offer it straight back."""
    order = queue_ids(client)
    first, second = order[0], order[1]

    client.post(
        f"/focus/{first}/finished",
        data={"order": "oldest", "playlist": "", "watched": "0"},
    )
    payload = client.post(
        f"/focus/{second}/finished",
        data={"order": "oldest", "playlist": "", "watched": "1", "skipped": str(first)},
    ).json()

    following = [payload["next"]["id"]] + [item["id"] for item in payload["upcoming"]]
    assert first not in following


def test_a_skipped_video_is_still_unwatched_afterwards(client, db):
    from dealgo.models import Video

    order = queue_ids(client)
    client.post(
        f"/focus/{order[0]}/finished",
        data={"order": "oldest", "playlist": "", "watched": "0"},
    )

    with db.session_scope() as session:
        assert session.get(Video, order[0]).watched_at is None
