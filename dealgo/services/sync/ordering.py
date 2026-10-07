"""Putting a batch in the order the Sort boxes ask for."""

from __future__ import annotations

from collections.abc import Sequence

from ...models import (
    GraphNode,
    Video,
)
from ...plugins import registry
from ...plugins.capabilities import acting_for
from sqlalchemy.orm import object_session

from .. import algorithm, graph, tagging
from .deciding import as_item, plugin_settings


def ordering_value(video: Video, piece: GraphNode, path: "graph.Route | None" = None) -> float:
    """Where this item goes in a batch, by whatever is slotted under the Sort.

    Two kinds of ordering answer the same question. The app's own Order piece
    names one of a handful of things it knows how to measure; a plugin's
    ordering works its own number out from the item. Bigger comes first,
    before the direction is applied, for both.

    A plugin that could not say puts the item at nothing in particular, which
    leaves it in the order it arrived in among the others it could not
    place — rather than at an invented position that would look deliberate.
    """
    if piece.kind == "aggregation":
        # What the algorithm predicts, most first; under the threshold, after
        # everything at or over it. Nothing to say: everything level, so the
        # batch keeps the order it came in.
        session = object_session(video)
        predicted = algorithm.score(
            session, video, piece,
            path.playlist.id if path is not None and path.playlist is not None else None,
            tagging.tags_for(session, video, path.stamps) if path is not None else (),
        ) if session is not None else None
        if predicted is None:
            return 0.0
        edge = int(algorithm.settings(piece)["threshold"]) / 100.0
        return predicted if predicted >= edge else predicted - 1.0
    if piece.kind != graph.RULE:
        return _sort_value(video, piece.sort_by or graph.DEFAULT_SORT_BY)
    owner = video.channel.owner_pk if video.channel is not None else None
    with acting_for(owner):
        said = registry.current().ranks(
            piece.plugin_ref or "", as_item(video), plugin_settings(piece)
        )
    return 0.0 if said is None else said


def reorder(pending: list[Video], routes_for: dict[int, list["graph.Route"]]) -> None:
    """Put the batch in the order the sort boxes asked for.

    Insertion order is the order things appear in a feed, and this list is
    what the insert loop walks — so ordering it here is what a sort box does.

    One list, so one order. A video reached by two paths that sort
    differently is ordered by the first of them, which is the one nearest the
    top of the graph; two feeds that genuinely disagree need two batches, and
    that is a larger change than this earns. Videos with no sort box on their
    path keep the order they came in with, which is oldest first.
    """
    keyed = [
        (video, _sorter(video, routes_for.get(video.channel_pk or 0, [])))
        for video in pending
    ]
    if not any(key is not None for _, key in keyed):
        return

    # Sorted once, with the original position as the tie-break, so anything
    # the sort boxes say nothing about stays where it was.
    order = {video.id: position for position, video in enumerate(pending)}
    pending.sort(
        key=lambda video: (
            _sorter(video, routes_for.get(video.channel_pk or 0, [])) or (0, 0),
            order[video.id],
        )
    )


def _sorter(video: Video, paths: Sequence["graph.Route"]) -> tuple[int, float] | None:
    """Where this video belongs in the batch, as the first sort box sees it.

    The leading number is the box's own position, so videos under different
    sort boxes do not interleave: each box's batch stays together, in its own
    order, rather than being shuffled through another's.
    """
    for path in paths:
        box = path.order
        if box is None:
            continue
        rank = ordering_value(video, box, path)
        return (box.id, -rank if (box.sort_dir or "desc") == "desc" else rank)
    return None


def _sort_value(video: Video, key: str) -> float:
    """The number a batch is ordered by. Unknown counts sort last either way.

    A video whose details were never fetched has no view count, and guessing
    zero would put it top of an ascending sort — which reads as "this is the
    least watched" rather than "nobody asked YouTube yet".
    """
    if key == "duration":
        return float(video.duration_sec or 0)
    if key == "views":
        return float(video.view_count or 0)
    if key == "likes":
        return float(video.like_count or 0)
    if key == "title":
        # Alphabetical, as a number: the first few characters are enough to
        # order a batch, and it keeps every key the same shape.
        return -sum(ord(letter) / (256.0 ** index) for index, letter in enumerate((video.title or "").lower()[:8]))
    published = video.published_at
    return published.timestamp() if published is not None else 0.0
