"""Fill order: which channel gets in first, and which playlist."""

from __future__ import annotations

from sqlalchemy import select

from dealgo.models import Channel, Playlist, Video
from dealgo.services import ordering
from dealgo.services import quota
from dealgo.services import sync as sync_service
from dealgo.youtube.api import VideoDetails
from fakes import MAIN_PLAYLIST, entry

SECOND = "PL_second"


def add_channel(db, channel_id: str, title: str, *, playlists=None):
    from dealgo.models import GraphEdge, GraphNode

    with db.session_scope() as session:
        channel = Channel(channel_id=channel_id, title=title)
        session.add(channel)
        session.flush()
        ordering.append(session, channel)
        channel.playlists = list(session.scalars(select(Playlist))) if playlists is None else playlists

        # On the canvas and wired to the trigger the fixture drew, because a
        # source with none is not polled at all.
        box = GraphNode(kind="source", channel_pk=channel.id, enabled=True, x=0, y=0)
        session.add(box)
        session.flush()
        pulse = session.scalar(select(GraphNode).where(GraphNode.kind == "trigger"))
        if pulse is not None:
            session.add(GraphEdge(source_pk=pulse.id, target_pk=box.id))
        return channel.id


def test_moving_a_channel_changes_the_order(db, world):
    second = add_channel(db, "UCbbbbbbbbbbbbbbbbbbbbbb", "Second")
    third = add_channel(db, "UCccccccccccccccccccccc1", "Third")

    with db.session_scope() as session:
        order = [c.title for c in session.scalars(select(Channel).order_by(Channel.priority))]
        assert order == ["Fake Channel", "Second", "Third"]

        assert ordering.move_channel(session, third, "up")
        order = [c.title for c in session.scalars(select(Channel).order_by(Channel.priority))]
        assert order == ["Fake Channel", "Third", "Second"]

        assert ordering.move_channel(session, third, "up")
        order = [c.title for c in session.scalars(select(Channel).order_by(Channel.priority))]
        assert order == ["Third", "Fake Channel", "Second"]

        # Already first: nothing to do, and the order is untouched.
        assert not ordering.move_channel(session, third, "up")
        assert [c.title for c in session.scalars(select(Channel).order_by(Channel.priority))] == [
            "Third",
            "Fake Channel",
            "Second",
        ]
        assert second is not None


def test_priorities_stay_dense_after_a_move(db, world):
    add_channel(db, "UCbbbbbbbbbbbbbbbbbbbbbb", "Second")
    add_channel(db, "UCccccccccccccccccccccc1", "Third")

    with db.session_scope() as session:
        rows = list(session.scalars(select(Channel).order_by(Channel.priority)))
        ordering.move_channel(session, rows[-1].id, "up")
        priorities = [c.priority for c in session.scalars(select(Channel).order_by(Channel.priority))]
        assert priorities == [0, 1, 2]


def test_the_highest_priority_channel_is_inserted_first(world, db):
    """With a budget for one insert, the top channel is the one that gets it."""
    other = add_channel(db, "UCbbbbbbbbbbbbbbbbbbbbbb", "Late Channel")

    with db.session_scope() as session:
        # Put the second channel first in the fill order.
        ordering.move_channel(session, other, "up")
        db.get_settings(session).initial_backfill = 10
        db.get_settings(session).daily_quota = 60  # one insert, plus reads

    # Both channels have an upload; the newer one belongs to the top channel.
    feeds_by_channel = {
        "UCzzzzzzzzzzzzzzzzzzzzzz": [entry("slow", 1)],
        "UCbbbbbbbbbbbbbbbbbbbbbb": [entry("fast", 99)],  # older, but higher priority
    }

    from dealgo.youtube import feeds as feed_module

    def per_channel(channel_id, _http):
        return feed_module.FeedResult(
            channel_id=channel_id, channel_title="c", entries=feeds_by_channel[channel_id]
        )

    world["client"].details = {
        "slow": VideoDetails("slow", "Slow", 600, "none", "public"),
        "fast": VideoDetails("fast", "Fast", 600, "none", "public"),
    }

    import pytest

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(feed_module, "fetch_feed", per_channel)
    try:
        result = sync_service.run_sync()
    finally:
        monkeypatch.undo()

    assert result.stopped_on_quota
    assert world["client"].contents() == ["fast"]
    with db.session_scope() as session:
        left = session.scalar(select(Video).where(Video.status == "pending"))
        assert left.video_id == "slow"


def test_within_a_channel_the_order_stays_chronological(world):
    with world["db"].session_scope() as session:
        world["db"].get_settings(session).initial_backfill = 10
    world["entries"] = [entry(f"v{i}", i) for i in range(3)]
    world["client"].details = {
        f"v{i}": VideoDetails(f"v{i}", f"Video v{i}", 600, "none", "public") for i in range(3)
    }

    sync_service.run_sync()

    # v2 is the oldest, so it goes in first and the playlist reads in order.
    assert world["client"].contents() == ["v2", "v1", "v0"]


def test_the_first_playlist_is_filled_first(world, add_playlist, db):
    second_pk = add_playlist(SECOND, "Mirror")
    with db.session_scope() as session:
        # Mirror goes to the top of the fill order.
        ordering.move_playlist(session, second_pk, "up")
        db.get_settings(session).daily_quota = 60  # room for exactly one insert

    world["entries"] = [entry("v0", 1)]
    world["client"].details = {"v0": VideoDetails("v0", "Video v0", 600, "none", "public")}

    result = sync_service.run_sync()

    assert result.stopped_on_quota
    assert world["client"].contents(SECOND) == ["v0"]
    assert world["client"].contents(MAIN_PLAYLIST) == []

    # The other playlist is filled once the quota allows it.
    with db.session_scope() as session:
        db.get_settings(session).daily_quota = 10000
        quota.spend(session, 0)
    sync_service.run_sync()
    assert world["client"].contents(MAIN_PLAYLIST) == ["v0"]


def test_a_new_channel_joins_the_end_of_the_order(world, db):
    import httpx

    from dealgo.services import channels as channel_service

    with db.session_scope() as session, httpx.Client() as http:
        channel = channel_service.add_channel(session, "UCaaaaaaaaaaaaaaaaaaaaaa", http)
        assert channel.priority == 1  # after the existing one, not ahead of it
