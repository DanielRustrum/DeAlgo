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
        session.get(GraphNode, ids[1]).tagged = "keep"
    uploads(world, 2)

    result = sync_service.run_sync("manual", force=True)

    assert result.added == 2


def test_a_filter_asking_for_a_tag_nothing_carries_turns_it_away(world, db):
    from dealgo.models import GraphNode

    ids = wire(db, lambda s: graph.add_filter(s, label="Only tagged"))
    with db.session_scope() as session:
        session.get(GraphNode, ids[0]).tagged = "never-applied"
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
    from dealgo.web.app import _focus_item

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
            session, get_settings(session), channels=[channel.id]
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
        session.get(GraphNode, ids[0]).title_include = "nothing matches this"
    uploads(world, 2)
    # The trial pushes what is already here through the graph, so there has
    # to be something here.
    sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        channel = session.scalar(select(Channel))
        trial = graph.try_it(
            session, get_settings(session), channels=[channel.id]
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
            session, get_settings(session), channels=[channel.id]
        )

    assert len(trial.through.get(ids[0], [])) == 3
