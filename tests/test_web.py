"""Web routes, with particular attention to the htmx contract."""

from __future__ import annotations

import re
import time
from urllib.parse import unquote_plus

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

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


def test_htmx_mutation_returns_the_list_and_an_out_of_band_flash(client):
    response = client.post("/channels/1/toggle", headers=HX)
    assert response.status_code == 200
    assert 'id="channel-list"' in response.text
    assert 'id="flash" hx-swap-oob="true"' in response.text
    assert "paused" in response.text


def test_plain_browser_post_still_redirects(client):
    response = client.post("/channels/1/toggle", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/channels?ok=")


def test_video_action_swaps_only_that_row(client, db):
    response = client.post("/videos/1/ignore", headers=HX)
    assert response.status_code == 200
    assert response.text.strip().startswith('<tr id="video-1"')
    assert "<table" not in response.text
    with db.session_scope() as session:
        assert session.scalar(select(Video)).status == "ignored"


def test_adding_a_channel_reports_the_error_in_the_flash(client):
    response = client.post("/channels/add", data={"reference": ""}, headers=HX)
    assert "flash-err" in response.text
    assert 'id="channel-list"' in response.text


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
    assert "flash-err" in no_account.text
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
    assert called == [("manual",)]


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


def test_target_playlists_panel_lives_on_the_channels_page(client):
    channels = client.get("/channels").text
    assert 'id="playlist-targets"' in channels
    assert "<h2>Feeds</h2>" in channels
    assert 'id="playlist-targets"' not in client.get("/settings").text


def test_channels_can_be_filtered_by_the_playlist_they_feed(client, db):
    from dealgo.models import Channel, Playlist

    with db.session_scope() as session:
        other = Playlist(playlist_id="PL_other", title="Other")
        session.add(other)
        session.flush()
        session.add(Channel(channel_id="UCbbbbbbbbbbbbbbbbbbbbbb", title="Unassigned Channel"))

    everything = client.get("/channels").text
    assert "Fake Channel" in everything and "Unassigned Channel" in everything

    # Only what feeds playlist 1.
    feeding = client.get("/channels?feed=1").text
    assert "Fake Channel" in feeding
    assert "Unassigned Channel" not in feeding

    # And the channels feeding nothing, which is what you want to spot.
    orphans = client.get("/channels?feed=none").text
    assert "Unassigned Channel" in orphans
    assert "Fake Channel" not in orphans

    empty = client.get("/channels?feed=2").text
    assert "No channels feed that playlist yet." in empty


def test_the_filter_survives_a_channel_mutation(client):
    response = client.post("/channels/1/toggle", data={"feed": "1"}, headers=HX)
    assert "Fake Channel" in response.text
    # The chip for that playlist comes back selected, not reset to "any".
    assert 'hx-push-url="/channels?feed=1"' in response.text


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

    monkeypatch.setattr(web_app, "build_client", lambda session, http: FakeClient())
    web_app._forget_account_playlists()

    client.get("/channels")
    client.get("/channels")
    client.get("/channels")
    assert len(calls) == 1

    # Adding a target must not leave a stale list behind.
    web_app._forget_account_playlists()
    client.get("/channels")
    assert len(calls) == 2


def test_shorts_can_be_toggled_from_the_channel_page(client, db):
    from dealgo.models import Channel

    page = client.get("/channels/1").text
    assert "/channels/1/shorts" in page
    assert 'class="toggle "' in page  # off by default
    # The list itself stays scannable.
    assert "/channels/1/shorts" not in client.get("/channels").text

    on = client.post(
        "/channels/1/shorts", data={"back": "/channels/1"}, follow_redirects=False
    )
    assert on.status_code == 303
    assert on.headers["location"].startswith("/channels/1?ok=")  # back to the page
    with db.session_scope() as session:
        assert session.get(Channel, 1).skip_shorts is False
    assert "toggle toggle-on" in client.get("/channels/1").text

    off = client.post("/channels/1/shorts", headers=HX)
    assert "Skipping Shorts from Fake Channel." in off.text
    with db.session_scope() as session:
        assert session.get(Channel, 1).skip_shorts is True


def test_toggling_shorts_keeps_the_active_feed_filter(client):
    response = client.post("/channels/1/shorts", data={"feed": "1"}, headers=HX)
    assert 'hx-push-url="/channels?feed=1"' in response.text


def test_live_can_be_toggled_from_the_channel_page(client, db):
    from dealgo.models import Channel

    assert "/channels/1/live" in client.get("/channels/1").text

    on = client.post("/channels/1/live", headers=HX)
    assert "Including live streams and premieres from Fake Channel." in on.text
    with db.session_scope() as session:
        assert session.get(Channel, 1).skip_live is False

    off = client.post("/channels/1/live", headers=HX)
    assert "Skipping live streams and premieres from Fake Channel." in off.text
    with db.session_scope() as session:
        assert session.get(Channel, 1).skip_live is True


def test_the_two_toggles_are_independent(client, db):
    from dealgo.models import Channel

    client.post("/channels/1/live", headers=HX)
    with db.session_scope() as session:
        channel = session.get(Channel, 1)
        assert channel.skip_live is False
        assert channel.skip_shorts is True  # untouched


def test_the_pull_interval_can_be_set_from_the_channel_page(client, db):
    from dealgo.models import Channel

    page = client.get("/channels/1").text
    assert "/channels/1/interval" in page
    assert "every 6 hours" in page

    response = client.post("/channels/1/interval", data={"minutes": "360"}, headers=HX)
    assert "Checking Fake Channel every 6 hours." in response.text
    with db.session_scope() as session:
        assert session.get(Channel, 1).min_pull_minutes == 360

    back_to_always = client.post("/channels/1/interval", data={"minutes": "0"}, headers=HX)
    assert "every sync" in back_to_always.text
    with db.session_scope() as session:
        assert session.get(Channel, 1).min_pull_minutes == 0


def test_a_custom_interval_is_kept_in_the_control(client, db):
    from dealgo.models import Channel

    with db.session_scope() as session:
        session.get(Channel, 1).min_pull_minutes = 45  # not one of the presets

    page = client.get("/channels/1").text
    assert 'value="45" selected' in page
    assert "every 45 min" in page


def test_a_nonsense_interval_is_refused(client, db):
    from dealgo.models import Channel

    response = client.post("/channels/1/interval", data={"minutes": "soon"}, headers=HX)
    assert "not a number" in response.text
    with db.session_scope() as session:
        assert session.get(Channel, 1).min_pull_minutes == 0


def test_force_sync_is_offered_and_reported(client, monkeypatch):
    from dealgo.services import sync as sync_service

    listing = client.get("/").text
    assert 'name="force" value="1"' in listing

    calls = []
    monkeypatch.setattr(sync_service, "run_sync", lambda *a, **k: calls.append((a, k)))

    plain = client.post("/sync", headers=HX)
    assert "Sync started." in plain.text

    forced = client.post("/sync", data={"force": "1"}, headers=HX)
    assert "Forced sync started" in forced.text
    assert "minimum gaps ignored" in forced.text

    for _ in range(50):
        if len(calls) == 2:
            break
        time.sleep(0.02)
    assert [kwargs["force"] for _, kwargs in calls] == [False, True]


def test_ordinary_uploads_can_be_toggled_from_the_channel_page(client, db):
    from dealgo.models import Channel

    assert "/channels/1/videos" in client.get("/channels/1").text

    off = client.post("/channels/1/videos", headers=HX)
    assert "Skipping regular videos from Fake Channel." in off.text
    with db.session_scope() as session:
        assert session.get(Channel, 1).skip_videos is True

    on = client.post("/channels/1/videos", headers=HX)
    assert "Including regular videos from Fake Channel." in on.text
    with db.session_scope() as session:
        assert session.get(Channel, 1).skip_videos is False


def test_a_channel_that_takes_nothing_says_so(client, db):
    # Videos off, and Shorts and Live are already off by default.
    response = client.post("/channels/1/videos", headers=HX)
    assert "all three are off" in response.text
    assert "takes nothing" in client.get("/channels").text


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


def test_a_newly_added_channel_waits_for_a_feed(client, db, monkeypatch):
    from dealgo.models import Channel
    from dealgo.youtube import feeds

    monkeypatch.setattr(
        feeds,
        "fetch_feed",
        lambda channel_id, http: feeds.FeedResult(
            channel_id=channel_id, channel_title="Brand New", entries=[]
        ),
    )

    response = client.post(
        "/channels/add", data={"reference": "UCbbbbbbbbbbbbbbbbbbbbbb"}, headers=HX
    )
    assert response.status_code == 200
    with db.session_scope() as session:
        added = session.scalar(select(Channel).where(Channel.title == "Brand New"))
        assert added.enabled is False
        assert added.playlists == []

    # Linking a feed from the feed row starts it watching.
    linked = client.post(
        "/settings/playlists/1/channels",
        data={"channel_id": str(added.id), "include": "1", "open": "1"},
        headers=HX,
    )
    assert "watching has started" in linked.text
    with db.session_scope() as session:
        assert session.get(Channel, added.id).enabled is True


def test_the_wide_tables_scroll_rather_than_escape_their_panel(client, db):
    """A table too wide for its panel scrolls instead of drawing past the edge."""
    assert '<div class="table-scroll">' in client.get("/videos").text

    # The run log only renders once there has been a run.
    with db.session_scope() as session:
        session.add(SyncRun(ok=True))
    assert '<div class="table-scroll">' in client.get("/").text


def test_a_channel_row_is_just_a_name_and_a_way_in(client):
    """Everything about a channel lives on its page; the list only has to scan."""
    body = client.get("/channels").text
    section = body.split('id="channel-list"', 1)[1]

    assert "table-channels" not in body
    assert '<ul class="channel-rows">' in body
    assert "row-groups" not in section      # no stats strip
    assert "group-label" not in section
    assert 'name="minutes"' not in section  # no interval control

    assert section.index('class="channel-head"') < section.index('class="channel-buttons"')
    assert ">Open<" in section


def test_a_control_sits_with_the_data_it_affects(client):
    """The poll interval belongs beside when it was last polled, not in a
    separate band of fields."""
    import re

    body = client.get("/channels/1").text
    checks = re.search(
        r'<span class="group-label">Checks</span>.*?</div>\s*</div>', body, re.S
    ).group(0)

    assert 'name="minutes"' in checks   # the control
    assert "last " in checks            # and the reading it governs


def test_the_feeds_panel_is_not_a_table_at_all(client):
    """Five columns of controls per feed was unreadable, and a scroll wrapper
    would have clipped the tooltips it carries."""
    body = client.get("/channels").text

    assert "table-playlists" not in body
    assert '<ul class="feed-rows">' in body
    assert "table-scroll" not in body.split('id="playlist-targets"')[1].split("</ul>")[0]


def test_the_channel_picture_shows_beside_the_name(client, db):
    from dealgo.models import Channel

    with db.session_scope() as session:
        session.get(Channel, 1).thumbnail_url = "https://yt3.example/avatar.jpg"

    body = client.get("/channels").text
    assert '<span class="channel-avatar">' in body
    assert 'src="https://yt3.example/avatar.jpg"' in body
    # Its own page too.
    assert 'src="https://yt3.example/avatar.jpg"' in client.get("/channels/1").text


def test_a_channel_with_no_picture_gets_a_letter(client, db):
    """A channel added by bare UC… id has no avatar until a sync fetches one."""
    from dealgo.models import Channel

    with db.session_scope() as session:
        channel = session.get(Channel, 1)
        channel.thumbnail_url = None
        expected_hue = channel.avatar_hue

    body = client.get("/channels").text
    assert 'class="avatar-letter"' in body
    assert f"--hue: {expected_hue}" in body
    assert ">F</span>" in body  # Fake Channel


def test_the_letter_colour_is_stable_for_a_channel(db):
    from dealgo.models import Channel

    channel = Channel(channel_id="UCzzzzzzzzzzzzzzzzzzzzzz", title="Anything")
    assert channel.avatar_hue == Channel(channel_id=channel.channel_id).avatar_hue
    assert 0 <= channel.avatar_hue < 360
    assert Channel(channel_id="UCaaaaaaaaaaaaaaaaaaaaaa").avatar_hue != channel.avatar_hue


def test_the_feeds_panel_offers_a_new_feed_button(client):
    body = client.get("/channels").text

    assert "New feed" in body
    assert "/partials/playlists?new=1" in body
    # The inline forms it replaced are gone.
    assert "or create a new private playlist" not in body
    assert "choose an existing playlist" not in body
    # And the dialog only appears when asked for.
    assert "<dialog" not in body


def test_the_dialog_guides_every_route(client, db):
    from dealgo.models import OAuthToken

    with db.session_scope() as session:
        session.add(OAuthToken(id=1, access_token="token"))

    body = client.get("/channels?new=1").text

    assert '<dialog class="modal"' in body
    assert "data-modal" in body  # dialog.js promotes it to the top layer
    assert 'action="/settings/feeds/new"' in body
    # Step 1: generic, make a playlist, or adopt one.
    assert 'id="source-generic"' in body
    assert 'id="source-new"' in body
    assert 'id="source-existing"' in body
    assert 'name="privacy"' in body
    # Step 2: what fills it.
    assert 'name="channels"' in body
    assert "Fake Channel" in body


def test_without_an_account_only_the_generic_route_is_offered(client):
    """A generic feed needs no sign-in, so it is the default then."""
    body = client.get("/channels?new=1").text

    assert "Generic feed" in body
    assert "checked" in body.split('id="source-generic"')[1][:80]
    for control in ("source-new", "source-existing"):
        assert "disabled" in body.split(f'id="{control}"')[1][:160], control


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

    monkeypatch.setattr(playlist_service, "build_client", lambda session, http: FakeClient())

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


def test_a_failed_creation_keeps_the_dialog_open(client):
    """Whatever was typed should still be there, not lost behind a closed box."""
    response = client.post(
        "/settings/feeds/new", data={"source": "new", "new_title": ""}, headers=HX
    )

    assert "flash-err" in response.text
    assert "<dialog" in response.text  # still open


def test_the_new_feed_box_is_a_real_dialog(client, db):
    """showModal() puts it in the browser's top layer, so no ancestor's
    overflow or z-index can trap it — and Esc and focus trapping come free."""
    from dealgo.models import OAuthToken

    with db.session_scope() as session:
        session.add(OAuthToken(id=1, access_token="token"))

    body = client.get("/channels?new=1").text
    assert '<dialog class="modal"' in body
    assert "data-modal" in body
    # It ships open, so it is visible even if the script never runs.
    assert " open>" in body
    # And it knows how to clear the server-side flag when Esc closes it.
    assert 'data-close="/partials/playlists"' in body

    page = client.get("/").text
    assert "/static/dialog.js" in page


def test_every_route_in_the_dialog_has_a_reachable_name_field(client, db):
    """The reveal must not depend on :has(): where it is unsupported every
    section stayed hidden, leaving no way to name a feed at all."""
    import re

    from dealgo.models import OAuthToken

    with db.session_scope() as session:
        session.add(OAuthToken(id=1, access_token="token"))

    body = client.get("/channels?new=1").text
    assert 'name="generic_title"' in body
    assert 'name="new_title"' in body

    # Each radio is a sibling of the fields it reveals, in that order.
    for radio, section in (
        ("source-generic", "section-generic"),
        ("source-new", "section-new"),
        ("source-existing", "section-existing"),
    ):
        assert body.index(f'id="{radio}"') < body.index(section), radio
        assert f'for="{radio}"' in body  # the label still drives the radio


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


def test_a_generic_feed_still_needs_a_name(client):
    response = client.post("/settings/feeds/new", data={"source": "generic"}, headers=HX)
    assert "Give the feed a name." in response.text
    assert "<dialog" in response.text  # and the box stays open to type one


def test_the_dialog_reveal_does_not_depend_on_has(client):
    css = (
        __import__("pathlib").Path("dealgo/web/static/app.css").read_text()
        if __import__("pathlib").Path("dealgo/web/static/app.css").exists()
        else client.get("/static/app.css").text
    )
    assert "#source-generic:checked~.section-generic" in squashed(css)
    assert "wizard:has" not in css


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


def test_tracking_a_channel_happens_in_a_dialog(client):
    listing = client.get("/channels").text

    # The standalone panel is gone; the button opens a box instead.
    assert "Track content" in listing
    assert "/partials/channels?track=1" in listing
    assert "<dialog" not in listing

    dialog = client.get("/channels?track=1").text
    assert '<dialog class="modal" id="track-channel"' in dialog
    assert 'action="/channels/add"' in dialog
    assert 'name="reference"' in dialog
    # Step 2 offers the feeds it could fill.
    assert 'name="feeds"' in dialog
    assert "My Feed" in dialog


def test_a_channel_can_be_linked_to_a_feed_as_it_is_added(client, db, monkeypatch):
    """A channel with no feed is paused, so linking here finishes the job."""
    from dealgo.models import Channel
    from dealgo.youtube import feeds as feed_module

    monkeypatch.setattr(
        feed_module,
        "fetch_feed",
        lambda channel_id, http: feed_module.FeedResult(
            channel_id=channel_id, channel_title="Brand New", entries=[]
        ),
    )

    response = client.post(
        "/channels/add",
        data={"reference": "UCbbbbbbbbbbbbbbbbbbbbbb", "feeds": ["1"]},
        headers=HX,
    )

    assert "Now watching Brand New." in response.text
    with db.session_scope() as session:
        added = session.scalar(select(Channel).where(Channel.title == "Brand New"))
        assert [p.title for p in added.playlists] == ["My Feed"]
        assert added.enabled is True  # linking a feed took it off pause


def test_adding_with_no_feed_says_it_is_paused(client, monkeypatch):
    from dealgo.youtube import feeds as feed_module

    monkeypatch.setattr(
        feed_module,
        "fetch_feed",
        lambda channel_id, http: feed_module.FeedResult(
            channel_id=channel_id, channel_title="Lonely", entries=[]
        ),
    )

    response = client.post(
        "/channels/add", data={"reference": "UCbbbbbbbbbbbbbbbbbbbbbb"}, headers=HX
    )
    assert "stays paused until a feed is linked" in response.text


def test_a_bad_channel_reference_keeps_the_dialog_open(client):
    response = client.post("/channels/add", data={"reference": ""}, headers=HX)

    assert "Paste a channel URL" in response.text
    assert "<dialog" in response.text  # still there to correct


def test_the_track_dialog_asks_how_far_back(client):
    body = client.get("/channels?track=1").text

    assert 'name="backfill"' in body
    for label in ("Default", "Nothing", "The last week", "The last month",
                  "Everything the feed still lists"):
        assert label in body, label
    # And is honest about the ceiling.
    assert "newest ~15 uploads" in body


def test_the_chosen_window_is_stored_on_the_channel(client, db, monkeypatch):
    from dealgo.models import Channel
    from dealgo.youtube import feeds as feed_module

    monkeypatch.setattr(
        feed_module,
        "fetch_feed",
        lambda channel_id, http: feed_module.FeedResult(
            channel_id=channel_id, channel_title="Brand New", entries=[]
        ),
    )

    client.post(
        "/channels/add",
        data={"reference": "UCbbbbbbbbbbbbbbbbbbbbbb", "backfill": "30"},
        headers=HX,
    )
    with db.session_scope() as session:
        assert session.scalar(select(Channel).where(Channel.title == "Brand New")).backfill_days == 30


def test_leaving_the_window_alone_uses_the_global_default(client, db, monkeypatch):
    from dealgo.models import Channel
    from dealgo.youtube import feeds as feed_module

    monkeypatch.setattr(
        feed_module,
        "fetch_feed",
        lambda channel_id, http: feed_module.FeedResult(
            channel_id=channel_id, channel_title="Plain", entries=[]
        ),
    )

    client.post("/channels/add", data={"reference": "UCbbbbbbbbbbbbbbbbbbbbbb"}, headers=HX)
    with db.session_scope() as session:
        assert session.scalar(select(Channel).where(Channel.title == "Plain")).backfill_days is None


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


def test_a_feed_row_is_just_a_name_and_a_way_in(client):
    """Everything about a feed lives on its page; the list only has to scan."""
    body = client.get("/channels").text
    panel = body.split('id="playlist-targets"', 1)[1].split('id="channel-list"')[0]

    assert "row-groups" not in panel      # no stats strip
    assert "group-label" not in panel
    assert 'name="max_items"' not in panel  # no limits form
    assert "channel-picker" not in panel

    assert 'href="/feeds/1"' in panel     # the name links through
    assert ">Open<" in panel and ">Remove<" in panel


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

    # The list links through rather than carrying every control.
    assert '/feeds/1"' in client.get("/channels").text

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


def test_the_channel_page_carries_what_the_row_gave_up(client, db):
    """Takes, Checks, Feeds and Videos moved here; nothing was lost."""
    import re

    page = client.get("/channels/1").text

    labels = re.findall(r'<span class="group-label">([^<]+)</span>', page)
    assert labels[:4] == ["Takes", "Checks", "Feeds", "Videos"]
    assert "/channels/1/videos" in page and "/channels/1/shorts" in page
    assert "/channels/1/live" in page and "/channels/1/interval" in page
    assert "placed" in page and "pending" in page


def test_the_filter_form_no_longer_fights_the_toggles(client, db):
    """Those checkboxes used to live in this form: saving it would switch
    every one of them off, because an unticked box sends nothing."""
    from dealgo.models import Channel

    page = client.get("/channels/1").text
    for gone in ('name="skip_videos"', 'name="skip_shorts"', 'name="skip_live"',
                 'name="min_pull_minutes"'):
        assert gone not in page, gone

    with db.session_scope() as session:
        channel = session.get(Channel, 1)
        channel.skip_shorts = False       # Shorts on
        channel.min_pull_minutes = 360    # checked every six hours

    client.post("/channels/1", data={"title_exclude": "podcast", "max_per_run": "4"})

    with db.session_scope() as session:
        channel = session.get(Channel, 1)
        assert channel.title_exclude == "podcast" and channel.max_per_run == 4
        assert channel.skip_shorts is False      # untouched
        assert channel.min_pull_minutes == 360   # untouched


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


def test_channels_can_be_searched_by_name(client, db):
    from dealgo.models import Channel

    with db.session_scope() as session:
        session.add(Channel(channel_id="UCbbbbbbbbbbbbbbbbbbbbbb", title="Cooking Weekly"))

    body = client.get("/channels").text
    assert 'name="q"' in body  # the box is offered

    hits = client.get("/channels?q=cooking").text
    assert "Cooking Weekly" in hits
    assert "Fake Channel" not in hits

    # By handle and id too, and case does not matter.
    assert "Fake Channel" in client.get("/channels?q=UCzzz").text
    assert "No channel matches" in client.get("/channels?q=nothinglikethis").text


def test_search_and_the_feed_chips_combine(client, db):
    from dealgo.models import Channel

    with db.session_scope() as session:
        session.add(Channel(channel_id="UCbbbbbbbbbbbbbbbbbbbbbb", title="Unlinked Cooking"))

    # feed=1 has only Fake Channel; the search excludes it.
    both = client.get("/channels?feed=1&q=cooking").text
    assert "Fake Channel" not in both
    assert "Unlinked Cooking" not in both  # it feeds nothing, so the chip wins

    # Each chip keeps the search when clicked.
    assert "q=cooking" in client.get("/channels?q=cooking").text


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


def test_the_detail_pickers_can_be_searched(client, db):
    """Client-side hiding was silently doing nothing; this is testable."""
    from dealgo.models import Channel, Playlist

    with db.session_scope() as session:
        session.add(Channel(channel_id="UCbbbbbbbbbbbbbbbbbbbbbb", title="Cooking Weekly"))
        session.add(Playlist(playlist_id="PL_music", title="Music Hour"))

    def picker(body: str, marker: str) -> str:
        # The page shows channel and feed names elsewhere too, so look only
        # inside the region the search actually narrows.
        return body.split(f'id="{marker}"', 1)[1].split("</div>", 1)[0]

    # A feed's page searches the channels that could fill it.
    body = client.get("/feeds/1?q=cooking").text
    assert "Cooking Weekly" in picker(body, "feed-channels")
    assert "Fake Channel" not in picker(body, "feed-channels")
    assert "No channel matches" in client.get("/feeds/1?q=nothinglikethis").text

    # A channel's page searches the feeds it could fill.
    body = client.get("/channels/1?q=music").text
    assert "Music Hour" in picker(body, "channel-feeds")
    assert "My Feed" not in picker(body, "channel-feeds")
    assert "No feed matches" in client.get("/channels/1?q=nothinglikethis").text


def test_the_detail_search_survives_typing(client):
    """The box must sit outside the region it swaps, as on the list pages."""
    for page, target in (("/feeds/1", "feed-channels"), ("/channels/1", "channel-feeds")):
        body = client.get(page).text
        assert body.index('name="q"') < body.index(f'id="{target}"'), page
        assert f'hx-target="#{target}"' in body, page


def test_search_matches_words_in_any_order(client, db):
    """"corruption puerto" should find "Puerto Rico Has A Corruption Problem"."""
    from dealgo.models import Channel, Video

    with db.session_scope() as session:
        session.add(
            Video(
                video_id="v9",
                channel_pk=1,
                title="Puerto Rico Has A Corruption Problem",
                status="added",
            )
        )
        session.add(Channel(channel_id="UCdanielbbbbbbbbbbbbbbb", title="Daniel Greene"))

    assert "Puerto Rico" in client.get("/videos?q=corruption+puerto").text
    assert "Puerto Rico" in client.get("/videos?q=puerto+corrupt").text  # partial words too
    assert "Puerto Rico" not in client.get("/videos?q=puerto+missing").text  # every term counts

    assert "Daniel Greene" in client.get("/channels?q=greene+daniel").text
    assert "Daniel Greene" in client.get("/channels?q=dani").text


def test_typing_narrows_the_list_without_pressing_enter(client):
    """The trigger has to be on the input; on the form it never sees a keystroke."""
    import re

    body = client.get("/channels").text
    box = re.search(r'<input type="search" name="q".*?>', body, re.S).group(0)

    assert "hx-trigger=" in box
    assert "input changed" in box
    assert "hx-get=" in box and "hx-include=" in box


def test_the_search_box_is_not_inside_what_it_swaps(client):
    """It was: every keystroke replaced the input and stole the focus."""
    for page, target in (("/channels", "channel-results"), ("/videos", "video-results")):
        body = client.get(page).text
        assert body.index('name="q"') < body.index(f'id="{target}"'), page
        # And the box points at that inner region, not the whole panel.
        assert f'hx-target="#{target}"' in body, page


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
