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
# Nor any plugin setting given by the environment.
for _name in [name for name in os.environ if name.startswith("DEALGO_PLUGIN_")]:
    os.environ.pop(_name, None)


@pytest.fixture
def db(tmp_path, monkeypatch):
    """A fresh SQLite database per test, wired into the real db module."""
    from dealgo import db as db_module
    from dealgo.config import CONFIG

    monkeypatch.setattr(db_module.engine, "CONFIG", replace(CONFIG, database_url=f"sqlite:///{tmp_path / 'test.sqlite3'}"))
    monkeypatch.setattr(db_module.engine, "_engine", None)
    monkeypatch.setattr(db_module.engine, "_SessionFactory", None)
    db_module.init_db()
    yield db_module
    engine = db_module.engine._engine
    if engine is not None:
        engine.dispose()


@pytest.fixture(autouse=True)
def fresh_plugins():
    """A registry built against this test's database, not the last one's.

    What a registry offers depends on rows saying which plugins are off and
    what each is granted, so one cached across a database swap is a registry
    answering about somewhere else.
    """
    from dealgo.plugins import registry
    from dealgo.services import plugin_settings

    # And the plugins' setting values, which are held the same way.
    registry.forget()
    plugin_settings.drop_held()
    yield
    registry.forget()
    plugin_settings.drop_held()


@pytest.fixture(autouse=True)
def no_community_scraping(monkeypatch, request):
    """A source's extras come from a live page, so no test may reach for one.

    Stopped at the registry rather than inside the plugin, because that is
    the one door every one of them goes through. Autouse rather than opt-in:
    a test running a sync without knowing posts exist would otherwise quietly
    hit YouTube. `world` overrides this with its own controllable list.
    """
    from dealgo.plugins import registry

    # Unless the test is about that reading itself, in which case it says so
    # and stubs the page it is fed.
    if request.node.get_closest_marker("reads_pages"):
        return
    monkeypatch.setattr(registry.Registry, "posts", lambda self, kind, key: [])


@pytest.fixture
def world(db, monkeypatch):
    """A watched channel, a target playlist, and controllable YouTube responses."""
    from dealgo.models import Channel, Playlist
    from dealgo.services import sync as sync_service
    from dealgo.services import watched as watched_service
    from dealgo.plugins import registry
    from dealgo.sources import syndication

    from fakes import CHANNEL_ID, MAIN_PLAYLIST, FakeYouTube

    state = {"entries": [], "posts": [], "client": FakeYouTube()}

    def serve_feed(_url, _http):
        """Whatever the test set, read the way a real feed is read.

        The host parses and the source's plugin refines, so a fixture that
        handed over finished items would skip the two halves that decide what
        an item actually is.
        """
        return syndication.Feed(title="Fake Channel", items=list(state["entries"]))

    # Kept, so a test about *which address* is asked for can put the real one
    # back without undoing everything else this fixture arranged — including
    # the database it is all running against.
    state["real_fetch"] = syndication.fetch
    monkeypatch.setattr(syndication, "fetch", serve_feed)
    # Posts are scraped from a real page, so the tests must never reach for
    # one. Nothing is posted unless a test says so.
    monkeypatch.setattr(
        registry.Registry, "posts", lambda self, kind, key: list(state["posts"])
    )
    from dealgo.services import quota

    def fake_build_client(session, http, owner=None):
        return state["client"].bind_meter(quota.meter(session))

    monkeypatch.setattr(sync_service.run, "build_client", fake_build_client)
    monkeypatch.setattr(watched_service, "build_client", fake_build_client)

    from dealgo.models import GraphEdge, GraphNode

    with db.session_scope() as session:
        channel = Channel(channel_id=CHANNEL_ID, title="Fake Channel")
        playlist = Playlist(playlist_id=MAIN_PLAYLIST, title="My Feed")
        channel.playlists.append(playlist)
        session.add_all([channel, playlist])
        session.flush()

        # A trigger, because nothing polls a source without one. A channel
        # with no trigger is a channel nobody has finished setting up, and a
        # fixture that leaves one that way is testing an install nobody has.
        box = GraphNode(kind="source", channel_pk=channel.id, enabled=True, x=0, y=0)
        feed = GraphNode(kind="feed", playlist_pk=playlist.id, enabled=True, x=400, y=0)
        # Every run there is, which is what this channel did before a trigger
        # was needed to say so. Tests about *when* a trigger fires replace it.
        pulse = GraphNode(
            kind="trigger", trigger_kind="pulse", every_minutes=0, enabled=True, x=0, y=0
        )
        session.add_all([box, feed, pulse])
        session.flush()
        session.add(GraphEdge(source_pk=pulse.id, target_pk=box.id))
        # The wire itself. A source's wire belongs to the box it is drawn
        # from, so a setup with none is a setup that routes nothing.
        session.add(GraphEdge(source_pk=box.id, target_pk=feed.id))

    state["db"] = db
    return state


@pytest.fixture
def add_playlist(db):
    """Create another target playlist and point the channel at it too."""

    def _add(playlist_id: str, title: str | None = None, *, feeds_channel: bool = True, **kwargs):
        from dealgo.models import Channel, Playlist

        from dealgo.models import GraphEdge, GraphNode

        with db.session_scope() as session:
            playlist = Playlist(playlist_id=playlist_id, title=title or playlist_id, **kwargs)
            session.add(playlist)
            session.flush()
            feed = GraphNode(kind="feed", playlist_pk=playlist.id, enabled=True, x=400, y=200)
            session.add(feed)
            session.flush()
            if feeds_channel:
                for channel in session.scalars(select(Channel)):
                    channel.playlists.append(playlist)
                    # And the wire that carries it, which is what routes now
                    # read rather than the pairing above.
                    for box in session.scalars(
                        select(GraphNode).where(
                            GraphNode.kind == "source", GraphNode.channel_pk == channel.id
                        )
                    ):
                        session.add(GraphEdge(source_pk=box.id, target_pk=feed.id))
            session.flush()
            return playlist.id

    return _add
