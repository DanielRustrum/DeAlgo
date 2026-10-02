"""End-to-end sync behaviour against a fake YouTube."""

from __future__ import annotations

from fakes import CHANNEL_ID, MAIN_PLAYLIST, entry, wire
from sqlalchemy import select

from dealgo import outgoing
from dealgo.models import Channel, Video
from dealgo.plugins.publisher import VideoDetails
from dealgo.services import sync as sync_service
from dealgo.sources import items


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

    from dealgo.sources import syndication

    def boom(_url, _http):
        raise httpx.ConnectError("dns is having a day")

    monkeypatch.setattr(syndication, "fetch", boom)
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
    from dealgo.plugins.publisher import ChannelInfo

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
# case that matters most is the one with no trigger at all: nothing polls it,
# because a trigger is how a run starts.


def wire_trigger(db, *, kind: str, every_minutes: int | None = None, cron: str | None = None):
    """Put a trigger box on the canvas and wire it into the only channel.

    Whatever was wired before comes off first: these tests are about what one
    trigger does, and a second one saying yes underneath would answer for it.
    """
    from dealgo.services import graph

    with db.session_scope() as session:
        graph.load(session)
        for existing in [n for n in graph.nodes(session) if n.kind == "trigger"]:
            session.delete(existing)
        session.flush()
        source = next(n for n in graph.nodes(session) if n.kind == "source")
        trigger = graph.add_trigger(
            session, trigger_kind=kind, every_minutes=every_minutes, cron=cron
        )
        graph.connect(session, trigger, source)
        return trigger.id


def last_checked(db, when):
    with db.session_scope() as session:
        session.scalars(select(Channel)).one().last_checked_at = when


def test_a_channel_with_no_trigger_is_not_polled_at_all(world, db):
    """A trigger is how a run starts. A source fetched on a schedule drawn
    nowhere is a source filling feeds for reasons the canvas cannot explain,
    which is exactly how a channel nobody wired ends up in somebody's feed."""
    from dealgo.models import GraphNode

    with db.session_scope() as session:
        for node in session.scalars(select(GraphNode).where(GraphNode.kind == "trigger")):
            session.delete(node)

    world["entries"] = [entry("v0", minutes_ago=5)]
    world["client"].details = {"v0": VideoDetails("v0", "Video v0", 600, "none", "public")}

    result = sync_service.run_sync()

    assert result.discovered == 0
    assert result.channels_checked == 0
    assert result.channels_waiting == 1


def test_an_unwired_channel_is_still_polled_when_a_person_forces_it(world, db):
    """Force means force: the CLI's `--force` is somebody saying "poll
    everything now", and it is the way to reach a source not yet wired."""
    from dealgo.models import GraphNode

    with db.session_scope() as session:
        for node in session.scalars(select(GraphNode).where(GraphNode.kind == "trigger")):
            session.delete(node)

    world["entries"] = [entry("v0", minutes_ago=5)]
    world["client"].details = {"v0": VideoDetails("v0", "Video v0", 600, "none", "public")}

    assert sync_service.run_sync(force=True).discovered == 1


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
        order = graph.add_sort(session)
        # What to order by is a piece under the box, not a field on it.
        graph.add_piece(
            session, kind="order", host=order,
            sort_by=sort_by, newest_first=newest_first,
        )
        graph.connect(session, source, order)
        graph.connect(session, order, feed)
        # The straight wire would skip the sort, so it comes out.
        for edge in graph.edges(session):
            if edge.source_pk == source.id and edge.target_pk == feed.id:
                graph.disconnect(session, edge.id)


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


# -- being asked to wait ---------------------------------------------------


def test_three_quick_presses_make_one_request_not_three(world, db, monkeypatch):
    """What actually happened: three Backfill presses 28 seconds apart, and
    Reddit allows an unauthenticated reader one request a window. The first
    succeeded and the other two were refused, which is what deepens a block.
    Now the other two never reach the network."""
    import httpx

    from dealgo.models import Channel as ChannelModel
    from dealgo.sources import patience, syndication

    patience.forget()
    asked = []

    def serve(url, headers=None):
        asked.append(url)
        return httpx.Response(
            200,
            headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "36"},
            request=httpx.Request("GET", url),
            text=REDDIT,
        )

    # The real reader, over a client that serves from memory: the point of
    # this test is what the reader does with the headers, so it must not be
    # the stub the world fixture puts in its place.
    monkeypatch.setattr(syndication, "fetch", world["real_fetch"])
    with db.session_scope() as session:
        source = ChannelModel(
            channel_id="r/python", title="r/python", source_kind="reddit",
            source_url="https://www.reddit.com/r/python/.rss", enabled=True,
        )
        session.add(source)
        session.flush()
        only = {source.id}

    monkeypatch.setattr(outgoing, "client", lambda: _Client(serve))

    try:
        for _ in range(3):
            result = sync_service.run_sync("backfill", force=True, reach_back=0, only=only)
    finally:
        patience.forget()

    assert len(asked) == 1, f"asked {len(asked)} times for a budget of one"
    # And the run says why it did nothing, rather than going quiet.
    assert any("waiting" in message for message in result.messages), result.messages

    with db.session_scope() as session:
        source = session.scalar(select(ChannelModel).where(ChannelModel.channel_id == "r/python"))
    assert "limits how often" in (source.last_error or "")


class _Client:
    """The smallest thing `syndication.fetch` will accept."""

    def __init__(self, serve):
        self._serve = serve

    def get(self, url, headers=None, params=None):
        return self._serve(url, headers)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


# -- a second chance at what an entry carries ------------------------------

REDDIT_WITH_A_PICTURE = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>r/python</title>
  <item>
    <title>Something worth reading</title>
    <link>https://reddit.com/r/python/comments/abc</link>
    <guid>t3_abc</guid>
    <pubDate>Tue, 05 May 2026 09:00:00 +0000</pubDate>
    <description>&lt;img src="https://preview.redd.it/p.png?width=640&amp;amp;s=sig"&gt;A body</description>
  </item>
</channel></rss>
"""


def test_an_item_already_here_gains_the_picture_we_can_now_read(world, db, monkeypatch):
    """The whole backlog was stored before there was anywhere to put a
    picture, and a feed says the same things about the same items every poll.
    An entry we have seen before is a second chance at it."""
    from dealgo.models import Video as VideoModel

    add_rss_source(db, monkeypatch, REDDIT)         # first, with no picture in it
    sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        stored = session.scalar(select(VideoModel).where(VideoModel.kind == "link"))
        assert stored.thumbnail_url is None and stored.images is None

    # The same entry, read again by a version that knows how to see pictures.
    from dealgo.sources import syndication

    monkeypatch.setattr(
        syndication, "fetch", lambda _url, _http: syndication.parse(REDDIT_WITH_A_PICTURE)
    )
    sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        again = session.scalar(select(VideoModel).where(VideoModel.kind == "link"))
    assert again.thumbnail_url is not None
    assert "width=640" in again.thumbnail_url
    assert again.image_list == [again.thumbnail_url]


def test_a_stale_reading_is_corrected_by_a_fresh_one(world, db, monkeypatch):
    """Nothing in the app lets a person write these fields, so what is on the
    row came from an earlier reading of this same entry — and an earlier
    reading is exactly what wants correcting. Under a fill-only rule a body
    stored before the words were unescaped keeps its "&#32;" for ever."""
    from dealgo.models import Video as VideoModel
    from dealgo.sources import syndication

    add_rss_source(db, monkeypatch, REDDIT)
    sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        stored = session.scalar(select(VideoModel).where(VideoModel.kind == "link"))
        stored.body = "A body &#32; read by an older version"

    monkeypatch.setattr(syndication, "fetch", lambda _url, _http: syndication.parse(REDDIT))
    sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        again = session.scalar(select(VideoModel).where(VideoModel.kind == "link"))
    assert again.body == "A body"


def test_a_reading_that_comes_back_empty_takes_nothing_away(world, db, monkeypatch):
    """A parse that finds nothing is a reason to keep what we have, not to
    throw it away."""
    from dealgo.models import Video as VideoModel
    from dealgo.sources import syndication

    add_rss_source(db, monkeypatch, REDDIT_WITH_A_PICTURE)
    sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        stored = session.scalar(select(VideoModel).where(VideoModel.kind == "link"))
        assert stored.thumbnail_url is not None
        had = stored.thumbnail_url

    # The same entry, with everything but its identity gone.
    bare = REDDIT_WITH_A_PICTURE.replace(
        '<description>&lt;img src="https://preview.redd.it/p.png?width=640&amp;amp;s=sig"&gt;A body</description>',
        "<description></description>",
    )
    monkeypatch.setattr(syndication, "fetch", lambda _url, _http: syndication.parse(bare))
    sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        again = session.scalar(select(VideoModel).where(VideoModel.kind == "link"))
    assert again.thumbnail_url == had


def test_a_second_reading_does_not_discover_it_twice(world, db, monkeypatch):
    """Filling a gap is not finding something new, and must not be counted
    as one."""
    from dealgo.models import Video as VideoModel
    from dealgo.sources import syndication

    add_rss_source(db, monkeypatch, REDDIT)
    sync_service.run_sync("manual", force=True)

    monkeypatch.setattr(
        syndication, "fetch", lambda _url, _http: syndication.parse(REDDIT_WITH_A_PICTURE)
    )
    result = sync_service.run_sync("manual", force=True)

    assert result.discovered == 0
    with db.session_scope() as session:
        items = session.scalars(select(VideoModel).where(VideoModel.kind == "link")).all()
    assert len(items) == 1


# -- reading pictures back out of what was already stored ------------------


def stored_link(db, *, body, thumbnail=None, images=None):
    from dealgo.models import Channel as ChannelModel
    from dealgo.models import Video as VideoModel

    with db.session_scope() as session:
        source = ChannelModel(
            channel_id="r/python", title="r/python", source_kind="reddit",
            source_url="https://www.reddit.com/r/python/.rss", enabled=True,
        )
        session.add(source)
        session.flush()
        item = VideoModel(
            video_id="item-old", channel_pk=source.id, kind="link", title="ltspice help",
            body=body, thumbnail_url=thumbnail, images=images, status="added",
        )
        session.add(item)
        session.flush()
        return item.id


def test_a_picture_is_read_back_out_of_the_words_it_was_left_in(world, db):
    """It cannot be fixed by polling again: a feed lists its most recent
    couple of dozen items and no more, and most of what is in hand fell off
    the end of it long ago. But nothing needs fetching — the address is in
    the text."""
    from dealgo.models import Video as VideoModel

    item_pk = stored_link(
        db,
        body=(
            "https://preview.redd.it/e8.png?width=2226&amp;s=big "
            "ltspice diagram &#32; submitted by &#32; /u/someone"
        ),
        thumbnail="https://preview.redd.it/e8.png?width=140&s=small",
    )

    assert sync_service.repair_stored_pictures_now() == 1

    with db.session_scope() as session:
        item = session.get(VideoModel, item_pk)
    # The bigger one wins, and the address comes out of the words.
    assert item.thumbnail_url == "https://preview.redd.it/e8.png?width=2226&s=big"
    assert item.image_list == ["https://preview.redd.it/e8.png?width=2226&s=big"]
    assert item.body == "ltspice diagram submitted by /u/someone"


def test_an_item_with_no_picture_is_still_tidied_and_marked_looked_at(world, db):
    from dealgo.models import Video as VideoModel

    item_pk = stored_link(db, body="just words &#32; submitted by &#32; /u/someone")

    sync_service.repair_stored_pictures_now()

    with db.session_scope() as session:
        item = session.get(VideoModel, item_pk)
    assert item.image_list == []
    assert item.images == "[]", "a row looked at once must not be looked at again"
    assert item.body == "just words submitted by /u/someone"


def test_the_repair_never_throws_away_a_picture_a_reading_found(world, db):
    """This one looks only at the words, and a feed names pictures the words
    do not."""
    from dealgo.models import Video as VideoModel

    item_pk = stored_link(
        db,
        body="just words &#32; here",
        thumbnail="https://preview.redd.it/named.png?width=640&s=x",
        images='["https://preview.redd.it/named.png?width=640&s=x"]',
    )

    sync_service.repair_stored_pictures_now()

    with db.session_scope() as session:
        item = session.get(VideoModel, item_pk)
    assert item.image_list == ["https://preview.redd.it/named.png?width=640&s=x"]
    assert item.thumbnail_url == "https://preview.redd.it/named.png?width=640&s=x"
    assert item.body == "just words here"


def test_the_repair_converges(world, db):
    """It selects exactly what it removes, so a second pass finds nothing."""
    stored_link(
        db,
        body="https://preview.redd.it/e8.png?width=2226&amp;s=big words &#32; here",
    )

    assert sync_service.repair_stored_pictures_now() == 1
    assert sync_service.repair_stored_pictures_now() == 0


def test_a_youtube_video_is_left_entirely_alone(world, db):
    """Its thumbnail comes from the feed's own field and its body is a
    community post's writing. Neither is this repair's business."""
    from dealgo.models import Channel as ChannelModel
    from dealgo.models import Video as VideoModel

    with db.session_scope() as session:
        channel = session.scalars(select(ChannelModel)).first()
        session.add(VideoModel(
            video_id="v9", channel_pk=channel.id, kind="post",
            title="A post", body="words &#32; kept exactly as they were",
        ))

    sync_service.repair_stored_pictures_now()

    with db.session_scope() as session:
        post = session.scalar(select(VideoModel).where(VideoModel.video_id == "v9"))
    assert post.body == "words &#32; kept exactly as they were"
    assert post.images is None


# -- a verdict about the route, revisited ----------------------------------


def stranded_reddit(db, *, playlist_id="generic:reading"):
    """A Reddit source whose items were refused for having nowhere to go, and
    a feed on the end of its wire."""
    from dealgo.models import Channel as ChannelModel
    from dealgo.models import Playlist as PlaylistModel
    from dealgo.models import Video as VideoModel

    with db.session_scope() as session:
        source = ChannelModel(
            channel_id="r/python", title="r/python", source_kind="reddit",
            source_url="https://www.reddit.com/r/python/.rss", enabled=True,
        )
        feed = PlaylistModel(playlist_id=playlist_id, title="Reading", enabled=True)
        session.add_all([source, feed])
        session.flush()
        wire(session, source, feed)
        for index in range(3):
            session.add(VideoModel(
                video_id=f"item-{index}", channel_pk=source.id, kind="link",
                title=f"A thread {index}", link=f"https://reddit.com/{index}",
                status="skipped", reason=sync_service.WRONG_KIND_OF_FEED,
            ))
        return source.id, feed.id


def test_a_feed_turned_generic_brings_back_what_it_could_not_hold(world, db, monkeypatch):
    """The wire was never redrawn — the feed on the end of it changed
    underneath. Connecting brings these back; nothing else did, so they sat
    there skipped for ever."""
    from dealgo.models import Video as VideoModel

    stranded_reddit(db)
    monkeypatch.setattr(sync_service, "_poll", lambda *a: items.Batch("r/python", "r/python", []))

    result = sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        back = session.scalars(select(VideoModel).where(VideoModel.kind == "link")).all()
    assert [v.status for v in back] == ["added"] * 3
    assert any("nowhere to go before" in m for m in result.messages), result.messages


def test_items_stay_put_while_the_only_feed_is_still_a_youtube_one(world, db, monkeypatch):
    """Reviving them into the same refusal every run would be churn that
    reads as a feed doing something."""
    from dealgo.models import Video as VideoModel

    stranded_reddit(db, playlist_id="PLarealyoutubeplaylist")
    monkeypatch.setattr(sync_service, "_poll", lambda *a: items.Batch("r/python", "r/python", []))

    result = sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        held = session.scalars(select(VideoModel).where(VideoModel.kind == "link")).all()
    assert [v.status for v in held] == ["skipped"] * 3
    assert all(v.reason == sync_service.WRONG_KIND_OF_FEED for v in held)
    assert not any("nowhere to go before" in m for m in result.messages)


def test_a_filters_verdict_is_not_reconsidered(world, db, monkeypatch):
    """Only the routing one. What a filter decided was about the item itself,
    and a rewiring is no argument against it."""
    from dealgo.models import Video as VideoModel

    source_pk, _ = stranded_reddit(db)
    with db.session_scope() as session:
        session.add(VideoModel(
            video_id="item-filtered", channel_pk=source_pk, kind="link",
            title="Held by a rule", status="skipped", reason="title did not match",
        ))
    monkeypatch.setattr(sync_service, "_poll", lambda *a: items.Batch("r/python", "r/python", []))

    sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        held = session.scalar(select(VideoModel).where(VideoModel.video_id == "item-filtered"))
    assert held.status == "skipped"
    assert held.reason == "title did not match"


# -- somewhere else to read the same feed ----------------------------------


def with_mirror(db, *, mirror="https://openrss.org/reddit.com/r/python"):
    from dealgo.models import Channel as ChannelModel

    with db.session_scope() as session:
        source = ChannelModel(
            channel_id="r/python", title="r/python", source_kind="reddit",
            source_url="https://www.reddit.com/r/python/.rss",
            mirror_url=mirror, enabled=True,
        )
        session.add(source)
        session.flush()
        return source.id


def serving(world, monkeypatch, answers):
    """A client that answers each URL however the map says.

    These tests are about *which address* is asked for, so the real reader
    has to run — the world fixture stubs it out, and that stub would answer
    without asking anybody anything. Only that one patch is lifted: undoing
    them all would take the test database with it.
    """
    import httpx

    from dealgo.sources import syndication

    monkeypatch.setattr(syndication, "fetch", world["real_fetch"])
    asked = []

    def serve(url, headers=None, params=None):
        asked.append(url)
        status, body = answers.get(url, (404, ""))
        return httpx.Response(status, request=httpx.Request("GET", url), text=body)

    return asked, _Client(serve)


def test_a_mirror_is_read_when_the_source_refuses(world, db, monkeypatch):
    """One request a window is workable until it is not. A mirror is how you
    get a second answer without pretending to be somebody else."""
    from dealgo.models import Video as VideoModel
    from dealgo.sources import patience

    patience.forget()
    only = {with_mirror(db)}
    asked, client = serving(world, monkeypatch, {
        "https://www.reddit.com/r/python/.rss": (403, ""),
        "https://openrss.org/reddit.com/r/python": (200, REDDIT),
    })
    monkeypatch.setattr(outgoing, "client", lambda: client)

    try:
        sync_service.run_sync("manual", force=True, only=only)
    finally:
        patience.forget()

    assert asked == [
        "https://www.reddit.com/r/python/.rss",       # the source first, always
        "https://openrss.org/reddit.com/r/python",    # and only then the mirror
    ]
    with db.session_scope() as session:
        item = session.scalar(select(VideoModel).where(VideoModel.kind == "link"))
    assert item is not None and item.title == "Something worth reading"


def test_the_source_is_always_tried_first(world, db, monkeypatch):
    """The mirror is somebody else's copy and a service we do not run. It is
    a fallback, not a shortcut."""
    from dealgo.sources import patience

    patience.forget()
    only = {with_mirror(db)}
    asked, client = serving(world, monkeypatch, {
        "https://www.reddit.com/r/python/.rss": (200, REDDIT),
        "https://openrss.org/reddit.com/r/python": (200, REDDIT),
    })
    monkeypatch.setattr(outgoing, "client", lambda: client)

    try:
        sync_service.run_sync("manual", force=True, only=only)
    finally:
        patience.forget()

    assert asked == ["https://www.reddit.com/r/python/.rss"]


def test_a_feed_that_is_gone_does_not_fall_through_to_the_mirror(world, db, monkeypatch):
    """A mirror routes around a host that will not have us. It cannot help
    with a feed that has genuinely gone, and trying it on a 404 would hide a
    source that needs fixing."""
    from dealgo.models import Channel as ChannelModel
    from dealgo.sources import patience

    patience.forget()
    only = {with_mirror(db)}
    asked, client = serving(world, monkeypatch, {
        "https://www.reddit.com/r/python/.rss": (404, ""),
        "https://openrss.org/reddit.com/r/python": (200, REDDIT),
    })
    monkeypatch.setattr(outgoing, "client", lambda: client)

    try:
        sync_service.run_sync("manual", force=True, only=only)
    finally:
        patience.forget()

    assert asked == ["https://www.reddit.com/r/python/.rss"]
    with db.session_scope() as session:
        source = session.scalar(select(ChannelModel).where(ChannelModel.channel_id == "r/python"))
    assert "no feed there any more" in (source.last_error or "")


def test_a_mirror_that_also_fails_reports_the_original_refusal(world, db, monkeypatch):
    """The source's answer is the one worth knowing. A second complaint about
    somebody else's copy helps nobody."""
    from dealgo.models import Channel as ChannelModel
    from dealgo.sources import patience

    patience.forget()
    only = {with_mirror(db)}
    asked, client = serving(world, monkeypatch, {
        "https://www.reddit.com/r/python/.rss": (429, ""),
        "https://openrss.org/reddit.com/r/python": (503, ""),  # as it happens, today
    })
    monkeypatch.setattr(outgoing, "client", lambda: client)

    try:
        sync_service.run_sync("manual", force=True, only=only)
    finally:
        patience.forget()

    assert len(asked) == 2
    with db.session_scope() as session:
        source = session.scalar(select(ChannelModel).where(ChannelModel.channel_id == "r/python"))
    assert "asked too often" in (source.last_error or ""), source.last_error


def test_a_source_with_no_mirror_just_reports_the_refusal(world, db, monkeypatch):
    from dealgo.models import Channel as ChannelModel
    from dealgo.sources import patience

    patience.forget()
    only = {with_mirror(db, mirror=None)}
    asked, client = serving(world, monkeypatch, {"https://www.reddit.com/r/python/.rss": (403, "")})
    monkeypatch.setattr(outgoing, "client", lambda: client)

    try:
        sync_service.run_sync("manual", force=True, only=only)
    finally:
        patience.forget()

    assert asked == ["https://www.reddit.com/r/python/.rss"]
    with db.session_scope() as session:
        source = session.scalar(select(ChannelModel).where(ChannelModel.channel_id == "r/python"))
    assert "refused us" in (source.last_error or "")


# -- reaching back ---------------------------------------------------------


def test_reaching_back_revives_what_was_too_old(world, db):
    """The first check sets aside anything outside the backfill window. Asking
    for a backfill is asking for exactly those."""
    from dealgo.models import Channel as ChannelModel
    from dealgo.models import Video as VideoModel

    with db.session_scope() as session:
        channel = session.scalars(select(ChannelModel)).first()
        for index in range(3):
            session.add(VideoModel(
                video_id=f"old{index}", channel_pk=channel.id, title=f"Old {index}",
                status="ignored", reason=sync_service.TOO_OLD,
            ))

    sync_service.run_sync("backfill", force=True, reach_back=0)

    with db.session_scope() as session:
        revived = session.scalars(
            select(VideoModel).where(VideoModel.video_id.like("old%"))
        ).all()
    assert all(v.status != "ignored" for v in revived)
    assert all(v.reason != sync_service.TOO_OLD for v in revived)


def test_reaching_back_leaves_a_filters_judgement_alone(world, db):
    """"Before your time" is the one judgement being revisited. Something a
    filter turned away was a decision about the thing itself, and reaching
    further back is no argument against it."""
    from dealgo.models import Channel as ChannelModel
    from dealgo.models import Video as VideoModel

    with db.session_scope() as session:
        channel = session.scalars(select(ChannelModel)).first()
        session.add(VideoModel(
            video_id="short1", channel_pk=channel.id, title="A short",
            status="skipped", reason="Shorts are switched off",
        ))

    sync_service.run_sync("backfill", force=True, reach_back=0)

    with db.session_scope() as session:
        held = session.scalar(select(VideoModel).where(VideoModel.video_id == "short1"))
    assert held.status == "skipped"
    assert held.reason == "Shorts are switched off"


def test_an_ordinary_run_leaves_what_was_too_old_where_it_is(world, db):
    from dealgo.models import Channel as ChannelModel
    from dealgo.models import Video as VideoModel

    with db.session_scope() as session:
        channel = session.scalars(select(ChannelModel)).first()
        session.add(VideoModel(
            video_id="old0", channel_pk=channel.id, title="Old",
            status="ignored", reason=sync_service.TOO_OLD,
        ))

    sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        left = session.scalar(select(VideoModel).where(VideoModel.video_id == "old0"))
    assert left.status == "ignored"


def test_reaching_back_takes_only_as_many_as_were_asked_for(world, db):
    """"The latest 2" means the latest 2, on the backlog as well as the feed."""
    import datetime as dt

    from dealgo.models import Channel as ChannelModel
    from dealgo.models import Video as VideoModel
    from dealgo.models import utcnow

    with db.session_scope() as session:
        channel = session.scalars(select(ChannelModel)).first()
        for index in range(5):
            session.add(VideoModel(
                video_id=f"old{index}", channel_pk=channel.id, title=f"Old {index}",
                published_at=utcnow() - dt.timedelta(days=index),
                status="ignored", reason=sync_service.TOO_OLD,
            ))

    sync_service.run_sync("backfill", force=True, reach_back=2)

    with db.session_scope() as session:
        revived = [
            v.video_id
            for v in session.scalars(select(VideoModel).where(VideoModel.video_id.like("old%")))
            if v.status != "ignored"
        ]
    # The two newest, which are the two with the smallest day offsets.
    assert sorted(revived) == ["old0", "old1"]


def test_reaching_back_takes_the_whole_feed_on_a_first_check(world, db, monkeypatch):
    """A source added with a tight backfill window would file most of its feed
    as too old. Reaching back the first time takes all of it instead."""
    from dealgo.models import Channel as ChannelModel
    from dealgo.models import Video as VideoModel

    add_rss_source(db, monkeypatch, REDDIT)
    with db.session_scope() as session:
        source = session.scalar(select(ChannelModel).where(ChannelModel.channel_id == "r/python"))
        source.backfill_days = 0  # nothing but brand new items

    sync_service.run_sync("backfill", force=True, reach_back=0)

    with db.session_scope() as session:
        item = session.scalar(select(VideoModel).where(VideoModel.kind == "link"))
    assert item is not None
    assert item.status != "ignored", "the whole feed was asked for, and it is what the feed lists"


# -- sources that are not YouTube ------------------------------------------


def add_rss_source(db, monkeypatch, feed_xml, *, url="https://example.com/feed"):
    """A subscribed RSS source, with its feed served from memory."""
    from dealgo.models import Channel as ChannelModel
    from dealgo.sources import syndication

    monkeypatch.setattr(syndication, "fetch", lambda _url, _http: syndication.parse(feed_xml))
    with db.session_scope() as session:
        channel = ChannelModel(
            channel_id="r/python",
            title="r/python",
            source_kind="reddit",
            source_url=url,
            enabled=True,
        )
        session.add(channel)
        session.flush()
        return channel.id


REDDIT = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>r/python</title>
  <item>
    <title>Something worth reading</title>
    <link>https://reddit.com/r/python/comments/abc</link>
    <guid>t3_abc</guid>
    <pubDate>Tue, 05 May 2026 09:00:00 +0000</pubDate>
    <description>A body</description>
  </item>
</channel></rss>
"""


def test_a_feed_source_is_polled_like_any_other(world, db, monkeypatch):
    from dealgo.models import Video as VideoModel

    add_rss_source(db, monkeypatch, REDDIT)
    result = sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        item = session.scalar(select(VideoModel).where(VideoModel.kind == "link"))
        assert item is not None
        assert item.title == "Something worth reading"
        assert item.link == "https://reddit.com/r/python/comments/abc"
        assert item.body == "A body"
        # Addressed by the feed's own id, under a prefix that cannot collide
        # with a video id.
        assert item.video_id.startswith("item-")
        assert item.url == "https://reddit.com/r/python/comments/abc"


def test_an_item_from_elsewhere_cannot_go_into_a_youtube_playlist(world, db, monkeypatch):
    """The one thing that does not generalise, said once rather than failing
    at the insert with whatever YouTube makes of it."""
    from dealgo.models import Video as VideoModel

    channel_pk = add_rss_source(db, monkeypatch, REDDIT)
    with db.session_scope() as session:
        from dealgo.models import Channel as ChannelModel
        from dealgo.models import Playlist as PlaylistModel

        channel = session.get(ChannelModel, channel_pk)
        # The fixture's feed is a real YouTube playlist.
        wire(session, channel, session.scalars(select(PlaylistModel)).one())

    sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        item = session.scalar(select(VideoModel).where(VideoModel.kind == "link"))
        assert item.status == "skipped"
        assert "YouTube playlist" in (item.reason or "")
    # And nothing was sent to YouTube about it.
    assert world["client"].inserted_into() == []


def test_an_item_from_elsewhere_fills_a_generic_feed(world, db, monkeypatch):
    from dealgo.models import Video as VideoModel
    from dealgo.services import playlists as playlist_service

    channel_pk = add_rss_source(db, monkeypatch, REDDIT)
    with db.session_scope() as session:
        from dealgo.models import Channel as ChannelModel

        local = playlist_service.create_generic(session, "Reading")
        channel = session.get(ChannelModel, channel_pk)
        wire(session, channel, local)

    sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        item = session.scalar(select(VideoModel).where(VideoModel.kind == "link"))
        assert item.status == "added"


def test_a_feed_items_words_are_what_a_filter_reads(world, db, monkeypatch):
    """It has no duration and is neither a Short nor a broadcast, so its title
    and its body are all there is to go on."""
    from dealgo.models import Channel as ChannelModel
    from dealgo.models import Video as VideoModel
    from dealgo.services import playlists as playlist_service

    channel_pk = add_rss_source(db, monkeypatch, REDDIT)
    with db.session_scope() as session:
        channel = session.get(ChannelModel, channel_pk)
        channel.title_exclude = "worth reading"
        wire(session, channel, playlist_service.create_generic(session, "Reading"))

    sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        item = session.scalar(select(VideoModel).where(VideoModel.kind == "link"))
        assert item.status == "skipped"
