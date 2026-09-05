"""The quota ledger, and stopping before YouTube refuses us."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select

from dealgo.models import Channel, Playlist, SyncRun, Video
from dealgo.services import quota
from dealgo.services import sync as sync_service
from dealgo.services import watched as watched_service
from dealgo.youtube.api import QUOTA_COST_INSERT, VideoDetails, YouTubeAPIError, cost_of
from fakes import MAIN_PLAYLIST, entry


def test_costs_match_googles_published_table():
    assert cost_of("POST", "playlistItems") == 50
    assert cost_of("DELETE", "playlistItems") == 50
    assert cost_of("GET", "videos") == 1
    assert cost_of("GET", "playlistItems") == 1
    assert cost_of("GET", "search") == 100  # why handles are resolved cheaply first
    assert cost_of("GET", "somethingNew") == 1  # unknown calls still count


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
    with db.session_scope() as session:
        settings = db.get_settings(session)
        settings.daily_quota = 200
        settings.quota_reserve = 100
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
    assert result.quota_spent >= 3 * QUOTA_COST_INSERT
    with loaded["db"].session_scope() as session:
        run = session.scalar(select(SyncRun).order_by(SyncRun.id.desc()))
        assert run.quota_spent == result.quota_spent
        assert not run.stopped_on_quota
        assert quota.state(session).used == run.quota_spent


def test_syncing_stops_at_the_budget_and_queues_the_rest(loaded):
    with loaded["db"].session_scope() as session:
        settings = loaded["db"].get_settings(session)
        settings.daily_quota = 120  # enough for two inserts and some reads

    result = sync_service.run_sync()

    assert result.stopped_on_quota
    assert len(loaded["client"].contents()) < 3
    assert "quota" in result.message.lower()
    with loaded["db"].session_scope() as session:
        # Whatever did not fit is still pending, not failed or dropped.
        pending = list(session.scalars(select(Video).where(Video.status == "pending")))
        assert pending
        assert all(v.status != "failed" for v in session.scalars(select(Video)))


def test_the_next_run_does_nothing_until_the_quota_resets(loaded):
    with loaded["db"].session_scope() as session:
        loaded["db"].get_settings(session).daily_quota = 120
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
        loaded["db"].get_settings(session).daily_quota = 120
    sync_service.run_sync()
    assert len(loaded["client"].contents()) < 3

    # Roll over to the next quota day.
    tomorrow = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)
    monkeypatch.setattr(quota, "quota_day", lambda now=None: quota.QUOTA_TZ and tomorrow.date().isoformat())
    with loaded["db"].session_scope() as session:
        loaded["db"].get_settings(session).daily_quota = 10000

    result = sync_service.run_sync()

    assert result.added > 0
    assert loaded["client"].contents() == ["v2", "v1", "v0"]


def test_youtube_refusing_mid_run_pauses_the_rest(loaded, monkeypatch):
    real_insert = loaded["client"].insert_playlist_item
    calls = []

    def refuse_after_one(playlist_id, video_id):
        calls.append(video_id)
        if len(calls) > 1:
            raise YouTubeAPIError("quota", status=403, reason="quotaExceeded")
        return real_insert(playlist_id, video_id)

    monkeypatch.setattr(loaded["client"], "insert_playlist_item", refuse_after_one)
    result = sync_service.run_sync()

    assert result.stopped_on_quota
    assert result.added == 1
    with loaded["db"].session_scope() as session:
        assert quota.state(session).exhausted
        # A later run must not even try again today.
        assert not quota.can_afford(session, QUOTA_COST_INSERT)


def test_removal_may_dip_into_the_reserve(loaded):
    sync_service.run_sync()
    with loaded["db"].session_scope() as session:
        settings = loaded["db"].get_settings(session)
        settings.daily_quota = quota.state(session).used + 100
        settings.quota_reserve = 100  # nothing left for syncing, all for manual work
        watched_service.mark_watched(session, [v.id for v in session.scalars(select(Video))])

    result = watched_service.remove_watched()

    assert result.removed >= 1


def test_the_real_client_charges_each_request(db):
    """The fake meters like the client; this checks the client itself does."""
    import httpx

    from dealgo.youtube.api import YouTubeClient

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/playlistItems") and request.method == "POST":
            return httpx.Response(200, json={"id": "item-1"})
        return httpx.Response(200, json={"items": []})

    spent: list[int] = []
    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as http:
        client = YouTubeClient(http=http, access_token="token", meter=spent.append)
        client.video_details(["a", "b"])          # 1
        client.playlist_items("PL")               # 1
        client.insert_playlist_item("PL", "a")    # 50

    assert spent == [1, 1, 50]


def test_a_request_youtube_refuses_is_still_charged(db):
    """Google bills failed calls too — except the one refused for no quota."""
    import httpx

    from dealgo.youtube.api import YouTubeClient

    responses = iter(
        [
            httpx.Response(
                404, json={"error": {"message": "gone", "errors": [{"reason": "videoNotFound"}]}}
            ),
            httpx.Response(
                403, json={"error": {"message": "no", "errors": [{"reason": "quotaExceeded"}]}}
            ),
        ]
    )
    spent: list[int] = []
    with httpx.Client(transport=httpx.MockTransport(lambda request: next(responses))) as http:
        client = YouTubeClient(http=http, access_token="token", meter=spent.append)
        for _ in range(2):
            with pytest.raises(YouTubeAPIError):
                client.insert_playlist_item("PL", "a")

    assert spent == [50]  # charged for the 404, not for the quota refusal


def test_a_fan_out_cut_short_is_finished_next_run(world, add_playlist, db):
    """Quota running out mid-video must not leave a playlist silently skipped."""
    from dealgo.models import Placement

    add_playlist("PL_second", "Mirror")
    with db.session_scope() as session:
        db.get_settings(session).daily_quota = 60  # room for one of the two inserts
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
        db.get_settings(session).daily_quota = 10000

    second = sync_service.run_sync()

    assert second.added == 1
    assert world["client"].contents(MAIN_PLAYLIST) == ["v0"]
    assert world["client"].contents("PL_second") == ["v0"]


def test_a_transient_insert_failure_is_retried_then_given_up_on(world, add_playlist, monkeypatch):
    """A failed placement should not be forgotten the way it once was."""
    from dealgo.models import Placement

    world["entries"] = [entry("v0", 1)]
    world["client"].details = {"v0": VideoDetails("v0", "Video v0", 600, "none", "public")}

    attempts = []

    def always_fail(playlist_id, video_id):
        attempts.append(video_id)
        raise YouTubeAPIError("server error", status=500, reason="backendError")

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
