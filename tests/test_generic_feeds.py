"""Generic feeds: not backed by a YouTube playlist at all."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from dealgo.models import Channel, Placement, Playlist, Video
from dealgo.services import playlists as playlist_service
from dealgo.services import quota
from dealgo.services import sync as sync_service
from dealgo.services import watched as watched_service
from dealgo.plugins.publisher import VideoDetails
from fakes import MAIN_PLAYLIST, entry, unwire, wire


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
                wire(session, channel, playlist)
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
        unwire(session, session.scalar(select(Channel)))  # only the generic feed
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
    """The point of a generic feed: Pamphlets alone is enough."""
    from fakes import FakeYouTube

    signed_out = FakeYouTube(write=False, read=False)
    monkeypatch.setattr(
        sync_service.run, "build_client", lambda session, http, owner=None: signed_out.bind_meter(quota.meter(session))
    )
    with db.session_scope() as session:
        unwire(session, session.scalar(select(Channel)))
    make_generic(db)
    uploads(world)

    result = sync_service.run_sync()

    assert result.added == 2
    assert signed_out.inserted == []


def test_without_an_account_every_feed_fills_locally(world, db, monkeypatch):
    """Google is optional. Signed out, a YouTube feed collects inside Pamphlets
    exactly as a generic one does, so the feed is still readable."""
    from fakes import FakeYouTube

    signed_out = FakeYouTube(write=False, read=False)
    monkeypatch.setattr(
        sync_service.run, "build_client", lambda session, http, owner=None: signed_out.bind_meter(quota.meter(session))
    )
    make_generic(db)  # the channel now feeds both
    uploads(world, count=1)

    result = sync_service.run_sync()

    assert result.added == 2  # both feeds, not just the generic one
    assert signed_out.inserted == []
    with db.session_scope() as session:
        placements = list(session.scalars(select(Placement)))
        assert all(p.playlist_item_id is not None for p in placements)
        # One is local for good, the other only until an account turns up.
        assert sorted(p.is_offline for p in placements) == [False, True]
        assert session.scalar(select(Video)).status == "added"


def test_connecting_an_account_hands_the_backlog_to_youtube(world, db, monkeypatch):
    """What was collected signed out is still owed to the playlist: the run
    after a sign-in inserts it for real and keeps the item id YouTube gives."""
    from fakes import FakeYouTube

    signed_out = FakeYouTube(write=False, read=False)
    monkeypatch.setattr(
        sync_service.run, "build_client", lambda session, http, owner=None: signed_out.bind_meter(quota.meter(session))
    )
    uploads(world, count=1)
    sync_service.run_sync()

    with db.session_scope() as session:
        assert session.scalar(select(Placement)).is_offline

    # An account is connected: back to the signed-in client.
    monkeypatch.setattr(
        sync_service.run,
        "build_client",
        lambda session, http, owner=None: world["client"].bind_meter(quota.meter(session)),
    )
    sync_service.run_sync()

    assert world["client"].contents() == ["v0"]
    with db.session_scope() as session:
        placement = session.scalar(select(Placement))
        assert not placement.is_offline
        assert placement.playlist_item_id.startswith("item-")  # YouTube's own id


def test_a_signed_out_run_says_what_it_did_with_the_youtube_feeds(world, db, monkeypatch):
    from fakes import FakeYouTube

    signed_out = FakeYouTube(write=False, read=False)
    monkeypatch.setattr(
        sync_service.run, "build_client", lambda session, http, owner=None: signed_out.bind_meter(quota.meter(session))
    )
    uploads(world, count=1)

    result = sync_service.run_sync()

    assert "collecting inside Pamphlets" in result.message


def test_a_generic_feed_prunes_itself(world, db):
    with db.session_scope() as session:
        unwire(session, session.scalar(select(Channel)))
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
        unwire(session, session.scalar(select(Channel)))
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
        unwire(session, session.scalar(select(Channel)))
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


def test_unlinking_keeps_the_feed_and_leaves_youtube_alone(world, db):
    """A middle ground between keeping a feed and deleting it."""
    uploads(world, count=1)
    sync_service.run_sync()
    assert world["client"].contents(MAIN_PLAYLIST) == ["v0"]

    with db.session_scope() as session:
        feed = session.scalar(select(Playlist).where(Playlist.playlist_id == MAIN_PLAYLIST))
        feed.max_items = 20
        was = playlist_service.unlink(session, feed)

        assert was == MAIN_PLAYLIST
        assert feed.is_generic
        assert feed.title == "My Feed"          # the feed itself survives
        assert feed.max_items == 20             # limits and
        assert [c.title for c in feed.channels] == ["Fake Channel"]  # channels too

    # Nothing was asked of YouTube: the video is still in the real playlist.
    assert world["client"].deleted == []
    assert world["client"].contents(MAIN_PLAYLIST) == ["v0"]


def test_an_unlinked_feed_keeps_its_videos_but_drops_stale_item_ids(world, db):
    uploads(world, count=1)
    sync_service.run_sync()

    with db.session_scope() as session:
        playlist_service.unlink(session, session.scalar(select(Playlist)))

    with db.session_scope() as session:
        placement = session.scalar(select(Placement))
        # Still in the feed, so it still shows on the Feed page…
        assert placement.playlist_item_id is not None
        # …but no longer pretending to reference a YouTube item.
        assert placement.playlist_item_id.startswith("generic-")


def test_an_unlinked_feed_is_filled_without_youtube_afterwards(world, db):
    uploads(world, count=1)
    sync_service.run_sync()
    with db.session_scope() as session:
        playlist_service.unlink(session, session.scalar(select(Playlist)))

    world["client"].inserted.clear()
    world["entries"] = [entry("v_new", 0)] + world["entries"]
    world["client"].details["v_new"] = VideoDetails("v_new", "New", 600, "none", "public")
    result = sync_service.run_sync()

    assert result.added == 1
    assert world["client"].inserted == []  # nothing written to YouTube


def test_a_generic_feed_has_nothing_to_unlink(db):
    with db.session_scope() as session:
        feed = playlist_service.create_generic(session, "Kept here")
        with pytest.raises(playlist_service.PlaylistError) as caught:
            playlist_service.unlink(session, feed)
    assert "no playlist behind it" in str(caught.value)


def test_renaming_a_generic_feed_touches_nothing_outside(world, db):
    import httpx

    with db.session_scope() as session:
        feed = playlist_service.create_generic(session, "Old name")
        with httpx.Client() as http:
            on_youtube = playlist_service.rename(session, feed, "New name", http)

        assert on_youtube is False  # nothing to update
        assert feed.title == "New name"
    assert world["client"].inserted == [] and world["client"].deleted == []


def test_a_local_feed_is_cleared_from_its_section_and_stays_clear(world, db, monkeypatch):
    from fastapi.testclient import TestClient

    from dealgo import scheduler
    from dealgo.web import app as web_app

    with db.session_scope() as session:
        unwire(session, session.scalar(select(Channel)))
    feed = make_generic(db, "Kept here")
    uploads(world, count=2)
    sync_service.run_sync()

    monkeypatch.setattr(scheduler, "start", lambda: None)
    monkeypatch.setattr(scheduler, "shutdown", lambda: None)
    monkeypatch.setattr(scheduler, "next_run_time", lambda: None)
    monkeypatch.setattr(web_app, "init_db", lambda: None)
    with TestClient(web_app.app) as client:
        page = client.get(f"/feed?playlist={feed}").text
        assert f'hx-post="/feeds/{feed}/clear"' in page
        assert "Clear “Kept here”? Its 2 items leave the feed." in page

        answer = client.post(f"/feeds/{feed}/clear", data={"playlist": str(feed)},
                             headers={"HX-Request": "true"})
        assert "Cleared 2 items from “Kept here”." in answer.text
        assert f'hx-post="/feeds/{feed}/clear"' not in answer.text  # nothing left to clear

    assert world["client"].deleted == []  # a local feed asks nothing of YouTube
    sync_service.run_sync()
    with db.session_scope() as session:
        held = session.scalars(
            select(Placement).where(Placement.playlist_pk == feed, Placement.playlist_item_id.is_not(None))
        ).all()
        assert held == []
