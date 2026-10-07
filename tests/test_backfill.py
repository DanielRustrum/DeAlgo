"""Choosing how much of a channel's history to take when tracking it."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from pamphlets.models import Channel, Video
from pamphlets.services import channels as channel_service
from pamphlets.services import sync as sync_service
from pamphlets.plugins.publisher import VideoDetails
from fakes import MAIN_PLAYLIST, entry


def aged_uploads(world, ages_in_days):
    """One upload per given age, newest first as the feed reports them."""
    world["entries"] = [
        entry(f"d{days}", minutes_ago=days * 24 * 60) for days in sorted(ages_in_days)
    ]
    world["client"].details = {
        f"d{days}": VideoDetails(f"d{days}", f"Video {days}d", 600, "none", "public")
        for days in ages_in_days
    }


def statuses(db) -> dict[str, str]:
    with db.session_scope() as session:
        return {v.video_id: v.status for v in session.scalars(select(Video))}


def set_backfill(db, days):
    with db.session_scope() as session:
        session.scalar(select(Channel)).backfill_days = days


def test_the_choices_map_to_days(db):
    assert channel_service.parse_backfill("") is None      # the global default
    assert channel_service.parse_backfill("0") == 0        # nothing
    assert channel_service.parse_backfill("30") == 30
    assert channel_service.parse_backfill("junk") is None
    assert channel_service.parse_backfill("-5") == 0


def test_a_window_takes_everything_inside_it(world, db):
    set_backfill(db, 30)
    aged_uploads(world, [1, 10, 25, 45, 200])

    sync_service.run_sync()

    assert sorted(world["client"].contents(MAIN_PLAYLIST)) == ["d1", "d10", "d25"]
    assert statuses(db) == {
        "d1": "added", "d10": "added", "d25": "added",
        "d45": "ignored", "d200": "ignored",
    }


def test_it_beats_the_global_count(world, db):
    """The global default would have taken the newest three regardless."""
    with db.session_scope() as session:
        db.get_settings(session).initial_backfill = 3
    set_backfill(db, 7)
    aged_uploads(world, [1, 2, 3, 4, 5])

    sync_service.run_sync()

    # All five are inside a week, even though the count would have capped at 3.
    assert len(world["client"].contents(MAIN_PLAYLIST)) == 5


def test_zero_days_takes_nothing_old(world, db):
    set_backfill(db, 0)
    aged_uploads(world, [1, 5, 30])

    result = sync_service.run_sync()

    assert result.added == 0
    assert set(statuses(db).values()) == {"ignored"}


def test_zero_days_still_takes_what_comes_next(world, db):
    set_backfill(db, 0)
    aged_uploads(world, [1, 5])
    sync_service.run_sync()
    assert world["client"].contents(MAIN_PLAYLIST) == []

    # A genuinely new upload after that first check is taken as normal.
    world["entries"] = [entry("fresh", 1)] + world["entries"]
    world["client"].details["fresh"] = VideoDetails("fresh", "Fresh", 600, "none", "public")
    sync_service.run_sync()

    assert world["client"].contents(MAIN_PLAYLIST) == ["fresh"]


def test_no_choice_keeps_the_old_behaviour(world, db):
    with db.session_scope() as session:
        db.get_settings(session).initial_backfill = 2
        assert session.scalar(select(Channel)).backfill_days is None
    aged_uploads(world, [1, 2, 3, 4])

    sync_service.run_sync()

    assert len(world["client"].contents(MAIN_PLAYLIST)) == 2


def test_the_window_only_applies_to_the_first_check(world, db):
    set_backfill(db, 7)
    aged_uploads(world, [1])
    sync_service.run_sync()
    assert world["client"].contents(MAIN_PLAYLIST) == ["d1"]

    # An older upload surfacing later is not retroactively judged by the window.
    world["entries"] = [entry("late", 20 * 24 * 60)] + world["entries"]
    world["client"].details["late"] = VideoDetails("late", "Late", 600, "none", "public")
    sync_service.run_sync()

    assert "late" in world["client"].contents(MAIN_PLAYLIST)
