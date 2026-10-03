"""Turning the Shorts and live-stream filters on and off per channel."""

from __future__ import annotations

from sqlalchemy import select

from dealgo.models import Channel, Video
from dealgo.services import channels as channel_service
from dealgo.services import sync as sync_service
from dealgo.sources import syndication
from dealgo.plugins.publisher import VideoDetails
from fakes import MAIN_PLAYLIST, entry


def short_entry(video_id: str, minutes_ago: int) -> syndication.Item:
    """A Shorts upload, as the channel feed reports one.

    Which is to say: an ordinary entry whose link goes to /shorts/. Nothing
    in the feed says "this is a Short" — the address is the only thing that
    does, and spotting it is the YouTube plugin's job.
    """
    return entry(video_id, minutes_ago, title=f"Short {video_id}", short=True)


def load(world, *, shorts=2, longs=1):
    with world["db"].session_scope() as session:
        world["db"].get_settings(session).initial_backfill = 10
    entries = [short_entry(f"s{i}", i) for i in range(shorts)]
    entries += [entry(f"v{i}", 50 + i) for i in range(longs)]
    world["entries"] = entries
    world["client"].details = {
        **{f"s{i}": VideoDetails(f"s{i}", f"Short s{i}", 30, "none", "public") for i in range(shorts)},
        **{f"v{i}": VideoDetails(f"v{i}", f"Video v{i}", 600, "none", "public") for i in range(longs)},
    }


def test_shorts_are_skipped_by_default(world):
    load(world)
    sync_service.run_sync()

    assert world["client"].contents(MAIN_PLAYLIST) == ["v0"]
    with world["db"].session_scope() as session:
        shorts = list(session.scalars(select(Video).where(Video.video_id.like("s%"))))
        assert all(v.status == "skipped" and v.reason.startswith("Short") for v in shorts)


def test_turning_shorts_on_brings_back_the_ones_already_skipped(world):
    load(world)
    sync_service.run_sync()

    with world["db"].session_scope() as session:
        channel = session.scalar(select(Channel))
        requeued = channel_service.set_take(session, channel, "shorts", include=True)
        assert requeued == 2
        assert "shorts" not in channel.left_out_names

    sync_service.run_sync()

    # Both Shorts join the playlist, in published order alongside the rest.
    assert sorted(world["client"].contents(MAIN_PLAYLIST)) == ["s0", "s1", "v0"]


def test_turning_shorts_off_again_leaves_what_is_already_there(world):
    load(world)
    with world["db"].session_scope() as session:
        channel_service.set_take(session, session.scalar(select(Channel)), "shorts", include=True)
    sync_service.run_sync()
    assert len(world["client"].contents(MAIN_PLAYLIST)) == 3

    with world["db"].session_scope() as session:
        channel = session.scalar(select(Channel))
        assert channel_service.set_take(session, channel, "shorts", include=False) == 0
        assert "shorts" in channel.left_out_names

    # A new Short arrives and is filtered; nothing already placed is removed.
    world["entries"] = [short_entry("s_new", 0)] + world["entries"]
    world["client"].details["s_new"] = VideoDetails("s_new", "Short s_new", 30, "none", "public")
    sync_service.run_sync()

    assert sorted(world["client"].contents(MAIN_PLAYLIST)) == ["s0", "s1", "v0"]
    with world["db"].session_scope() as session:
        assert session.scalar(select(Video).where(Video.video_id == "s_new")).status == "skipped"


def test_the_toggle_only_touches_its_own_channel(world, db):
    load(world)
    with db.session_scope() as session:
        other = Channel(channel_id="UCbbbbbbbbbbbbbbbbbbbbbb", title="Other")
        session.add(other)
        session.flush()
        session.add(
            Video(
                video_id="other_short",
                channel_pk=other.id,
                title="Their short",
                status="skipped",
                reason="Short (20s)",
            )
        )
    sync_service.run_sync()

    with db.session_scope() as session:
        mine = session.scalar(select(Channel).where(Channel.title == "Fake Channel"))
        channel_service.set_take(session, mine, "shorts", include=True)
        # The other channel's skipped Short is left exactly as it was.
        assert session.scalar(
            select(Video).where(Video.video_id == "other_short")
        ).status == "skipped"


def test_a_video_skipped_for_another_reason_is_not_brought_back(world):
    load(world, shorts=1, longs=0)
    with world["db"].session_scope() as session:
        session.scalar(select(Channel)).title_exclude = "Short"
    sync_service.run_sync()

    with world["db"].session_scope() as session:
        video = session.scalar(select(Video))
        assert video.status == "skipped"
        assert "exclude pattern" in video.reason  # the title rule caught it first

        channel = session.scalar(select(Channel))
        assert channel_service.set_take(session, channel, "shorts", include=True) == 0
        assert session.scalar(select(Video)).status == "skipped"


def live_stream(world, video_id="stream", *, state="live"):
    """An upload the API reports as a broadcast rather than a normal video."""
    world["entries"] = [entry(video_id, 1, title="Going live")]
    world["client"].details = {
        video_id: VideoDetails(video_id, "Going live", 7200, state, "public")
    }


def test_live_streams_are_skipped_by_default(world):
    live_stream(world)
    sync_service.run_sync()

    assert world["client"].contents(MAIN_PLAYLIST) == []
    with world["db"].session_scope() as session:
        assert session.scalar(select(Video)).reason == "Live"


def test_premieres_are_skipped_too(world):
    live_stream(world, "premiere", state="upcoming")
    sync_service.run_sync()

    with world["db"].session_scope() as session:
        assert session.scalar(select(Video)).reason == "Live"


def test_turning_live_on_brings_back_the_finished_stream(world):
    live_stream(world)
    sync_service.run_sync()
    assert world["client"].contents(MAIN_PLAYLIST) == []

    with world["db"].session_scope() as session:
        channel = session.scalar(select(Channel))
        assert channel_service.set_take(session, channel, "live", include=True) == 1
        assert "live" not in channel.left_out_names

    # By the next run the broadcast has finished, so it is an ordinary video.
    world["client"].details["stream"] = VideoDetails("stream", "Going live", 7200, "none", "public")
    sync_service.run_sync()

    assert world["client"].contents(MAIN_PLAYLIST) == ["stream"]


def test_turning_live_off_again_leaves_what_is_already_there(world):
    live_stream(world)
    with world["db"].session_scope() as session:
        channel_service.set_take(session, session.scalar(select(Channel)), "live", include=True)
    world["client"].details["stream"] = VideoDetails("stream", "Going live", 7200, "none", "public")
    sync_service.run_sync()
    assert world["client"].contents(MAIN_PLAYLIST) == ["stream"]

    with world["db"].session_scope() as session:
        channel = session.scalar(select(Channel))
        assert channel_service.set_take(session, channel, "live", include=False) == 0

    sync_service.run_sync()
    assert world["client"].contents(MAIN_PLAYLIST) == ["stream"]


def test_each_toggle_only_brings_back_its_own_kind(world):
    """Turning live on must not drag the skipped Shorts back with it."""
    with world["db"].session_scope() as session:
        world["db"].get_settings(session).initial_backfill = 10
    world["entries"] = [short_entry("s0", 1), entry("stream", 2, title="Going live")]
    world["client"].details = {
        "s0": VideoDetails("s0", "Short s0", 30, "none", "public"),
        "stream": VideoDetails("stream", "Going live", 7200, "live", "public"),
    }
    sync_service.run_sync()

    with world["db"].session_scope() as session:
        channel = session.scalar(select(Channel))
        assert channel_service.set_take(session, channel, "live", include=True) == 1
        # The Short is still skipped, because that is a different switch.
        assert session.scalar(select(Video).where(Video.video_id == "s0")).status == "skipped"

        assert channel_service.set_take(session, channel, "shorts", include=True) == 1
        assert session.scalar(select(Video).where(Video.video_id == "s0")).status == "pending"


def test_ordinary_uploads_can_be_switched_off(world):
    """A channel you follow only for its Shorts."""
    load(world, shorts=1, longs=1)
    with world["db"].session_scope() as session:
        channel = session.scalar(select(Channel))
        channel_service.set_take(session, channel, "shorts", include=True)
        channel_service.set_take(session, channel, "videos", include=False)

    sync_service.run_sync()

    assert world["client"].contents(MAIN_PLAYLIST) == ["s0"]
    with world["db"].session_scope() as session:
        skipped = session.scalar(select(Video).where(Video.video_id == "v0"))
        assert skipped.status == "skipped" and skipped.reason == "Videos"


def test_turning_ordinary_uploads_back_on_brings_them_back(world):
    load(world, shorts=0, longs=2)
    with world["db"].session_scope() as session:
        channel_service.set_take(session, session.scalar(select(Channel)), "videos", include=False)
    sync_service.run_sync()
    assert world["client"].contents(MAIN_PLAYLIST) == []

    with world["db"].session_scope() as session:
        channel = session.scalar(select(Channel))
        assert channel_service.set_take(session, channel, "videos", include=True) == 2

    sync_service.run_sync()
    assert sorted(world["client"].contents(MAIN_PLAYLIST)) == ["v0", "v1"]


def test_switching_videos_off_leaves_shorts_and_streams_alone(world):
    load(world, shorts=1, longs=1)
    with world["db"].session_scope() as session:
        channel = session.scalar(select(Channel))
        channel_service.set_take(session, channel, "shorts", include=True)
        channel_service.set_take(session, channel, "videos", include=False)
    sync_service.run_sync()

    with world["db"].session_scope() as session:
        channel = session.scalar(select(Channel))
        # Bringing ordinary uploads back does not disturb the other switches.
        channel_service.set_take(session, channel, "videos", include=True)
        assert "shorts" not in channel.left_out_names
        assert "live" in channel.left_out_names


def test_a_broadcast_is_not_an_ordinary_upload(world):
    """Switching videos off must not silently take live streams with it."""
    live_stream(world)
    with world["db"].session_scope() as session:
        channel = session.scalar(select(Channel))
        channel_service.set_take(session, channel, "live", include=True)
        channel_service.set_take(session, channel, "videos", include=False)

    sync_service.run_sync()

    assert world["client"].contents(MAIN_PLAYLIST) == ["stream"]


def test_all_three_off_takes_nothing(world):
    load(world, shorts=1, longs=1)
    with world["db"].session_scope() as session:
        channel = session.scalar(select(Channel))
        channel_service.set_take(session, channel, "videos", include=False)
        channel_service.set_take(session, channel, "posts", include=False)
        assert channel.takes_nothing is True

    sync_service.run_sync()

    assert world["client"].contents(MAIN_PLAYLIST) == []
