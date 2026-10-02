"""Withdraw boxes: letting items out of a pile and down the path that starts there."""

from __future__ import annotations

from collections.abc import Collection

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ...db import get_settings
from ...models import (
    GraphNode,
    Playlist,
    RepositoryItem,
    Video,
    utcnow,
)
from .. import graph, runlog
from ..scope import OwnerId, owned
from .deciding import decide
from .filing import place_locally
from .repositories import waiting_in
from .result import SyncResult


def withdraw(
    session: Session,
    node: GraphNode,
    result: SyncResult,
    owner: OwnerId = None,
    say: runlog.Pen | None = None,
) -> int:
    """Pull from one Withdraw box's repository and send what comes out onward.

    A Withdraw box stands where a source stands: it starts a path. What comes
    out of it has already been through whatever filtered it on the way in, so
    only the boxes between here and a feed get another say.

    Oldest first, so a repository behaves like the pile it looks like. What
    is taken is taken — the rows go, which is what makes it a withdrawal
    rather than a look.
    """
    name = graph.store_name(node.repository)
    if not name:
        return 0
    if not node.enabled:
        return 0

    most = node.takes or 0
    query = (
        owned(select(RepositoryItem), RepositoryItem, owner)
        .options(selectinload(RepositoryItem.video).selectinload(Video.channel))
        .where(RepositoryItem.name == name)
        .order_by(RepositoryItem.deposited_at, RepositoryItem.id)
    )
    if most > 0:
        query = query.limit(most)
    holding = list(session.scalars(query))
    if not holding:
        if say is not None:
            say.write(f"the {name} repository is empty", about=node.title)
        return 0

    settings = get_settings(session, owner)
    sent = 0
    held_back = 0
    for row in holding:
        video, channel = row.video, row.video.channel if row.video else None
        if video is None or channel is None:
            session.delete(row)   # the item is gone; the row is a leftover
            continue

        # Every box between here and a feed still gets a say. A filter wired
        # after a Withdraw is a filter on what comes out, and ignoring it
        # would make it a box that draws a wire and does nothing.
        allowed: list[Playlist] = []
        for path in graph.paths_from(session, node, channel, owner):
            if path.playlist is None or not path.playlist.enabled:
                continue
            if decide(video, path, None, settings).accept:
                allowed.append(path.playlist)
        feeds = sorted(
            {one.id: one for one in allowed}.values(),
            key=lambda one: (one.priority, one.id),
        )

        # Taken either way. A withdrawal is a withdrawal: an item every path
        # turned away has been dealt with, and leaving it in would mean a
        # repository that fills up with things nothing will ever accept.
        session.delete(row)
        if not feeds:
            held_back += 1
            continue

        place_locally(session, video, channel, result, {}, {}, feeds)
        sent += 1

    session.flush()
    result.withdrawn += sent
    if say is not None:
        said = f"took {sent} from the {name} repository"
        if held_back:
            said += f"; {held_back} filtered out on the way"
        if most > 0:
            said += f", leaving {waiting_in(session, name, owner)}"
        say.write(said, about=node.title)
    return sent


def withdraw_now(
    session: Session, boxes: Collection[int], owner: OwnerId = None
) -> str:
    """Pull from these Withdraw boxes at once, and say what came out.

    For a trigger somebody pressed that is wired to nothing but repositories.
    Pulling touches no network and spends no quota, so there is nothing worth
    starting a thread for — the answer is ready by the time the button lets
    go.
    """
    result = SyncResult()
    wanted = set(boxes)
    for node in nodes_of_kind(session, "withdraw", owner):
        if node.id not in wanted:
            continue
        withdraw(session, node, result, owner)
        node.last_fired_at = utcnow()
    session.flush()

    if result.withdrawn == 0:
        return "Nothing came through."
    return f"Took {result.withdrawn} out and sent {'it' if result.withdrawn == 1 else 'them'} on."


def nodes_of_kind(
    session: Session, kind: str, owner: OwnerId = None
) -> list[GraphNode]:
    """Every box of one kind on this account's canvas."""
    return [node for node in graph.nodes(session, owner) if node.kind == kind]


def withdraw_what_is_due(
    session: Session,
    result: SyncResult,
    owner: OwnerId = None,
    *,
    pen: runlog.Pen | None = None,
    only: frozenset[int] | None = None,
) -> None:
    """Pull from every repository whose turn it has come round.

    `only` is the boxes one trigger was set off by hand for; without it,
    whichever boxes their own triggers say are due.
    """
    due = graph.due_withdrawals(session, owner)
    if only is not None:
        due = [node for node in due if node.id in only] if due else []
        # Pressed by hand, so its turn is now whatever its trigger would say.
        wanted = {node.id for node in due}
        for node in graph.nodes(session, owner):
            if node.id in only and node.kind == "withdraw" and node.id not in wanted:
                due.append(node)
    if not due:
        return

    for node in due:
        withdraw(session, node, result, owner, say=pen)
        node.last_fired_at = utcnow()
    session.flush()
