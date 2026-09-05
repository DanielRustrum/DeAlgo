"""The minimum gap between feed checks, per channel."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from dealgo.models import Channel, Video, utcnow
from dealgo.services import channels as channel_service
from dealgo.services import sync as sync_service
from dealgo.youtube.api import VideoDetails
from fakes import MAIN_PLAYLIST, entry


def set_interval(db, minutes: int) -> None:
    with db.session_scope() as session:
        channel_service.set_pull_interval(session, session.scalar(select(Channel)), minutes)


def checked_ago(db, **delta) -> None:
    with db.session_scope() as session:
        session.scalar(select(Channel)).last_checked_at = utcnow() - dt.timedelta(**delta)


def upload(world, video_id, minutes_ago=1):
    world["entries"] = [entry(video_id, minutes_ago)]
    world["client"].details[video_id] = VideoDetails(video_id, video_id, 600, "none", "public")


def test_no_minimum_means_every_sync(world):
    upload(world, "v0")
    assert sync_service.run_sync().channels_checked == 1
    upload(world, "v1")
    result = sync_service.run_sync()

    assert result.channels_checked == 1
    assert result.channels_waiting == 0
    assert result.discovered == 1


def test_a_channel_is_left_alone_until_its_gap_has_passed(world, db):
    upload(world, "v0")
    sync_service.run_sync()
    set_interval(db, 360)  # six hours

    upload(world, "v1")  # published in the meantime
    result = sync_service.run_sync()

    assert result.channels_checked == 0
    assert result.channels_waiting == 1
    assert result.discovered == 0
    with db.session_scope() as session:
        assert session.scalar(select(Video).where(Video.video_id == "v1")) is None


def test_it_is_polled_again_once_the_gap_elapses(world, db):
    upload(world, "v0")
    sync_service.run_sync()
    set_interval(db, 360)
    checked_ago(db, hours=7)

    upload(world, "v1")
    result = sync_service.run_sync()

    assert result.channels_checked == 1
    assert result.discovered == 1
    assert world["client"].contents(MAIN_PLAYLIST) == ["v0", "v1"]


def test_a_never_checked_channel_is_always_due(world, db):
    set_interval(db, 10080)  # weekly, but it has never been polled
    upload(world, "v0")

    result = sync_service.run_sync()

    assert result.channels_checked == 1
    assert result.discovered == 1


def test_the_gap_applies_to_manual_runs_too(world, db):
    """It is a minimum, not a schedule — pressing Sync now does not bypass it."""
    upload(world, "v0")
    sync_service.run_sync(trigger="scheduled")
    set_interval(db, 1440)

    upload(world, "v1")
    assert sync_service.run_sync(trigger="manual").channels_waiting == 1


def test_waiting_does_not_stall_the_videos_already_queued(world, db):
    """A throttled channel still gets its pending videos published."""
    with db.session_scope() as session:
        db.get_settings(session).initial_backfill = 10
        db.get_settings(session).daily_quota = 60  # room for one insert
    world["entries"] = [entry("v0", 1), entry("v1", 2)]
    world["client"].details = {
        "v0": VideoDetails("v0", "v0", 600, "none", "public"),
        "v1": VideoDetails("v1", "v1", 600, "none", "public"),
    }
    first = sync_service.run_sync()
    assert first.added == 1

    set_interval(db, 1440)
    with db.session_scope() as session:
        db.get_settings(session).daily_quota = 10000

    second = sync_service.run_sync()

    assert second.channels_waiting == 1  # not polled
    assert second.added == 1             # but the queue still moved
    assert sorted(world["client"].contents(MAIN_PLAYLIST)) == ["v0", "v1"]


def test_intervals_are_described_readably():
    assert channel_service.describe_interval(0) == "every sync"
    assert channel_service.describe_interval(360) == "every 6 hours"
    assert channel_service.describe_interval(1440) == "daily"
    assert channel_service.describe_interval(2880) == "every 2 days"
    assert channel_service.describe_interval(120) == "every 2 hours"
    assert channel_service.describe_interval(45) == "every 45 min"


def test_next_check_is_reported(world, db):
    set_interval(db, 120)
    with db.session_scope() as session:
        channel = session.scalar(select(Channel))
        assert channel.next_check_at is None  # never polled, so always due

        channel.last_checked_at = utcnow()
        assert not channel.is_due()
        assert channel.next_check_at is not None


def test_a_forced_run_polls_a_channel_that_is_not_due(world, db):
    upload(world, "v0")
    sync_service.run_sync()
    set_interval(db, 10080)  # weekly

    upload(world, "v1")
    waited = sync_service.run_sync()
    assert waited.channels_waiting == 1 and waited.discovered == 0

    forced = sync_service.run_sync(force=True)

    assert forced.channels_checked == 1
    assert forced.channels_waiting == 0
    assert forced.discovered == 1
    assert world["client"].contents(MAIN_PLAYLIST) == ["v0", "v1"]


def test_forcing_does_not_reset_the_gap_for_later_runs(world, db):
    """A forced poll updates last_checked_at, so the gap restarts from now."""
    upload(world, "v0")
    sync_service.run_sync()
    set_interval(db, 1440)
    checked_ago(db, days=2)

    sync_service.run_sync(force=True)

    upload(world, "v2")
    assert sync_service.run_sync().channels_waiting == 1


def test_a_forced_run_is_recorded_as_such(world, db):
    from dealgo.models import SyncRun

    sync_service.run_sync(force=True)

    with db.session_scope() as session:
        run = session.scalar(select(SyncRun).order_by(SyncRun.id.desc()))
        assert run.forced is True

    sync_service.run_sync()
    with db.session_scope() as session:
        run = session.scalar(select(SyncRun).order_by(SyncRun.id.desc()))
        assert run.forced is False


def test_a_disabled_channel_stays_disabled_even_when_forced(world, db):
    """Force ignores the minimum gap, not the pause switch."""
    with db.session_scope() as session:
        session.scalar(select(Channel)).enabled = False
    upload(world, "v0")

    result = sync_service.run_sync(force=True)

    assert result.channels_checked == 0
    assert result.discovered == 0
