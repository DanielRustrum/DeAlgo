"""Deposit and Withdraw: a named repository, from its two ends.

Every source can funnel into one pile instead of into feeds, and a pipeline
pulls from that pile when it is ready rather than each source pushing on its
own schedule. A Deposit box ends a path the way a feed does; a Withdraw box
starts one the way a source does.
"""

from __future__ import annotations

from sqlalchemy import select

from dealgo.models import Channel, Placement, Playlist, RepositoryItem, Video, utcnow
from dealgo.plugins.publisher import VideoDetails
from dealgo.services import graph
from dealgo.services import sync as sync_service
from fakes import entry, unwire


def build(world, db, *, name="News", takes=None, pull=True, wired=True):
    """The fixture's channel, funnelled into a repository instead of a feed.

    Returns the ids of the boxes a test will want to press.
    """
    from dealgo.models import GraphNode

    with db.session_scope() as session:
        # Far enough back that every upload a test writes arrives; these are
        # about what happens after that, not about the backfill window.
        db.get_settings(session).initial_backfill = 50
        channel = session.scalar(select(Channel))
        unwire(session, channel)  # nothing goes straight to a feed any more
        source = session.scalar(
            select(GraphNode).where(GraphNode.kind == "source")
        )
        playlist = session.scalar(select(Playlist))
        feed = session.scalar(select(GraphNode).where(GraphNode.kind == "feed"))
        if feed is None:
            feed = graph.add_feed(session, playlist)

        deposit = graph.add_store(session, kind="deposit", repository=name)
        graph.connect(session, source, deposit)

        withdraw = None
        if pull:
            withdraw = graph.add_store(
                session, kind="withdraw", repository=name, takes=takes
            )
            if wired:
                graph.connect(session, withdraw, feed)
            pulse = graph.add_trigger(session, trigger_kind="pulse")
            pulse.every_minutes = 1440
            # Just pulled, so its own gap has not come round: a run leaves
            # what is waiting alone until somebody presses it.
            pulse.last_fired_at = utcnow()
            withdraw.last_fired_at = utcnow()
            graph.connect(session, pulse, withdraw)
        return deposit.id, (withdraw.id if withdraw else None)


def uploads(world, how_many=3):
    world["entries"] = [entry(f"v{n}", minutes_ago=n) for n in range(how_many)]
    world["client"].details = {
        f"v{n}": VideoDetails(f"v{n}", f"Video v{n}", 600, "none", "public")
        for n in range(how_many)
    }


def holding(db, name="news") -> int:
    with db.session_scope() as session:
        return sync_service.waiting_in(session, name)


def in_feeds(db) -> int:
    with db.session_scope() as session:
        return len(session.scalars(select(Placement)).all())


# -- the deposit half ------------------------------------------------------


def test_what_reaches_a_deposit_is_held_rather_than_delivered(world, db):
    """The whole point of it. A path into a repository is a path that ends
    there — nothing goes on to a feed until somebody pulls."""
    build(world, db)
    uploads(world)

    result = sync_service.run_sync("manual", force=True)

    assert result.deposited == 3
    assert holding(db) == 3
    assert in_feeds(db) == 0


def test_a_name_is_filed_one_way_however_it_is_typed(world, db):
    """Two boxes only share a repository when they share its name, so "News"
    and "news " had better be one name rather than two that look alike."""
    build(world, db, name="  NEWS  ")
    uploads(world, 1)

    sync_service.run_sync("manual", force=True)

    assert holding(db, "news") == 1


def test_the_same_item_is_not_piled_up_twice(world, db):
    """A second run over the same item is a second look, not a second copy."""
    build(world, db)
    uploads(world, 2)
    sync_service.run_sync("manual", force=True)

    sync_service.run_sync("manual", force=True)

    assert holding(db) == 2


def test_a_deposit_with_no_name_holds_nothing(world, db):
    """It names no repository, so there is nowhere for anything to go. The
    item stays pending rather than vanishing into a box with no name on it."""
    build(world, db, name="")
    uploads(world, 2)

    result = sync_service.run_sync("manual", force=True)

    assert result.deposited == 0
    assert holding(db) == 0
    with db.session_scope() as session:
        held = session.scalars(select(Video).where(Video.status == "pending")).all()
        assert len(held) == 2


def test_an_item_held_in_a_repository_counts_as_filed(world, db):
    """It went where the canvas sent it. Left pending it would be looked at
    again every run for ever, and reported as waiting on something."""
    build(world, db)
    uploads(world, 1)

    sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        video = session.scalar(select(Video))
        assert video.status == "added"


# -- the withdraw half -----------------------------------------------------


def test_a_withdraw_leaves_it_alone_until_its_trigger_says_so(world, db):
    """A repository nobody pulls from is a repository that fills up. That is
    what it is for."""
    build(world, db)
    uploads(world, 3)

    sync_service.run_sync("manual", force=True)

    assert holding(db) == 3
    assert in_feeds(db) == 0


def test_pulling_sends_what_comes_out_down_its_own_path(world, db):
    build(world, db)
    uploads(world, 3)
    sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        from dealgo.models import GraphNode

        box = session.scalar(select(GraphNode).where(GraphNode.kind == "withdraw"))
        said = sync_service.withdraw_now(session, [box.id])

    assert "3" in said
    assert holding(db) == 0
    assert in_feeds(db) == 3


def test_it_takes_only_as_many_as_it_was_told_to(world, db):
    """Left empty the field means everything; set, it drips."""
    build(world, db, takes=2)
    uploads(world, 5)
    sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        from dealgo.models import GraphNode

        box = session.scalar(select(GraphNode).where(GraphNode.kind == "withdraw"))
        pk = box.id
        sync_service.withdraw_now(session, [pk])
    assert (holding(db), in_feeds(db)) == (3, 2)

    with db.session_scope() as session:
        sync_service.withdraw_now(session, [pk])
    assert (holding(db), in_feeds(db)) == (1, 4)

    with db.session_scope() as session:
        sync_service.withdraw_now(session, [pk])
    assert (holding(db), in_feeds(db)) == (0, 5)


def test_the_oldest_goes_first(world, db):
    """It is a pile, and a pile is taken from the bottom."""
    build(world, db, takes=1)
    uploads(world, 3)
    sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        from dealgo.models import GraphNode

        box = session.scalar(select(GraphNode).where(GraphNode.kind == "withdraw"))
        first = session.scalars(
            select(RepositoryItem).order_by(RepositoryItem.deposited_at, RepositoryItem.id)
        ).first()
        wanted = first.video.video_id
        sync_service.withdraw_now(session, [box.id])

    with db.session_scope() as session:
        placed = session.scalars(select(Placement)).all()
        assert len(placed) == 1
        assert placed[0].video.video_id == wanted


def test_what_is_taken_is_taken(world, db):
    """A withdrawal empties what it took, or the next pull would send the
    same items again."""
    build(world, db)
    uploads(world, 2)
    sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        from dealgo.models import GraphNode

        box = session.scalar(select(GraphNode).where(GraphNode.kind == "withdraw"))
        pk = box.id
        sync_service.withdraw_now(session, [pk])
    with db.session_scope() as session:
        assert sync_service.withdraw_now(session, [pk]) == "Nothing was waiting."


def test_a_withdraw_wired_to_nothing_still_empties_it(world, db):
    """A box somebody has not finished wiring is not a reason to fill the
    repository for ever."""
    build(world, db, wired=False)
    uploads(world, 2)
    sync_service.run_sync("manual", force=True)
    assert holding(db) == 2

    with db.session_scope() as session:
        from dealgo.models import GraphNode

        box = session.scalar(select(GraphNode).where(GraphNode.kind == "withdraw"))
        sync_service.withdraw_now(session, [box.id])

    assert holding(db) == 0
    assert in_feeds(db) == 0


def test_a_withdraw_that_is_switched_off_pulls_nothing(world, db):
    build(world, db)
    uploads(world, 2)
    sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        from dealgo.models import GraphNode

        box = session.scalar(select(GraphNode).where(GraphNode.kind == "withdraw"))
        box.enabled = False
        sync_service.withdraw_now(session, [box.id])

    assert holding(db) == 2


# -- the two ends together -------------------------------------------------


def test_a_run_pulls_when_the_trigger_has_come_round(world, db):
    """Nobody has to press anything: a trigger wired to a Withdraw box says
    when to pull, the way one wired to a source says when to poll."""
    build(world, db)
    uploads(world, 2)

    with db.session_scope() as session:
        from dealgo.models import GraphNode

        for box in session.scalars(
            select(GraphNode).where(GraphNode.kind.in_(("trigger", "withdraw")))
        ):
            box.last_fired_at = None  # never pulled, so overdue

    result = sync_service.run_sync("manual", force=True)

    assert result.deposited == 2
    assert result.withdrawn == 2
    assert holding(db) == 0
    assert in_feeds(db) == 2


def test_two_deposits_with_one_name_are_one_pile(world, db):
    """Which is how you funnel several sources into one place."""
    from dealgo.models import GraphNode

    build(world, db)
    uploads(world, 2)
    with db.session_scope() as session:
        source = session.scalar(select(GraphNode).where(GraphNode.kind == "source"))
        second = graph.add_store(session, kind="deposit", repository="News")
        graph.connect(session, source, second)

    result = sync_service.run_sync("manual", force=True)

    # Two ways in, one pile: the item is not held twice for having two
    # doors into the same room.
    assert result.deposited == 2
    assert holding(db) == 2
