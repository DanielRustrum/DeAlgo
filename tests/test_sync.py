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


# -- what the trigger boxes do ---------------------------------------------
#
# A trigger on the canvas is only meaningful if the sync engine obeys it. The
# case that matters most is the one with no trigger at all: every setup that
# existed before triggers did has none, and must go on syncing as it always has.


def wire_trigger(db, *, kind: str, every_minutes: int | None = None, cron: str | None = None):
    """Put a trigger box on the canvas and wire it into the only channel."""
    from dealgo.services import graph

    with db.session_scope() as session:
        graph.load(session)
        source = next(n for n in graph.nodes(session) if n.kind == "source")
        trigger = graph.add_trigger(
            session, trigger_kind=kind, every_minutes=every_minutes, cron=cron
        )
        graph.connect(session, trigger, source)
        return trigger.id


def last_checked(db, when):
    with db.session_scope() as session:
        session.scalars(select(Channel)).one().last_checked_at = when


def test_a_channel_with_no_trigger_syncs_as_it_always_did(world):
    world["entries"] = [entry("v0", minutes_ago=5)]
    world["client"].details = {"v0": VideoDetails("v0", "Video v0", 600, "none", "public")}

    assert sync_service.run_sync().discovered == 1


def test_a_pulse_replaces_the_channels_own_gap(world):
    """The box on the canvas has the last word, not the channel's settings."""
    import datetime as dt

    from dealgo.models import utcnow

    wire_trigger(world["db"], kind="pulse", every_minutes=60)
    world["entries"] = [entry("v0", minutes_ago=5)]
    world["client"].details = {"v0": VideoDetails("v0", "Video v0", 600, "none", "public")}

    # Polled ten minutes ago, and the pulse says hourly: not yet.
    last_checked(world["db"], utcnow() - dt.timedelta(minutes=10))
    assert sync_service.run_sync("scheduled").channels_waiting == 1

    # Polled two hours ago: due, even though the channel's own gap is zero.
    last_checked(world["db"], utcnow() - dt.timedelta(hours=2))
    assert sync_service.run_sync("scheduled").discovered == 1


def test_a_schedule_polls_once_its_time_has_come_round(world):
    """A time of day, not a gap: polled before it, the channel is due; polled
    after it, it waits for tomorrow."""
    import datetime as dt

    from dealgo.models import utcnow

    now = utcnow()
    # A time an hour ago, so today's occurrence has already passed.
    gone_by = now - dt.timedelta(hours=1)
    wire_trigger(world["db"], kind="schedule", cron=f"{gone_by.minute} {gone_by.hour} * * *")
    world["entries"] = [entry("v0", minutes_ago=5)]
    world["client"].details = {"v0": VideoDetails("v0", "Video v0", 600, "none", "public")}

    # Last polled two hours ago — before the time came round today.
    last_checked(world["db"], now - dt.timedelta(hours=2))
    assert sync_service.run_sync("scheduled").discovered == 1

    # Now it has been polled since, so it waits rather than going again.
    assert sync_service.run_sync("scheduled").channels_waiting == 1


def test_a_forced_run_ignores_the_triggers_too(world):
    """Force means every channel, whatever anything else says."""
    import datetime as dt

    from dealgo.models import utcnow

    wire_trigger(world["db"], kind="pulse", every_minutes=600)
    last_checked(world["db"], utcnow() - dt.timedelta(minutes=5))
    world["entries"] = [entry("v0", minutes_ago=5)]
    world["client"].details = {"v0": VideoDetails("v0", "Video v0", 600, "none", "public")}

    assert sync_service.run_sync("manual", force=True).discovered == 1


def test_only_narrows_a_pass_to_the_channels_named(world, db):
    """A pulse is wired to some channels and not others."""
    from dealgo.models import Channel as ChannelModel

    with db.session_scope() as session:
        session.add(ChannelModel(channel_id="UCother", title="Other"))

    world["entries"] = [entry("v0", minutes_ago=5)]
    world["client"].details = {"v0": VideoDetails("v0", "Video v0", 600, "none", "public")}

    with db.session_scope() as session:
        wanted = session.scalar(select(Channel).where(Channel.channel_id == CHANNEL_ID)).id

    result = sync_service.run_sync("pulse", force=True, only={wanted})
    assert result.channels_checked == 1


# -- what a sort box does --------------------------------------------------
#
# Insertion order is the order things appear in a feed, so a sort box's whole
# effect is on the order this batch is walked in.


def wire_sort(db, *, sort_by: str, newest_first: bool = True):
    """Put a sort box between the channel and the feed."""
    from dealgo.services import graph

    with db.session_scope() as session:
        graph.load(session)
        source = next(n for n in graph.nodes(session) if n.kind == "source")
        feed = next(n for n in graph.nodes(session) if n.kind == "feed")
        order = graph.add_sort(session, sort_by=sort_by, newest_first=newest_first)
        graph.connect(session, source, order)
        graph.connect(session, order, feed)
        graph.unlink(session, source, feed)  # the direct wire would skip the sort


def three_videos(world):
    """Three uploads, with the middle one the longest and the most watched."""
    world["entries"] = [entry("v0", minutes_ago=30), entry("v1", minutes_ago=20),
                        entry("v2", minutes_ago=10)]
    world["client"].details = {
        "v0": VideoDetails("v0", "Video v0", 600, "none", "public", view_count=10, like_count=5),
        "v1": VideoDetails("v1", "Video v1", 9000, "none", "public", view_count=900, like_count=1),
        "v2": VideoDetails("v2", "Video v2", 300, "none", "public", view_count=50, like_count=90),
    }


def test_without_a_sort_box_the_oldest_goes_in_first(world):
    """A feed reads chronologically, which is what it did before sort boxes."""
    three_videos(world)
    sync_service.run_sync()

    assert world["client"].inserted_into() == ["v0", "v1", "v2"]


def test_a_sort_box_puts_the_newest_in_first(world):
    three_videos(world)
    wire_sort(world["db"], sort_by="published")

    sync_service.run_sync()
    assert world["client"].inserted_into() == ["v2", "v1", "v0"]


def test_a_sort_box_can_order_by_length(world):
    three_videos(world)
    wire_sort(world["db"], sort_by="duration")

    sync_service.run_sync()
    assert world["client"].inserted_into() == ["v1", "v0", "v2"]  # 9000, 600, 300


def test_a_sort_box_can_order_by_views(world):
    three_videos(world)
    wire_sort(world["db"], sort_by="views", newest_first=False)  # least watched first

    sync_service.run_sync()
    assert world["client"].inserted_into() == ["v0", "v2", "v1"]  # 10, 50, 900


def test_a_sort_box_can_order_by_likes(world):
    three_videos(world)
    wire_sort(world["db"], sort_by="likes")

    sync_service.run_sync()
    assert world["client"].inserted_into() == ["v2", "v0", "v1"]  # 90, 5, 1


def test_the_counts_are_kept_so_the_next_run_need_not_ask_again(world, db):
    from dealgo.models import Video as VideoModel

    three_videos(world)
    sync_service.run_sync()

    with db.session_scope() as session:
        counts = {
            v.video_id: (v.view_count, v.like_count)
            for v in session.scalars(select(VideoModel))
        }
    assert counts["v1"] == (900, 1)
