"""The Feed page: what is in each playlist, laid out to watch."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from dealgo.models import Channel, OAuthToken, Placement, Playlist, Video, utcnow


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
        # These feeds write to YouTube, so the page is exercised signed in.
        # The signed-out shape has its own tests below.
        session.add(OAuthToken(id=1, access_token="tok", account_title="Someone"))
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

    # The thumbnail links by row id; the fixture's v1..v4 share that numbering.
    return [f"v{pk}" for pk in re.findall(r"focus\?start=(\d+)", body)]


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


def test_watched_videos_are_hidden_by_default(client, db):
    from dealgo.models import Playlist

    body = client.get("/feed").text
    assert "Seen already" not in body
    # …and the count says what is being held back.
    assert "2 of 3" in body

    # Each feed decides for itself, and remembers.
    with db.session_scope() as session:
        session.scalar(select(Playlist).where(Playlist.title == "Science")).view_show = "all"

    everything = client.get("/feed").text
    assert "Seen already" in everything
    assert "card-watched" in everything


def test_showing_everything_is_set_on_one_feed_only(client, db):
    from dealgo.models import Placement, Playlist, Video, utcnow

    with db.session_scope() as session:
        music = session.scalar(select(Playlist).where(Playlist.title == "Music"))
        session.scalar(select(Video).where(Video.title == "A concert")).watched_at = utcnow()
        music_id = music.id

    client.post(f"/feeds/{music_id}/view", data={"show": "all"}, headers={"HX-Request": "true"})

    with db.session_scope() as session:
        assert session.get(Playlist, music_id).view_show == "all"
        # The other feed is untouched.
        science = session.scalar(select(Playlist).where(Playlist.title == "Science"))
        assert science.view_show == "unwatched"

    body = client.get("/feed").text
    assert "A concert" in body          # watched, but its feed shows everything
    assert "Seen already" not in body   # the other feed still hides them


def test_oldest_first_by_default_and_newest_per_feed(client, db):
    from dealgo.models import Playlist

    assert order_of(client.get("/feed").text)[:2] == ["v1", "v2"]

    with db.session_scope() as session:
        science = session.scalar(select(Playlist).where(Playlist.title == "Science"))
        science_id = science.id

    client.post(
        f"/feeds/{science_id}/view", data={"order": "newest"}, headers={"HX-Request": "true"}
    )
    assert order_of(client.get("/feed").text)[:2] == ["v2", "v1"]

    with db.session_scope() as session:
        # Set on that feed, remembered, and not imposed on the other.
        assert session.get(Playlist, science_id).view_order == "newest"
        music = session.scalar(select(Playlist).where(Playlist.title == "Music"))
        assert music.view_order == "oldest"


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


def test_a_thumbnail_opens_focus_mode(client, db):
    """One click starts a sitting rather than a single play."""
    import re

    from dealgo.models import Playlist

    with db.session_scope() as session:
        science = session.scalar(select(Playlist).where(Playlist.title == "Science"))
        science.view_order = "newest"
        science_id = science.id

    body = client.get("/feed").text
    thumb = re.search(r'<a class="card-thumb"[^>]*>', body).group(0)

    assert "/focus?start=" in thumb
    # It starts inside the feed you clicked from, in that feed's own order.
    assert f"playlist={science_id}" in thumb
    assert "order=newest" in thumb
    # The title is the link's accessible name rather than printed text.
    assert "New science video" in thumb

    # The inline player it replaced is gone entirely.
    assert "/partials/player/" not in body
    assert client.get("/partials/player/1").status_code == 404


def test_a_card_outside_a_section_still_opens_focus(client):
    """A card re-rendered on its own has no section; Focus starts from the
    whole queue rather than erroring."""
    response = client.post(
        "/videos/1/watched", data={"view": "feed"}, headers={"HX-Request": "true"}
    )
    assert response.status_code == 200
    assert "/focus?start=1" in response.text
    assert "playlist=" not in response.text.split("card-thumb")[1][:120]


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


def test_the_watch_page_does_not_label_generic_feeds(client, db):
    """Whether a feed writes to YouTube is a setting, not something you need
    while choosing what to watch."""
    from dealgo.models import Playlist

    with db.session_scope() as session:
        session.scalar(select(Playlist).where(Playlist.title == "Music")).playlist_id = "generic:x"

    assert ">generic<" not in client.get("/feed").text
    # Nor in the list you scan; only where the setting itself lives.
    assert ">generic<" not in client.get("/channels").text


def test_feed_sections_start_collapsed(client):
    """With several feeds the page should open as an index, not a wall."""
    body = client.get("/feed").text

    assert "<details id=\"feed-" in body
    assert "<summary>" in body
    # No section carries the open attribute.
    import re

    assert not re.search(r"<details id=\"feed-\d+\" open", body)


def test_a_section_summary_is_only_a_toggle(client):
    """A link inside <summary> would fire the toggle when clicked."""
    import re

    body = client.get("/feed").text
    summary = re.search(r"<summary>.*?</summary>", body, re.S).group(0)

    assert "<a " not in summary
    assert "<button" not in summary
    assert "Science" in summary  # the title is there, just not as a link


def test_the_actions_moved_into_the_section_body(client):
    body = client.get("/feed").text

    assert "/focus?order=oldest&playlist=" in body   # focus mode
    assert "playlist?list=PL_sci" in body            # the YouTube link
    assert "/feeds/" in body                         # and its settings page


def test_open_sections_survive_a_refresh(client):
    """A sync landing mid-browse must not fold a section shut."""
    page = client.get("/").text
    assert "/static/sections.js" in page


def test_the_controls_sit_inside_each_section(client):
    """Show and order belong to a feed, so they render once per feed."""
    import re

    body = client.get("/feed").text
    sections = re.findall(r"<section class=\"panel feed-section\">.*?</section>", body, re.S)
    assert len(sections) == 2

    for section in sections:
        assert 'class="section-view"' in section
        assert "/view" in section          # posts to that feed
        assert "unwatched" in section and "oldest first" in section

    # And no page-wide pair remains. (The Focus link's tooltip mentions
    # "unwatched", so look for the controls themselves, not the word.)
    header = body.split('id="feed-sections"')[0]
    assert 'class="section-view"' not in header
    assert "/view" not in header
    assert "oldest first" not in header


def test_each_section_launches_focus_its_own_way(client, db):
    from dealgo.models import Playlist

    with db.session_scope() as session:
        science = session.scalar(select(Playlist).where(Playlist.title == "Science"))
        science.view_order = "newest"
        science_id = science.id

    body = client.get("/feed").text
    assert f"/focus?order=newest&playlist={science_id}" in body


def test_feeds_can_be_tagged_and_searched_by_tag(client, db):
    from dealgo.models import Playlist
    from dealgo.services import playlists as playlist_service

    with db.session_scope() as session:
        science = session.scalar(select(Playlist).where(Playlist.title == "Science"))
        applied = playlist_service.set_tags(session, science, "Long-form,  WEEKLY , long-form")
        assert applied == ["long-form", "weekly"]  # trimmed, lowercased, deduped

    body = client.get("/feed").text
    assert "long-form" in body  # shown on the section

    hits = client.get("/feed?q=weekly").text
    assert "Science" in hits
    assert "Music" not in hits

    # By name still, and both are partial and order-free.
    assert "Science" in client.get("/feed?q=scien").text
    assert "No feed matches" in client.get("/feed?q=nothinglikethis").text


def test_the_feed_select_is_now_a_search_box(client):
    body = client.get("/feed").text

    assert 'name="q"' in body
    assert "Search feeds and tags…" in body
    # The old dropdown of every feed is gone.
    assert "Every feed" not in body


def test_the_feed_search_survives_typing(client):
    """As on the other pages, the box must sit outside what it swaps."""
    body = client.get("/feed").text
    assert body.index('name="q"') < body.index('id="feed-sections"')
    assert 'hx-target="#feed-sections"' in body


def test_tags_are_edited_on_the_feeds_own_page(client, db):
    from dealgo.models import Playlist

    assert 'name="tags"' in client.get("/feeds/1").text

    response = client.post(
        "/settings/playlists/1/tags",
        data={"tags": "science, deep dives", "back": "/feeds/1"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    with db.session_scope() as session:
        assert session.get(Playlist, 1).tag_list == ["science", "deep dives"]

    # Clearing them says so rather than failing.
    client.post("/settings/playlists/1/tags", data={"tags": "  "}, headers={"HX-Request": "true"})
    with db.session_scope() as session:
        assert session.get(Playlist, 1).tags is None


def test_a_card_shows_only_a_thumbnail_and_a_timestamp(client, db):
    """Everything else was noise once the thumbnail opens Focus mode."""
    import re

    from dealgo.models import Video

    with db.session_scope() as session:
        session.get(Video, 1).thumbnail_url = "https://i.ytimg.example/1.jpg"

    body = client.get("/feed").text
    card = re.search(r'<article class="card[^"]*".*?</article>', body, re.S).group(0)

    assert "<img" in card and "card-age" in card
    # No printed title, channel line, or labelled buttons.
    assert "card-title" not in card
    assert "Mark watched</button>" not in card
    assert "YouTube ↗" not in card

    # The title is still the link's name, so hover and screen readers have it.
    assert 'alt="Old science video"' in card
    assert "Old science video" in re.search(r'<a class="card-thumb"[^>]*>', card).group(0)


# -- a window on when a feed may be read ------------------------------------


def daily_window(db, *, minutes=90, last_fired_at=None):
    """Pieces under the Science feed: 90 minutes once you sit down, and
    another 90 every midnight."""
    from dealgo.models import GraphNode, Playlist

    with db.session_scope() as session:
        science = session.scalar(select(Playlist).where(Playlist.title == "Science"))
        feed = GraphNode(kind="feed", playlist_pk=science.id, enabled=True, x=0, y=0)
        session.add(feed)
        session.flush()
        timer = GraphNode(
            kind="timer", duration_minutes=minutes, enabled=True,
            attached_to=feed.id, last_fired_at=last_fired_at, x=0, y=0,
        )
        session.add(timer)
        session.flush()
        session.add(GraphNode(
            kind="reset", cron="0 0 * * *", enabled=True,
            attached_to=timer.id, x=0, y=0,
        ))
        return timer.id


def test_a_daily_window_is_open_when_you_first_come_to_it(client, db):
    """The bug this replaces: "90 min in every 1 day" was counted from the
    Unix epoch, so the feed was shut for all but the 90 minutes after midnight
    UTC — whatever hour you actually sat down."""
    daily_window(db)

    body = client.get("/feed").text

    assert "This feed is shut" not in body
    assert "Old science video" in body


def test_coming_to_the_feed_starts_the_sitting(client, db):
    from dealgo.models import GraphNode

    pulse_pk = daily_window(db)
    client.get("/feed")

    with db.session_scope() as session:
        assert session.get(GraphNode, pulse_pk).last_fired_at is not None


def test_a_spent_sitting_shuts_the_feed_and_says_when_it_opens(client, db):
    import datetime as dt

    daily_window(db, last_fired_at=utcnow() - dt.timedelta(hours=12))

    body = client.get("/feed").text

    assert "This feed is shut" in body
    assert "90 minutes once you start reading" in body
    # The thing actually worth knowing, rather than leaving you to work it out.
    assert "It opens again" in body


def test_a_sync_landing_does_not_spend_the_days_reading(client, db):
    """The sections refresh themselves when a sync finishes. Nobody arrived,
    so that must not start the sitting."""
    from dealgo.models import GraphNode

    pulse_pk = daily_window(db)
    client.get("/partials/feed", headers={"HX-Request": "true"})

    with db.session_scope() as session:
        assert session.get(GraphNode, pulse_pk).last_fired_at is None


def test_a_card_for_an_item_from_elsewhere_says_where_it_came_from(client, db):
    """There is no duration to show and nothing to play, so the card says
    which kind of somewhere it is and leads out to it."""
    import re

    from dealgo.models import Channel, Placement, Playlist, Video

    with db.session_scope() as session:
        source = Channel(
            channel_id="r/python", title="r/python", source_kind="reddit",
            source_url="https://www.reddit.com/r/python/.rss",
        )
        session.add(source)
        playlist = session.scalar(select(Playlist).where(Playlist.title == "Science"))
        session.flush()
        item = Video(
            video_id="item-abc", channel_pk=source.id, kind="link",
            title="An article", body="Its opening words",
            link="https://reddit.com/r/python/comments/abc",
            published_at=utcnow(), status="added",
        )
        session.add(item)
        session.flush()
        session.add(
            Placement(video_pk=item.id, playlist_pk=playlist.id, playlist_item_id="generic-1-5")
        )
        item_pk = item.id

    body = client.get("/feed").text
    card = re.search(
        rf'<article class="card[^"]*" *\n? *id="feed-card-{item_pk}".*?</article>', body, re.S
    ).group(0)

    assert "card-link" in card
    # Where a duration would be. Written as its kind is written, and lowered
    # by the stylesheet the same way "post" is.
    assert ">Reddit</span>" in card
    assert "Its opening words" in card          # no thumbnail, so its words
    assert 'title="Open on Reddit"' in card
    assert "https://reddit.com/r/python/comments/abc" in card


def test_the_watched_action_is_still_reachable_from_a_card(client, db):
    """Quiet, not gone: it appears on hover and works from the keyboard."""
    import re

    from dealgo.models import Video

    body = client.get("/feed").text
    card = re.search(r'<article class="card[^"]*".*?</article>', body, re.S).group(0)
    assert "/videos/1/watched" in card
    assert "card-quick" in card

    client.post("/videos/1/watched", data={"view": "feed"}, headers={"HX-Request": "true"})
    with db.session_scope() as session:
        assert session.get(Video, 1).watched_at is not None


def signed_out(db):
    """Drop the account the fixture set up."""
    with db.session_scope() as session:
        token = session.get(OAuthToken, 1)
        if token is not None:
            session.delete(token)


def test_without_an_account_the_feed_page_warns(client, db):
    signed_out(db)

    body = client.get("/feed").text

    assert 'data-toast="no-google"' in body
    assert "No Google account is connected" in body
    assert "2 feeds point at a YouTube playlist" in body


def test_without_an_account_youtube_feeds_read_as_local(client, db):
    """Greyed out and labelled, rather than offering a link to a playlist
    that De-Algo is no longer keeping up to date."""
    signed_out(db)

    body = client.get("/feed").text

    assert "pill-dormant" in body
    assert "playlist?list=PL_sci" not in body


def test_the_warning_names_a_stale_account_differently(client, db):
    """A revoked grant is not the same as never having connected one."""
    with db.session_scope() as session:
        session.get(OAuthToken, 1).refresh_error = "invalid_grant"

    body = client.get("/feed").text

    assert "needs reconnecting" in body


def test_a_connected_account_gets_no_warning(client):
    body = client.get("/feed").text

    assert 'data-toast="no-google"' not in body
    assert "pill-dormant" not in body


def test_generic_feeds_are_not_greyed_out(client, db):
    """Nothing changes for them: they never wrote to YouTube in the first place."""
    from dealgo.models import GENERIC_PLAYLIST_PREFIX

    with db.session_scope() as session:
        session.delete(session.get(OAuthToken, 1))
        for playlist in session.scalars(select(Playlist)):
            playlist.playlist_id = f"{GENERIC_PLAYLIST_PREFIX}{playlist.id}"

    body = client.get("/feed").text

    assert 'data-toast="no-google"' not in body      # no YouTube feed to warn about
    assert "pill-dormant" not in body


def test_leaving_focus_returns_to_every_feed(client, db):
    """The reported bug: Focus was entered from one feed, and the way back
    carried that feed as a filter, so the feed list came back holding only the
    one just watched."""
    from dealgo.models import Playlist

    with db.session_scope() as session:
        science_id = session.scalar(select(Playlist).where(Playlist.title == "Science")).id

    body = client.get(f"/focus?playlist={science_id}").text
    back = body.split('class="crumbs"', 1)[1].split("</p>", 1)[0]

    assert 'href="/feed"' in back
    assert "playlist=" not in back

    # And following it really does show both feeds.
    listing = client.get("/feed").text
    assert "Science" in listing and "Music" in listing


def test_a_feed_page_filtered_to_one_feed_says_so(client, db):
    """The filter is still reachable — changing a feed's view keeps it — so it
    has to be visible, with a way out."""
    from dealgo.models import Playlist

    with db.session_scope() as session:
        music_id = session.scalar(select(Playlist).where(Playlist.title == "Music")).id

    body = client.get(f"/feed?playlist={music_id}").text

    assert "Showing" in body and "Music" in body
    assert "Show every feed" in body
    assert 'href="/feed"' in body


def test_the_unfiltered_feed_page_says_nothing_about_filtering(client):
    body = client.get("/feed").text
    assert "Show every feed" not in body


def test_clearing_the_filter_keeps_a_search(client, db):
    from dealgo.models import Playlist

    with db.session_scope() as session:
        music_id = session.scalar(select(Playlist).where(Playlist.title == "Music")).id

    body = client.get(f"/feed?playlist={music_id}&q=mus").text
    assert 'href="/feed?q=mus"' in body
