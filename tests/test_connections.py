"""Signing in to a plugin's service: the plugin declares how, the host does it.

The YouTube plugin's `connect` says where Google signs people in, which scope
to ask for and which hosts the token is for; its settings for everyone hold
the OAuth client. Nothing about Google is the app's own any more.
"""

from __future__ import annotations

import datetime as dt
from urllib.parse import parse_qs, unquote_plus, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from fakes import give_youtube_a_client
from dealgo.models import AllowanceUsage, OAuthToken, PluginAppSetting, utcnow
from dealgo.plugins import registry
from dealgo.plugins.registry.connect import connect_in
from dealgo.plugins.registry.settings import settings_in
from dealgo.services import connections, oauth, plugin_settings

APP = settings_in({"app": [{"name": "client_id"}, {"name": "client_secret", "type": "secret"}]})

GOOD = {
    "name": "Example",
    "authorize": "https://accounts.example.com/auth",
    "token": "https://accounts.example.com/token",
    "hosts": ["api.example.com"],
}


# -- declaring it -----------------------------------------------------------


def test_a_plugin_declares_its_sign_in():
    connect = connect_in({**GOOD, "scopes": ["read", "write"], "params": {"prompt": "consent"}}, APP)
    assert connect is not None
    assert connect.scopes == ("read", "write")
    assert connect.signs("https://api.example.com/v1/x")
    assert connect.signs("https://eu.api.example.com/v1/x")
    assert not connect.signs("http://api.example.com/v1/x")        # HTTPS only
    assert not connect.signs("https://api.example.com.evil.net/")  # not a suffix trick
    assert not connect.signs("https://example.com/")


@pytest.mark.parametrize("change, said", [
    ({"name": ""}, "needs a `name`"),
    ({"authorize": "http://accounts.example.com/auth"}, "https:// address"),
    ({"token": None}, "`connect.token` is required"),
    ({"hosts": []}, "has to name the hosts"),
    ({"hosts": ["https://api.example.com"]}, "not a plain host name"),
    ({"client_id": "nowhere"}, "not one of its `settings.app`"),
    ({"allowance": {"daily": "nowhere"}}, "a number or one of its `settings.app`"),
    ({"allowance": {"daily": 10, "timezone": "Mars/Olympus"}}, "is not a time zone"),
])
def test_a_sign_in_that_could_not_work_refuses_the_plugin(change, said):
    with pytest.raises(registry.PluginError, match=said):
        connect_in({**GOOD, **change}, APP)


def test_youtube_declares_googles_sign_in_and_nothing_else_does():
    found = registry.read(registry.storage.shipped())
    declared = {plugin.id: plugin.connect for plugin in found.plugins if plugin.connect}
    assert list(declared) == ["youtube"]
    google = declared["youtube"]
    assert google.name == "Google"
    assert google.hosts == ("googleapis.com",)
    assert google.allowance is not None and google.allowance.timezone == "America/Los_Angeles"


# -- settings from the environment ----------------------------------------------


def test_an_app_setting_can_come_from_the_environment(db, monkeypatch):
    monkeypatch.setenv("DEALGO_PLUGIN_YOUTUBE_CLIENT_ID", "from-env")
    youtube = connections.connecting("youtube")
    assert connections.client_credentials(youtube)[0] == "from-env"

    # What the admin saved wins, so the card always says what is in use.
    plugin_settings.save("youtube", "app", None, {"client_id": "from-card"})
    assert connections.client_credentials(youtube)[0] == "from-card"


def test_the_environment_name_cannot_reach_the_apps_own_variables():
    """Without PLUGIN_, a plugin called "admin" would read DEALGO_ADMIN_PASSWORD."""
    assert plugin_settings.env_name("admin", "password") == "DEALGO_PLUGIN_ADMIN_PASSWORD"
    assert plugin_settings.env_name("my-plugin", "api.key") == "DEALGO_PLUGIN_MY_PLUGIN_API_KEY"


# -- signing in -------------------------------------------------------------------


@pytest.fixture
def site(db, monkeypatch):
    from dealgo import scheduler
    from dealgo.web import app as web_app

    monkeypatch.setattr(scheduler, "start", lambda: None)
    monkeypatch.setattr(scheduler, "shutdown", lambda: None)
    monkeypatch.setattr(scheduler, "next_run_time", lambda: None)
    monkeypatch.setattr(web_app, "init_db", lambda: None)
    with TestClient(web_app.app) as client:
        yield client


def test_a_sign_in_comes_back_and_is_kept_for_its_plugin(site, monkeypatch):
    give_youtube_a_client()
    traded = []

    def exchange(connect, **asked):
        traded.append((connect.token, asked["code"], asked["client_id"]))
        return oauth.TokenResponse(
            access_token="fresh", refresh_token="refresh",
            expires_at=dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1), scope="s",
        )

    monkeypatch.setattr(oauth, "exchange_code", exchange)
    leaving = site.get("/connect/youtube", follow_redirects=False).headers["location"]
    state = parse_qs(urlparse(leaving).query)["state"][0]

    back = site.get(f"/oauth/callback?code=the-code&state={state}", follow_redirects=False)

    assert "Google account connected" in unquote_plus(back.headers["location"])
    assert traded == [("https://oauth2.googleapis.com/token", "the-code", "client-id")]
    with site_session() as session:
        token = session.scalar(select(OAuthToken))
        assert token.provider == "youtube" and token.access_token == "fresh"


def test_a_state_is_good_for_one_sign_in(site, monkeypatch):
    give_youtube_a_client()
    leaving = site.get("/connect/youtube", follow_redirects=False).headers["location"]
    state = parse_qs(urlparse(leaving).query)["state"][0]
    monkeypatch.setattr(oauth, "exchange_code", lambda *a, **k: (_ for _ in ()).throw(AssertionError))

    site.get(f"/oauth/callback?error=access_denied&state={state}", follow_redirects=False)
    again = site.get(f"/oauth/callback?code=x&state={state}", follow_redirects=False)
    assert "expired" in unquote_plus(again.headers["location"])


def test_disconnecting_forgets_this_accounts_sign_in(site, monkeypatch):
    revoked = []
    monkeypatch.setattr(oauth, "revoke", lambda connect, token, http: revoked.append(token))
    with site_session() as session:
        session.add(OAuthToken(provider="youtube", access_token="a", refresh_token="r",
                               expires_at=utcnow() + dt.timedelta(hours=1)))

    site.post("/connect/youtube/disconnect")

    assert revoked == ["r"]
    with site_session() as session:
        assert session.scalar(select(OAuthToken)) is None


# -- what an existing install had ---------------------------------------------------


def test_an_installs_google_state_moves_into_the_youtube_plugin(db, monkeypatch):
    from dealgo.db.engine import get_engine
    from dealgo.db.migrations import youtube_becomes_a_plugin

    with get_engine().begin() as connection:
        for column in ("client_id", "client_secret", "api_key"):
            connection.execute(text(f"ALTER TABLE settings ADD COLUMN {column} VARCHAR(255)"))
        connection.execute(text("ALTER TABLE settings ADD COLUMN daily_quota INTEGER DEFAULT 10000"))
        connection.execute(text(
            "INSERT INTO settings (owner_pk, auto_sync, poll_interval_minutes, initial_backfill,"
            " post_seconds,"
            " client_id, client_secret, daily_quota, updated_at)"
            " VALUES (NULL, 1, 30, 3, 30, 'old-id', 'old-secret', 10000,"
            " CURRENT_TIMESTAMP)"
        ))
        connection.execute(text(
            "CREATE TABLE quota_usage (id INTEGER PRIMARY KEY, owner_pk INTEGER, day VARCHAR(10),"
            " units INTEGER, exhausted_at DATETIME, updated_at DATETIME)"
        ))
        connection.execute(text(
            "INSERT INTO quota_usage (owner_pk, day, units) VALUES (1, '2026-10-01', 300),"
            " (2, '2026-10-01', 700)"
        ))
        connection.execute(text(
            "INSERT INTO oauth_token (owner_pk, provider, access_token, created_at, updated_at)"
            " VALUES (NULL, '', 'tok', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ))
    monkeypatch.setenv("DEALGO_API_KEY", "key-from-env")

    youtube_becomes_a_plugin()
    youtube_becomes_a_plugin()  # and running it again changes nothing

    with db.session_scope() as session:
        saved = {row.key: row.value for row in session.scalars(select(PluginAppSetting))}
        assert saved == {
            "youtube:client_id": "old-id",
            "youtube:client_secret": "old-secret",
            "youtube:api_key": "key-from-env",
            # 10000 was only ever the default, so it is not carried.
        }
        assert session.scalar(select(OAuthToken)).provider == "youtube"
        day = session.scalar(select(AllowanceUsage))
        assert (day.provider, day.day, day.units) == ("youtube", "2026-10-01", 700)
    with get_engine().connect() as connection:
        tables = {row[0] for row in connection.execute(text("select name from sqlite_master"))}
        assert "quota_usage" not in tables


def site_session():
    from dealgo.db import session_scope

    return session_scope()


# -- feeds published through it ----------------------------------------------------


def test_a_feeds_link_is_where_the_plugin_says(db):
    from dealgo.models import Playlist

    assert Playlist(playlist_id="PLabc", title="x").url == (
        "https://www.youtube.com/playlist?list=PLabc"
    )
    assert Playlist(playlist_id="generic:abc", title="x").url is None


def test_making_a_published_feed_sits_in_its_plugins_block(site):
    page = site.get("/settings").text
    block = page.split('id="plugin-youtube"', 1)[1].split("</article>", 1)[0]
    assert "Feeds on YouTube" in block
    # And nowhere else on the page.
    assert page.count('id="new-feed"') == 1


def test_youtubes_switches_move_into_its_declared_kinds(db):
    from dealgo.db.engine import get_engine
    from dealgo.db.migrations import youtube_takes_become_declared
    from dealgo.models import Channel, Video

    with get_engine().begin() as connection:
        for column, default in (("skip_videos", 0), ("skip_shorts", 1), ("skip_live", 1),
                                ("skip_posts", 0)):
            connection.execute(text(
                f"ALTER TABLE channel ADD COLUMN {column} BOOLEAN NOT NULL DEFAULT {default}"
            ))
        connection.execute(text("ALTER TABLE video ADD COLUMN is_short BOOLEAN NOT NULL DEFAULT 0"))
        connection.execute(text(
            "INSERT INTO channel (owner_pk, channel_id, title, enabled, priority, min_pull_minutes,"
            " max_per_run, source_kind, added_at, skip_videos, skip_shorts, skip_live, skip_posts)"
            " VALUES (NULL, 'UCx', 'x', 1, 0, 0, 5, 'youtube', CURRENT_TIMESTAMP, 0, 0, 1, 1)"
        ))
        connection.execute(text(
            "INSERT INTO video (owner_pk, video_id, channel_pk, title, status, reason, kind,"
            " is_short, attempts, view_locked, discovered_at)"
            " VALUES (NULL, 'v1', 1, 'clip', 'skipped', 'Short (30s)', 'video', 1, 0, 0,"
            " CURRENT_TIMESTAMP)"
        ))

    youtube_takes_become_declared()

    with db.session_scope() as session:
        channel = session.scalar(select(Channel))
        assert channel.left_out_names == {"live", "posts"}
        video = session.scalar(select(Video))
        assert (video.hint, video.reason) == ("shorts", "Shorts")


def test_switching_a_kind_back_on_brings_back_what_it_held(db):
    from dealgo.models import Channel, Video
    from dealgo.services import channels as channel_service

    with db.session_scope() as session:
        channel = Channel(channel_id="UCx", title="x", source_kind="youtube")
        session.add(channel)
        session.flush()
        session.add(Video(video_id="v1", channel_pk=channel.id, title="clip",
                          status="skipped", reason="Shorts"))
        session.flush()
        assert channel_service.set_take(session, channel, "shorts", include=True) == 1
        assert "shorts" not in channel.left_out_names
        # A name its plugin never declared changes nothing.
        assert channel_service.set_take(session, channel, "podcasts", include=False) == 0
