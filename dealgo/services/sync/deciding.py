"""Whether an item belongs in a feed, by the rules on the path between them."""

from __future__ import annotations

import json

from ...models import (
    GraphNode,
    Settings,
    Video,
    utcnow,
)
from ...plugins import registry
from ...plugins.capabilities import acting_for
from ...plugins.publisher import VideoDetails
from .. import filters, graph
from .progress import note_filtered
from .reasons import WRONG_KIND_OF_FEED
from .result import SyncResult


def plugin_refusal(
    video: Video, path: "graph.Route", detail: "VideoDetails | None" = None
) -> filters.Decision | None:
    """Ask each plugin condition on this path, and stop at the first no.

    The item is handed over as plain values, not as a database row: a plugin
    is given what it needs to judge and nothing it could write through.
    """
    if not path.checks:
        return None


    found = registry.current()
    item = as_item(video, detail)
    # Whose work this is, for the whole of the asking. A plugin reaching the
    # site through `dealgo` sees this account and no other, and outside a
    # block like this it sees nobody at all.
    with acting_for(path.channel.owner_pk):
        for node in path.checks:
            ref = node.plugin_ref or ""
            box = found.augmentation(ref)
            if box is None:
                # Its plugin is switched off or gone. The box stays on the
                # canvas and stops narrowing anything, which is the same
                # thing a filter with no rules does.
                continue
            if not found.keeps(ref, item, plugin_settings(node)):
                return filters.Decision(False, f"held by {node.title}")
    return None


def as_item(video: Video, detail: VideoDetails | None = None) -> dict[str, object]:
    """One item as a plugin is handed it: plain values, nothing to write to.

    The same shape whether it is being judged or being put in order, so a
    plugin only ever learns one vocabulary for what an item is.
    """
    return {
        "title": video.title or "",
        "kind": video.kind,
        "words": video.body or "",
        "link": video.link or "",
        "duration": video.duration_sec or 0,
        "views": video.view_count or 0,
        "likes": video.like_count or 0,
        # What its plugin said about it when it was read, if anything.
        "hint": video.hint or "",
        # Whether it is a broadcast, live or still to come. Only known while
        # the details are in hand — a plugin cannot go and look it up, and a
        # batch is put in order long after they have been let go of.
        "live": (detail.live_state or "") if detail else "",
        "source": video.channel.source_kind if video.channel else "",
    }


def plugin_settings(node: GraphNode) -> dict[str, str]:
    """What a plugin augmentation's fields were set to, as plain strings."""
    if not node.plugin_settings:
        return {}
    try:
        loaded = json.loads(node.plugin_settings)
    except (TypeError, ValueError):
        return {}
    if not isinstance(loaded, dict):
        return {}
    return {str(key): str(value) for key, value in loaded.items()}


def decide(
    video: Video, path: "graph.Route", detail: VideoDetails | None, settings: Settings
) -> filters.Decision:
    """Whether this video belongs in this feed, by this path's rules.

    The channel's own filters with every filter node on the path laid over
    them — which is what makes a filter node an override rather than a second
    set of settings to keep in step.
    """
    rules = path.effective()

    # A tag, which is the one rule that can be true of an item because of
    # where it has been rather than because of what it is.
    #
    # What this path would put on it counts as well as what it already
    # carries, or a Tag box and a Filter box on the same path could never
    # work together: the marks are left after every path has decided, so on
    # the run that brought the item in the tag would not be there yet.
    # Order within a path is already flattened for the filters themselves,
    # so flattening it here is the same bargain.
    wanted = graph.tag_name(str(rules.get("tagged") or ""))
    if wanted:
        carried = set(video.tag_list) | set(graph.stamped_tags(path.stamps))
        if wanted not in carried:
            return filters.Decision(False, f"not tagged “{wanted}”")

    # A published playlist holds only what its service does, so an item it
    # cannot hold can only go into a feed that lives inside De-Algo — said
    # here, once, rather than failing at the insert with whatever the
    # service makes of it.
    if not video.publishable and path.playlist is not None and path.playlist.is_published:
        return filters.Decision(False, WRONG_KIND_OF_FEED)

    # Plugin boxes, before the rules that cost anything to work out. Each is
    # somebody's Lua answering one question about one item, and a box that
    # says no ends the path there.
    refused = plugin_refusal(video, path, detail)
    if refused is not None:
        return refused

    left_out = kind_left_out(video, detail, rules["left_out"])

    if video.kind == "link":
        # Nothing to measure but its words: a feed entry has no duration.
        return filters.evaluate_post(
            text=f"{video.title} {video.body or ''}",
            left_out=left_out,
            title_include=rules["title_include"],
            title_exclude=rules["title_exclude"],
        )

    if video.is_post:
        return filters.evaluate_post(
            text=video.body or video.title,
            left_out=left_out,
            title_include=rules["title_include"],
            title_exclude=rules["title_exclude"],
        )
    return filters.evaluate(
        title=video.title,
        duration_sec=video.duration_sec,
        left_out=left_out,
        title_include=rules["title_include"],
        title_exclude=rules["title_exclude"],
        min_duration_sec=rules["min_duration_sec"],
        max_duration_sec=rules["max_duration_sec"],
    )


def kind_left_out(
    video: Video, detail: VideoDetails | None, left_out: set[str]
) -> str | None:
    """The label of the kind of content this item is, if its source leaves it out.

    Which kind it is, its source's plugin says (`classify`), for the account
    whose item it is. A source with no kinds, or an item its plugin cannot
    place, leaves nothing out.
    """
    channel = video.channel
    if channel is None or not left_out:
        return None
    from ...plugins import registry

    found = registry.current()
    kind = found.classify(channel.source_kind, as_item(video, detail), channel.owner_pk)
    if kind is None or kind not in left_out:
        return None
    label = next((one.label for one in found.takes(channel.source_kind) if one.name == kind), kind)
    return label


def attribute(
    video: Video, path: "graph.Route", detail: VideoDetails | None, settings: Settings
) -> None:
    """Say which box on this path let the video through, and which stopped it.

    The decision for the path as a whole says yes or no; it does not say where
    the no happened. This walks the path a box at a time and asks the same
    question of each prefix, so the canvas can point at the box that is
    actually holding things up rather than at the path in general.
    """
    for index, node in enumerate(path.filters):
        so_far = graph.Route(
            channel=path.channel, playlist=path.playlist,
            filters=path.filters[: index + 1], slots=path.slots,
        )
        if decide(video, so_far, detail, settings).accept:
            note_filtered(node.id, passed=True)
        else:
            note_filtered(node.id, passed=False)
            return  # it got no further, so the boxes after this one never saw it


def reject(video: Video, result: SyncResult, reason: str) -> None:
    """Hold an item back with a reason, and count it."""
    video.status = "skipped"
    video.reason = reason
    video.processed_at = utcnow()
    result.skipped += 1
