"""Marking videos watched, and clearing them out of the playlist on request."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from dealgo.models import SyncRun, Video
from dealgo.services import sync as sync_service
from dealgo.services import watched as watched_service
from dealgo.plugins.publisher import PublishError, VideoDetails
from fakes import MAIN_PLAYLIST, entry, set_quota


def fill_playlist(world, count=3):
    """Run a sync so the playlist holds `count` videos."""
    with world["db"].session_scope() as session:
        world["db"].get_settings(session).initial_backfill = 10
    world["entries"] = [entry(f"v{i}", minutes_ago=i) for i in range(count)]
    world["client"].details = {
        f"v{i}": VideoDetails(f"v{i}", f"Video v{i}", 600, "none", "public") for i in range(count)
    }
    sync_service.run_sync()


def video_by(db, video_id: str) -> Video:
    from sqlalchemy.orm import selectinload

    with db.session_scope() as session:
        return session.scalar(
            select(Video).options(selectinload(Video.placements)).where(Video.video_id == video_id)
        )


def test_nothing_is_removed_until_a_video_is_marked_watched(world):
    fill_playlist(world)
    result = watched_service.remove_watched()

    assert result.removed == 0
    assert world["client"].deleted == []
    assert "No watched videos" in result.message


def test_marking_and_removing_clears_only_watched_videos(world):
    fill_playlist(world)
    item_id = world["client"].item_id_for("v1")
    with world["db"].session_scope() as session:
        target = session.scalar(select(Video).where(Video.video_id == "v1"))
        assert watched_service.mark_watched(session, [target.id]) == 1

    result = watched_service.remove_watched()

    assert result.removed == 1
    assert world["client"].deleted == [item_id]
    assert world["client"].contents() == ["v2", "v0"]

    with world["db"].session_scope() as session:
        removed = session.scalar(select(Video).where(Video.video_id == "v1"))
        assert removed.watched_at is not None
        assert removed.status == "added"  # the record survives, which is the point
        assert not removed.in_playlist
        placement = removed.placements[0]
        assert placement.playlist_item_id is None
        assert "after watching" in placement.removal_reason


def test_a_removed_video_is_never_re_added(world):
    """The whole safety property: watching and removing must be permanent."""
    fill_playlist(world)
    with world["db"].session_scope() as session:
        watched_service.mark_watched(
            session, [v.id for v in session.scalars(select(Video))]
        )
    watched_service.remove_watched()
    assert world["client"].contents() == []

    world["client"].inserted.clear()
    result = sync_service.run_sync()

    assert result.added == 0
    assert world["client"].inserted == []
    assert world["client"].contents() == []


def test_removal_reconciles_items_youtube_no_longer_has(world, monkeypatch):
    fill_playlist(world, count=1)
    with world["db"].session_scope() as session:
        watched_service.mark_watched(session, [session.scalar(select(Video)).id])

    def gone(_item_id):
        raise PublishError("not found", status=404, reason="playlistItemNotFound")

    monkeypatch.setattr(world["client"], "delete_playlist_item", gone)
    result = watched_service.remove_watched()

    assert result.missing == 1
    assert result.ok
    assert not video_by(world["db"], "v0").in_playlist


def test_removal_records_a_run_so_the_ui_can_report_it(world):
    fill_playlist(world, count=2)
    with world["db"].session_scope() as session:
        watched_service.mark_watched(session, [session.scalar(select(Video)).id])

    watched_service.remove_watched(trigger="cli")

    with world["db"].session_scope() as session:
        run = session.scalar(select(SyncRun).where(SyncRun.trigger == "cli"))
        assert run is not None and run.finished_at is not None
        assert run.removed == 1
        assert "Removed 1 watched video" in run.message


def test_unmarking_takes_a_video_out_of_the_removal_set(world):
    fill_playlist(world, count=1)
    with world["db"].session_scope() as session:
        video = session.scalar(select(Video))
        watched_service.mark_watched(session, [video.id])
        assert watched_service.count_removable(session) == 1
        watched_service.mark_unwatched(session, [video.id])
        assert watched_service.count_removable(session) == 0

    assert watched_service.remove_watched().removed == 0
    assert world["client"].deleted == []


def test_mark_all_only_touches_what_is_in_the_playlist(world):
    fill_playlist(world, count=2)
    with world["db"].session_scope() as session:
        # A skipped video is not in the playlist and must stay unwatched.
        session.add(
            Video(video_id="skipped", channel_pk=1, title="A short", status="skipped", reason="Short")
        )
    with world["db"].session_scope() as session:
        assert watched_service.mark_all_in_playlist_watched(session) == 2
    assert video_by(world["db"], "skipped").watched_at is None


def test_removal_needs_a_playlist_and_an_account(world):
    from dealgo.models import Playlist

    fill_playlist(world, count=1)
    with world["db"].session_scope() as session:
        watched_service.mark_watched(session, [session.scalar(select(Video)).id])
        session.scalar(select(Playlist)).enabled = False

    result = watched_service.remove_watched()
    assert not result.ok
    assert "No feeds are set up" in result.message
    assert world["client"].deleted == []


def test_watched_marking_is_idempotent(world):
    fill_playlist(world, count=1)
    with world["db"].session_scope() as session:
        video = session.scalar(select(Video))
        assert watched_service.mark_watched(session, [video.id]) == 1
        first = video.watched_at
        assert watched_service.mark_watched(session, [video.id]) == 0
        assert video.watched_at == first
        assert isinstance(first, dt.datetime)


def test_running_out_of_quota_stops_the_removal_and_says_so_once(world):
    """The rest wait for the reset, rather than each being refused in turn."""
    from dealgo.services import quota

    fill_playlist(world)
    with world["db"].session_scope() as session:
        watched_service.mark_watched(session, [v.id for v in session.scalars(select(Video))])
        used = quota.state(session).used
        set_quota(daily=used + 60, session=session)  # one removal, and no more

    result = watched_service.remove_watched()

    assert result.removed == 1
    assert result.stopped_on_quota
    assert sum("Quota ran out" in message for message in result.messages) == 1
    assert len(world["client"].deleted) == 1


# -- clearing a feed -----------------------------------------------------------------


def feed_pk(world) -> int:
    from dealgo.models import Playlist

    with world["db"].session_scope() as session:
        return session.scalar(select(Playlist.id).where(Playlist.playlist_id == MAIN_PLAYLIST))


def test_clearing_a_feed_takes_everything_out_watched_or_not(world):
    fill_playlist(world)
    with world["db"].session_scope() as session:
        watched_service.mark_watched(session, [session.scalar(select(Video).where(Video.video_id == "v1")).id])

    result = watched_service.clear_feed(feed_pk(world))

    assert result.ok and result.removed == 3
    assert "Cleared 3 items" in result.message
    assert world["client"].contents() == []
    for video_id in ("v0", "v1", "v2"):
        placement = video_by(world["db"], video_id).placements[0]
        assert placement.playlist_item_id is None
        assert placement.removal_reason == "cleared from the feed and its playlist"


def test_what_is_cleared_is_not_put_back_by_the_next_run(world):
    fill_playlist(world)
    watched_service.clear_feed(feed_pk(world))
    world["client"].inserted.clear()

    result = sync_service.run_sync()

    assert result.added == 0
    assert world["client"].contents() == []
    # Still in the history: clearing a feed is not forgetting what was seen.
    assert video_by(world["db"], "v0") is not None


def test_clearing_an_empty_or_unknown_feed_says_so(world):
    assert "already empty" in watched_service.clear_feed(feed_pk(world)).message
    missing = watched_service.clear_feed(999_999)
    assert not missing.ok and "not here" in missing.message


def test_clearing_stops_when_the_quota_runs_out(world):
    fill_playlist(world)
    set_quota(daily=0, reserve=0)

    result = watched_service.clear_feed(feed_pk(world))

    assert result.stopped_on_quota and result.removed == 0
    assert world["client"].contents() != []
