"""The quota ledger, and stopping before YouTube refuses us."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from pamphlets.models import Channel, Playlist, SyncRun, Video
from pamphlets.services import quota
from pamphlets.services import sync as sync_service
from pamphlets.services import watched as watched_service
from pamphlets.plugins.publisher import PublishError, VideoDetails, cost_of
from fakes import MAIN_PLAYLIST, entry, set_quota


def test_costs_match_googles_published_table():
    """Asked of the plugin rather than kept here: a service's price list is
    its own, and a second copy would be a second thing to keep in step."""
    assert cost_of("add") == 50
    assert cost_of("remove") == 50
    assert cost_of("read") == 1
    assert cost_of("search") == 100  # why handles are resolved cheaply first
    assert cost_of("somethingNew") == 1  # a call nobody priced still counts


def test_the_quota_day_follows_pacific_not_utc():
    # 07:00 UTC is midnight Pacific in summer: the allowance has just reset.
    just_before = dt.datetime(2026, 9, 4, 6, 30, tzinfo=dt.timezone.utc)
    just_after = dt.datetime(2026, 9, 4, 7, 30, tzinfo=dt.timezone.utc)
    assert quota.quota_day(just_before) == "2026-09-03"
    assert quota.quota_day(just_after) == "2026-09-04"
    assert quota.next_reset(just_before) == just_after.replace(minute=0)


def test_spending_accumulates_and_resets_with_the_day(db):
    with db.session_scope() as session:
        quota.spend(session, 50)
        quota.spend(session, 1)
        state = quota.state(session)
        assert state.used == 51
        assert state.remaining == 10000 - 51
        assert not state.exhausted

        # Tomorrow's row starts clean.
        assert quota.quota_day(dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)) != state.day


def test_the_reserve_is_held_back_from_syncing(db):
    set_quota(daily=200, reserve=100)
    with db.session_scope() as session:
        quota.spend(session, 100)

        state = quota.state(session)
        assert state.remaining == 100
        assert state.spendable == 0  # all that is left is the reserve
        assert not quota.can_afford(session, 50)
        assert quota.can_afford(session, 50, use_reserve=True)


def test_a_refusal_from_youtube_beats_our_own_arithmetic(db):
    with db.session_scope() as session:
        quota.mark_exhausted(session)
        state = quota.state(session)
        assert state.exhausted
        assert state.spendable == 0
        assert not quota.can_afford(session, 1, use_reserve=True)


@pytest.fixture
def loaded(world):
    """Three uploads waiting, and a client that reports their details."""
    with world["db"].session_scope() as session:
        world["db"].get_settings(session).initial_backfill = 10
    world["entries"] = [entry(f"v{i}", i) for i in range(3)]
    world["client"].details = {
        f"v{i}": VideoDetails(f"v{i}", f"Video v{i}", 600, "none", "public") for i in range(3)
    }
    return world


def test_a_sync_spends_and_records_what_it_used(loaded):
    result = sync_service.run_sync()

    assert result.added == 3
    # Three inserts at 50 each, plus the cheap reads around them.
    assert result.quota_spent >= 3 * cost_of("add")
    with loaded["db"].session_scope() as session:
        run = session.scalar(select(SyncRun).order_by(SyncRun.id.desc()))
        assert run.quota_spent == result.quota_spent
        assert not run.stopped_on_quota
        assert quota.state(session).used == run.quota_spent


def test_syncing_stops_at_the_budget_and_queues_the_rest(loaded):
    with loaded["db"].session_scope() as session:
        settings = loaded["db"].get_settings(session)
        set_quota(daily=120, session=session)  # enough for two inserts and some reads

    result = sync_service.run_sync()

    assert result.stopped_on_quota
    assert len(loaded["client"].contents()) < 3
    assert "allowance is spent" in result.message.lower()
    with loaded["db"].session_scope() as session:
        # Whatever did not fit is still pending, not failed or dropped.
        pending = list(session.scalars(select(Video).where(Video.status == "pending")))
        assert pending
        assert all(v.status != "failed" for v in session.scalars(select(Video)))


def test_the_next_run_does_nothing_until_the_quota_resets(loaded):
    with loaded["db"].session_scope() as session:
        set_quota(daily=120, session=session)
    sync_service.run_sync()
    before = list(loaded["client"].contents())

    loaded["client"].inserted.clear()
    result = sync_service.run_sync()

    assert result.stopped_on_quota
    assert result.added == 0
    assert loaded["client"].inserted == []
    assert loaded["client"].contents() == before
    assert "resets" in result.message

    # Polling is free, so discovery still happened.
    assert result.channels_checked == 1


def test_a_fresh_quota_day_resumes_the_queue(loaded, monkeypatch):
    with loaded["db"].session_scope() as session:
        set_quota(daily=120, session=session)
    sync_service.run_sync()
    assert len(loaded["client"].contents()) < 3

    # Roll over to the next quota day.
    tomorrow = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)
    monkeypatch.setattr(quota, "quota_day", lambda now=None, **_: tomorrow.date().isoformat())
    with loaded["db"].session_scope() as session:
        set_quota(daily=10000, session=session)

    result = sync_service.run_sync()

    assert result.added > 0
    assert loaded["client"].contents() == ["v2", "v1", "v0"]


def test_youtube_refusing_mid_run_pauses_the_rest(loaded, monkeypatch):
    real_insert = loaded["client"].insert_playlist_item
    calls = []

    def refuse_after_one(playlist_id, video_id):
        calls.append(video_id)
        if len(calls) > 1:
            raise PublishError("quota", status=403, reason="quotaExceeded")
        return real_insert(playlist_id, video_id)

    monkeypatch.setattr(loaded["client"], "insert_playlist_item", refuse_after_one)
    result = sync_service.run_sync()

    assert result.stopped_on_quota
    assert result.added == 1
    with loaded["db"].session_scope() as session:
        assert quota.state(session).exhausted
        # A later run must not even try again today.
        assert not quota.can_afford(session, cost_of("add"))


def test_removal_may_dip_into_the_reserve(loaded):
    sync_service.run_sync()
    with loaded["db"].session_scope() as session:
        settings = loaded["db"].get_settings(session)
        set_quota(daily=quota.state(session).used + 100, session=session)
        set_quota(reserve=100, session=session)  # nothing left for syncing, all for manual work
        watched_service.mark_watched(session, [v.id for v in session.scalars(select(Video))])

    result = watched_service.remove_watched()

    assert result.removed >= 1


def test_a_fan_out_cut_short_is_finished_next_run(world, add_playlist, db):
    """Quota running out mid-video must not leave a playlist silently skipped."""
    from pamphlets.models import Placement

    add_playlist("PL_second", "Mirror")
    with db.session_scope() as session:
        set_quota(daily=60, session=session)  # room for one of the two inserts
    world["entries"] = [entry("v0", 1)]
    world["client"].details = {"v0": VideoDetails("v0", "Video v0", 600, "none", "public")}

    first = sync_service.run_sync()
    assert first.added == 1 and first.stopped_on_quota

    with db.session_scope() as session:
        # The playlist that missed out is recorded as owed, not forgotten.
        owed = list(
            session.scalars(select(Placement).where(Placement.playlist_item_id.is_(None)))
        )
        assert len(owed) == 1
        assert owed[0].removed_at is None
        set_quota(daily=10000, session=session)

    second = sync_service.run_sync()

    assert second.added == 1
    assert world["client"].contents(MAIN_PLAYLIST) == ["v0"]
    assert world["client"].contents("PL_second") == ["v0"]


def test_a_transient_insert_failure_is_retried_then_given_up_on(world, add_playlist, monkeypatch):
    """A failed placement should not be forgotten the way it once was."""
    from pamphlets.models import Placement

    world["entries"] = [entry("v0", 1)]
    world["client"].details = {"v0": VideoDetails("v0", "Video v0", 600, "none", "public")}

    attempts = []

    def always_fail(playlist_id, video_id):
        attempts.append(video_id)
        raise PublishError("server error", status=500, reason="backendError")

    monkeypatch.setattr(world["client"], "insert_playlist_item", always_fail)
    for _ in range(4):
        sync_service.run_sync()

    # Tried MAX_INSERT_ATTEMPTS times in total, then left alone.
    assert len(attempts) == sync_service.MAX_INSERT_ATTEMPTS
    with world["db"].session_scope() as session:
        placement = session.scalar(select(Placement))
        assert placement.playlist_item_id is None
        assert "server error" in placement.error


def test_a_playlist_assigned_later_does_not_backfill_history(world, add_playlist, db):
    """Only placements a run actually attempted are retried."""
    world["entries"] = [entry("v0", 1)]
    world["client"].details = {"v0": VideoDetails("v0", "Video v0", 600, "none", "public")}
    sync_service.run_sync()
    assert world["client"].contents(MAIN_PLAYLIST) == ["v0"]

    # A new playlist for the same channel, added after the fact.
    add_playlist("PL_late", "Late")
    sync_service.run_sync()

    assert world["client"].contents("PL_late") == []
