from __future__ import annotations

import os
from dataclasses import replace

import pytest
from sqlalchemy import select

# Keep tests off any real data directory before dealgo.config is imported.
os.environ.setdefault("DEALGO_DATA_DIR", "/tmp/dealgo-tests")
os.environ.pop("DEALGO_CLIENT_ID", None)
os.environ.pop("DEALGO_CLIENT_SECRET", None)
os.environ.pop("DEALGO_API_KEY", None)


@pytest.fixture
def db(tmp_path, monkeypatch):
    """A fresh SQLite database per test, wired into the real db module."""
    from dealgo import db as db_module
    from dealgo.config import CONFIG

    monkeypatch.setattr(db_module, "CONFIG", replace(CONFIG, database_url=f"sqlite:///{tmp_path / 'test.sqlite3'}"))
    monkeypatch.setattr(db_module, "_engine", None)
    monkeypatch.setattr(db_module, "_SessionFactory", None)
    db_module.init_db()
    yield db_module
    engine = db_module._engine
    if engine is not None:
        engine.dispose()


@pytest.fixture(autouse=True)
def no_community_scraping(monkeypatch):
    """Community posts come from a live page, so no test may reach for one.

    Autouse rather than opt-in: a test that runs a sync without knowing posts
    exist would otherwise quietly hit YouTube. `world` overrides this with its
    own controllable list.
    """
    from dealgo.youtube import community

    monkeypatch.setattr(community, "fetch_posts", lambda channel_id, _http: [])


@pytest.fixture
def world(db, monkeypatch):
    """A watched channel, a target playlist, and controllable YouTube responses."""
    from dealgo.models import Channel, Playlist
    from dealgo.services import sync as sync_service
    from dealgo.services import watched as watched_service
    from dealgo.youtube import community, feeds

    from fakes import CHANNEL_ID, MAIN_PLAYLIST, FakeYouTube

    state = {"entries": [], "posts": [], "client": FakeYouTube()}

    def fake_fetch_feed(channel_id, _http):
        return feeds.FeedResult(
            channel_id=channel_id, channel_title="Fake Channel", entries=list(state["entries"])
        )

    monkeypatch.setattr(feeds, "fetch_feed", fake_fetch_feed)
    # Posts are scraped from a real page, so the tests must never reach for
    # one. Nothing is posted unless a test says so.
    monkeypatch.setattr(
        community, "fetch_posts", lambda channel_id, _http: list(state["posts"])
    )
    from dealgo.services import quota

    def fake_build_client(session, http, owner=None):
        return state["client"].bind_meter(quota.meter(session))

    monkeypatch.setattr(sync_service, "build_client", fake_build_client)
    monkeypatch.setattr(watched_service, "build_client", fake_build_client)

    with db.session_scope() as session:
        channel = Channel(channel_id=CHANNEL_ID, title="Fake Channel")
        playlist = Playlist(playlist_id=MAIN_PLAYLIST, title="My Feed")
        channel.playlists.append(playlist)
        session.add_all([channel, playlist])

    state["db"] = db
    return state


@pytest.fixture
def add_playlist(db):
    """Create another target playlist and point the channel at it too."""

    def _add(playlist_id: str, title: str | None = None, *, feeds_channel: bool = True, **kwargs):
        from dealgo.models import Channel, Playlist

        with db.session_scope() as session:
            playlist = Playlist(playlist_id=playlist_id, title=title or playlist_id, **kwargs)
            session.add(playlist)
            if feeds_channel:
                for channel in session.scalars(select(Channel)):
                    channel.playlists.append(playlist)
            session.flush()
            return playlist.id

    return _add
