"""Boxes that mark what passes rather than narrowing it.

A Filter says no. These say something *about* an item and let it through:
what it is called, how long you get with it, how long it belongs in a feed.
What they leave on it is read later — by a Filter further down the path, by
Focus mode, by the sweep that clears out what has had its time.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from dealgo.models import Channel, Placement, Playlist, Video, utcnow
from dealgo.plugins.publisher import VideoDetails
from dealgo.services import graph
from dealgo.services import playlists as playlist_service
from dealgo.services import sync as sync_service
from fakes import entry, unwire


def wire(db, *boxes):
    """Wire a chain of boxes between the fixture's source and its feed."""
    from dealgo.models import GraphNode

    with db.session_scope() as session:
        db.get_settings(session).initial_backfill = 50
        channel = session.scalar(select(Channel))
        unwire(session, channel)
        source = session.scalar(select(GraphNode).where(GraphNode.kind == "source"))
        feed = session.scalar(select(GraphNode).where(GraphNode.kind == "feed"))

        made = [make(session) for make in boxes]
        last = source
        for box in made:
            graph.connect(session, last, box)
            last = box
        graph.connect(session, last, feed)
        return [box.id for box in made]


def uploads(world, how_many=2):
    world["entries"] = [entry(f"v{n}", minutes_ago=n) for n in range(how_many)]
    world["client"].details = {
        f"v{n}": VideoDetails(f"v{n}", f"Video v{n}", 600, "none", "public")
        for n in range(how_many)
    }


def box_of(session, channel) -> int:
    """The source box that stands for this channel on the canvas."""
    from dealgo.models import GraphNode

    return session.scalar(
        select(GraphNode.id).where(
            GraphNode.kind == "source", GraphNode.channel_pk == channel.id
        )
    )


def items(db) -> list[Video]:
    with db.session_scope() as session:
        return list(session.scalars(select(Video)))


# -- Tag -------------------------------------------------------------------


def test_a_tag_box_marks_everything_that_passes(world, db):
    wire(db, lambda s: graph.add_stamp(s, kind="tag", marks="Long Reads"))
    uploads(world, 2)

    sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        for video in session.scalars(select(Video)):
            # Filed lowercased and squeezed, the way a repository name is:
            # a Tag box and a Filter box that disagreed about capitals would
            # look joined up and not be.
            assert video.tag_list == ["long reads"]


def test_a_filter_further_down_can_ask_for_that_tag(world, db):
    """Which is the point of putting one on."""
    from dealgo.models import GraphNode

    ids = wire(
        db,
        lambda s: graph.add_stamp(s, kind="tag", marks="keep"),
        lambda s: graph.add_filter(s, label="Only tagged"),
    )
    with db.session_scope() as session:
        # What a Filter narrows by is a condition slotted under it.
        graph.add_piece(
            session, kind="carrying", host=session.get(GraphNode, ids[1])
        ).tagged = "keep"
    uploads(world, 2)

    result = sync_service.run_sync("manual", force=True)

    assert result.added == 2


def test_a_filter_asking_for_a_tag_nothing_carries_turns_it_away(world, db):
    from dealgo.models import GraphNode

    ids = wire(db, lambda s: graph.add_filter(s, label="Only tagged"))
    with db.session_scope() as session:
        graph.add_piece(
            session, kind="carrying", host=session.get(GraphNode, ids[0])
        ).tagged = "never-applied"
    uploads(world, 2)

    result = sync_service.run_sync("manual", force=True)

    assert result.added == 0
    with db.session_scope() as session:
        held = session.scalars(select(Video).where(Video.status == "skipped")).all()
        assert held and "not tagged" in (held[0].reason or "")


def test_a_tag_box_with_no_tag_marks_nothing(world, db):
    """It has been put on the canvas and not yet told anything."""
    wire(db, lambda s: graph.add_stamp(s, kind="tag"))
    uploads(world, 1)

    sync_service.run_sync("manual", force=True)

    assert items(db)[0].tag_list == []


# -- Decay -----------------------------------------------------------------


def decay(minutes=2, lock=False):
    def make(session):
        box = graph.add_stamp(session, kind="decay")
        graph.add_piece(session, kind="timer", host=box, duration_minutes=minutes)
        if lock:
            graph.add_piece(session, kind="lock", host=box)
        return box

    return make


def test_a_decay_box_says_how_long_you_get_with_each_item(world, db):
    wire(db, decay(minutes=2))
    uploads(world, 1)

    sync_service.run_sync("manual", force=True)

    # Minutes on the piece, seconds on the item: the page counts in seconds.
    assert items(db)[0].view_seconds == 120


def test_a_lock_under_it_makes_that_time_one_you_cannot_hold(world, db):
    wire(db, decay(minutes=1, lock=True))
    uploads(world, 1)

    sync_service.run_sync("manual", force=True)

    video = items(db)[0]
    assert video.view_seconds == 60
    assert video.view_locked is True


def test_without_a_lock_the_time_can_still_be_held(world, db):
    wire(db, decay(minutes=1))
    uploads(world, 1)

    sync_service.run_sync("manual", force=True)

    assert items(db)[0].view_locked is False


def test_a_decay_box_with_no_timer_says_nothing(world, db):
    """Put on the canvas and not yet told how long."""
    wire(db, lambda s: graph.add_stamp(s, kind="decay"))
    uploads(world, 1)

    sync_service.run_sync("manual", force=True)

    assert items(db)[0].view_seconds is None


def test_the_shorter_of_two_decays_wins(world, db):
    """A limit is a limit: two of them mean the tighter one."""
    wire(db, decay(minutes=5), decay(minutes=2))
    uploads(world, 1)

    sync_service.run_sync("manual", force=True)

    assert items(db)[0].view_seconds == 120


def test_what_a_decay_box_said_reaches_the_page(world, db):
    """Focus reads it off the queue it is handed, so that is where it has
    to be for the countdown to know about it at all."""
    from dealgo.web.routes.focus import _focus_item

    wire(db, decay(minutes=2, lock=True))
    uploads(world, 1)
    sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        video = session.scalar(select(Video))
        row = _focus_item(video, "News")

    assert row["seconds"] == 120
    assert row["locked"] is True


# -- Expire ----------------------------------------------------------------


def expires(minutes=1440):
    def make(session):
        box = graph.add_stamp(session, kind="expire")
        graph.add_piece(session, kind="timer", host=box, duration_minutes=minutes)
        return box

    return make


def placements(db) -> list[Placement]:
    with db.session_scope() as session:
        return list(session.scalars(select(Placement)))


def test_an_expire_box_puts_an_end_on_what_it_lets_through(world, db):
    wire(db, expires(minutes=1440))
    uploads(world, 1)

    sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        placement = session.scalar(select(Placement))
        assert placement.expires_at is not None
        # Counted from when it reached the feed, so a day is a day from now.
        away = (placement.expires_at - utcnow()).total_seconds()
        assert 23.5 * 3600 < away <= 24 * 3600


def test_what_has_had_its_time_is_taken_out_of_the_feed(world, db):
    wire(db, expires(minutes=60))
    uploads(world, 2)
    sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        for placement in session.scalars(select(Placement)):
            placement.expires_at = utcnow() - dt.timedelta(minutes=1)
    sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        gone = session.scalars(
            select(Placement).where(Placement.removed_at.is_not(None))
        ).all()
        assert len(gone) == 2
        assert "ran out" in (gone[0].removal_reason or "")


def test_expiring_removes_it_from_the_feed_and_not_from_history(world, db):
    """It is still in Raw, and still in any other feed whose path said
    nothing about expiry."""
    wire(db, expires(minutes=60))
    uploads(world, 1)
    sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        session.scalar(select(Placement)).expires_at = utcnow() - dt.timedelta(hours=1)
    sync_service.run_sync("manual", force=True)

    assert len(items(db)) == 1


def test_something_with_time_left_is_left_alone(world, db):
    wire(db, expires(minutes=1440))
    uploads(world, 1)
    sync_service.run_sync("manual", force=True)

    sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        assert session.scalar(select(Placement)).removed_at is None


def test_an_expire_box_with_no_timer_puts_no_end_on_anything(world, db):
    wire(db, lambda s: graph.add_stamp(s, kind="expire"))
    uploads(world, 1)

    sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        assert session.scalar(select(Placement)).expires_at is None


# -- all three on one path -------------------------------------------------


def test_the_boxes_stack_on_one_path(world, db):
    wire(
        db,
        lambda s: graph.add_stamp(s, kind="tag", marks="news"),
        decay(minutes=2, lock=True),
        expires(minutes=1440),
    )
    uploads(world, 1)

    sync_service.run_sync("manual", force=True)

    video = items(db)[0]
    assert video.tag_list == ["news"]
    assert (video.view_seconds, video.view_locked) == (120, True)
    with db.session_scope() as session:
        assert session.scalar(select(Placement)).expires_at is not None


# -- what they call themselves ---------------------------------------------


def test_each_box_is_named_after_what_it_is(db):
    """They all read "Filter" before this: the fallback at the end of the
    list caught every kind nobody had written a branch for."""
    from dealgo.models import GraphNode

    named = {
        kind: GraphNode(kind=kind).title
        for kind in ("tag", "decay", "expire", "timer", "reset", "alive", "lock")
    }

    assert named == {
        "tag": "Tag",
        "decay": "Decay",
        "expire": "Expire",
        "timer": "Timer",
        "reset": "Reset",
        "alive": "Alive",
        "lock": "Lock",
    }


def test_a_tag_box_is_named_after_the_tag_it_puts_on(db):
    """On a canvas with three of them, which one this is, is the useful
    half — the same reason a Deposit box carries its repository."""
    from dealgo.models import GraphNode

    assert GraphNode(kind="tag", marks="long reads").title == "Tag: long reads"


# -- an Expire box says something about the feed, not only about arrivals ---


def test_wiring_an_expire_box_reaches_what_is_already_in_the_feed(world, db):
    """Without this a box wired to a feed of eighty items changes nothing
    anybody can see until the eighty have been read."""
    from dealgo.models import GraphNode

    uploads(world, 2)
    sync_service.run_sync("manual", force=True)
    with db.session_scope() as session:
        assert all(one.expires_at is None for one in session.scalars(select(Placement)))

    # The box arrives afterwards, the way it does when somebody adds one.
    wire(db, expires(minutes=1440))
    sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        assert all(one.expires_at is not None for one in session.scalars(select(Placement)))


def test_something_that_has_already_overstayed_goes_on_that_run(world, db):
    """Counted from when it arrived, which is what the Timer says — so the
    rule is true of the feed the moment it is wired, not a week later."""
    import datetime as dt

    uploads(world, 2)
    sync_service.run_sync("manual", force=True)
    with db.session_scope() as session:
        for placement in session.scalars(select(Placement)):
            placement.added_at = utcnow() - dt.timedelta(days=15)

    wire(db, expires(minutes=7 * 1440))
    sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        gone = session.scalars(
            select(Placement).where(Placement.removed_at.is_not(None))
        ).all()
        assert len(gone) == 2
    # And they are still items, in the history and in any other feed.
    assert len(items(db)) == 2


def test_an_end_already_worked_out_is_not_worked_out_again(world, db):
    """A second run must not push the end further away each time."""
    wire(db, expires(minutes=1440))
    uploads(world, 1)
    sync_service.run_sync("manual", force=True)
    with db.session_scope() as session:
        first = session.scalar(select(Placement)).expires_at

    sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        assert session.scalar(select(Placement)).expires_at == first


def test_a_feed_with_no_expire_box_gets_no_ends(world, db):
    wire(db, lambda s: graph.add_filter(s, label="Just a filter"))
    uploads(world, 2)

    sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        assert all(one.expires_at is None for one in session.scalars(select(Placement)))


# -- the trial follows them too --------------------------------------------


def test_a_test_marks_the_boxes_that_mark_what_passes(world, db):
    """They turn nothing away, but an item still goes through them — and a
    box that reported nothing looked broken rather than uninvolved."""
    from dealgo.db import get_settings
    from dealgo.models import GraphNode

    ids = wire(
        db,
        lambda s: graph.add_stamp(s, kind="tag", marks="news"),
        decay(minutes=2),
        expires(minutes=1440),
    )
    uploads(world, 2)
    sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        channel = session.scalar(select(Channel))
        trial = graph.try_it(
            session, get_settings(session), sources=[box_of(session, channel)]
        )
        marked = set(trial.through) | set(trial.held)

    # Every one of them, not just the filters and sorts.
    assert set(ids) <= marked


def test_a_box_after_the_one_that_turned_it_away_is_not_marked(world, db):
    """It never saw the item. Saying it did would be worse than saying
    nothing."""
    from dealgo.db import get_settings
    from dealgo.models import GraphNode

    ids = wire(
        db,
        lambda s: graph.add_filter(s, label="Refuses everything"),
        lambda s: graph.add_stamp(s, kind="tag", marks="never"),
    )
    with db.session_scope() as session:
        graph.add_piece(
            session, kind="has-words", host=session.get(GraphNode, ids[0])
        ).title_include = "nothing matches this"
    uploads(world, 2)
    # The trial pushes what is already here through the graph, so there has
    # to be something here.
    sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        channel = session.scalar(select(Channel))
        trial = graph.try_it(
            session, get_settings(session), sources=[box_of(session, channel)]
        )

    assert ids[0] in trial.held          # the filter stopped them
    assert ids[1] not in trial.through   # the tag box never saw them


def test_a_sort_box_is_counted_once(world, db):
    """It is in the walked list with everything else now; noting it again
    would count every item through it twice."""
    from dealgo.db import get_settings

    ids = wire(db, lambda s: graph.add_sort(s, label="Newest"))
    uploads(world, 3)
    sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        channel = session.scalar(select(Channel))
        trial = graph.try_it(
            session, get_settings(session), sources=[box_of(session, channel)]
        )

    assert len(trial.through.get(ids[0], [])) == 3


def test_a_test_follows_the_flow_its_trigger_is_wired_to(world, db):
    """A channel drawn twice is one channel and two boxes, and the two may
    run down quite different paths. Narrowing the trial by the channel lit
    up both, so a test on one trigger reported what another flow would do.
    """
    from dealgo.db import get_settings
    from dealgo.models import GraphNode, Playlist

    # The fixture's channel, wired a second time down a path of its own.
    ids = wire(db, lambda s: graph.add_stamp(s, kind="tag", marks="first"))
    uploads(world, 2)
    sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        channel = session.scalar(select(Channel))
        playlist = session.scalar(select(Playlist))
        second = graph.add_source(session, channel=channel, source_kind="youtube")
        elsewhere = graph.add_stamp(session, kind="tag", marks="second")
        feed = session.scalar(select(GraphNode).where(GraphNode.kind == "feed"))
        graph.connect(session, second, elsewhere)
        graph.connect(session, elsewhere, feed)
        pulse = graph.add_trigger(session, trigger_kind="pulse")
        graph.connect(session, pulse, second)
        asked, other, mine = pulse.id, ids[0], elsewhere.id

    with db.session_scope() as session:
        node = session.get(GraphNode, asked)
        trial = graph.try_it(
            session,
            get_settings(session),
            sources=graph.wired_sources(session, node),
        )
        marked = set(trial.through) | set(trial.held)

    # Its own flow, and not the other one that the same channel also feeds.
    assert mine in marked
    assert other not in marked


def test_the_marks_arrive_box_by_box_and_not_all_at_once(world, db):
    """What an item carries depends on how far along it has got. An Expire
    box wired before a Decay box has not met the Decay box when the item
    reaches it, and saying otherwise told the reader the flow ran in an
    order it does not."""
    from dealgo.db import get_settings
    from dealgo.models import GraphNode

    ids = wire(
        db,
        lambda s: graph.add_stamp(s, kind="tag", marks="news"),
        expires(minutes=7 * 1440),
        decay(minutes=3),
    )
    uploads(world, 1)
    sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        channel = session.scalar(select(Channel))
        source = box_of(session, channel)
        feed = session.scalar(select(GraphNode).where(GraphNode.kind == "feed")).id
        trial = graph.try_it(session, get_settings(session), sources=[source])
        carried = {
            where: (trial.through[pk][0].marks if trial.through.get(pk) else None)
            for where, pk in (
                ("source", source), ("tag", ids[0]), ("expire", ids[1]),
                ("decay", ids[2]), ("feed", feed),
            )
        }

    assert carried["source"] == []
    assert carried["tag"] == ["“news”"]
    # The Expire box is before the Decay box, so it has not met it yet.
    assert carried["expire"] == ["“news”", "gone 1 week after it arrives"]
    assert carried["decay"] == ["“news”", "3 min", "gone 1 week after it arrives"]
    # And the feed sees everything every box put on it.
    assert carried["feed"] == ["“news”", "3 min", "gone 1 week after it arrives"]


# -- Expire, once watched -------------------------------------------------


def expires_after_watch(minutes=None):
    """An Expire box with After watching under it, and a Timer too if given:
    it goes once watched, or when the Timer from arriving runs out."""
    def make(session):
        box = graph.add_stamp(session, kind="expire")
        if minutes is not None:
            graph.add_piece(session, kind="timer", host=box, duration_minutes=minutes)
        graph.add_piece(session, kind="after-watch", host=box)
        return box

    return make


def watch(db, when):
    with db.session_scope() as session:
        for video in session.scalars(select(Video)):
            video.watched_at = when


def test_after_watching_alone_keeps_what_is_unwatched(world, db):
    wire(db, expires_after_watch())
    uploads(world, 1)
    sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        placement = session.scalar(select(Placement))
        assert placement.expires_at is None  # no Timer, no clock from the arrival
        assert placement.expires_after_watch_minutes == 0

    # A week on, still unwatched, still there.
    with db.session_scope() as session:
        session.scalar(select(Placement)).added_at = utcnow() - dt.timedelta(days=7)
    sync_service.run_sync("manual", force=True)
    with db.session_scope() as session:
        assert session.scalar(select(Placement)).removed_at is None


def test_it_goes_at_the_next_run_once_watched(world, db):
    wire(db, expires_after_watch())
    uploads(world, 2)
    sync_service.run_sync("manual", force=True)

    watch(db, utcnow() - dt.timedelta(minutes=1))
    sync_service.run_sync("manual", force=True)
    with db.session_scope() as session:
        gone = session.scalars(select(Placement).where(Placement.removed_at.is_not(None))).all()
        assert len(gone) == 2
    # From the feed, not the history.
    assert len(items(db)) == 2


def test_unwatching_keeps_it(world, db):
    wire(db, expires_after_watch())
    uploads(world, 1)
    sync_service.run_sync("manual", force=True)
    watch(db, utcnow() - dt.timedelta(minutes=10))
    watch(db, None)  # changed their mind
    sync_service.run_sync("manual", force=True)
    with db.session_scope() as session:
        assert session.scalar(select(Placement)).removed_at is None


def test_with_a_timer_watching_it_comes_first(world, db):
    wire(db, expires_after_watch(minutes=7 * 1440))
    uploads(world, 1)
    sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        placement = session.scalar(select(Placement))
        assert placement.expires_at is not None  # the Timer counts from arriving
        assert placement.expires_after_watch_minutes == 0

    watch(db, utcnow() - dt.timedelta(minutes=1))
    sync_service.run_sync("manual", force=True)
    with db.session_scope() as session:
        assert session.scalar(select(Placement)).removed_at is not None


def test_with_a_timer_the_timer_comes_first(world, db):
    wire(db, expires_after_watch(minutes=60))
    uploads(world, 1)
    sync_service.run_sync("manual", force=True)

    # Never watched, but the Timer from arriving has run out.
    with db.session_scope() as session:
        session.scalar(select(Placement)).expires_at = utcnow() - dt.timedelta(minutes=1)
    sync_service.run_sync("manual", force=True)
    with db.session_scope() as session:
        assert session.scalar(select(Placement)).removed_at is not None


def test_adding_after_watching_reaches_what_is_already_watched(world, db):
    """As with the plain box, wiring it says something about the feed now."""
    uploads(world, 1)
    sync_service.run_sync("manual", force=True)
    watch(db, utcnow() - dt.timedelta(days=2))

    wire(db, expires_after_watch())
    sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        assert session.scalar(select(Placement)).removed_at is not None


def test_after_watching_only_slots_under_an_expire_box(db):
    from dealgo.services.graph.errors import GraphError

    with db.session_scope() as session:
        piece = graph.add_piece(session, kind="after-watch")
        decay = graph.add_stamp(session, kind="decay")
        try:
            graph.attach(session, piece, decay)
        except GraphError:
            pass
        else:
            raise AssertionError("an After watching piece went under a Decay box")
        assert piece.title == "After watching"


def test_the_boxes_say_when_they_take_things_out(db):
    from dealgo.services.graph.stamps import stamp_marks
    from dealgo.services.graph.words import piece_words, stamp_words

    with db.session_scope() as session:
        alone = expires_after_watch()(session)
        both = expires_after_watch(minutes=1440)(session)
        pieces_for = graph.pieces_of(session)
        assert stamp_words(alone, pieces_for(alone)) == "gone once you watch it"
        assert stamp_words(both, pieces_for(both)) == (
            "gone once you watch it, or 1 day after it arrives"
        )
        after = next(p for p in pieces_for(alone) if p.kind == "after-watch")
        assert piece_words(after) == "once you watch it"
        assert stamp_marks([alone], pieces_for) == ["gone once you watch it"]
        assert stamp_marks([both], pieces_for) == [
            "gone once you watch it, or 1 day after it arrives"
        ]


def test_a_delay_after_watching_from_before_becomes_once_watched(db):
    """Placements stamped when After watching started the Timer at the
    watching carried a delay; now they go once watched, and do so twice over
    without change."""
    from dealgo.db.migrations import after_watching_is_its_own_condition

    with db.session_scope() as session:
        channel = Channel(channel_id="UCold", title="Old")
        session.add(channel)
        session.flush()
        video = Video(video_id="old1", channel_pk=channel.id, title="Old", status="added")
        session.add(video)
        session.flush()
        feed = playlist_service.create_generic(session, "Old feed")
        session.add(Placement(video_pk=video.id, playlist_pk=feed.id,
                              playlist_item_id="generic-1", expires_after_watch_minutes=1440))

    after_watching_is_its_own_condition()
    after_watching_is_its_own_condition()
    with db.session_scope() as session:
        assert session.scalar(select(Placement)).expires_after_watch_minutes == 0
