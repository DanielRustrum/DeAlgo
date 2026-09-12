"""The Configuration canvas: what is wired to what.

The graph is the truth about routing. A video leaves a source node, follows
wires, and lands in every feed node it can reach — narrowed on the way by any
filter node it passes through.

Two rules make it comprehensible:

* **A channel's own filters are the default.** They apply on every path out of
  that channel, exactly as they did before there was a graph.
* **A filter node overrides, it does not replace.** Anything it leaves unset
  stays whatever the channel said. So a channel can take Shorts everywhere
  except down one particular wire, without its settings being duplicated.

Existing setups are turned into a graph the first time one is asked for, so
nobody has to build theirs again.

Wires have one home each, which is what keeps the canvas and the rest of the
app from disagreeing:

* **Source to feed** is the link that already existed — a row in
  ``channel_playlist``. Drawing one on the canvas writes that, so a channel's
  own page shows it too.
* **Anything touching a filter node** is a ``GraphEdge``, because there was
  nowhere else for it to live.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from typing import Any

from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..models import Channel, GraphEdge, GraphNode, Playlist, Settings, Video
from .scope import OwnerId, owned

log = logging.getLogger(__name__)

KINDS = ("trigger", "source", "filter", "feed")
TRIGGER_KINDS = ("schedule", "pulse")

# Which wires make sense. Triggers feed channels, sources start paths, feeds
# end them, filters sit in between — and nothing runs backwards.
ALLOWED: dict[str, tuple[str, ...]] = {
    "trigger": ("source",),
    "source": ("filter", "feed"),
    "filter": ("filter", "feed"),
    "feed": (),
}

# Where a newly laid-out graph puts things: sources on the left, feeds on the
# right, filters between them. Triggers are placed beside the channel they are
# added next to rather than in a column, so they fit a canvas already laid out.
COLUMN_X = {"trigger": 60, "source": 60, "filter": 420, "feed": 780}
ROW_HEIGHT = 130

# What a trigger means if it is wired up without anything being chosen.
DEFAULT_EVERY_MINUTES = 60
DEFAULT_CRON = "0 9 * * *"  # every day at 09:00 UTC

# Where the trigger column goes, and how much clear space a channel box needs
# to its left for one to fit beside it.
TRIGGER_COLUMN = 40
TRIGGER_GAP = 260


def _aware(when: dt.datetime) -> dt.datetime:
    """Stored instants are naive UTC; APScheduler wants them to say so."""
    return when if when.tzinfo is not None else when.replace(tzinfo=dt.timezone.utc)


class GraphError(RuntimeError):
    """Something the person drawing it should be told."""


@dataclass
class Route:
    """One path from a channel to a feed, and what narrows it."""

    channel: Channel
    playlist: Playlist
    filters: list[GraphNode] = field(default_factory=list)

    def effective(self) -> dict[str, Any]:
        """The channel's filters with each filter node laid over the top.

        Later nodes win, so a path can narrow twice and the last word is the
        one nearest the feed.
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
            settings.update(node.overrides)
        return settings


# -- reading ---------------------------------------------------------------


def nodes(session: Session, owner: OwnerId = None) -> list[GraphNode]:
    return list(
        session.scalars(
            owned(select(GraphNode), GraphNode, owner)
            .options(selectinload(GraphNode.channel), selectinload(GraphNode.playlist))
            .order_by(GraphNode.id)
        )
    )


def edges(session: Session, owner: OwnerId = None) -> list[GraphEdge]:
    return list(
        session.scalars(owned(select(GraphEdge), GraphEdge, owner).order_by(GraphEdge.id))
    )


def load(session: Session, owner: OwnerId = None) -> tuple[list[GraphNode], list[GraphEdge]]:
    """The whole graph, built from the existing setup if it has none yet."""
    existing = nodes(session, owner)
    if not existing:
        existing = _lay_out_existing(session, owner)
    _add_missing(session, existing, owner)
    return nodes(session, owner), edges(session, owner)


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

    feed_node_for = {node.playlist_pk: node for node in all_nodes if node.kind == "feed"}

    found: list[Route] = []
    for node in all_nodes:
        if node.kind != "source" or node.channel is None:
            continue
        # The direct wires: the channel-to-feed links, unfiltered by anything
        # but the channel itself.
        for playlist in node.channel.playlists:
            if playlist.id in feed_node_for:
                found.append(Route(channel=node.channel, playlist=playlist))
        # And the paths that go through filter nodes.
        _walk(node, by_id, out, node.channel, [], set(), found)
    return found


def _walk(
    node: GraphNode,
    by_id: dict[int, GraphNode],
    out: dict[int, list[int]],
    channel: Channel,
    carried: list[GraphNode],
    seen: set[int],
    found: list[Route],
) -> None:
    """Depth-first from a source, collecting filters until a feed is reached.

    `seen` is per path, not global: two paths may legitimately pass through the
    same filter node, and only a loop is a problem.
    """
    if node.id in seen:
        return
    seen = seen | {node.id}

    for target_id in out.get(node.id, []):
        target = by_id.get(target_id)
        if target is None:
            continue
        if target.kind == "feed":
            if target.playlist is not None:
                found.append(Route(channel=channel, playlist=target.playlist, filters=list(carried)))
        elif target.kind == "filter":
            _walk(target, by_id, out, channel, carried + [target], seen, found)


@dataclass
class Step:
    """What one path did with one item, for drawing on the canvas."""

    playlist_pk: int
    node_ids: list[int]
    wire_ids: list[str]
    accepted: bool
    reason: str | None = None


def trace(session: Session, video: Video, settings: Settings, owner: OwnerId = None) -> list[Step]:
    """Follow one item through the graph and say what became of it.

    Answers the question a page of settings never can: *why is this not in my
    feed?* Every path is walked and judged, so the canvas can light the ones
    it travelled and name the box that stopped the rest. Nothing is written.
    """
    from . import sync as sync_service

    all_nodes, all_edges = load(session, owner)
    # The canvas names a wire by where it lives, so the trace has to look the
    # id up rather than make one from the two ends: an edge is "edge:7", and
    # only a channel-to-feed link is named after the boxes it joins.
    edge_between = {(edge.source_pk, edge.target_pk): f"edge:{edge.id}" for edge in all_edges}
    source_for = {node.channel_pk: node for node in all_nodes if node.kind == "source"}
    feed_for = {node.playlist_pk: node for node in all_nodes if node.kind == "feed"}

    steps: list[Step] = []
    for path in routes(session, owner):
        if path.channel.id != video.channel_pk:
            continue
        start = source_for.get(path.channel.id)
        end = feed_for.get(path.playlist.id)
        if start is None or end is None:
            continue

        walked = [start.id] + [node.id for node in path.filters] + [end.id]
        wires_used: list[str] = []
        for first, second in zip(walked, walked[1:]):
            edge_id = edge_between.get((first, second))
            if edge_id is not None:
                wires_used.append(edge_id)
            elif first == start.id and second == end.id:
                wires_used.append(f"link:{first}:{second}")

        decision = sync_service._decide(video, path, None, settings)
        steps.append(
            Step(
                playlist_pk=path.playlist.id,
                node_ids=walked,
                wire_ids=wires_used,
                accepted=decision.accept,
                reason=decision.reason,
            )
        )
    return steps


# -- what the triggers say --------------------------------------------------


def triggers_for(session: Session, owner: OwnerId = None) -> dict[int, list[GraphNode]]:
    """The trigger boxes wired into each channel, by channel primary key."""
    all_nodes, all_edges = load(session, owner)
    by_id = {node.id: node for node in all_nodes}

    wired: dict[int, list[GraphNode]] = {}
    for edge in all_edges:
        start, end = by_id.get(edge.source_pk), by_id.get(edge.target_pk)
        if start is None or end is None:
            continue
        if start.kind == "trigger" and end.kind == "source" and end.channel_pk is not None:
            wired.setdefault(end.channel_pk, []).append(start)
    return wired


# Cron counts weekdays from Sunday; APScheduler counts them from Monday, and
# reads its own names unambiguously. So the day-of-week field is expanded to
# names before it is handed over — otherwise "0 9 * * 1" would quietly mean
# Tuesday here and Monday everywhere else somebody has ever written cron.
CRON_DAYS = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")
CRON_DAY_NUMBERS = {name: number for number, name in enumerate(CRON_DAYS)}


def cron_trigger(expression: str) -> CronTrigger:
    """An APScheduler trigger that fires when cron says it would.

    APScheduler is already a dependency and already parses these, so there is
    no second dialect to keep in step — only the weekday numbering to correct.
    """
    fields = expression.split()
    if len(fields) != 5:
        raise GraphError(
            "A cron expression has five fields: minute, hour, day, month, weekday. "
            "“0 9 * * *” is every day at nine."
        )
    minute, hour, day, month, weekday = fields
    try:
        return CronTrigger(
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=_weekdays(weekday),
            timezone=dt.timezone.utc,
        )
    except (ValueError, KeyError) as exc:
        raise GraphError(f"“{expression}” is not a cron expression: {exc}") from exc


def _weekdays(field: str) -> str:
    """A cron weekday field as APScheduler day names.

    Expanded rather than shifted: a step like ``*/2`` counts from a different
    day in each dialect, and there are only seven values to write out.
    """
    if field == "*":
        return "*"

    wanted: set[int] = set()
    for part in field.split(","):
        step = 1
        if "/" in part:
            part, _, raw_step = part.partition("/")
            if not raw_step.isdigit() or int(raw_step) < 1:
                raise GraphError(f"“{field}” is not a weekday: {raw_step!r} is not a step.")
            step = int(raw_step)
        first, last = (part, part) if "-" not in part.strip("-") else part.split("-", 1)
        if part == "*":
            first, last = "0", "6"
        wanted.update(range(_weekday(first), _weekday(last) + 1, step))

    if not wanted:
        raise GraphError(f"“{field}” names no weekday.")
    return ",".join(CRON_DAYS[day] for day in sorted(wanted))


def _weekday(token: str) -> int:
    """One weekday, counted from Sunday as cron counts them."""
    wanted = token.strip().lower()
    if wanted.isdigit():
        number = int(wanted)
        if number > 7:
            raise GraphError(f"“{token}” is not a weekday: cron counts 0 to 7.")
        return 0 if number == 7 else number  # both 0 and 7 are Sunday
    if wanted[:3] in CRON_DAY_NUMBERS:
        return CRON_DAY_NUMBERS[wanted[:3]]
    raise GraphError(f"“{token}” is not a weekday.")


def check_cron(expression: str) -> str:
    """A cron expression, tidied — or a complaint about it in words."""
    wanted = " ".join(expression.split())
    if not wanted:
        raise GraphError("Give the schedule a cron expression, such as 0 9 * * *.")
    cron_trigger(wanted)
    return wanted


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
        if last_checked is None:
            # Never polled. Both kinds agree that is overdue.
            return True
        if self.kind == "pulse":
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
        due_at = trigger.get_next_fire_time(None, _aware(last_checked))
        return due_at is not None and due_at <= _aware(now)


def polling_plan(session: Session, owner: OwnerId = None) -> dict[int, list[When]]:
    """When each wired channel wants polling, by channel primary key.

    A channel absent from this has no trigger wired, and keeps following the
    account's own sync settings — which is what every setup did before
    triggers existed, and what an upgrade must not change.

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
        raise GraphError("That box is not a trigger.")

    all_nodes, all_edges = load(session, owner)
    by_id = {entry.id: entry for entry in all_nodes}
    reached: list[int] = []
    for edge in all_edges:
        if edge.source_pk != node.id:
            continue
        target = by_id.get(edge.target_pk)
        if target is not None and target.kind == "source" and target.channel_pk is not None:
            reached.append(target.channel_pk)
    return reached


# -- building it from what is already there --------------------------------


def _lay_out_existing(session: Session, owner: OwnerId) -> list[GraphNode]:
    """Turn the channels, feeds and links already set up into a graph.

    Runs once, the first time the canvas is opened. Every existing link
    becomes a direct wire, so what someone sees the first time is what they
    already had.
    """
    channels = list(
        session.scalars(
            owned(select(Channel), Channel, owner)
            .options(selectinload(Channel.playlists))
            .order_by(Channel.priority, Channel.id)
        )
    )
    playlists = list(
        session.scalars(
            owned(select(Playlist), Playlist, owner).order_by(Playlist.priority, Playlist.id)
        )
    )
    if not channels and not playlists:
        return []

    made: dict[tuple[str, int], GraphNode] = {}
    for row, channel in enumerate(channels):
        made[("source", channel.id)] = _place(session, owner, "source", row, channel_pk=channel.id)
    for row, playlist in enumerate(playlists):
        made[("feed", playlist.id)] = _place(session, owner, "feed", row, playlist_pk=playlist.id)
    session.flush()

    # No edges to write: a direct wire is the channel-to-feed link, which is
    # already there. Laying out the boxes is the whole job.
    log.info("laid out a graph from %d channel(s) and %d feed(s)", len(channels), len(playlists))
    return nodes(session, owner)


def _add_missing(session: Session, existing: list[GraphNode], owner: OwnerId) -> None:
    """A channel or feed added since the graph was drawn gets a box of its own.

    Unwired, and off to one side: appearing already connected to something
    would be a guess about what someone meant.
    """
    have_channels = {node.channel_pk for node in existing if node.kind == "source"}
    have_feeds = {node.playlist_pk for node in existing if node.kind == "feed"}

    rows = sum(1 for node in existing if node.kind == "source")
    for channel in session.scalars(owned(select(Channel), Channel, owner).order_by(Channel.id)):
        if channel.id not in have_channels:
            _place(session, owner, "source", rows, channel_pk=channel.id)
            rows += 1

    rows = sum(1 for node in existing if node.kind == "feed")
    for playlist in session.scalars(owned(select(Playlist), Playlist, owner).order_by(Playlist.id)):
        if playlist.id not in have_feeds:
            _place(session, owner, "feed", rows, playlist_pk=playlist.id)
            rows += 1
    session.flush()


def _place(
    session: Session,
    owner: OwnerId,
    kind: str,
    row: int,
    *,
    channel_pk: int | None = None,
    playlist_pk: int | None = None,
    label: str = "",
) -> GraphNode:
    node = GraphNode(
        owner_pk=owner,
        kind=kind,
        x=COLUMN_X[kind],
        y=40 + row * ROW_HEIGHT,
        channel_pk=channel_pk,
        playlist_pk=playlist_pk,
        label=label,
    )
    session.add(node)
    return node


# -- changing it -----------------------------------------------------------


def connect(
    session: Session, source: GraphNode, target: GraphNode, owner: OwnerId = None
) -> GraphEdge | None:
    """Wire one box to another, refusing what would not make sense.

    Returns the edge it made, or None for a source-to-feed wire — that one is
    a channel-to-feed link rather than an edge, so that the channel's own page
    and the canvas are looking at the same thing.
    """
    if source.id == target.id:
        raise GraphError("A box cannot feed itself.")
    if target.kind not in ALLOWED.get(source.kind, ()):
        raise GraphError(f"A {source.kind} cannot feed a {target.kind}.")

    if source.kind == "source" and target.kind == "feed":
        if source.channel is None or target.playlist is None:
            raise GraphError("That box no longer has anything behind it.")
        if target.playlist not in source.channel.playlists:
            source.channel.playlists.append(target.playlist)
            session.flush()
        return None

    if _reaches(session, target, source, owner):
        raise GraphError("That would make a loop, and nothing would ever come out of it.")

    existing = session.scalar(
        select(GraphEdge).where(
            GraphEdge.source_pk == source.id, GraphEdge.target_pk == target.id
        )
    )
    if existing is not None:
        return existing

    edge = GraphEdge(owner_pk=owner, source_pk=source.id, target_pk=target.id)
    session.add(edge)
    session.flush()
    return edge


def unlink(session: Session, source: GraphNode, target: GraphNode) -> bool:
    """Take out a source-to-feed wire, which is a link rather than an edge."""
    if source.channel is None or target.playlist is None:
        return False
    if target.playlist in source.channel.playlists:
        source.channel.playlists.remove(target.playlist)
        session.flush()
        return True
    return False


def wires(session: Session, owner: OwnerId = None) -> list[dict[str, Any]]:
    """Every wire, of both kinds, in the one shape the canvas draws from."""
    all_nodes, all_edges = load(session, owner)
    feed_node_for = {node.playlist_pk: node for node in all_nodes if node.kind == "feed"}

    drawn: list[dict[str, Any]] = []
    for node in all_nodes:
        if node.kind == "source" and node.channel is not None:
            for playlist in node.channel.playlists:
                target = feed_node_for.get(playlist.id)
                if target is not None:
                    drawn.append({"id": f"link:{node.id}:{target.id}", "from": node.id,
                                  "to": target.id, "kind": "link"})
    for edge in all_edges:
        drawn.append({"id": f"edge:{edge.id}", "from": edge.source_pk,
                      "to": edge.target_pk, "kind": "edge"})
    return drawn


def disconnect(session: Session, edge_pk: int, owner: OwnerId = None) -> bool:
    edge = session.scalar(owned(select(GraphEdge), GraphEdge, owner).where(GraphEdge.id == edge_pk))
    if edge is None:
        return False
    session.delete(edge)
    session.flush()
    return True


def _reaches(session: Session, start: GraphNode, goal: GraphNode, owner: OwnerId) -> bool:
    """Whether `goal` is already downstream of `start` — a loop in waiting."""
    out: dict[int, list[int]] = {}
    for edge in edges(session, owner):
        out.setdefault(edge.source_pk, []).append(edge.target_pk)

    seen: set[int] = set()
    stack = [start.id]
    while stack:
        current = stack.pop()
        if current == goal.id:
            return True
        if current in seen:
            continue
        seen.add(current)
        stack.extend(out.get(current, []))
    return False


def add_filter(session: Session, owner: OwnerId = None, *, label: str = "Filter",
               x: int = COLUMN_X["filter"], y: int = 40) -> GraphNode:
    node = GraphNode(owner_pk=owner, kind="filter", label=label or "Filter", x=x, y=y)
    session.add(node)
    session.flush()
    return node


def add_source(
    session: Session,
    owner: OwnerId = None,
    *,
    channel: Channel | None = None,
    x: int = 0,
    y: int = 0,
) -> GraphNode:
    """A box for a channel — which may not have been named yet.

    A channel box is dropped on the canvas first and told which channel it is
    afterwards, by typing an @handle into it. Until then it stands for nothing,
    and everything that walks the graph skips it: an empty box cannot route
    anything, and saying so is better than refusing to make one.
    """
    node = GraphNode(
        owner_pk=owner,
        kind="source",
        channel_pk=channel.id if channel is not None else None,
        x=x,
        y=y,
    )
    session.add(node)
    session.flush()
    return node


def attach_channel(
    session: Session, node: GraphNode, channel: Channel, owner: OwnerId = None
) -> GraphNode:
    """Say which channel an empty channel box stands for."""
    if node.kind != "source":
        raise GraphError("Only a channel box stands for a channel.")
    node.channel_pk = channel.id
    node.label = ""  # the channel's own name takes over from the placeholder
    session.flush()
    return node


def add_feed(
    session: Session, playlist: Playlist, owner: OwnerId = None, *, x: int = 0, y: int = 0
) -> GraphNode:
    """A box for a feed somebody just made."""
    node = GraphNode(owner_pk=owner, kind="feed", playlist_pk=playlist.id, x=x, y=y)
    session.add(node)
    session.flush()
    return node


def rename(session: Session, node_pk: int, name: str, owner: OwnerId = None) -> GraphNode:
    """Rename a box, and the thing behind it.

    A box that stands for a channel or a feed writes the new name through, so
    the rest of the app agrees with the canvas. The sync engine only fills in
    a channel's title when it is blank, so a rename is not undone by the next
    poll.
    """
    node = session.scalar(owned(select(GraphNode), GraphNode, owner).where(GraphNode.id == node_pk))
    if node is None:
        raise GraphError("That box is not here.")

    wanted = " ".join(name.split())
    node.label = wanted
    if wanted:
        if node.kind == "source" and node.channel is not None:
            node.channel.title = wanted
        elif node.kind == "feed" and node.playlist is not None:
            node.playlist.title = wanted
    session.flush()
    return node


def add_trigger(
    session: Session,
    owner: OwnerId = None,
    *,
    trigger_kind: str = "pulse",
    label: str = "",
    every_minutes: int | None = None,
    cron: str | None = None,
    x: int | None = None,
    y: int | None = None,
) -> GraphNode:
    """Put a trigger box on the canvas, to the left of the channels.

    A pulse repeats on a gap; a schedule comes round at a time of day. Only
    the field that belongs to the kind is filled in, so a box changed from one
    to the other cannot carry a stale answer from the other shape.

    Its column is worked out from where the channels actually are rather than
    fixed, because a graph laid out before triggers existed has its channels
    hard against the left edge and a fixed column would land on top of them.
    """
    if trigger_kind not in TRIGGER_KINDS:
        raise GraphError(f"A trigger is a pulse or a schedule, not a {trigger_kind}.")

    # load() rather than nodes(): a trigger may be the first thing anyone adds,
    # and it is placed relative to the channel column, which has to exist.
    existing, _ = load(session, owner)
    if x is None or y is None:
        spot = _room_for_a_trigger(session, existing)
        x = spot[0] if x is None else x
        y = spot[1] if y is None else y

    node = GraphNode(
        owner_pk=owner,
        kind="trigger",
        trigger_kind=trigger_kind,
        label=label,
        every_minutes=(
            (every_minutes or DEFAULT_EVERY_MINUTES) if trigger_kind == "pulse" else None
        ),
        cron=(check_cron(cron or DEFAULT_CRON) if trigger_kind == "schedule" else None),
        x=max(0, x),
        y=max(0, y),
    )
    session.add(node)
    session.flush()
    return node


def _room_for_a_trigger(session: Session, existing: list[GraphNode]) -> tuple[int, int]:
    """A free spot in the trigger column: left of the channels, below the last.

    A graph laid out before triggers existed has its channels hard against the
    left edge, with no column to put one in. Rather than drop a box on top of
    them, everything slides right to make room — once, when the first trigger
    is added. Relative positions are kept, so the drawing is the same drawing,
    further along.
    """
    taken = [node for node in existing if node.kind == "trigger"]
    sources = [node for node in existing if node.kind == "source"]
    left = min((node.x for node in sources), default=COLUMN_X["source"])

    if not taken and left < TRIGGER_COLUMN + TRIGGER_GAP:
        shift = TRIGGER_COLUMN + TRIGGER_GAP - left
        for node in existing:
            node.x += shift
        session.flush()
        log.info("moved the canvas %dpx right to make room for a trigger column", shift)
        return TRIGGER_COLUMN, 40

    column = TRIGGER_COLUMN if not taken else min(node.x for node in taken)
    return column, 40 + len(taken) * ROW_HEIGHT


def move(session: Session, node_pk: int, x: int, y: int, owner: OwnerId = None) -> bool:
    node = session.scalar(owned(select(GraphNode), GraphNode, owner).where(GraphNode.id == node_pk))
    if node is None:
        return False
    node.x, node.y = int(x), int(y)
    session.flush()
    return True


def remove(session: Session, node_pk: int, owner: OwnerId = None) -> bool:
    """Take a box off the canvas, and the thing behind it with it.

    The canvas is the whole of the configuration now, so this is the only
    place a channel or a feed can be removed — there is no list to do it from
    any more. What that costs is spelled out where it is pressed, not here.
    """
    node = session.scalar(owned(select(GraphNode), GraphNode, owner).where(GraphNode.id == node_pk))
    if node is None:
        return False

    channel, playlist = node.channel, node.playlist
    session.delete(node)
    session.flush()
    if node.kind == "source" and channel is not None:
        session.delete(channel)
    elif node.kind == "feed" and playlist is not None:
        session.delete(playlist)
    session.flush()
    return True
