"""What a Filter box is doing: what it let through and what it held, and why."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import (
    GraphNode,
    Playlist,
    Settings,
    Video,
)
from ..scope import OwnerId, owned
from .canvas import load
from .errors import GraphError
from .reading import channels_of
from .routes import Route, slot_in


@dataclass
class Judged:
    """One item, and what this filter box does with it."""

    video_pk: int
    title: str
    kind: str
    passed: bool
    reason: str | None = None
    #: What the boxes on this path would leave on it, in the words they use
    #: on the canvas. A trial says what would happen, and these are as much
    #: of what would happen as which feed it lands in.
    marks: list[str] = field(default_factory=list)


def filter_report(
    session: Session,
    node_pk: int,
    settings: Settings,
    owner: OwnerId = None,
    limit: int = 60,
) -> tuple[list[Judged], list[Judged]]:
    """What gets through this filter box, and what it holds back.

    Judged rather than remembered: the answer is worked out from the rules as
    they stand now, over everything the channels upstream have ever brought
    in. A log of past decisions would show what an older version of the rules
    did, which is the opposite of useful when the question being asked is
    "why is this one not getting through?".

    Everything reaching the box counts once, even when two paths lead to it.
    """
    from .. import sync as sync_service

    node = session.scalar(owned(select(GraphNode), GraphNode, owner).where(GraphNode.id == node_pk))
    if node is None or node.kind != "filter":
        raise GraphError("Only a filter node holds anything back.")

    through: list[Judged] = []
    held: list[Judged] = []
    seen: set[int] = set()
    switched_off = not node.enabled

    for path in _paths_into(session, node, owner):
        videos = session.scalars(
            owned(select(Video), Video, owner)
            .where(Video.channel_pk == path.channel.id)
            .order_by(Video.id.desc())
            .limit(limit)
        )
        for video in videos:
            if video.id in seen:
                continue
            seen.add(video.id)
            decision = sync_service._decide(video, path, None, settings)
            passed = decision.accept and not switched_off
            judged = Judged(
                video_pk=video.id,
                title=video.title or video.video_id,
                kind=video.kind,
                passed=passed,
                reason="this filter is switched off" if switched_off else decision.reason,
            )
            (through if passed else held).append(judged)

    return through[:limit], held[:limit]


def _paths_into(session: Session, node: GraphNode, owner: OwnerId) -> list[Route]:
    """Every way into this box, as a route ending at it.

    A filter judges by the channel's own rules with each earlier filter laid
    over the top, so the answer depends on how the item got here — which is
    why this is a list and not one set of rules.
    """
    all_nodes, all_edges = load(session, owner)
    by_id = {entry.id: entry for entry in all_nodes}
    into: dict[int, list[int]] = {}
    for edge in all_edges:
        into.setdefault(edge.target_pk, []).append(edge.source_pk)

    found: list[Route] = []

    def walk(at: GraphNode, carried: list[GraphNode], seen: set[int]) -> None:
        if at.id in seen:
            return
        seen = seen | {at.id}
        for source_id in into.get(at.id, []):
            earlier = by_id.get(source_id)
            if earlier is None:
                continue
            if earlier.kind == "source":
                # A route needs a feed to name; nothing here asks for one, and
                # the placeholder is never read.
                for channel in channels_of(session, earlier, owner):
                    found.append(
                        Route(channel=channel, playlist=Playlist(), filters=list(carried))
                    )
            elif earlier.kind == "filter" and earlier.enabled:
                walk(earlier, [earlier] + carried, seen)

    walk(node, [node], set())
    return slot_in(found, all_nodes)
