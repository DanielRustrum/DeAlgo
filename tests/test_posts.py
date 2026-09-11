"""Community posts: written content, alongside the videos.

There is no API for these, so the parser is fed saved page shapes rather than
a live channel — the tests must never reach YouTube.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from sqlalchemy import select

from dealgo.models import Channel, Placement, Playlist, Video
from dealgo.services import channels as channel_service
from dealgo.services import sync as sync_service
from dealgo.youtube import community
from dealgo.youtube.api import VideoDetails
from fakes import entry


def page(posts: list[dict]) -> str:
    """A Posts tab, shaped the way YouTube ships one."""
    threads = [
        {
            "backstagePostThreadRenderer": {
                "post": {
                    "backstagePostRenderer": {
                        "postId": post["id"],
                        "contentText": {"runs": [{"text": post.get("text", "")}]},
                        "publishedTimeText": {"runs": [{"text": post.get("age", "2 days ago")}]},
                        **(
                            {
                                "backstageAttachment": {
                                    "postMultiImageRenderer": {
                                        "images": [
                                            {
                                                "backstageImageRenderer": {
                                                    "image": {
                                                        "thumbnails": [
                                                            {"url": url + "?s=100", "width": 100},
                                                            {"url": url, "width": 800},
                                                        ]
                                                    }
                                                }
                                            }
                                            for url in post["images"]
                                        ]
                                    }
                                }
                            }
                            if post.get("images")
                            else {}
                        ),
                    }
                }
            }
        }
        for post in posts
    ]
    data = {"contents": {"twoColumnBrowseResultsRenderer": {"tabs": threads}}}
    return "<html><script>var ytInitialData = " + json.dumps(data) + ";</script></html>"


# -- the parser ------------------------------------------------------------


def test_it_reads_the_text_images_and_age_of_a_post():
    now = dt.datetime(2026, 9, 9, 12, 0, tzinfo=dt.timezone.utc)
    posts = community.parse_posts(
        page([{"id": "Ugk1", "text": "Back on Friday", "age": "3 days ago",
               "images": ["https://img.test/a.jpg", "https://img.test/b.jpg"]}]),
        now=now,
    )

    assert len(posts) == 1
    post = posts[0]
    assert post.post_id == "Ugk1"
    assert post.text == "Back on Friday"
    # The largest thumbnail wins: a tile is displayed big.
    assert post.image_urls == ["https://img.test/a.jpg", "https://img.test/b.jpg"]
    assert post.published_at == now - dt.timedelta(days=3)


def test_a_post_with_no_date_it_understands_keeps_none():
    posts = community.parse_posts(page([{"id": "Ugk1", "text": "Hi", "age": "just now"}]))
    assert posts[0].published_at is None


def test_the_title_is_an_excerpt_of_the_first_line():
    long = "x" * 200
    posts = community.parse_posts(page([{"id": "Ugk1", "text": long}]))
    assert posts[0].title.endswith("…")
    assert len(posts[0].title) <= 80


def test_an_image_only_post_still_has_something_to_call_itself():
    posts = community.parse_posts(page([{"id": "Ugk1", "text": "", "images": ["https://i.test/x"]}]))
    assert posts[0].title == "(image post)"


@pytest.mark.parametrize("html", ["", "<html>nothing here</html>",
                                  "<script>var ytInitialData = {oops;</script>"])
def test_a_page_it_cannot_read_yields_nothing_rather_than_raising(html):
    """YouTube can change this shape whenever it likes. It must not take a
    sync down when it does."""
    assert community.parse_posts(html) == []


def test_the_same_post_is_only_read_once():
    """The blob repeats a renderer in more than one place."""
    once = page([{"id": "Ugk1", "text": "Hello"}])
    twice = once.replace('"contents"', '"header": {"x": ' + json.dumps(
        json.loads(once.split("var ytInitialData = ")[1].rsplit(";", 1)[0])["contents"]) + '}, "contents"')
    assert len(community.parse_posts(twice)) == 1


# -- discovery and placement ----------------------------------------------


def posted(world, *posts):
    world["posts"] = [
        community.Post(
            post_id=p["id"],
            text=p.get("text", ""),
            published_at=dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=p.get("hours", 1)),
            image_urls=p.get("images", []),
        )
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
    from dealgo.services import quota

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
        channel_service.set_posts(session, channel, include=False)
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
        channel_service.set_posts(session, channel, include=False)
        # The post is already here; deny it and it is filtered out on sight.
        post = session.scalar(select(Video).where(Video.kind == "post"))
        post.status = "skipped"
        post.reason = channel_service.POST_REASON
        for placement in list(post.placements):
            session.delete(placement)

    with db.session_scope() as session:
        channel = session.scalar(select(Channel))
        brought_back = channel_service.set_posts(session, channel, include=True)
        assert brought_back == 1
        assert session.scalar(select(Video).where(Video.kind == "post")).status == "pending"


def test_a_channel_that_cannot_be_scraped_still_gets_its_videos(world, db, monkeypatch):
    """The Posts tab is a page, not an API. Losing it must cost nothing else."""
    def boom(channel_id, http):
        raise RuntimeError("YouTube changed the page again")

    monkeypatch.setattr(community, "fetch_posts", boom)
    monkeypatch.setattr(sync_service.community, "fetch_posts", boom)
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
    from dealgo.services import watched as watched_service

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
