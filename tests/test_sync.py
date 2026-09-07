"""End-to-end sync behaviour against a fake YouTube."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from dealgo.models import Channel, Video
from dealgo.services import sync as sync_service
from dealgo.youtube.api import VideoDetails
from fakes import CHANNEL_ID, MAIN_PLAYLIST, entry

def statuses(db) -> dict[str, str]:
    with db.session_scope() as session:
        return {v.video_id: v.status for v in session.scalars(select(Video))}


def test_first_run_only_backfills_recent_uploads(world):
    world["entries"] = [entry(f"v{i}", minutes_ago=i * 10) for i in range(6)]
    world["client"].details = {
        f"v{i}": VideoDetails(f"v{i}", f"Video v{i}", 600, "none", "public") for i in range(6)
    }

    result = sync_service.run_sync()

    # initial_backfill defaults to 3: the three newest are added, the rest ignored.
    assert result.added == 3
    # oldest first, so the playlist reads chronologically
    assert world["client"].inserted_into() == ["v2", "v1", "v0"]
    assert statuses(world["db"]) == {
        "v0": "added", "v1": "added", "v2": "added",
        "v3": "ignored", "v4": "ignored", "v5": "ignored",
    }


def test_later_uploads_are_added_and_never_twice(world):
    world["entries"] = [entry("v0", minutes_ago=10)]
    world["client"].details = {"v0": VideoDetails("v0", "Video v0", 600, "none", "public")}
    sync_service.run_sync()

    world["entries"] = [entry("v1", minutes_ago=1), entry("v0", minutes_ago=10)]
    world["client"].details["v1"] = VideoDetails("v1", "Video v1", 900, "none", "public")
    result = sync_service.run_sync()

    assert result.added == 1
    assert world["client"].inserted_into() == ["v0", "v1"]

    # A third pass with nothing new must be a no-op.
    assert sync_service.run_sync().added == 0
    assert world["client"].inserted_into() == ["v0", "v1"]


def test_filters_keep_shorts_and_streams_out(world):
    world["entries"] = [entry("short", 3), entry("stream", 2), entry("essay", 1)]
    world["client"].details = {
        "short": VideoDetails("short", "A short", 30, "none", "public"),
        "stream": VideoDetails("stream", "Going live", 7200, "live", "public"),
        "essay": VideoDetails("essay", "An essay", 1500, "none", "public"),
    }

    result = sync_service.run_sync()

    assert world["client"].inserted_into() == ["essay"]
    assert result.skipped == 2
    with world["db"].session_scope() as session:
        short = session.scalar(select(Video).where(Video.video_id == "short"))
        assert short.status == "skipped" and "Short" in short.reason


def test_per_channel_title_filter(world):
    with world["db"].session_scope() as session:
        channel = session.scalar(select(Channel))
        channel.title_exclude = "podcast"
    world["entries"] = [entry("a", 2, "Weekly Podcast #12"), entry("b", 1, "Field notes")]
    world["client"].details = {
        "a": VideoDetails("a", "Weekly Podcast #12", 3600, "none", "public"),
        "b": VideoDetails("b", "Field notes", 800, "none", "public"),
    }

    sync_service.run_sync()

    assert world["client"].inserted_into() == ["b"]


def test_videos_already_in_the_playlist_are_adopted_not_reinserted(world):
    world["client"].seed(MAIN_PLAYLIST, "v0", item_id="existing-1")
    world["entries"] = [entry("v0", 5)]
    world["client"].details = {"v0": VideoDetails("v0", "Video v0", 600, "none", "public")}

    sync_service.run_sync()

    assert world["client"].inserted == []
    with world["db"].session_scope() as session:
        video = session.scalar(select(Video).where(Video.video_id == "v0"))
        assert video.status == "added"
        assert [p.playlist_item_id for p in video.placements] == ["existing-1"]


def test_max_per_run_defers_the_rest_to_the_next_pass(world):
    with world["db"].session_scope() as session:
        channel = session.scalar(select(Channel))
        channel.max_per_run = 1
        db_settings = world["db"].get_settings(session)
        db_settings.initial_backfill = 10
    world["entries"] = [entry(f"v{i}", i) for i in range(3)]
    world["client"].details = {
        f"v{i}": VideoDetails(f"v{i}", f"Video v{i}", 600, "none", "public") for i in range(3)
    }

    assert sync_service.run_sync().added == 1
    assert sync_service.run_sync().added == 1
    assert sync_service.run_sync().added == 1
    assert sorted(world["client"].inserted_into()) == ["v0", "v1", "v2"]


def test_pruning_trims_the_oldest_entries(world):
    from dealgo.models import Playlist

    with world["db"].session_scope() as session:
        world["db"].get_settings(session).initial_backfill = 10
        session.scalar(select(Playlist)).max_items = 2
    world["entries"] = [entry(f"v{i}", i) for i in range(4)]
    world["client"].details = {
        f"v{i}": VideoDetails(f"v{i}", f"Video v{i}", 600, "none", "public") for i in range(4)
    }

    result = sync_service.run_sync()

    assert result.pruned == 2
    assert world["client"].contents() == ["v1", "v0"]


def test_without_a_playlist_videos_are_queued_not_lost(world):
    from dealgo.models import Playlist

    with world["db"].session_scope() as session:
        session.delete(session.scalar(select(Playlist)))
    world["entries"] = [entry("v0", 1)]

    result = sync_service.run_sync()

    assert result.added == 0
    assert result.discovered == 1
    assert statuses(world["db"]) == {"v0": "pending"}
    assert "No feeds are set up" in result.message


def test_unavailable_videos_are_skipped_with_a_reason(world):
    world["entries"] = [entry("gone", 1)]
    world["client"].details = {}  # the API returns nothing for a deleted video

    sync_service.run_sync()

    with world["db"].session_scope() as session:
        video = session.scalar(select(Video).where(Video.video_id == "gone"))
        assert video.status == "skipped"
        assert "unavailable" in video.reason


def test_a_feed_failure_is_recorded_on_the_channel(world, monkeypatch):
    import httpx

    from dealgo.youtube import feeds

    def boom(_channel_id, _http):
        raise httpx.ConnectError("dns is having a day")

    monkeypatch.setattr(feeds, "fetch_feed", boom)
    sync_service.run_sync()

    with world["db"].session_scope() as session:
        channel = session.scalar(select(Channel))
        assert "feed unreachable" in channel.last_error
        assert channel.last_checked_at is None


def test_a_channel_added_by_bare_id_gets_its_picture_on_the_next_sync(world, db):
    """The Atom feed carries a title and nothing else, so the avatar is filled
    in from the API — fifty channels for one quota unit."""
    from dealgo.models import Channel

    with db.session_scope() as session:
        assert session.scalar(select(Channel)).thumbnail_url is None

    sync_service.run_sync()

    with db.session_scope() as session:
        channel = session.scalar(select(Channel))
        assert channel.thumbnail_url == f"https://example.test/{CHANNEL_ID}.jpg"
        assert channel.handle == f"@{CHANNEL_ID.lower()}"
        assert channel.description == f"All about {CHANNEL_ID}."


def test_a_channel_tracked_before_descriptions_existed_gets_one(world, db):
    """The lookup keys off anything missing, not the avatar alone, so an
    already-pictured channel from an older database is still filled in."""
    from dealgo.models import Channel

    with db.session_scope() as session:
        channel = session.scalar(select(Channel))
        channel.thumbnail_url = "https://example.test/old.jpg"
        channel.description = None

    sync_service.run_sync()

    with db.session_scope() as session:
        assert session.scalar(select(Channel)).description == f"All about {CHANNEL_ID}."


def test_a_channel_with_no_about_text_is_not_asked_about_again(world, db, monkeypatch):
    """An empty description is an answer. Storing NULL would mean every sync
    spent a lookup on a channel that simply has nothing to say."""
    from dealgo.models import Channel
    from dealgo.youtube.api import ChannelInfo

    asked: list[int] = []

    def once(ids):
        asked.append(len(ids))
        return {CHANNEL_ID: ChannelInfo(CHANNEL_ID, "Fake Channel", None, "pic.jpg", "")}

    monkeypatch.setattr(world["client"], "get_channels", once)

    sync_service.run_sync()
    sync_service.run_sync()

    assert asked == [1]
    with db.session_scope() as session:
        assert session.scalar(select(Channel)).description == ""


def test_a_failed_picture_lookup_does_not_stop_the_sync(world, db, monkeypatch):
    """Cosmetic enrichment must never cost a run: this once turned an
    AttributeError into a sync that added nothing at all."""
    def boom(_ids):
        raise RuntimeError("channels.list is having a day")

    monkeypatch.setattr(world["client"], "get_channels", boom)
    world["entries"] = [entry("v0", 1)]
    world["client"].details = {"v0": VideoDetails("v0", "Video v0", 600, "none", "public")}

    result = sync_service.run_sync()

    assert result.added == 1
    assert world["client"].contents() == ["v0"]
    with db.session_scope() as session:
        assert session.scalar(select(Channel)).thumbnail_url is None
