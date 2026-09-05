"""Generic feeds: not backed by a YouTube playlist at all."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from dealgo.models import Channel, Placement, Playlist, Video
from dealgo.services import playlists as playlist_service
from dealgo.services import quota
from dealgo.services import sync as sync_service
from dealgo.services import watched as watched_service
from dealgo.youtube.api import VideoDetails
from fakes import MAIN_PLAYLIST, entry


def uploads(world, count=2):
    with world["db"].session_scope() as session:
        world["db"].get_settings(session).initial_backfill = 10
    world["entries"] = [entry(f"v{i}", i) for i in range(count)]
    world["client"].details = {
        f"v{i}": VideoDetails(f"v{i}", f"Video v{i}", 600, "none", "public") for i in range(count)
    }


def make_generic(db, title="Kept here", *, feeds_channel=True) -> int:
    with db.session_scope() as session:
        playlist = playlist_service.create_generic(session, title)
        if feeds_channel:
            for channel in session.scalars(select(Channel)):
                channel.playlists.append(playlist)
        session.flush()
        return playlist.id


def test_a_generic_feed_needs_no_playlist_id(db):
    with db.session_scope() as session:
        playlist = playlist_service.create_generic(session, "Kept here")
        assert playlist.is_generic
        assert playlist.url is None
        assert playlist.title == "Kept here"


def test_it_is_filled_without_touching_youtube(world, db):
    with db.session_scope() as session:
        session.scalar(select(Channel)).playlists = []  # only the generic feed
    generic = make_generic(db)
    uploads(world)

    before = None
    with db.session_scope() as session:
        before = quota.state(session).used

    result = sync_service.run_sync()

    assert result.added == 2
    assert world["client"].inserted == []          # no API writes at all
    assert world["client"].contents(MAIN_PLAYLIST) == []
    with db.session_scope() as session:
        placed = list(
            session.scalars(
                select(Placement).where(
                    Placement.playlist_pk == generic, Placement.playlist_item_id.is_not(None)
                )
            )
        )
        assert len(placed) == 2
        # Only the free feed poll and the details lookup were charged.
        assert quota.state(session).used - before <= 2


def test_it_works_with_no_google_account_at_all(world, db, monkeypatch):
    """The point of a generic feed: De-Algo alone is enough."""
    from fakes import FakeYouTube

    signed_out = FakeYouTube(write=False, read=False)
    monkeypatch.setattr(
        sync_service, "build_client", lambda session, http: signed_out.bind_meter(quota.meter(session))
    )
    with db.session_scope() as session:
        session.scalar(select(Channel)).playlists = []
    make_generic(db)
    uploads(world)

    result = sync_service.run_sync()

    assert result.added == 2
    assert signed_out.inserted == []


def test_a_youtube_feed_still_waits_for_a_sign_in(world, db, monkeypatch):
    """Generic feeds fill; the YouTube ones are held back, not failed."""
    from fakes import FakeYouTube

    signed_out = FakeYouTube(write=False, read=False)
    monkeypatch.setattr(
        sync_service, "build_client", lambda session, http: signed_out.bind_meter(quota.meter(session))
    )
    generic = make_generic(db)  # the channel now feeds both
    uploads(world, count=1)

    result = sync_service.run_sync()

    assert result.added == 1  # the generic one only
    with db.session_scope() as session:
        owed = session.scalar(
            select(Placement).where(Placement.playlist_item_id.is_(None))
        )
        assert owed is not None and owed.playlist_pk != generic
        assert owed.attempts == 0  # waiting on an account, not failing
        assert session.scalar(select(Video)).status == "added"


def test_a_generic_feed_prunes_itself(world, db):
    with db.session_scope() as session:
        session.scalar(select(Channel)).playlists = []
    generic = make_generic(db)
    with db.session_scope() as session:
        session.get(Playlist, generic).max_items = 1
    uploads(world, count=3)

    result = sync_service.run_sync()

    assert result.pruned == 2
    with db.session_scope() as session:
        held = list(
            session.scalars(
                select(Placement).where(
                    Placement.playlist_pk == generic, Placement.playlist_item_id.is_not(None)
                )
            )
        )
        assert len(held) == 1
        assert session.get(Video, held[0].video_pk).video_id == "v0"  # the newest kept


def test_watching_clears_it_locally(world, db):
    with db.session_scope() as session:
        session.scalar(select(Channel)).playlists = []
    make_generic(db)
    uploads(world, count=1)
    sync_service.run_sync()

    with db.session_scope() as session:
        watched_service.mark_watched(session, [session.scalar(select(Video)).id])
        assert watched_service.count_removable(session) == 1

    result = watched_service.remove_watched()

    assert result.removed == 1
    assert world["client"].deleted == []  # nothing asked of YouTube
    with db.session_scope() as session:
        assert session.scalar(select(Placement)).playlist_item_id is None


def test_it_shows_up_on_the_feed_page_like_any_other(world, db):
    with db.session_scope() as session:
        session.scalar(select(Channel)).playlists = []
    make_generic(db, "Kept here")
    uploads(world, count=1)
    sync_service.run_sync()

    with db.session_scope() as session:
        playlist = session.scalar(select(Playlist).where(Playlist.title == "Kept here"))
        # A placement with an item id is what the Feed page reads.
        placement = session.scalar(
            select(Placement).where(Placement.playlist_pk == playlist.id)
        )
        assert placement.playlist_item_id is not None
        assert placement.playlist_item_id.startswith("generic-")
