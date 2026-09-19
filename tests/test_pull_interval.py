"""How often a source is polled, and what happens while it waits.

This used to be a per-channel minimum gap, set from a list of channels that
no longer exists. The canvas is the whole configuration now: a trigger box
says when a source is polled, and a source with none is not polled at all.
So these are the same properties, asked of the thing that decides them.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from dealgo.models import Channel, GraphNode, Video, utcnow
from dealgo.services import sync as sync_service
from dealgo.youtube.api import VideoDetails
from fakes import MAIN_PLAYLIST, entry


def set_pulse(db, minutes: int) -> None:
    """Change the gap on the trigger the world fixture wired in."""
    with db.session_scope() as session:
        pulse = session.scalar(select(GraphNode).where(GraphNode.kind == "trigger"))
        pulse.every_minutes = minutes


def checked_ago(db, **delta) -> None:
    with db.session_scope() as session:
        session.scalar(select(Channel)).last_checked_at = utcnow() - dt.timedelta(**delta)


def upload(world, video_id, minutes_ago=1):
    world["entries"] = [entry(video_id, minutes_ago)]
    world["client"].details[video_id] = VideoDetails(video_id, video_id, 600, "none", "public")


def test_a_pulse_of_zero_means_every_run(world):
    """The plainest thing a pulse can say, and what a channel with no minimum
    gap always did before the canvas had triggers to say it with."""
    upload(world, "v0")
    assert sync_service.run_sync().channels_checked == 1

    upload(world, "v1")
    assert sync_service.run_sync().channels_checked == 1


def test_a_source_is_left_alone_until_its_pulse_comes_round(world, db):
    set_pulse(db, 1440)
    upload(world, "v0")
    sync_service.run_sync()

    upload(world, "v1")
    result = sync_service.run_sync()

    assert result.channels_waiting == 1
    assert result.discovered == 0


def test_it_is_polled_again_once_the_gap_elapses(world, db):
    set_pulse(db, 60)
    upload(world, "v0")
    sync_service.run_sync()
    checked_ago(db, hours=2)

    upload(world, "v1")
    result = sync_service.run_sync()

    assert result.channels_checked == 1
    assert result.discovered == 1


def test_a_source_never_checked_is_always_due(world, db):
    set_pulse(db, 10080)  # weekly, and it has never been looked at
    upload(world, "v0")

    assert sync_service.run_sync().discovered == 1


def test_the_gap_applies_to_a_run_somebody_started_too(world, db):
    """A run by hand is still a run. Pressing the trigger itself is the thing
    that ignores the gap, and that forces."""
    set_pulse(db, 1440)
    sync_service.run_sync()

    upload(world, "v1")
    assert sync_service.run_sync("manual").channels_waiting == 1


def test_waiting_does_not_stall_the_videos_already_queued(world, db):
    """A source that is not due still gets its pending videos published: the
    two halves of a run are separate, and only the polling half waits."""
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

    set_pulse(db, 1440)
    with db.session_scope() as session:
        db.get_settings(session).daily_quota = 10000

    second = sync_service.run_sync()

    assert second.channels_waiting == 1  # not polled
    assert second.added == 1             # but the queue still moved


def test_a_forced_run_polls_a_source_that_is_not_due(world, db):
    upload(world, "v0")
    sync_service.run_sync()
    set_pulse(db, 10080)  # weekly

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
    set_pulse(db, 1440)
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
    """Force ignores when a source is due, not the pause switch."""
    with db.session_scope() as session:
        session.scalar(select(Channel)).enabled = False
    upload(world, "v0")

    result = sync_service.run_sync(force=True)

    assert result.channels_checked == 0
    assert result.discovered == 0


def test_a_switched_off_trigger_polls_nothing(world, db):
    """The box is still drawn and still wired; it is simply not firing."""
    with db.session_scope() as session:
        session.scalar(select(GraphNode).where(GraphNode.kind == "trigger")).enabled = False
    upload(world, "v0")

    result = sync_service.run_sync()

    assert result.channels_checked == 0
    assert result.discovered == 0
    with db.session_scope() as session:
        assert session.scalars(select(Video)).all() == []
