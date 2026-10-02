"""Every path from a source to a feed or a repository, and what narrows each."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from ...models import (
    Channel,
    GraphNode,
    Playlist,
)
from ..scope import OwnerId
from .canvas import load
from .conditions import RULE, filter_rules
from .names import store_name
from .pieces import pieces_under
from .reading import channels_of
from .vocabulary import MIDDLE, SLOTTED, STAMPS


@dataclass
class Route:
    """One path from a channel to a feed, and what narrows it."""

    channel: Channel
    #: Where it ends, when it ends at a feed. None when it ends at a
    #: repository instead — a path has one end or the other, never both.
    playlist: Playlist | None = None
    #: The repository it ends in, when it ends in one. "" when it does not.
    #: Lowercased, because that is how the rows are filed.
    store: str = ""
    filters: list[GraphNode] = field(default_factory=list)
    #: Sort boxes on this path, in the order they are passed through.
    sorts: list[GraphNode] = field(default_factory=list)
    #: The plugin conditions on this path: the pieces slotted under the
    #: Filter boxes it passes whose rule is somebody's Lua. Kept apart from
    #: `filters` because a filter lays settings over the channel's and these
    #: ask a question per item — the two cannot be merged into one dictionary.
    checks: list[GraphNode] = field(default_factory=list)
    #: What is slotted under each box on the canvas, by box id. Carried on
    #: the path because what a Filter narrows by and what a Sort orders by
    #: are now pieces, and a path that could not see them would be a path
    #: that filters nothing.
    slots: dict[int, list[GraphNode]] = field(default_factory=dict)
    #: Boxes that mark what passes rather than narrowing it — Decay, Expire,
    #: Tag. Kept apart from the filters because they turn nothing away: they
    #: are read after an item has been let through, not while deciding.
    stamps: list[GraphNode] = field(default_factory=list)
    #: Every box between the start and the end, in the order they are
    #: passed. The other lists are what each kind is *for*; this is what an
    #: item actually walks through, which is the only way to say which boxes
    #: it reached before one of them turned it away.
    walked: list[GraphNode] = field(default_factory=list)
    #: The node this path started at. Carried rather than looked up: a
    #: channel may be drawn twice, so there is no answering "which box is
    #: this channel" after the fact.
    source: GraphNode | None = None
    #: The box it ends at, feed or deposit. For marking the run on the canvas.
    finish: GraphNode | None = None

    @property
    def deposits(self) -> bool:
        """Whether this path ends in a repository rather than a feed."""
        return self.playlist is None and self.store != ""

    @property
    def order(self) -> GraphNode | None:
        """What decides this path's order, if anything does.

        The ordering piece under the last sort box: the nearest the feed has
        the final say, because that is the one describing what arrives. A
        sort box with nothing slotted under it orders nothing, the same way a
        Filter with no conditions narrows nothing.

        Either the app's own Order piece or a plugin's ordering. Both answer
        the same question — where does this item go in the batch — so which
        of the two it is, is the ordering's business rather than the path's.
        """
        for box in reversed(self.sorts):
            for piece in self.slots.get(box.id, []):
                if piece.enabled and piece.kind in ("order", RULE):
                    return piece
        return None

    def effective(self) -> dict[str, Any]:
        """The channel's filters with every condition on the path over them.

        A filter box narrows by whatever is slotted under it. Later boxes
        win, so a path can narrow twice and the last word is the one nearest
        the feed.
        """
        settings: dict[str, Any] = {
            "skip_videos": self.channel.skip_videos,
            "skip_shorts": self.channel.skip_shorts,
            "skip_live": self.channel.skip_live,
            "skip_posts": self.channel.skip_posts,
            "title_include": self.channel.title_include,
            "title_exclude": self.channel.title_exclude,
            "min_duration_sec": self.channel.min_duration_sec,
            "max_duration_sec": self.channel.max_duration_sec,
            "max_per_run": self.channel.max_per_run,
        }
        for node in self.filters:
            settings.update(filter_rules(self.slots.get(node.id, [])))
        return settings


def routes(session: Session, owner: OwnerId = None) -> list[Route]:
    """Every channel-to-feed path in the graph, with what narrows each.

    This is what the sync engine asks instead of reading a channel's targets:
    the same channel can reach two feeds down two paths that filter
    differently, which a list of targets cannot express.
    """
    all_nodes, all_edges = load(session, owner)
    by_id = {node.id: node for node in all_nodes}
    out: dict[int, list[int]] = {}
    for edge in all_edges:
        out.setdefault(edge.source_pk, []).append(edge.target_pk)

    found: list[Route] = []
    for node in all_nodes:
        # A box that is switched off is out of the graph. Said of the box and
        # not only of the channel, because a channel may be drawn twice and
        # switching one box off must not take the other with it.
        if node.kind != "source" or not node.enabled:
            continue
        for channel in channels_of(session, node, owner):
            # Every path out of this box, whether it reaches a feed straight
            # away or goes through filters on the way.
            _walk(node, by_id, out, channel, [], set(), found, source=node)
    return _once_each(slot_in(found, all_nodes))


def slot_in(found: list[Route], all_nodes: list[GraphNode]) -> list[Route]:
    """Hand every path what is slotted under the boxes it passes.

    Worked out once for the whole canvas rather than per path: a filter box
    on nine paths has one chain of conditions under it, and reading it nine
    times would be nine walks of the same chain.

    The plugin conditions a path passes are gathered here as well: they are
    pieces under the Filter boxes it already carries, and they are kept apart
    from the rest because a condition answered by somebody's Lua is asked per
    item rather than laid over the channel's settings.
    """
    slots = {
        node.id: pieces_under(all_nodes, node.id)
        for node in all_nodes
        if node.kind in SLOTTED
    }
    for path in found:
        path.slots = slots
        # Only the ones under a Filter: a plugin's ordering is under a Sort,
        # and is read as the path's order rather than asked of each item.
        path.checks = [
            piece
            for box in path.filters
            for piece in slots.get(box.id, [])
            if piece.kind == RULE and piece.enabled
        ]
    return found


def _once_each(found: list[Route]) -> list[Route]:
    """Drop paths that are the same path twice.

    A channel may have two boxes on the canvas, wired down two routes that
    filter differently — which is the point of being allowed a second one.
    Two boxes wired the same way are the same path said twice, and the same
    video must not be weighed twice for one feed.
    """
    seen: set[
        tuple[
            int, int, str,
            tuple[int, ...], tuple[int, ...], tuple[int, ...], tuple[int, ...],
        ]
    ] = set()
    kept: list[Route] = []
    for path in found:
        signature = (
            path.channel.id,
            path.playlist.id if path.playlist is not None else 0,
            path.store,
            tuple(node.id for node in path.filters),
            tuple(node.id for node in path.sorts),
            # Two paths that differ only by which plugin conditions they meet
            # are two different paths: each asks a different question.
            tuple(node.id for node in path.checks),
            # Two paths that mark an item differently are two paths: what
            # they leave on it is as much a difference as what they refuse.
            tuple(node.id for node in path.stamps),
        )
        if signature in seen:
            continue
        seen.add(signature)
        kept.append(path)
    return kept


def _walk(
    node: GraphNode,
    by_id: dict[int, GraphNode],
    out: dict[int, list[int]],
    channel: Channel,
    carried: list[GraphNode],
    seen: set[int],
    found: list[Route],
    ordered: list[GraphNode] | None = None,
    source: GraphNode | None = None,
    marked: list[GraphNode] | None = None,
    passed: list[GraphNode] | None = None,
) -> None:
    """Depth-first from a start, collecting what it passes until an end.

    An end is a feed or a Deposit box: one sends what arrives onward, the
    other holds it until somebody pulls. Everything in between narrows or
    orders what passes and is collected on the way.

    `seen` is per path, not global: two paths may legitimately pass through the
    same box, and only a loop is a problem.
    """
    if node.id in seen:
        return
    seen = seen | {node.id}
    ordered = ordered or []
    marked = marked or []
    passed = passed or []

    for target_id in out.get(node.id, []):
        target = by_id.get(target_id)
        if target is None:
            continue
        if target.kind == "feed":
            if target.playlist is not None and target.enabled:
                found.append(
                    Route(
                        channel=channel,
                        playlist=target.playlist,
                        filters=list(carried),
                        sorts=list(ordered),
                        stamps=list(marked),
                        walked=list(passed),
                        source=source,
                        finish=target,
                    )
                )
        elif target.kind == "deposit":
            # A box with no name on it holds nothing: two Deposit boxes only
            # mean the same repository when they carry the same name, and an
            # unnamed one names none.
            named = store_name(target.repository)
            if named and target.enabled:
                found.append(
                    Route(
                        channel=channel,
                        store=named,
                        filters=list(carried),
                        sorts=list(ordered),
                        stamps=list(marked),
                        walked=list(passed),
                        source=source,
                        finish=target,
                    )
                )
        elif target.kind in MIDDLE and target.enabled:
            # A box that is switched off is not a box that passes everything:
            # nothing goes through it at all, so the path ends.
            _walk(
                target,
                by_id,
                out,
                channel,
                carried + [target] if target.kind == "filter" else carried,
                seen,
                found,
                ordered + [target] if target.kind == "sort" else ordered,
                source,
                marked + [target] if target.kind in STAMPS else marked,
                passed + [target],
            )


def paths_from(
    session: Session, node: GraphNode, channel: Channel, owner: OwnerId = None
) -> list[Route]:
    """Every path out of one box, for an item that came from `channel`.

    Used for a Withdraw box, which starts a path the way a source does — but
    what comes out of it has a channel of its own already, so the channel is
    given rather than read off the box.
    """
    all_nodes, all_edges = load(session, owner)
    by_id = {one.id: one for one in all_nodes}
    out: dict[int, list[int]] = {}
    for edge in all_edges:
        out.setdefault(edge.source_pk, []).append(edge.target_pk)

    found: list[Route] = []
    _walk(node, by_id, out, channel, [], set(), found, source=node)
    return _once_each(slot_in(found, all_nodes))
