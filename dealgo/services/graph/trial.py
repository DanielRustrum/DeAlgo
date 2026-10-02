"""Trying a flow without running it: where recent items would land, and why."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import (
    GraphNode,
    Settings,
    Video,
)
from ..scope import OwnerId, owned
from .canvas import load
from .names import store_name
from .pieces import pieces_of
from .reading import nodes
from .report import Judged
from .routes import Route, paths_from, routes
from .stamps import stamp_marks
from .vocabulary import STAMPS


@dataclass
class Trial:
    """What a run would do, worked out without doing it.

    Kept per box rather than per feed, so every box the trial passed through
    can show its own share of it — which is the question asked while looking
    at that box, not at the trigger three wires back.
    """

    #: Per box: what got through it, and what it turned away.
    through: dict[int, list[Judged]] = field(default_factory=dict)
    held: dict[int, list[Judged]] = field(default_factory=dict)


def try_it(
    session: Session,
    settings: Settings,
    owner: OwnerId = None,
    limit: int = 30,
    sources: Collection[int] | None = None,
    pulls: Collection[int] | None = None,
) -> Trial:
    """Push recent items through the graph and say where they would land.

    Nothing is written and nothing is sent to YouTube: this answers "is this
    wired up the way I think" without waiting for a run, and without a run's
    consequences.

    ``sources`` narrows it to what one trigger sets off, which is how it is
    asked: a trigger is the thing that starts a run, so it is the thing worth
    asking what a run would do.

    Source *boxes*, not channels. A channel may be drawn twice — that is the
    point of being allowed a second box — and the two may run down quite
    different paths. Narrowing by the channel lit up both of them, so a test
    on one trigger reported what a different flow would do.

    ``pulls`` is the other half of that: the Withdraw boxes it is wired to.
    A withdrawal is a path like any other and its filters have as much to
    say, so what is waiting in its repository is pushed through it here —
    without which a trigger wired to one could be tested and report nothing
    at all.

    What is already in a feed is not excluded. The question being asked is
    what this configuration does with this content, not what is left to do —
    a test that went quiet once everything had been filed would be no use at
    the moment it is most wanted.
    """
    all_nodes, _ = load(session, owner)
    feed_node = {node.playlist_pk: node for node in all_nodes if node.kind == "feed"}

    trial = Trial()
    recent: dict[int, list[Video]] = {}
    # Read once for the whole trial: every path asks the same boxes what is
    # slotted under them.
    known = pieces_of(session, owner)

    for path in routes(session, owner):
        # A trial follows items to a feed. A path into a repository has no
        # feed to show them arriving at, and what happens to them there is
        # the Withdraw box's business.
        if path.playlist is None or not path.playlist.enabled:
            continue
        if sources is not None and (path.source is None or path.source.id not in sources):
            continue  # asked of one trigger: only what that trigger sets off
        start, end = path.source, feed_node.get(path.playlist.id)
        if start is None or end is None:
            continue

        if path.channel.id not in recent:
            recent[path.channel.id] = list(
                session.scalars(
                    owned(select(Video), Video, owner)
                    .where(Video.channel_pk == path.channel.id)
                    .order_by(Video.id.desc())
                    .limit(limit)
                )
            )

        landing: list[tuple[Video, Judged]] = []
        for video in recent[path.channel.id]:
            judged, stopped_at = _judge(video, path, settings, start)
            if judged.passed:
                _walk_marks(trial, judged, path, start, known)
                landing.append((video, judged))
            else:
                _note(trial.held, [stopped_at], judged)
                # Everything before the box that stopped it did let it by.
                _note(trial.through, _before(stopped_at, path, start), judged)

        order = path.order
        if order is not None:
            landing.sort(key=lambda pair: _ranked(pair[0], order))

        # The feed sees the batch in the order it arrives, carrying whatever
        # every box on the way left on it. The sort box is already in
        # `walked` with the rest, so noting it again would count it twice.
        for _, judged in landing:
            _note(trial.through, [end.id], _carrying(judged, path.stamps, known))

    for box in nodes(session, owner):
        if box.kind != "withdraw":
            continue
        if pulls is not None and box.id not in pulls:
            continue
        _try_withdrawal(session, settings, box, trial, feed_node, owner, limit)

    return trial


def _try_withdrawal(
    session: Session,
    settings: Settings,
    box: GraphNode,
    trial: Trial,
    feed_node: dict[int | None, GraphNode],
    owner: OwnerId,
    limit: int,
) -> None:
    """What one Withdraw box would send on, from what is waiting in it.

    The same walk as a source's, with the pile standing in for a feed's worth
    of new items — and bounded by what the box says it takes, so the answer
    is what the next pull would do rather than what every pull eventually
    would.
    """
    from ...models import RepositoryItem

    known = pieces_of(session, owner)
    name = store_name(box.repository)
    if not name:
        return

    most = box.takes or 0
    query = (
        owned(select(RepositoryItem), RepositoryItem, owner)
        .where(RepositoryItem.name == name)
        .order_by(RepositoryItem.deposited_at, RepositoryItem.id)
        .limit(min(most, limit) if most > 0 else limit)
    )
    waiting = [row.video for row in session.scalars(query) if row.video is not None]
    if not waiting:
        return

    for video in waiting:
        channel = video.channel
        if channel is None:
            continue
        for path in paths_from(session, box, channel, owner):
            if path.playlist is None or not path.playlist.enabled:
                continue
            end = feed_node.get(path.playlist.id)
            if end is None:
                continue
            judged, stopped_at = _judge(video, path, settings, box)
            if judged.passed:
                _walk_marks(trial, judged, path, box, known)
                _note(trial.through, [end.id], _carrying(judged, path.stamps, known))
            else:
                _note(trial.held, [stopped_at], judged)
                _note(trial.through, _before(stopped_at, path, box), judged)


def _judge(
    video: Video, path: Route, settings: Settings, start: GraphNode
) -> tuple[Judged, int]:
    """Whether this path takes the video, and the box that turned it away.

    Asked a box at a time rather than of the path as a whole, so the answer
    names the box actually holding things up.
    """
    from .. import sync as sync_service

    def seen(passed: bool, reason: str | None) -> Judged:
        """A verdict on this item, before any box has marked it."""
        return Judged(
            video_pk=video.id,
            title=video.title or video.video_id,
            kind=video.kind,
            passed=passed,
            reason=reason,
            # Filled in per box by whoever is walking the path: what an
            # item carries depends on how far along it has got, not on the
            # path as a whole.
            marks=[],
        )

    # The channel's own settings first: if they refuse it, it never left.
    own = Route(channel=path.channel, playlist=path.playlist)
    refusal = sync_service.decide(video, own, None, settings)
    if not refusal.accept:
        return seen(False, refusal.reason), start.id

    for index, node in enumerate(path.filters):
        so_far = Route(
            channel=path.channel, playlist=path.playlist,
            filters=path.filters[: index + 1], slots=path.slots,
        )
        decision = sync_service.decide(video, so_far, None, settings)
        if not decision.accept:
            return seen(False, decision.reason), node.id

    decision = sync_service.decide(video, path, None, settings)
    return seen(decision.accept, decision.reason), start.id


def _walk_marks(
    trial: Trial, judged: Judged, path: Route, start: GraphNode, pieces_for: Any
) -> None:
    """Note an item at every box it passed, carrying what it had by then.

    What an item carries depends on how far along it has got. An Expire box
    wired before a Decay box has not met the Decay box when the item reaches
    it, and saying otherwise told the reader the flow ran in an order it
    does not.
    """
    # At the source box it carries nothing: nothing has been applied yet.
    _note(trial.through, [start.id], _carrying(judged, [], pieces_for))

    so_far: list[GraphNode] = []
    for box in path.walked:
        if box.kind in STAMPS:
            so_far = so_far + [box]
        _note(trial.through, [box.id], _carrying(judged, so_far, pieces_for))


def _carrying(judged: Judged, stamps: list[GraphNode], pieces_for: Any) -> Judged:
    """The same item, said to be carrying what these boxes put on it."""
    import dataclasses

    return dataclasses.replace(judged, marks=stamp_marks(stamps, pieces_for))


def _before(stopped_at: int, path: Route, start: GraphNode) -> list[int]:
    """The boxes an item passed before the one that stopped it.

    From the boxes it actually walks through, in that order — not from the
    filters alone. A Decay or a Tag box turns nothing away, but it is still
    a box an item went through, and one that reported nothing looked broken
    rather than uninvolved.
    """
    walked = [start.id] + [node.id for node in path.walked]
    return walked[: walked.index(stopped_at)] if stopped_at in walked else []


def _note(seen: dict[int, list[Judged]], node_ids: list[int], judged: Judged) -> None:
    """File a verdict under every box it reached."""
    for node_id in node_ids:
        seen.setdefault(node_id, []).append(judged)


def _ranked(video: Video, order: GraphNode) -> tuple[float, int]:
    """Where this video lands in a sorted batch, as the sort box sees it."""
    from .. import sync as sync_service

    value = sync_service.ordering_value(video, order)
    return (-value if (order.sort_dir or "desc") == "desc" else value, video.id)
