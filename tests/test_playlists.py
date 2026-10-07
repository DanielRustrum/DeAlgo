"""Fan-out: one channel feeding several playlists."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from dealgo.models import Channel, Placement, Playlist, Video
from dealgo.services import playlists as playlist_service
from dealgo.services import sync as sync_service
from dealgo.services import watched as watched_service
from dealgo.plugins.publisher import PublishError, VideoDetails
from fakes import MAIN_PLAYLIST, FakeYouTube, entry, unwire, wire

SECOND = "PL_second"


def upload(world, video_id="v0", minutes_ago=1):
    world["entries"] = [entry(video_id, minutes_ago)]
    world["client"].details[video_id] = VideoDetails(video_id, f"Video {video_id}", 600, "none", "public")


def test_a_video_lands_in_every_playlist_the_channel_feeds(world, add_playlist):
    add_playlist(SECOND, "Mirror")
    upload(world)

    result = sync_service.run_sync()

    assert world["client"].contents(MAIN_PLAYLIST) == ["v0"]
    assert world["client"].contents(SECOND) == ["v0"]
    # Two insertions, one per playlist, but one video.
    assert result.added == 2
    with world["db"].session_scope() as session:
        video = session.scalar(select(Video).options(selectinload(Video.placements)))
        assert video.status == "added"
        assert len(video.placements) == 2


def test_each_playlist_is_filled_only_once(world, add_playlist):
    add_playlist(SECOND, "Mirror")
    upload(world)
    sync_service.run_sync()

    world["client"].inserted.clear()
    sync_service.run_sync()

    assert world["client"].inserted == []


def test_a_paused_playlist_is_left_alone(world, add_playlist):
    add_playlist(SECOND, "Mirror", enabled=False)
    upload(world)

    sync_service.run_sync()

    assert world["client"].contents(MAIN_PLAYLIST) == ["v0"]
    assert world["client"].contents(SECOND) == []


def test_a_channel_feeding_nothing_keeps_its_videos_pending(world):
    with world["db"].session_scope() as session:
        unwire(session, session.scalar(select(Channel)))
    upload(world)

    result = sync_service.run_sync()

    assert result.added == 0
    assert world["client"].inserted == []
    with world["db"].session_scope() as session:
        assert session.scalar(select(Video)).status == "pending"


def test_assigning_a_playlist_later_picks_up_queued_videos(world, add_playlist):
    with world["db"].session_scope() as session:
        unwire(session, session.scalar(select(Channel)))
    upload(world)
    sync_service.run_sync()

    # Point the channel at a playlist; the queued video goes in on the next run.
    with world["db"].session_scope() as session:
        channel = session.scalar(select(Channel))
        wire(session, channel, session.scalar(select(Playlist)))
    sync_service.run_sync()

    assert world["client"].contents(MAIN_PLAYLIST) == ["v0"]


def test_playlists_are_pruned_to_their_own_caps(world, add_playlist):
    add_playlist(SECOND, "Small", max_items=1)
    with world["db"].session_scope() as session:
        world["db"].get_settings(session).initial_backfill = 10
    world["entries"] = [entry(f"v{i}", i) for i in range(3)]
    world["client"].details = {
        f"v{i}": VideoDetails(f"v{i}", f"Video v{i}", 600, "none", "public") for i in range(3)
    }

    sync_service.run_sync()

    # The uncapped playlist keeps everything; the capped one keeps the newest.
    assert world["client"].contents(MAIN_PLAYLIST) == ["v2", "v1", "v0"]
    assert world["client"].contents(SECOND) == ["v0"]


def test_one_failing_playlist_does_not_block_the_others(world, add_playlist, monkeypatch):
    add_playlist(SECOND, "Broken")
    upload(world)

    real_insert = world["client"].insert_playlist_item

    def flaky(playlist_id, video_id):
        if playlist_id == SECOND:
            raise PublishError("nope", status=403, reason="playlistOperationUnsupported")
        return real_insert(playlist_id, video_id)

    monkeypatch.setattr(world["client"], "insert_playlist_item", flaky)
    sync_service.run_sync()

    assert world["client"].contents(MAIN_PLAYLIST) == ["v0"]
    with world["db"].session_scope() as session:
        video = session.scalar(select(Video).options(selectinload(Video.placements)))
        assert video.status == "added"  # it did land somewhere
        failed = [p for p in video.placements if p.playlist_item_id is None]
        assert len(failed) == 1 and "nope" in failed[0].error


def test_watching_a_video_removes_it_from_every_playlist(world, add_playlist):
    add_playlist(SECOND, "Mirror")
    upload(world)
    sync_service.run_sync()

    with world["db"].session_scope() as session:
        watched_service.mark_watched(session, [session.scalar(select(Video)).id])
        assert watched_service.count_removable(session) == 2  # two placements

    result = watched_service.remove_watched()

    assert result.removed == 2
    assert world["client"].contents(MAIN_PLAYLIST) == []
    assert world["client"].contents(SECOND) == []

    # And it stays out of both.
    sync_service.run_sync()
    assert world["client"].contents(MAIN_PLAYLIST) == []
    assert world["client"].contents(SECOND) == []


def test_dropping_a_playlist_target_leaves_youtube_alone(world, add_playlist):
    second_pk = add_playlist(SECOND, "Mirror")
    upload(world)
    sync_service.run_sync()

    with world["db"].session_scope() as session:
        playlist_service.remove(session, session.get(Playlist, second_pk))

    # Pamphlets forgets the placements; the playlist itself keeps its videos.
    assert world["client"].contents(SECOND) == ["v0"]
    with world["db"].session_scope() as session:
        assert session.scalar(select(Placement).where(Placement.playlist_pk == second_pk)) is None
        assert world["client"].deleted == []


def test_a_new_channel_starts_paused_with_no_feed(world, add_playlist):
    """Nothing is assigned by default, so it waits rather than queueing into
    the void."""
    import httpx

    from dealgo.services import channels as channel_service

    add_playlist(SECOND, "Another", feeds_channel=False)

    with world["db"].session_scope() as session, httpx.Client() as http:
        channel = channel_service.add_source(session, "UCaaaaaaaaaaaaaaaaaaaaaa", http)
        assert channel.playlists == []
        assert channel.enabled is False
        assert channel.awaiting_feed is True


def test_linking_the_first_feed_takes_it_off_pause(world, add_playlist, db):
    import httpx

    from dealgo.services import channels as channel_service
    from dealgo.services import playlists as playlist_service

    with db.session_scope() as session, httpx.Client() as http:
        channel = channel_service.add_source(session, "UCaaaaaaaaaaaaaaaaaaaaaa", http)
        assert channel.enabled is False

        playlist = session.scalar(select(Playlist))
        playlist_service.set_membership(session, playlist, channel.id, include=True)
        assert channel.enabled is True
        assert channel.awaiting_feed is False


def test_losing_the_last_feed_pauses_it_again(world, db):
    from dealgo.services import playlists as playlist_service

    with db.session_scope() as session:
        channel = session.scalar(select(Channel))
        playlist = session.scalar(select(Playlist))
        assert channel.enabled is True

        playlist_service.set_membership(session, playlist, channel.id, include=False)
        assert channel.enabled is False
        assert channel.awaiting_feed is True


def test_a_hand_paused_channel_is_not_resumed_by_a_second_feed(world, add_playlist, db):
    """Only the transitions matter: a pause someone chose must stick."""
    from dealgo.services import playlists as playlist_service

    second_pk = add_playlist(SECOND, "Another", feeds_channel=False)
    with db.session_scope() as session:
        channel = session.scalar(select(Channel))
        channel.enabled = False  # paused by hand, while it still has a feed

        playlist_service.set_membership(
            session, session.get(Playlist, second_pk), channel.id, include=True
        )
        assert channel.enabled is False  # still paused, as chosen


def test_renaming_a_feed_renames_the_playlist_too(world, db, monkeypatch):
    """Pamphlets's label and the playlist's own name should not drift apart."""
    import httpx

    renamed = {}

    class Renaming(FakeYouTube):
        has_write_access = True

        def rename_playlist(self, playlist_id, title):
            renamed[playlist_id] = title

    client = Renaming()
    monkeypatch.setattr(playlist_service.editing, "build_client", lambda session, http, owner=None: client)

    with db.session_scope() as session, httpx.Client() as http:
        feed = session.scalar(select(Playlist))
        assert playlist_service.rename(session, feed, "Renamed", http) is True
        assert feed.title == "Renamed"

    assert renamed == {MAIN_PLAYLIST: "Renamed"}


def test_a_rename_youtube_refuses_still_lands_locally(world, db, monkeypatch):
    """Better a name that differs than an edit that silently vanished."""
    import httpx

    from dealgo.plugins.publisher import PublishError

    class Refusing(FakeYouTube):
        has_write_access = True

        def rename_playlist(self, playlist_id, title):
            raise PublishError("nope", status=403, reason="forbidden")

    monkeypatch.setattr(playlist_service.editing, "build_client", lambda session, http, owner=None: Refusing())

    with db.session_scope() as session, httpx.Client() as http:
        feed = session.scalar(select(Playlist))
        with pytest.raises(playlist_service.PlaylistError) as caught:
            playlist_service.rename(session, feed, "Renamed", http)
        assert feed.title == "Renamed"  # kept here even so
    assert "YouTube refused" in str(caught.value)


def test_a_feed_still_needs_a_name(world, db):
    import httpx

    with db.session_scope() as session, httpx.Client() as http:
        feed = session.scalar(select(Playlist))
        with pytest.raises(playlist_service.PlaylistError):
            playlist_service.rename(session, feed, "   ", http)
        assert feed.title == "My Feed"
