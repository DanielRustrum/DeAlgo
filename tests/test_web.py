"""Web routes, with particular attention to the htmx contract."""

from __future__ import annotations

import time
from urllib.parse import unquote_plus

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from dealgo.models import Channel, Placement, Playlist, SyncRun, Video

HX = {"HX-Request": "true"}


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


def test_watched_view_and_feed_target_partial_render(client):
    assert client.get("/videos?watched=1").status_code == 200
    body = client.get("/partials/feed-target", headers=HX).text
    assert "<html" not in body.lower()
    assert "Feed target" in body


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


def test_shorts_can_be_toggled_from_the_channel_list(client, db):
    from dealgo.models import Channel

    listing = client.get("/channels").text
    assert "/channels/1/shorts" in listing
    assert 'class="toggle "' in listing  # off by default

    on = client.post("/channels/1/shorts", headers=HX)
    assert "Including Shorts from Fake Channel." in on.text
    assert "toggle toggle-on" in on.text
    with db.session_scope() as session:
        assert session.get(Channel, 1).skip_shorts is False

    off = client.post("/channels/1/shorts", headers=HX)
    assert "Skipping Shorts from Fake Channel." in off.text
    with db.session_scope() as session:
        assert session.get(Channel, 1).skip_shorts is True


def test_toggling_shorts_keeps_the_active_feed_filter(client):
    response = client.post("/channels/1/shorts", data={"feed": "1"}, headers=HX)
    assert 'hx-push-url="/channels?feed=1"' in response.text


def test_live_can_be_toggled_from_the_channel_list(client, db):
    from dealgo.models import Channel

    assert "/channels/1/live" in client.get("/channels").text

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


def test_the_pull_interval_can_be_set_from_the_channel_list(client, db):
    from dealgo.models import Channel

    listing = client.get("/channels").text
    assert "/channels/1/interval" in listing
    assert "every 6 hours" in listing

    response = client.post("/channels/1/interval", data={"minutes": "360"}, headers=HX)
    assert "Checking Fake Channel every 6 hours." in response.text
    with db.session_scope() as session:
        assert session.get(Channel, 1).min_pull_minutes == 360

    back_to_always = client.post("/channels/1/interval", data={"minutes": "0"}, headers=HX)
    assert "every sync" in back_to_always.text
    with db.session_scope() as session:
        assert session.get(Channel, 1).min_pull_minutes == 0


def test_a_custom_interval_is_kept_in_the_list_control(client, db):
    from dealgo.models import Channel

    with db.session_scope() as session:
        session.get(Channel, 1).min_pull_minutes = 45  # not one of the presets

    listing = client.get("/channels").text
    assert 'value="45" selected' in listing
    assert "every 45 min" in listing


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


def test_ordinary_uploads_can_be_toggled_from_the_channel_list(client, db):
    from dealgo.models import Channel

    listing = client.get("/channels").text
    assert "/channels/1/videos" in listing

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

    listing = client.get("/channels").text
    assert 'name="max_per_run"' in listing

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


def test_the_feed_row_controls_are_explained(client):
    """"feed it" and "new channels" say nothing on their own."""
    body = client.get("/channels").text

    # One info bubble per control: feed it, max size, per sync.
    assert body.count('class="info-bubble"') == 3
    assert "new channels" not in body
    assert "Untick to pause it" in body
    assert "rolling window" in body
    assert "queued for the next run" in body


def test_the_descriptions_are_reachable_without_a_mouse(client):
    """With no icon to focus, the description hangs off the control itself:
    :focus-within shows it on tab or tap, and aria-describedby announces it."""
    body = client.get("/channels").text

    assert "info-mark" not in body  # no icon
    assert body.count("aria-describedby=") == 3
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

    closed = client.get("/channels").text
    assert "channel-picker" not in closed  # collapsed by default

    open_row = client.get("/channels?open=1").text
    assert "channel-picker" in open_row
    assert "Channels feeding My Feed" in open_row
    # Every watched channel is offered, feeding or not.
    assert "Fake Channel" in open_row and "Second Channel" in open_row


def test_a_channel_can_be_added_to_a_feed_from_its_row(client, db):
    from dealgo.models import Channel, Playlist

    with db.session_scope() as session:
        session.add(Channel(channel_id="UCbbbbbbbbbbbbbbbbbbbbbb", title="Second Channel"))

    response = client.post(
        "/settings/playlists/1/channels",
        data={"channel_id": "2", "include": "1", "open": "1"},
        headers=HX,
    )
    assert "Second Channel now feeds My Feed." in response.text
    with db.session_scope() as session:
        playlist = session.get(Playlist, 1)
        assert {c.title for c in playlist.channels} == {"Fake Channel", "Second Channel"}
    # The row it was edited from stays open.
    assert "channel-picker" in response.text


def test_a_channel_can_be_removed_from_a_feed(client, db):
    from dealgo.models import Channel, Playlist

    response = client.post(
        "/settings/playlists/1/channels",
        data={"channel_id": "1", "include": "0", "open": "1"},
        headers=HX,
    )
    assert "Fake Channel no longer feeds My Feed." in response.text
    with db.session_scope() as session:
        assert session.get(Playlist, 1).channels == []
        # Removing an assignment does not stop watching the channel.
        assert session.get(Channel, 1) is not None


def test_editing_membership_leaves_placed_videos_alone(client, db):
    from dealgo.models import Placement

    client.post(
        "/settings/playlists/1/channels",
        data={"channel_id": "1", "include": "0", "open": "1"},
        headers=HX,
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


def test_channels_are_grouped_blocks_not_a_wide_table(client):
    """Eleven columns never fit, and four stacked bands are just as unreadable.
    Each channel is one block whose parts are grouped by subject."""
    import re

    body = client.get("/channels").text

    assert "table-channels" not in body
    assert '<ul class="channel-rows">' in body

    # Identity and its buttons share the head; the rest is grouped below it.
    head = body.index('class="channel-head"')
    assert head < body.index('class="channel-buttons"') < body.index('class="channel-groups"')

    labels = re.findall(r'<span class="group-label">([^<]+)</span>', body)
    assert labels[:4] == ["Takes", "Checks", "Feeds", "Videos"]


def test_a_control_sits_with_the_data_it_affects(client):
    """The poll interval belongs beside when it was last polled, not in a
    separate band of fields."""
    import re

    body = client.get("/channels").text
    checks = re.search(
        r'<span class="group-label">Checks</span>.*?</div>\s*</div>', body, re.S
    ).group(0)

    assert 'name="minutes"' in checks   # the control
    assert "last " in checks            # and the reading it governs


def test_the_feeds_table_is_not_wrapped_so_its_tooltips_show(client):
    """A scroll container clips a bubble that renders above its row."""
    import re

    body = client.get("/channels").text
    feeds_table = re.search(r'<table class="table table-playlists">.*?</table>', body, re.S)
    assert feeds_table, "feeds table missing"
    # The bubbles live in this table, and no scroll wrapper encloses it.
    assert "info-bubble" in feeds_table.group(0)
    before = body[: body.index(feeds_table.group(0))]
    assert before.rstrip().endswith(">")
    assert not before.rstrip().endswith('<div class="table-scroll">')


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
