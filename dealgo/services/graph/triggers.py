"""When each source is polled and each repository pulled, as the trigger boxes say."""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import (
    GraphNode,
    to_naive_utc,
    utcnow,
)
from ..scope import OwnerId, owned
from .canvas import load
from .cron import cron_trigger
from .errors import GraphError
from .reading import channels_of, nodes
from .units import DEFAULT_CRON, DEFAULT_EVERY_MINUTES, as_aware

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class When:
    """One trigger box's answer to "when is this channel polled?".

    The two kinds are asked the same question and answer it differently: a
    pulse counts from the last poll, a schedule counts from the clock. Keeping
    both behind one method means the sync engine never has to know which is
    which.
    """

    kind: str
    every_minutes: int | None = None
    cron: str | None = None

    def due(self, last_checked: dt.datetime | None, now: dt.datetime) -> bool:
        """Whether a source last polled at `last_checked` is due at `now`."""
        if last_checked is None:
            # Never polled. Both kinds agree that is overdue.
            return True
        if self.kind == "pulse":
            if self.every_minutes == 0:
                # Every run there is. The plainest thing a pulse can say, and
                # what a channel with no minimum gap always did before the
                # canvas had triggers to say it with.
                return True
            gap = self.every_minutes or DEFAULT_EVERY_MINUTES
            return now >= last_checked + dt.timedelta(minutes=gap)
        return self.came_round_since(last_checked, now)

    def came_round_since(self, last_checked: dt.datetime, now: dt.datetime) -> bool:
        """Whether a cron firing time fell between the last poll and now.

        Asked of the schedule rather than worked out here: "the next time this
        would have gone off after the last poll" is one call, and it is right
        for every expression, including the ones that skip days.
        """
        try:
            trigger = cron_trigger(self.cron or DEFAULT_CRON)
        except GraphError:
            # A saved expression that no longer parses must not stop a sync.
            log.warning("ignoring an unreadable cron expression: %r", self.cron)
            return False
        due_at = trigger.get_next_fire_time(None, as_aware(last_checked))
        return due_at is not None and due_at <= as_aware(now)


def triggers_for(session: Session, owner: OwnerId = None) -> dict[int, list[GraphNode]]:
    """The trigger boxes wired into each channel, by channel primary key."""
    all_nodes, all_edges = load(session, owner)
    by_id = {node.id: node for node in all_nodes}

    wired: dict[int, list[GraphNode]] = {}
    for edge in all_edges:
        start, end = by_id.get(edge.source_pk), by_id.get(edge.target_pk)
        if start is None or end is None:
            continue
        if not start.enabled:
            continue  # a trigger that is switched off sets nothing off
        if start.kind == "trigger" and end.kind == "source" and end.enabled:
            # A tag node stands for several channels, and a trigger wired to
            # it is wired to all of them.
            for channel in channels_of(session, end, owner):
                wired.setdefault(channel.id, []).append(start)
    return wired


def polling_plan(session: Session, owner: OwnerId = None) -> dict[int, list[When]]:
    """When each wired channel wants polling, by channel primary key.

    A channel absent from this has no trigger wired, and is not polled at all.
    A trigger is how a run starts; a source fetched on a schedule that is
    drawn nowhere is a source filling feeds for reasons the canvas cannot
    explain.

    A channel with several is polled when *any* of them says so. Two triggers
    are two reasons to poll, not a negotiation.
    """
    plan: dict[int, list[When]] = {}
    for channel_pk, wired in triggers_for(session, owner).items():
        plan[channel_pk] = [
            When(
                kind=node.trigger_kind or "pulse",
                every_minutes=node.every_minutes,
                cron=node.cron,
            )
            for node in wired
        ]
    return plan


def pulse_targets(session: Session, node_pk: int, owner: OwnerId = None) -> list[int]:
    """The channels one trigger box is wired to, ready to be polled."""
    node = session.scalar(owned(select(GraphNode), GraphNode, owner).where(GraphNode.id == node_pk))
    if node is None or node.kind != "trigger":
        raise GraphError("That node is not a trigger.")
    if not node.enabled:
        raise GraphError("That trigger is switched off.")
    return wired_channels(session, node, owner)


def due_withdrawals(
    session: Session, owner: OwnerId = None, now: dt.datetime | None = None
) -> list[GraphNode]:
    """The Withdraw boxes whose turn it is to pull.

    Each remembers when it last pulled, and its wired triggers say how often.
    A box with no trigger never pulls on its own, which is the same rule a
    source with no trigger lives by: a pull that happens for reasons the
    canvas cannot explain is not something anybody drew.
    """
    # Naive UTC, the way everything stored is: `last_fired_at` comes out of
    # the database that way, and comparing it with an aware instant raises
    # rather than answering.
    when = to_naive_utc(now) if now is not None else utcnow()
    if when is None:  # pragma: no cover - only for a `now` of None, handled above
        when = utcnow()
    due: list[GraphNode] = []
    by_id = {node.id: node for node in nodes(session, owner)}
    for box_pk, wired in triggers_for_withdrawals(session, owner).items():
        box = by_id.get(box_pk)
        if box is None or not box.enabled:
            continue
        asked = [
            When(kind=one.trigger_kind or "pulse", every_minutes=one.every_minutes, cron=one.cron)
            for one in wired
            if one.enabled
        ]
        # Any of them saying so is enough. Two triggers are two reasons to
        # pull, not a negotiation.
        if any(one.due(box.last_fired_at, when) for one in asked):
            due.append(box)
    return due


def wired_sources(
    session: Session, node: GraphNode, owner: OwnerId = None
) -> list[int]:
    """The source boxes a trigger box is wired to, by box.

    Not the channels behind them, which is a different question with a
    different answer: a channel drawn twice is one channel and two boxes,
    and a trigger reaches one of the boxes.
    """
    all_nodes, all_edges = load(session, owner)
    by_id = {entry.id: entry for entry in all_nodes}
    reached: list[int] = []
    for edge in all_edges:
        if edge.source_pk != node.id:
            continue
        target = by_id.get(edge.target_pk)
        if target is not None and target.kind == "source" and target.id not in reached:
            reached.append(target.id)
    return reached


def wired_withdrawals(
    session: Session, node: GraphNode, owner: OwnerId = None
) -> list[GraphNode]:
    """The Withdraw boxes a trigger box reaches.

    The same question as `wired_channels`, asked of the other kind of start.
    A trigger wired to one says when to pull from its repository, exactly as
    one wired to a source says when to poll it.
    """
    all_nodes, all_edges = load(session, owner)
    by_id = {entry.id: entry for entry in all_nodes}
    reached: list[GraphNode] = []
    for edge in all_edges:
        if edge.source_pk != node.id:
            continue
        target = by_id.get(edge.target_pk)
        if target is None or target.kind != "withdraw":
            continue
        if target.id not in {one.id for one in reached}:
            reached.append(target)
    return reached


def triggers_for_withdrawals(
    session: Session, owner: OwnerId = None
) -> dict[int, list[GraphNode]]:
    """Which triggers are wired to each Withdraw box, by box primary key."""
    all_nodes, all_edges = load(session, owner)
    by_id = {node.id: node for node in all_nodes}
    wired: dict[int, list[GraphNode]] = {}
    for edge in all_edges:
        start, end = by_id.get(edge.source_pk), by_id.get(edge.target_pk)
        if start is None or end is None:
            continue
        if start.kind != "trigger" or end.kind != "withdraw":
            continue
        wired.setdefault(end.id, []).append(start)
    return wired


def wired_channels(
    session: Session, node: GraphNode, owner: OwnerId = None
) -> list[int]:
    """The channels a trigger box reaches, switched on or not.

    Not the same question as "what would it poll": a trigger that is switched
    off still reaches what it is wired to, and being able to ask what it would
    do is most of the point of being able to test it.
    """
    all_nodes, all_edges = load(session, owner)
    by_id = {entry.id: entry for entry in all_nodes}
    reached: list[int] = []
    for edge in all_edges:
        if edge.source_pk != node.id:
            continue
        target = by_id.get(edge.target_pk)
        if target is None or target.kind != "source":
            continue
        # Whatever that node stands for: one channel, or every channel
        # carrying its tag.
        for channel in channels_of(session, target, owner):
            if channel.id not in reached:
                reached.append(channel.id)
    return reached
