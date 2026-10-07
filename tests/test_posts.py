"""Community posts: written content, landing in a feed beside the videos.

How they are *read* is the YouTube plugin's business and is tested there.
This is about what the app does with them once it has them, which is the same
whichever source keeps things its feed does not carry.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from pamphlets.models import Channel, Placement, Video
from pamphlets.services import channels as channel_service
from pamphlets.services import sync as sync_service
from pamphlets.plugins.publisher import VideoDetails
from fakes import entry


# -- discovery and placement ----------------------------------------------


def posted(world, *posts):
    """What a plugin hands back: plain rows, dated in seconds since the epoch
    because a plugin has no date type and a number is what it can compare."""
    now = dt.datetime.now(dt.timezone.utc).timestamp()
    world["posts"] = [
        {
            "id": p["id"],
            "text": p.get("text", ""),
            "published_at": now - p.get("hours", 1) * 3600,
            "images": p.get("images", []),
        }
        for p in posts
    ]


def test_posts_land_in_the_feed_beside_the_videos(world, db):
    with db.session_scope() as session:
        db.get_settings(session).initial_backfill = 10
    world["entries"] = [entry("v0", 1)]
    world["client"].details = {"v0": VideoDetails("v0", "Video v0", 600, "none", "public")}
    posted(world, {"id": "Ugk1", "text": "A note", "images": ["https://i.test/a.jpg"]})

    sync_service.run_sync()

    with db.session_scope() as session:
        post = session.scalar(select(Video).where(Video.kind == "post"))
        assert post is not None
        assert post.title == "A note"
        assert post.body == "A note"
        assert post.image_list == ["https://i.test/a.jpg"]
        # The first image is what the feed list shows.
        assert post.thumbnail_url == "https://i.test/a.jpg"
        assert post.status == "added"


def test_a_post_is_never_pushed_to_a_youtube_playlist(world, db):
    """There is no playlist that takes one, so it is local for good — not
    owed to YouTube the way a video collected while signed out is."""
    with db.session_scope() as session:
        db.get_settings(session).initial_backfill = 10
    posted(world, {"id": "Ugk1", "text": "A note"})

    sync_service.run_sync()

    assert world["client"].inserted == []
    with db.session_scope() as session:
        placement = session.scalar(select(Placement))
        assert placement.playlist_item_id.startswith("generic-")
        assert not placement.is_offline
        assert placement.is_local


def test_a_post_costs_no_quota(world, db):
    from pamphlets.services import quota

    with db.session_scope() as session:
        db.get_settings(session).initial_backfill = 10
        # Nothing left for the channel-detail lookup to fetch, so anything
        # charged in this run would have to be the post.
        channel = session.scalar(select(Channel))
        channel.thumbnail_url = "https://i.test/avatar.jpg"
        channel.description = "About the channel"
        before = quota.state(session).used
    posted(world, {"id": "Ugk1", "text": "A note"})

    sync_service.run_sync()

    with db.session_scope() as session:
        assert quota.state(session).used == before


def test_denying_posts_stops_them_being_collected(world, db):
    with db.session_scope() as session:
        db.get_settings(session).initial_backfill = 10
        channel = session.scalar(select(Channel))
        channel_service.set_take(session, channel, "posts", include=False)
    posted(world, {"id": "Ugk1", "text": "A note"})

    sync_service.run_sync()

    with db.session_scope() as session:
        assert session.scalar(select(Video).where(Video.kind == "post")) is None


def test_allowing_posts_again_brings_back_what_was_skipped(world, db):
    with db.session_scope() as session:
        db.get_settings(session).initial_backfill = 10
    posted(world, {"id": "Ugk1", "text": "A note"})
    sync_service.run_sync()

    with db.session_scope() as session:
        channel = session.scalar(select(Channel))
        channel_service.set_take(session, channel, "posts", include=False)
        # The post is already here; deny it and it is filtered out on sight.
        post = session.scalar(select(Video).where(Video.kind == "post"))
        post.status = "skipped"
        post.reason = "Posts"
        for placement in list(post.placements):
            session.delete(placement)

    with db.session_scope() as session:
        channel = session.scalar(select(Channel))
        brought_back = channel_service.set_take(session, channel, "posts", include=True)
        assert brought_back == 1
        assert session.scalar(select(Video).where(Video.kind == "post")).status == "pending"


def test_a_channel_that_cannot_be_scraped_still_gets_its_videos(world, db, monkeypatch):
    """The Posts tab is a page, not an API. Losing it must cost nothing else."""
    from pamphlets.plugins import registry

    def boom(self, kind, key):
        raise RuntimeError("YouTube changed the page again")

    monkeypatch.setattr(registry.Registry, "posts", boom)
    with db.session_scope() as session:
        db.get_settings(session).initial_backfill = 10
    world["entries"] = [entry("v0", 1)]
    world["client"].details = {"v0": VideoDetails("v0", "Video v0", 600, "none", "public")}

    result = sync_service.run_sync()

    assert result.added == 1
    assert world["client"].contents() == ["v0"]


def test_the_backfill_window_applies_to_posts_too(world, db):
    """Tracking a channel should not drop a year of its writing into a feed."""
    with db.session_scope() as session:
        db.get_settings(session).initial_backfill = 1
    posted(world,
           {"id": "Ugk1", "text": "Newest"},
           {"id": "Ugk2", "text": "Older", "hours": 40},
           {"id": "Ugk3", "text": "Oldest", "hours": 90})

    sync_service.run_sync()

    with db.session_scope() as session:
        kept = session.scalars(
            select(Video).where(Video.kind == "post", Video.status == "added")
        ).all()
        ignored = session.scalars(
            select(Video).where(Video.kind == "post", Video.status == "ignored")
        ).all()
        assert [v.title for v in kept] == ["Newest"]
        assert len(ignored) == 2


def test_watching_a_post_clears_it_without_touching_youtube(world, db):
    from pamphlets.services import watched as watched_service

    with db.session_scope() as session:
        db.get_settings(session).initial_backfill = 10
    posted(world, {"id": "Ugk1", "text": "A note"})
    sync_service.run_sync()

    with db.session_scope() as session:
        post = session.scalar(select(Video).where(Video.kind == "post"))
        watched_service.mark_watched(session, [post.id])

    result = watched_service.remove_watched()

    assert result.removed == 1
    assert world["client"].deleted == []
