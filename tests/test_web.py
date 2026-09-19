"""Web routes, with particular attention to the htmx contract."""

from __future__ import annotations

import re
import time
from urllib.parse import unquote_plus

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from dealgo.db import get_settings
from dealgo.models import Channel, Placement, Playlist, SyncRun, Video

HX = {"HX-Request": "true"}


def squashed(css: str) -> str:
    """A whitespace-free view of a stylesheet.

    app.css is compiled from SCSS and minified, so a test that matches on its
    exact layout is testing the compiler, not the rule it cares about.
    """
    return re.sub(r"\s+", "", css)


@pytest.fixture
def client(db, monkeypatch):
    from dealgo import scheduler
    from dealgo.web import app as web_app

    # No background thread in tests, and the app must use the temp database.
    monkeypatch.setattr(scheduler, "start", lambda: None)
    monkeypatch.setattr(scheduler, "shutdown", lambda: None)
    monkeypatch.setattr(scheduler, "next_run_time", lambda: None)
    monkeypatch.setattr(web_app, "init_db", lambda: None)

    with db.session_scope() as session:
        channel = Channel(channel_id="UCzzzzzzzzzzzzzzzzzzzzzz", title="Fake Channel")
        playlist = Playlist(playlist_id="PL_target", title="My Feed")
        channel.playlists.append(playlist)
        session.add_all([channel, playlist])
        session.flush()
        session.add(Video(video_id="v0", channel_pk=channel.id, title="A video", status="pending"))
        placed = Video(video_id="v1", channel_pk=channel.id, title="An added video", status="added")
        session.add(placed)
        session.flush()
        session.add(
            Placement(video_pk=placed.id, playlist_pk=playlist.id, playlist_item_id="item-1")
        )

    with TestClient(web_app.app) as test_client:
        yield test_client


@pytest.mark.parametrize("path", ["/", "/channels", "/channels/1", "/videos", "/settings", "/healthz"])
def test_pages_render(client, path):
    assert client.get(path).status_code == 200


def test_full_page_carries_the_htmx_runtime(client):
    body = client.get("/").text
    assert "/static/htmx.min.js" in body
    assert 'hx-boost="true"' in body


def test_partials_return_fragments_not_documents(client):
    for path in ("/partials/stats", "/partials/activity", "/partials/channels", "/partials/sync-status"):
        body = client.get(path, headers=HX).text
        assert "<!doctype html>" not in body.lower(), path
        assert "<html" not in body.lower(), path


def test_sync_finished_event_fires_once_per_run(client, db):
    with db.session_scope() as session:
        session.add(SyncRun(ok=True, finished_at=None))
        session.flush()
        run = session.scalar(select(SyncRun))
        run.finished_at = run.started_at
        run_id = run.id

    stale = client.get("/partials/sync-status?seen=0", headers=HX)
    assert stale.headers.get("HX-Trigger") == "dealgo:sync-finished"

    current = client.get(f"/partials/sync-status?seen={run_id}", headers=HX)
    assert "HX-Trigger" not in current.headers


def test_video_action_swaps_only_that_row(client, db):
    response = client.post("/videos/1/ignore", headers=HX)
    assert response.status_code == 200
    assert response.text.strip().startswith('<tr id="video-1"')
    assert "<table" not in response.text
    with db.session_scope() as session:
        assert session.scalar(select(Video)).status == "ignored"


def test_watched_view_and_dashboard_partial_render(client):
    assert client.get("/videos?watched=1").status_code == 200
    body = client.get("/partials/dashboard", headers=HX).text
    assert "<html" not in body.lower()
    assert "Status" in body and "Feeds" in body


def test_marking_watched_swaps_the_row_and_announces_the_change(client, db):
    response = client.post("/videos/2/watched", headers=HX)
    assert response.status_code == 200
    assert response.headers.get("HX-Trigger") == "dealgo:watched-changed"
    assert 'pill-watched' in response.text
    with db.session_scope() as session:
        assert session.get(Video, 2).watched_at is not None

    undo = client.post("/videos/2/unwatched", headers=HX)
    assert undo.headers.get("HX-Trigger") == "dealgo:watched-changed"
    with db.session_scope() as session:
        assert session.get(Video, 2).watched_at is None


def test_remove_watched_does_nothing_when_nothing_is_watched(client, db, monkeypatch):
    from dealgo.models import OAuthToken
    from dealgo.services import watched as watched_service

    with db.session_scope() as session:
        session.add(OAuthToken(id=1, access_token="token"))

    called = []
    monkeypatch.setattr(watched_service, "remove_watched", lambda *a, **k: called.append(a))

    response = client.post("/playlist/remove-watched", headers=HX)
    assert "No watched videos are in the playlist." in response.text
    assert called == []


def test_remove_watched_refuses_when_it_could_not_work(client, db):
    client.post("/videos/2/watched", headers=HX)

    # A playlist exists but no account can act on the user's behalf.
    no_account = client.post("/playlist/remove-watched", headers=HX)
    assert "toast-bad" in no_account.text
    assert "Connect a Google account" in no_account.text

    # With every target disabled there is nowhere to remove from either.
    with db.session_scope() as session:
        session.query(Playlist).delete()
    no_playlist = client.post("/playlist/remove-watched", headers=HX)
    assert "No feeds are set up." in no_playlist.text


def test_remove_watched_starts_only_on_request(client, db, monkeypatch):
    from dealgo.models import OAuthToken
    from dealgo.services import watched as watched_service

    with db.session_scope() as session:
        session.add(OAuthToken(id=1, access_token="token"))

    called = []
    monkeypatch.setattr(watched_service, "remove_watched", lambda *a, **k: called.append(a))

    client.post("/videos/2/watched", headers=HX)
    response = client.post("/playlist/remove-watched", headers=HX)

    assert "Removing 1 watched video" in response.text
    # The worker is a thread; give it a moment to be scheduled.
    for _ in range(50):
        if called:
            break
        time.sleep(0.02)
    # The owner rides along now: a removal is one account's.
    assert called == [("manual", None)]


def test_mark_playlist_watched_covers_everything_in_the_playlist(client, db):
    response = client.post("/playlist/mark-all-watched", headers=HX)
    assert "Marked 1 video watched." in response.text
    with db.session_scope() as session:
        assert session.get(Video, 2).watched_at is not None
        assert session.get(Video, 1).watched_at is None  # pending, never in the playlist


def test_connect_link_opts_out_of_boosting(client, db):
    """A boosted click cannot follow a redirect to accounts.google.com."""
    with db.session_scope() as session:
        settings = db.get_settings(session)
        settings.client_id = "client-id"
        settings.client_secret = "secret"

    body = client.get("/settings").text
    assert 'href="/oauth/start" hx-boost="false"' in body


def test_oauth_start_redirects_to_google(client, db):
    with db.session_scope() as session:
        settings = db.get_settings(session)
        settings.client_id = "client-id"
        settings.client_secret = "secret"

    plain = client.get("/oauth/start", follow_redirects=False)
    assert plain.status_code == 303
    assert plain.headers["location"].startswith("https://accounts.google.com/o/oauth2/v2/auth?")

    # If htmx does make the request, it must be told to navigate the window.
    boosted = client.get("/oauth/start", headers=HX, follow_redirects=False)
    assert boosted.status_code == 200
    assert boosted.headers["HX-Redirect"].startswith("https://accounts.google.com/")


def test_google_errors_are_explained(client):
    def flash_of(error: str) -> str:
        response = client.get(f"/oauth/callback?error={error}", follow_redirects=False)
        return unquote_plus(response.headers["location"])

    assert "test-user list" in flash_of("access_denied")
    assert "/oauth/callback" in flash_of("redirect_uri_mismatch")
    assert "some_new_error" in flash_of("some_new_error")


def test_a_dead_refresh_grant_is_reported_not_hidden(client, db):
    """While the consent screen is in Testing, Google expires grants weekly."""
    from dealgo.models import OAuthToken

    with db.session_scope() as session:
        session.add(
            OAuthToken(
                id=1,
                access_token="stale",
                account_title="Someone",
                refresh_error="Token has been expired or revoked.",
            )
        )
        settings = db.get_settings(session)
        settings.client_id = "client-id"
        settings.client_secret = "secret"

    settings_page = client.get("/settings").text
    assert "Token has been expired or revoked." in settings_page
    assert "Reconnect YouTube account" in settings_page

    dashboard = client.get("/").text
    assert "Google needs you to sign in again." in dashboard


def test_the_account_playlist_lookup_is_cached_across_renders(client, db, monkeypatch):
    """The panel renders on a page you actually browse, so it must not call
    YouTube every time."""
    from dealgo.models import OAuthToken
    from dealgo.web import app as web_app

    with db.session_scope() as session:
        session.add(OAuthToken(id=1, access_token="token"))

    calls = []

    class FakeClient:
        has_write_access = True

        def my_playlists(self):
            calls.append(1)
            return []

    monkeypatch.setattr(web_app, "build_client", lambda session, http, owner=None: FakeClient())
    web_app._forget_account_playlists()

    client.get("/channels")
    client.get("/channels")
    client.get("/channels")
    assert len(calls) == 1

    # Adding a target must not leave a stale list behind.
    web_app._forget_account_playlists()
    client.get("/channels")
    assert len(calls) == 2


def test_there_is_no_way_to_sync_everything_from_the_header(client):
    """A run is started from a trigger box on the canvas, which polls what it
    is wired to and nothing else. A header button that ignored every wire
    drawn there was a second, contradictory answer to "when does this get
    polled", so it is gone and so is the route behind it."""
    body = client.get("/").text
    assert "Sync now" not in body
    assert 'name="force" value="1"' not in body

    assert client.post("/sync", headers=HX).status_code == 404


def test_a_playlists_add_limit_can_be_saved(client, db):
    from dealgo.models import Playlist

    assert 'name="max_per_run"' in client.get("/feeds/1").text

    response = client.post(
        "/settings/playlists/1",
        data={"max_items": "50", "max_per_run": "3", "enabled": "on"},
        headers=HX,
    )
    assert response.status_code == 200
    with db.session_scope() as session:
        playlist = session.get(Playlist, 1)
        assert playlist.max_per_run == 3
        assert playlist.max_items == 50


def test_a_nonsense_add_limit_is_refused(client, db):
    from dealgo.models import Playlist

    response = client.post(
        "/settings/playlists/1", data={"max_items": "0", "max_per_run": "lots"}, headers=HX
    )
    assert "Max added per sync must be a whole number." in response.text
    with db.session_scope() as session:
        assert session.get(Playlist, 1).max_per_run == 0


def test_the_feed_limits_are_explained(client):
    """"max size" and "per sync" say nothing on their own."""
    body = client.get("/feeds/1").text

    assert body.count('class="info-bubble"') == 2
    assert "rolling window" in body
    assert "queued for the next run" in body


def test_the_descriptions_are_reachable_without_a_mouse(client):
    """With no icon to focus, the description hangs off the control itself:
    :focus-within shows it on tab or tap, and aria-describedby announces it."""
    body = client.get("/feeds/1").text

    assert "info-mark" not in body  # no icon
    assert body.count("aria-describedby=") == 2
    assert 'role="tooltip"' in body

    # Every bubble is addressable, and every control points at its own.
    import re

    tip_ids = set(re.findall(r'class="info-bubble" role="tooltip" id="([^"]+)"', body))
    described = set(re.findall(r'aria-describedby="([^"]+)"', body))
    assert described and described <= tip_ids


def test_a_feed_lists_its_channels_for_editing(client, db):
    from dealgo.models import Channel

    with db.session_scope() as session:
        session.add(Channel(channel_id="UCbbbbbbbbbbbbbbbbbbbbbb", title="Second Channel"))

    # The list stays scannable; the picker lives on the feed's own page.
    assert "channel-picker" not in client.get("/channels").text

    page = client.get("/feeds/1").text
    assert "channel-picker" in page
    assert "Filled by" in page
    # Every watched channel is offered, filling or not.
    assert "Fake Channel" in page and "Second Channel" in page


def test_a_channel_can_be_added_to_a_feed_from_its_row(client, db):
    from dealgo.models import Channel, Playlist

    with db.session_scope() as session:
        session.add(Channel(channel_id="UCbbbbbbbbbbbbbbbbbbbbbb", title="Second Channel"))

    response = client.post(
        "/settings/playlists/1/channels",
        data={"channel_id": "2", "include": "1", "back": "/feeds/1"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].startswith("/feeds/1?ok=")  # back where you were
    with db.session_scope() as session:
        playlist = session.get(Playlist, 1)
        assert {c.title for c in playlist.channels} == {"Fake Channel", "Second Channel"}


def test_a_channel_can_be_removed_from_a_feed(client, db):
    from dealgo.models import Channel, Playlist

    response = client.post(
        "/settings/playlists/1/channels", data={"channel_id": "1", "include": "0"}, headers=HX
    )
    assert "Fake Channel no longer feeds My Feed." in response.text
    with db.session_scope() as session:
        assert session.get(Playlist, 1).channels == []
        # Removing an assignment does not stop watching the channel.
        assert session.get(Channel, 1) is not None


def test_editing_membership_leaves_placed_videos_alone(client, db):
    from dealgo.models import Placement

    client.post(
        "/settings/playlists/1/channels", data={"channel_id": "1", "include": "0"}, headers=HX
    )
    with db.session_scope() as session:
        placement = session.scalar(select(Placement))
        assert placement is not None and placement.playlist_item_id == "item-1"


def test_editing_an_unknown_channel_is_refused(client):
    response = client.post(
        "/settings/playlists/1/channels", data={"channel_id": "999", "include": "1"}, headers=HX
    )
    assert "no longer being watched" in response.text


def test_the_wide_tables_scroll_rather_than_escape_their_panel(client, db):
    """A table too wide for its panel scrolls instead of drawing past the edge."""
    assert '<div class="table-scroll">' in client.get("/videos").text

    # The run log only renders once there has been a run.
    with db.session_scope() as session:
        session.add(SyncRun(ok=True))
    assert '<div class="table-scroll">' in client.get("/").text


def test_the_letter_colour_is_stable_for_a_channel(db):
    from dealgo.models import Channel

    channel = Channel(channel_id="UCzzzzzzzzzzzzzzzzzzzzzz", title="Anything")
    assert channel.avatar_hue == Channel(channel_id=channel.channel_id).avatar_hue
    assert 0 <= channel.avatar_hue < 360
    assert Channel(channel_id="UCaaaaaaaaaaaaaaaaaaaaaa").avatar_hue != channel.avatar_hue


def test_creating_a_feed_makes_the_playlist_and_links_the_channels(client, db, monkeypatch):
    from dealgo.models import Channel, Playlist
    from dealgo.services import playlists as playlist_service
    from dealgo.youtube.api import PlaylistInfo

    made = {}

    class FakeClient:
        has_write_access = True

        def create_playlist(self, title, *, description="", privacy="private"):
            made["title"], made["privacy"] = title, privacy
            return PlaylistInfo(playlist_id="PL_new", title=title, item_count=0, privacy_status=privacy)

    monkeypatch.setattr(playlist_service, "build_client", lambda session, http, owner=None: FakeClient())

    with db.session_scope() as session:
        session.get(Channel, 1).playlists = []  # unlinked, so it is paused
        session.get(Channel, 1).enabled = False

    response = client.post(
        "/settings/feeds/new",
        data={"source": "new", "new_title": "Science", "privacy": "unlisted", "channels": ["1"]},
        headers=HX,
    )

    assert made == {"title": "Science", "privacy": "unlisted"}
    assert "Now feeding" in response.text and "Science" in response.text
    assert "1 channel linked" in response.text
    with db.session_scope() as session:
        feed = session.scalar(select(Playlist).where(Playlist.playlist_id == "PL_new"))
        assert [c.title for c in feed.channels] == ["Fake Channel"]
        # Linking its first feed takes the channel off pause.
        assert session.get(Channel, 1).enabled is True


def test_naming_a_generic_feed_sticks(client, db):
    from dealgo.models import Playlist

    response = client.post(
        "/settings/feeds/new",
        data={"source": "generic", "generic_title": "My Reading List"},
        headers=HX,
    )

    assert "Now feeding" in response.text and "My Reading List" in response.text
    with db.session_scope() as session:
        feed = session.scalar(select(Playlist).where(Playlist.title == "My Reading List"))
        assert feed is not None and feed.is_generic


def test_a_feed_can_be_unlinked_from_its_playlist(client, db):
    from dealgo.models import Playlist

    detail = client.get("/feeds/1").text
    assert "/settings/playlists/1/unlink" in detail
    assert "Unlink from YouTube" in detail

    response = client.post("/settings/playlists/1/unlink", headers=HX)
    assert "is now a generic feed" in response.text
    assert "untouched" in response.text

    with db.session_scope() as session:
        feed = session.get(Playlist, 1)
        assert feed.is_generic
        assert feed.title == "My Feed"


def test_a_generic_feed_offers_no_unlink_button(client, db):
    from dealgo.models import Playlist

    with db.session_scope() as session:
        session.get(Playlist, 1).playlist_id = "generic:abc123"

    body = client.get("/feeds/1").text
    assert "/settings/playlists/1/unlink" not in body
    # Remove is still there — unlink is the softer of the two.
    assert "/settings/playlists/1/delete" in body


def test_unlink_is_visually_distinct_from_remove(client):
    """Three different consequences should not look like one button repeated."""
    import re

    body = client.get("/feeds/1").text
    retiring = re.search(r'<h2>Retiring it</h2>.*?</div>', body, re.S).group(0)

    assert 'class="btn btn-warn"' in retiring    # unlink: caution
    assert 'class="btn btn-danger"' in retiring  # remove: destructive
    assert retiring.index("btn-warn") < retiring.index("btn-danger")


def test_the_nav_reads_configuration_and_raw(client):
    body = client.get("/").text

    assert ">Configuration</a>" in body
    assert ">Raw</a>" in body
    assert ">Channels</a>" not in body
    assert ">Videos</a>" not in body

    # The URLs are unchanged, so links and bookmarks still work.
    assert 'href="/channels"' in body and 'href="/videos"' in body
    assert client.get("/channels").status_code == 200
    assert client.get("/videos").status_code == 200


def test_the_pages_are_titled_to_match_their_tab(client):
    assert "<title>De-Algo — Configuration</title>" in client.get("/channels").text
    assert "<title>De-Algo — Raw</title>" in client.get("/videos").text
    assert "Raw videos" in client.get("/videos").text


def test_a_feed_can_be_renamed_from_its_row(client, db):
    from dealgo.models import Playlist

    listing = client.get("/feeds/1").text
    assert ">Rename<" in listing
    assert "rename-form" not in listing  # not until asked

    editing = client.get("/feeds/1?rename=1").text
    assert 'class="rename-form"' in editing
    assert 'name="title"' in editing
    assert 'value="My Feed"' in editing

    # A generic feed renames with no API call at all.
    with db.session_scope() as session:
        session.get(Playlist, 1).playlist_id = "generic:abc123"

    response = client.post(
        "/settings/playlists/1/rename", data={"title": "Reading List"}, headers=HX
    )
    assert "Renamed to" in response.text and "Reading List" in response.text
    with db.session_scope() as session:
        assert session.get(Playlist, 1).title == "Reading List"


def test_an_empty_rename_keeps_the_field_open(client, db):
    from dealgo.models import Playlist

    with db.session_scope() as session:
        session.get(Playlist, 1).playlist_id = "generic:abc123"

    response = client.post("/settings/playlists/1/rename", data={"title": "  "}, headers=HX)

    assert "Give the feed a name." in response.text
    with db.session_scope() as session:
        assert session.get(Playlist, 1).title == "My Feed"


def test_filling_is_a_toggle_not_a_checkbox_in_the_save_form(client, db):
    from dealgo.models import Playlist

    body = client.get("/feeds/1").text
    assert "/settings/playlists/1/filling" in body
    assert 'name="enabled"' not in body  # no longer part of the limits form

    off = client.post("/settings/playlists/1/filling", headers=HX)
    assert "Paused My Feed" in off.text
    assert "Nothing already in it is removed" in off.text
    with db.session_scope() as session:
        assert session.get(Playlist, 1).enabled is False

    on = client.post("/settings/playlists/1/filling", headers=HX)
    assert "Filling My Feed again." in on.text


def test_saving_limits_no_longer_pauses_the_feed(client, db):
    """The checkbox used to live in this form: submitting without it would
    silently switch the feed off."""
    from dealgo.models import Playlist

    client.post(
        "/settings/playlists/1", data={"max_items": "10", "max_per_run": "2"}, headers=HX
    )
    with db.session_scope() as session:
        feed = session.get(Playlist, 1)
        assert feed.max_items == 10 and feed.max_per_run == 2
        assert feed.enabled is True  # untouched


def test_a_feed_has_its_own_page(client, db):
    from dealgo.models import Playlist

    # The canvas links through rather than carrying every control: a feed's
    # box opens its page, where the rest of its settings are.
    page = client.get("/feeds/1").text
    assert "<title>De-Algo — My Feed</title>" in page
    for section in ("Filling", "Filled by", "In this feed", "Retiring it"):
        assert section in page, section
    assert "Fill order" in page and "1 of 1" in page
    assert 'name="max_items"' in page and 'name="max_per_run"' in page
    assert "Fake Channel" in page  # the membership picker


def test_a_feed_page_action_returns_to_that_page(client, db):
    """The detail page posts plainly, so it must not land back on the list."""
    from dealgo.models import Playlist

    response = client.post(
        "/settings/playlists/1/filling", data={"back": "/feeds/1"}, follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"].startswith("/feeds/1?ok=")
    with db.session_scope() as session:
        assert session.get(Playlist, 1).enabled is False


def test_an_unknown_feed_page_says_so(client):
    response = client.get("/feeds/999", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/channels?err=")


def test_only_a_feeds_own_page_says_it_is_generic(client, db):
    """Whether a feed is backed by a playlist belongs with its settings, not
    in either list."""
    from dealgo.models import Playlist

    with db.session_scope() as session:
        session.get(Playlist, 1).playlist_id = "generic:abc123"

    assert ">generic<" not in client.get("/channels").text
    assert ">generic<" not in client.get("/feed").text

    page = client.get("/feeds/1").text
    assert ">generic</span>" in page
    assert "videos live in De-Algo only" in page


def test_videos_can_be_searched(client, db):
    body = client.get("/videos").text
    assert 'name="q"' in body

    hits = client.get("/videos?q=added").text
    assert "An added video" in hits
    assert ">A video<" not in hits

    # The channel name matches too.
    assert "An added video" in client.get("/videos?q=Fake+Channel").text


def test_search_survives_paging_and_status_chips(client):
    body = client.get("/videos?q=video&status=added").text
    assert "q=video" in body  # chips and pager carry it


def test_hidden_items_are_actually_hidden(client):
    """Author rules that set `display` outrank the UA's [hidden] rule, which
    left the pickers' filter doing nothing at all."""
    css = client.get("/static/app.css").text
    assert "[hidden]{display:none!important" in squashed(css)


def test_searching_a_picker_matches_ids_as_well_as_names(client):
    """Ids are searchable, which is why an id-shaped needle finds a channel."""
    body = client.get("/feeds/1?q=UCzzz").text
    assert "Fake Channel" in body.split('id="feed-channels"', 1)[1].split("</div>", 1)[0]


def test_the_tour_walks_from_setup_to_daily_use(client):
    body = client.get("/").text
    assert 'href="/tour"' in body and ">Tour</a>" in body

    first = client.get("/tour").text
    assert "1. What this is" in first
    assert "Make a feed" in first and "Day to day" in first  # the whole rail
    assert "Next →" in first and "← Back" not in first  # nowhere to go back to

    last = client.get("/tour?step=8").text
    assert "8. Day to day" in last
    assert "Start watching" in last  # the end offers the app, not another step


def test_the_tour_ticks_off_what_is_already_done(client, db):
    """It should guide from where you are, not lecture from zero."""
    from dealgo.models import OAuthToken

    body = client.get("/tour").text
    # The fixture has a feed, a channel and a link between them.
    assert body.count("tour-done") >= 3
    assert "tour-done" not in body.split("Connect YouTube")[1][:200]  # not connected yet

    with db.session_scope() as session:
        session.add(OAuthToken(id=1, access_token="token"))
    assert client.get("/tour").text.count("tour-done") >= 4


def test_an_out_of_range_step_lands_somewhere_sensible(client):
    assert client.get("/tour?step=0").status_code == 200
    assert client.get("/tour?step=99").status_code == 200


def test_the_tour_button_can_be_hidden(client, db):
    from dealgo.models import Settings

    assert ">Tour</a>" in client.get("/").text

    client.post("/settings", data={"hide_tour": "1", "poll_interval_minutes": "30"})
    with db.session_scope() as session:
        assert db.get_settings(session).hide_tour is True

    hidden = client.get("/").text
    assert ">Tour</a>" not in hidden
    # The tour itself is still reachable for anyone who wants it.
    assert client.get("/tour").status_code == 200


def test_saving_settings_does_not_hide_the_tour_by_accident(client, db):
    """The checkbox is opt-out: a "show it" box would switch itself off on the
    first save, because an unticked box sends nothing."""
    client.post("/settings", data={"poll_interval_minutes": "45"})
    with db.session_scope() as session:
        assert db.get_settings(session).hide_tour is False
    assert ">Tour</a>" in client.get("/").text


def test_the_dashboard_speaks_the_same_language_as_the_rest(client):
    """It still said "Feed target", "Playlists" and "from playlist"."""
    body = client.get("/").text

    assert "Feed target" not in body
    assert "from playlist" not in body
    assert "Mark playlist watched" not in body

    assert "Remove 0 watched from feeds" in body
    assert "Mark all watched" in body


def test_the_dashboard_links_each_feed_to_its_page(client, db):
    from dealgo.models import Playlist
    from dealgo.services import playlists as playlist_service

    with db.session_scope() as session:
        playlist_service.set_tags(session, session.get(Playlist, 1), "news")

    body = client.get("/").text
    assert 'href="/feeds/1"' in body      # the name is a way in
    assert "pill-tag" in body             # tags carry through
    assert "1 channel" in body            # counts read as words, not bare numbers


def test_the_dashboard_status_is_grouped_like_everything_else(client):
    import re

    body = client.get("/").text
    panel = body.split('id="dashboard-state"', 1)[1]

    labels = re.findall(r'<span class="group-label">([^<]+)</span>', panel)
    assert labels == ["Account", "Syncing", "Watched", "API quota"]


def test_the_channel_page_shows_the_channel_in_its_own_words(client, db):
    from dealgo.models import Channel

    with db.session_scope() as session:
        session.get(Channel, 1).description = "Woodworking, badly, on a budget."

    body = client.get("/channels/1").text
    name = body.index("Fake Channel")
    blurb = body.index("Woodworking, badly, on a budget.")
    assert name < blurb                       # under the name, not above it
    assert '<div class="titled-text">' in body


def test_a_long_channel_description_folds_away(client, db):
    """A channel that treats its about box as a blog would otherwise push
    every control on the page below the fold."""
    from dealgo.models import Channel

    essay = "I make videos about lathes. " * 40
    with db.session_scope() as session:
        session.get(Channel, 1).description = essay

    body = client.get("/channels/1").text
    assert "blurb-folded" in body
    assert "blurb-toggle" in body
    # One copy, folded by CSS rather than shortened: every word is on the page
    # exactly once, and the toggle only changes how much of it you can see.
    assert body.count(essay.strip()) == 1
    text = body.split('class="blurb-text"', 1)[1].split("</p>", 1)[0]
    assert "…" not in text                    # folded, never abbreviated


def test_a_description_of_a_few_short_lines_is_not_folded(client, db):
    """Folding three lines away behind a toggle costs a click and buys nothing."""
    from dealgo.models import Channel

    with db.session_scope() as session:
        session.get(Channel, 1).description = "Lathes.\nMostly.\nSometimes chisels."

    body = client.get("/channels/1").text
    assert '<p class="blurb">' in body
    assert "blurb-folded" not in body


def test_a_short_description_of_many_lines_still_folds(client, db):
    """Length is not the only way to fill the panel — a stack of link lines
    is short by character count and tall on screen."""
    from dealgo.models import Channel

    with db.session_scope() as session:
        session.get(Channel, 1).description = "\n".join(f"link {n}" for n in range(12))

    body = client.get("/channels/1").text
    assert "blurb-folded" in body


def test_a_channel_without_a_description_shows_no_empty_space(client, db):
    from dealgo.models import Channel

    with db.session_scope() as session:
        session.get(Channel, 1).description = ""

    body = client.get("/channels/1").text
    assert "blurb" not in body


def test_the_reading_time_can_be_set(client, db):
    from dealgo.models import Settings

    assert 'name="post_seconds"' in client.get("/settings").text

    client.post("/settings", data={"post_seconds": "45"}, follow_redirects=False)
    with db.session_scope() as session:
        assert get_settings(session).post_seconds == 45


def test_a_reading_time_too_short_to_read_is_refused(client, db):
    """Zero would flick a post past before anyone could see it."""
    from dealgo.models import Settings

    client.post("/settings", data={"post_seconds": "0"}, follow_redirects=False)
    with db.session_scope() as session:
        assert get_settings(session).post_seconds == 3


def test_the_layout_answers_to_a_phone(client):
    """A stylesheet with no narrow rules is a desktop site with a viewport tag."""
    css = squashed(client.get("/static/app.css").text)

    assert "@media(max-width:640px)" in css      # the phone breakpoint
    assert "@media(pointer:coarse)" in css       # and touch, which is not a width
    # The top bar's tabs cannot sit on one line with everything else.
    assert "flex-wrap:wrap" in css


def test_the_page_frame_allows_for_a_notch(client):
    """Installed full-screen, the bar and the content run under the cutout."""
    css = client.get("/static/app.css").text
    assert "env(safe-area-inset-top)" in css
    assert "env(safe-area-inset-bottom)" in css


def test_nothing_invites_a_sideways_scroll(client):
    css = squashed(client.get("/static/app.css").text)
    assert "overflow-x:hidden" in css


def test_the_tabs_become_a_drawer_below_tablet_width(client):
    """Five tabs, a brand and two sync buttons never shared a row honestly.
    Below 860px the tabs move behind a hamburger instead."""
    css = client.get("/static/app.css").text
    tablet = css.split("@media (max-width: 860px){", 1)[1]

    assert ".menu-button" in tablet          # the hamburger appears
    assert "translateX(100%)" in tablet      # the drawer waits off-screen
    assert ".menu-check:checked~.menu-panel" in squashed(tablet)


def test_the_hamburger_is_only_there_when_it_is_needed(client):
    """On a wide screen the tabs are the navigation; a menu button would be a
    second way to do what is already on screen."""
    import re

    css = client.get("/static/app.css").text
    hidden = re.search(r"([^{}]*\.menu-button[^{}]*)\{display:none\}", css)

    assert hidden is not None, "the hamburger is never hidden"
    assert ".menu-scrim" in hidden.group(1)      # nor is the scrim


def test_the_menu_opens_without_javascript(client):
    """A checkbox and two labels, not a button and a listener: the drawer
    works with scripting switched off, like every other control here."""
    body = client.get("/").text

    assert '<input class="menu-check" type="checkbox" id="menu-toggle"' in body
    assert '<label class="menu-button" for="menu-toggle"' in body
    # And tapping beside the drawer shuts it, also with no script.
    assert '<label class="menu-scrim" for="menu-toggle"' in body


def test_the_menu_control_precedes_what_it_controls(client):
    """The CSS reaches the drawer and the scrim as later siblings of the
    checkbox, so the order in the markup is load-bearing."""
    body = client.get("/").text

    assert body.index('id="menu-toggle"') < body.index('class="menu-scrim"')
    assert body.index('id="menu-toggle"') < body.index('id="site-nav"')


def test_the_drawer_says_whether_it_is_open(client):
    """A label for a checkbox announces as a checkbox, which says nothing
    about a drawer. The script fills that in, and only claims it while it is
    actually running."""
    source = (
        __import__("pathlib").Path("dealgo/web/ts/menu.ts").read_text()
    )

    assert 'setAttribute("aria-expanded"' in source
    assert 'setAttribute("aria-controls", "site-menu")' in source
    assert 'event.key !== "Escape"' in source        # and Escape closes it


def test_the_hamburger_stays_reachable_over_the_open_drawer(client):
    """The drawer is a later sibling with a higher z-index, so without this it
    paints over the very button that closes it."""
    css = client.get("/static/app.css").text
    tablet = css.split("@media (max-width: 860px){", 1)[1].split("@media", 1)[0]

    import re

    drawer = re.search(r"\.menu-panel\{([^}]*)\}", tablet)
    button = re.search(r"(?:^|[,}])\.menu-button\{([^}]*)\}", tablet)
    assert drawer and button

    depth = lambda rule: int(re.search(r"z-index:(\d+)", rule).group(1))
    assert depth(button.group(1)) > depth(drawer.group(1))

    # And the drawer's header reserves the space the button floats in, so the
    # two read as one row rather than one sitting on top of the other.
    title = re.search(r"\.menu-title\{([^}]*)\}", tablet)
    assert title is not None
    assert "padding:0 46px 10px 0" in title.group(1)


def test_the_bar_outranks_the_page_while_the_drawer_is_open(client):
    """The drawer lives inside the bar, so the bar's stacking context has to
    sit above content that raises itself — a tooltip is z-index 30."""
    css = client.get("/static/app.css").text
    tablet = css.split("@media (max-width: 860px){", 1)[1].split("@media", 1)[0]

    import re

    bar = re.search(r"\.topbar\{([^}]*)\}", tablet)
    assert bar and "z-index:40" in bar.group(1)


def test_the_drawers_own_furniture_stays_in_the_drawer(client):
    """The label and the version line belong to the drawer. On a wide screen
    the tabs are a row in the bar, and stray text in the middle of it would be
    the whole layout undone."""
    css = squashed(client.get("/static/app.css").text)
    assert ".menu-button,.menu-scrim,.menu-title,.menu-foot{display:none}" in css


def test_the_current_page_is_marked_the_way_the_app_marks_things(client):
    """Accent for what is current, the same as a primary button or an open
    tab — not a different idea invented for the menu."""
    css = client.get("/static/app.css").text
    tablet = css.split("@media (max-width: 860px){", 1)[1].split("@media", 1)[0]

    assert "inset 3px 0 0 var(--accent)" in tablet
    # Drawn transparent when not current, so arriving at a page moves the mark
    # rather than nudging the text sideways.
    assert "inset 3px 0 0 transparent" in tablet


def test_the_scrim_is_a_token_so_it_suits_both_themes(client):
    """A hard black wash looks like a mistake on the light theme."""
    css = client.get("/static/app.css").text

    assert "background:var(--scrim)" in squashed(css)
    assert css.count("--scrim:") == 2      # defined for dark and for light


def test_the_rows_arrive_a_beat_apart(client):
    css = client.get("/static/app.css").text
    tablet = css.split("@media (max-width: 860px){", 1)[1].split("@media", 1)[0]

    import re

    delays = re.findall(r"nth-child\((\d)\)\{transition-delay:(\d+)ms\}", tablet)
    assert len(delays) >= 6
    # Each one a little after the last, in order.
    steps = [int(ms) for _, ms in delays]
    assert steps == sorted(steps)


def test_nothing_waits_on_an_animation_that_will_not_happen(client):
    """With motion turned down there is no stagger — so the rows must not be
    left sitting at zero opacity waiting for one."""
    css = client.get("/static/app.css").text
    reduced = css.split("@media (prefers-reduced-motion: reduce){", 1)[1]
    # Up to the end of this media block, not just its first rule.
    block = squashed(reduced.split("@media", 1)[0])

    assert "transition-delay:0s" in block
    assert ".topbarnav>*{opacity:1;transform:none}" in block


# -- the tabs, in both shapes ----------------------------------------------
#
# The drawer work removed these rules once, which left the desktop tabs as
# plain underlined links and the drawer's rows the same. Nothing was checking
# the ordinary case, so nothing said so.

def test_the_desktop_tabs_are_a_styled_row(client):
    """The default state, which is easy to delete while working on the other
    one."""
    css = client.get("/static/app.css").text
    desktop = css.split("@media (max-width: 860px){", 1)[0]

    import re

    nav = re.search(r"\.topbar nav\{([^}]*)\}", desktop)
    link = re.search(r"\.topbar nav a\{([^}]*)\}", desktop)

    assert nav is not None, "the tabs have no desktop rule at all"
    assert "display:flex" in nav.group(1)     # a row, not a stack
    assert link is not None
    assert "text-decoration:none" in link.group(1)
    assert "color:var(--muted)" in link.group(1)


def test_both_shapes_of_the_nav_share_their_look(client):
    """The drawer overrides what it must and inherits the rest, so the tabs
    are recognisably the same control in either place."""
    css = client.get("/static/app.css").text
    base_at = css.index(".topbar nav{display:flex")
    drawer_at = css.index(".menu-panel{display:flex;position:fixed")

    # The shared rules have to come first, or the drawer loses to them.
    assert base_at < drawer_at


def test_the_drawer_stacks_its_tabs(client):
    import re

    css = client.get("/static/app.css").text
    tablet = css.split("@media (max-width: 860px){", 1)[1].split("@media", 1)[0]
    tabs = re.search(r"\.topbar nav\{([^}]*)\}", tablet)

    assert tabs is not None
    assert "flex-direction:column" in tabs.group(1)
    assert "flex:none" in tabs.group(1)       # not the row's `flex: 1`


def test_the_hamburger_matches_the_buttons_beside_it(client):
    """Three 2px bars in a padded box come out about 20px tall, which stands
    half as high as the sync buttons it sits next to. It is sized to them."""
    import re

    css = client.get("/static/app.css").text
    tablet = css.split("@media (max-width: 860px){", 1)[1].split("@media", 1)[0]
    button = re.search(r"(?:^|[,}])\.menu-button\{([^}]*)\}", tablet).group(1)

    assert "width:38px" in button and "height:38px" in button
    # The same recipe as .btn: it belongs to that row of controls.
    assert "border:1px solid var(--line)" in button
    assert "background:var(--panel-2)" in button
    assert "border-radius:8px" in button


def test_the_hamburger_answers_to_a_pointer(client):
    css = client.get("/static/app.css").text
    tablet = css.split("@media (max-width: 860px){", 1)[1].split("@media", 1)[0]

    assert ".menu-button:hover{border-color:var(--muted)}" in squashed(tablet)
    assert ".menu-button:active" in tablet


def test_an_open_menu_marks_its_own_button(client):
    """While the drawer is open that button is the live control on screen, so
    it takes the accent — the same signal the app uses everywhere else."""
    import re

    css = client.get("/static/app.css").text
    tablet = css.split("@media (max-width: 860px){", 1)[1].split("@media", 1)[0]
    open_state = re.search(r"\.menu-check:checked~\.menu-button\{([^}]*)\}", squashed(tablet))

    assert open_state is not None
    assert "border-color:var(--accent)" in open_state.group(1)
    assert "color:var(--accent)" in open_state.group(1)


def test_the_buttons_name_is_readable_even_though_its_word_is_not(client):
    """The glyph carries no text, so the label keeps a word for anything that
    cannot see it."""
    import re

    body = client.get("/").text
    assert 'class="menu-word">Menu</span>' in body

    css = client.get("/static/app.css").text
    tablet = css.split("@media (max-width: 860px){", 1)[1].split("@media", 1)[0]
    word = re.search(r"\.menu-word\{([^}]*)\}", tablet).group(1)
    assert "clip-path:inset(50%)" in word      # hidden, not removed
    assert "display:none" not in word


def test_the_sync_listener_is_still_in_the_drawer(client):
    """No buttons left in it, but it is what announces a finished run to the
    rest of the page — so it has to stay on the page to do the listening."""
    body = client.get("/").text
    panel = body.split('class="menu-panel"', 1)[1].split("</div>", 1)[0]

    assert 'id="sync-controls"' in panel
    assert "/partials/sync-status" in panel


def test_the_bar_is_unchanged_on_a_wide_screen(client):
    """`display: contents` takes the wrapper out of the layout, so the tabs,
    Tour and the sync controls stay direct children of the bar — which is what
    `flex: 1` on the tabs is written against."""
    css = squashed(client.get("/static/app.css").text)
    assert ".menu-panel{display:contents}" in css


def test_the_drawers_controls_outrank_their_plain_rules(client):
    """A media query adds no specificity, and _forms.scss is imported after
    _base.scss — so an unscoped `.topbar-action` in the drawer would lose to
    the plain one, silently."""
    import re

    css = client.get("/static/app.css").text
    scoped = re.search(r"\.menu-panel \.topbar-action\{([^}]*)\}", css)
    plain = re.search(r"(?<!\w)(?<!\.menu-panel )\.topbar-action\{([^}]*)\}", css)

    assert scoped is not None, "the drawer does not scope its control rules"
    assert plain is not None and plain.start() > scoped.start(), (
        "the plain rule comes first, so scoping is what makes this work"
    )


def test_what_is_left_of_the_sync_corner_gets_the_width(client):
    """Only the "Syncing…" note now, and only while one is running."""
    import re

    css = client.get("/static/app.css").text
    tablet = css.split("@media (max-width: 860px){", 1)[1].split("@media", 1)[0]

    assert re.search(r"\.menu-panel \.topbar-action \.btn\{flex:1\}", tablet)
    assert "width:100%" in re.search(r"\.menu-panel \.btn\{([^}]*)\}", tablet).group(1)


def test_the_buttons_are_a_second_group_in_the_drawer(client):
    """A hairline after the tabs, written against whatever follows them —
    Tour is only there when the setting says so."""
    css = squashed(client.get("/static/app.css").text)
    assert ".menu-panel>nav+*{margin-top:6px;padding-top:14px;border-top:1pxsolidvar(--line)}" in css


def test_the_drawer_is_a_box_of_its_own(client):
    """The regression this pins, twice over.

    On a wide screen the panel is `display: contents`, which makes it generate
    no box at all — deliberately, so its children lay out as children of the
    bar. In the drawer it must take that back: without a display of its own,
    `position`, `background`, `width` and `transform` are all ignored, the
    panel never exists, and the tabs and sync buttons fall back into the bar.
    """
    import re

    css = client.get("/static/app.css").text
    tablet = css.split("@media (max-width: 860px){", 1)[1].split("@media", 1)[0]
    drawer = re.search(r"\.menu-panel\{([^}]*)\}", tablet)

    assert drawer is not None
    declarations = drawer.group(1)
    assert "display:flex" in declarations, (
        "the drawer inherits `display: contents` and generates no box"
    )
    # And the things that only work because it does.
    assert "position:fixed" in declarations
    assert "transform:translateX(100%)" in declarations


def test_anything_positioned_declares_its_own_display(client):
    """A general form of the same trap: `display: contents` anywhere means a
    later rule that positions that element has to say what kind of box it is."""
    import re

    css = client.get("/static/app.css").text
    contents = {
        selector.strip()
        for selector, body in re.findall(r"([^{}]+)\{([^}]*)\}", css)
        if "display:contents" in body
    }
    for selector in contents:
        for other, body in re.findall(r"([^{}]+)\{([^}]*)\}", css):
            if other.strip() != selector:
                continue
            if "position:fixed" in body or "position:absolute" in body:
                assert "display:" in body, (
                    f"{selector} is positioned but leaves display as contents"
                )


def test_the_hamburger_sits_at_the_right_of_the_bar(client):
    """Once the tabs and the sync controls move into the drawer, the brand and
    this button are all that is left in the bar — so nothing pushes it right
    unless it pushes itself. Without this it packs against the brand, and the
    close button then lands over the drawer's label instead of its corner."""
    import re

    css = client.get("/static/app.css").text
    tablet = css.split("@media (max-width: 860px){", 1)[1].split("@media", 1)[0]
    button = re.search(r"(?:^|[,}])\.menu-button\{([^}]*)\}", tablet).group(1)

    assert "margin-left:auto" in button


def test_the_close_button_lands_on_the_drawers_corner(client):
    """It is the same element in both states, positioned by the bar. The two
    right edges line up only because the bar's padding and the drawer's are
    the same, and the label reserves exactly the button's width plus its gap."""
    import re

    css = client.get("/static/app.css").text
    tablet = css.split("@media (max-width: 860px){", 1)[1].split("@media", 1)[0]

    bar = re.search(r"\.topbar\{([^}]*)\}", tablet).group(1)
    drawer = re.search(r"\.menu-panel\{([^}]*)\}", tablet).group(1)
    title = re.search(r"\.menu-title\{([^}]*)\}", tablet).group(1)
    button = re.search(r"(?:^|[,}])\.menu-button\{([^}]*)\}", tablet).group(1)

    assert "padding:10px 14px" in bar
    assert "padding:18px 14px" in drawer          # same 14px on the right
    # 38px of button plus an 8px gap is the 46px the label keeps clear.
    assert "width:38px" in button
    assert "padding:0 46px 10px 0" in title


# -- the settings page -----------------------------------------------------

def test_every_preference_is_under_a_heading_that_describes_it(client):
    """The panel was titled Syncing and held eleven fields across five
    concerns — the Tour toggle sat beside the polling checkbox as though the
    two were related."""
    import re

    body = client.get("/settings").text
    panel = body.split("<h2>Preferences</h2>", 1)[1].split("</section>", 1)[0]
    groups = re.findall(r"<h3>([^<]*)</h3>", panel)

    assert groups == ["Syncing", "Watching", "API quota", "This interface",
                      "Google API credentials"]

    # And each field sits under the heading that describes it.
    def group_of(field: str) -> str:
        before = panel.split(f'name="{field}"', 1)[0]
        return re.findall(r"<h3>([^<]*)</h3>", before)[-1]

    assert group_of("auto_sync") == "Syncing"
    assert group_of("poll_interval_minutes") == "Syncing"
    assert group_of("initial_backfill") == "Syncing"
    assert group_of("shorts_max_seconds") == "Syncing"
    assert group_of("post_seconds") == "Watching"
    assert group_of("hide_tour") == "This interface"
    assert group_of("client_secret") == "Google API credentials"


def test_the_preferences_stay_in_one_form(client):
    """Splitting them would be the tidy-looking mistake: /settings reads every
    field at once and defaults anything absent, so a second form would save
    its own fields and reset the others without saying so."""
    body = client.get("/settings").text
    panel = body.split("<h2>Preferences</h2>", 1)[1].split("</section>", 1)[0]

    assert panel.count("<form") == 1
    for field in ["auto_sync", "poll_interval_minutes", "shorts_max_seconds",
                  "post_seconds", "hide_tour", "daily_quota", "client_id"]:
        assert f'name="{field}"' in panel


def test_saving_one_group_keeps_the_others(client, db):
    """The behaviour that constraint protects."""
    from dealgo.models import Settings

    with db.session_scope() as session:
        settings = get_settings(session)
        settings.post_seconds = 45
        settings.daily_quota = 8000
        settings.hide_tour = True

    body = client.get("/settings").text
    import re

    # Submit the form exactly as the browser would: every field it contains.
    fields = dict(re.findall(r'name="([a-z_]+)" value="([^"]*)"', body))
    fields["poll_interval_minutes"] = "12"
    client.post("/settings", data=fields, follow_redirects=False)

    with db.session_scope() as session:
        settings = get_settings(session)
        assert settings.poll_interval_minutes == 12    # what was changed
        assert settings.post_seconds == 45             # and what was not
        assert settings.daily_quota == 8000


# -- the standing notices --------------------------------------------------

def test_the_notices_can_each_be_switched_off(client, db):
    from dealgo.models import Settings

    body = client.get("/").text
    assert "No sign-in required" in body
    assert "No Google account is connected" in body

    with db.session_scope() as session:
        settings = get_settings(session)
        settings.hide_open_notice = True
        settings.hide_connect_notice = True

    body = client.get("/").text
    assert "No sign-in required" not in body
    assert "No Google account is connected" not in body
    assert "Connect your YouTube account" not in body     # the dashboard's too


def test_one_switch_covers_both_google_notices(client, db):
    """They say the same thing twice — the banner above every page and the one
    on the dashboard — so they go together."""
    from dealgo.models import Settings

    with db.session_scope() as session:
        get_settings(session).hide_connect_notice = True

    body = client.get("/").text
    assert 'data-toast="no-google"' not in body
    assert "Connect your YouTube account" not in body


def test_switching_a_notice_off_leaves_the_page_working(client, db):
    from dealgo.models import Settings

    with db.session_scope() as session:
        settings = get_settings(session)
        settings.hide_open_notice = True
        settings.hide_connect_notice = True

    for path in ["/", "/feed", "/channels", "/settings"]:
        assert client.get(path).status_code == 200, path


def test_the_switches_are_opt_out(client, db):
    """An unticked checkbox sends nothing, so "hide" has to be what is stored
    — a "show" checkbox would switch itself off the first time this form was
    saved."""
    from dealgo.models import Settings

    body = client.get("/settings").text
    assert 'name="hide_open_notice" value="1"' in body
    assert 'name="hide_connect_notice" value="1"' in body

    # Saving the form without them means "show", not "leave as they were".
    with db.session_scope() as session:
        get_settings(session).hide_open_notice = True

    fields = dict(__import__("re").findall(r'name="([a-z_]+)" value="([^"]*)"', body))
    fields.pop("hide_open_notice", None)
    client.post("/settings", data=fields, follow_redirects=False)

    with db.session_scope() as session:
        assert get_settings(session).hide_open_notice is False


def test_hiding_the_notice_does_not_hide_the_state(client, db):
    """A security warning you can dismiss must not become a security state you
    cannot see."""
    from dealgo.models import Settings

    with db.session_scope() as session:
        get_settings(session).hide_open_notice = True

    page = client.get("/settings").text
    assert "Sign-in is off right now" in page
    assert "No account is connected" in page


# -- the sources tab -------------------------------------------------------
#
# What this account watches, and the labels it groups them by. Separate from
# the canvas: this is the list of what is available, the canvas is what is
# done with it.


def test_the_sources_page_lists_what_is_watched(client):
    body = client.get("/sources").text
    assert "Fake Channel" in body
    assert 'name="reference"' in body  # and offers to add another


def test_a_source_can_be_tagged_from_its_row(client, db):
    from dealgo.models import Channel

    response = client.post("/sources/1/tags", data={"tags": "News, Long Form"},
                           follow_redirects=False)
    assert response.status_code == 303

    with db.session_scope() as session:
        assert session.get(Channel, 1).tag_list == ["news", "long form"]


def test_tagging_something_that_is_gone_says_so(client):
    response = client.post("/sources/99/tags", data={"tags": "news"}, follow_redirects=False)
    assert "err=" in response.headers["location"]


def test_adding_a_source_with_no_channel_is_refused(client):
    response = client.post("/sources", data={"reference": "  "}, follow_redirects=False)
    assert "err=" in response.headers["location"]


def test_the_sources_tab_is_in_the_nav(client):
    body = client.get("/").text
    assert 'href="/sources"' in body
