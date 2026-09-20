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

Every wire is a ``GraphEdge``, and an edge belongs to the box it was drawn
from. A source's used to be stored against its *channel* instead, which meant
two boxes for one channel could not be told apart: wiring either drew a wire
from both, and unwiring either unwired both. A second box is a second box.

``channel.playlists`` — what the feed page, the backup and the sync engine
read — is a view of those wires, worked out again whenever they change. One
writer, so the two cannot disagree.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Collection
from dataclasses import dataclass, field
from typing import Any

from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..models import (
    Channel, GraphEdge, GraphNode, Playlist, Settings, Video, to_naive_utc, utcnow,
)
from . import ordering
from .scope import OwnerId, owned

log = logging.getLogger(__name__)

KINDS = (
    "trigger", "source", "filter", "sort", "feed", "group", "plugin",
    # A repository, from its two ends. A Deposit ends a path the way a feed
    # does; a Withdraw starts one the way a source does. Together they let
    # every source funnel into one place and be pulled from when a pipeline
    # is ready, instead of each source pushing on its own schedule.
    "deposit", "withdraw",
)

# What a group starts out as, and the least it can be shrunk to.
GROUP_SIZE = (520, 300)
GROUP_LEAST = (200, 140)
TRIGGER_KINDS = ("schedule", "pulse")

# What a sort box can order a batch by: the name it is stored under, what it
# is called, and the two ends of it. "Most first" means something different
# for a duration than for a date, so each key brings its own words rather than
# leaving the reader to work out which end "most" is.
SORT_KEYS: tuple[tuple[str, str, str, str], ...] = (
    ("published", "When it went up", "Newest first", "Oldest first"),
    ("duration", "How long it is", "Longest first", "Shortest first"),
    ("views", "How many have watched it", "Most watched first", "Least watched first"),
    ("likes", "How many liked it", "Most liked first", "Least liked first"),
    ("title", "Its title", "Z to A", "A to Z"),
)


def sort_words(key: str, falling: bool) -> str:
    """What this box does, in the words that belong to what it sorts by."""
    for name, _, first, last in SORT_KEYS:
        if name == key:
            return first if falling else last
    return "Newest first" if falling else "Oldest first"
DEFAULT_SORT_BY = "published"

# Which wires make sense. Triggers feed channels, sources start paths, feeds
# end them, filters and sorts sit in between — and nothing runs backwards.
MIDDLE = ("filter", "sort", "plugin")
#: Where a path may end: a feed, or a repository to be pulled from later.
ENDS = ("feed", "deposit")

ALLOWED: dict[str, tuple[str, ...]] = {
    # A group is not on any path: it surrounds, it does not carry.
    "group": (),
    # Into a channel it says when to poll; into a feed it says when that feed
    # may be read; into a withdraw it says when to pull. A trigger carries no
    # content any of those ways.
    "trigger": ("source", "feed", "withdraw"),
    "source": MIDDLE + ENDS,
    "filter": MIDDLE + ENDS,
    # A plugin box is a filter whose rule is somebody's Lua, so it sits
    # exactly where a filter sits and wires to the same things.
    "plugin": MIDDLE + ENDS,
    "sort": MIDDLE + ENDS,
    # A withdraw stands where a source stands: it starts a path, and what
    # comes out of it has already been through whatever filtered it on the
    # way in.
    "withdraw": MIDDLE + ENDS,
    "feed": (),
    # The end of the line. What is in it comes out through a Withdraw box,
    # which is a path of its own rather than a continuation of this one.
    "deposit": (),
}

# Where a newly laid-out graph puts things: sources on the left, feeds on the
# right, filters between them. Triggers are placed beside the channel they are
# added next to rather than in a column, so they fit a canvas already laid out.
COLUMN_X = {
    "trigger": 60, "source": 60, "filter": 420, "sort": 420, "feed": 780,
    "group": 40,
    # A deposit sits where a feed sits, since it ends a path; a withdraw sits
    # where a source sits, since it starts one.
    "deposit": 780, "withdraw": 60,
}
ROW_HEIGHT = 130

# What a trigger means if it is wired up without anything being chosen.
DEFAULT_EVERY_MINUTES = 60
DEFAULT_CRON = "0 9 * * *"  # every day at 09:00 UTC

# How long a window stays open when nobody has said.
DEFAULT_DURATION_MINUTES = 30

# What a pulse's gap can be said in. Stored as minutes whichever is chosen —
# one number in the database, so nothing has to know which unit it was typed
# in. A month is thirty days here, and says so where it is offered: there is
# no honest fixed number of minutes in a month.
EVERY_UNITS: tuple[tuple[str, int, str], ...] = (
    ("minutes", 1, "minutes"),
    ("hours", 60, "hours"),
    ("days", 1440, "days"),
    ("weeks", 10080, "weeks"),
    ("months", 43200, "months (30 days)"),
)


def split_every(minutes: int) -> tuple[int, str]:
    """A gap in minutes as an amount and the largest unit it divides into.

    120 reads back as 2 hours and 90 as 90 minutes: the unit it was typed in
    is not stored, so the one that comes back is the one that needs no
    fraction to say.
    """
    for name, size, _ in reversed(EVERY_UNITS):
        if minutes >= size and minutes % size == 0:
            return minutes // size, name
    return max(1, minutes), "minutes"


def every_minutes_from(amount: int, unit: str) -> int:
    """An amount and a unit as the minutes to store.

    Zero survives, because zero means something: every run there is. Anything
    negative is nonsense and becomes the smallest gap the unit can express.
    """
    size = next((size for name, size, _ in EVERY_UNITS if name == unit), 1)
    if amount == 0:
        return 0
    return max(1, amount) * size


def every_words(minutes: int) -> str:
    """A gap said the way it was most likely meant."""
    if minutes == 0:
        return "run"  # reads as "every run", which is what it means
    amount, unit = split_every(minutes)
    return f"{amount} {unit[:-1] if amount == 1 else unit}"

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
    #: Where it ends, when it ends at a feed. None when it ends at a
    #: repository instead — a path has one end or the other, never both.
    playlist: Playlist | None = None
    #: The repository it ends in, when it ends in one. "" when it does not.
    #: Lowercased, because that is how the rows are filed.
    store: str = ""
    filters: list[GraphNode] = field(default_factory=list)
    #: Sort boxes on this path, in the order they are passed through.
    sorts: list[GraphNode] = field(default_factory=list)
    #: Plugin boxes on this path. Kept apart from `filters` because a filter
    #: lays settings over the channel's and these ask a question per item —
    #: the two cannot be merged into one dictionary.
    checks: list[GraphNode] = field(default_factory=list)
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
        """The sort box that decides this path's order, if any.

        The last one, as with filters: the nearest the feed has the final say,
        because that is the one describing what arrives.
        """
        return self.sorts[-1] if self.sorts else None

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


def channels_of(session: Session, node: GraphNode, owner: OwnerId = None) -> list[Channel]:
    """Which channel a source node stands for, if it stands for one yet.

    A list rather than one, because every caller walks it and an empty box
    standing for nothing is the ordinary case rather than an error.
    """
    if node.kind != "source":
        return []
    return [node.channel] if node.channel is not None else []


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

    found: list[Route] = []
    for node in all_nodes:
        if node.kind != "source":
            continue
        for channel in channels_of(session, node, owner):
            # Every path out of this box, whether it reaches a feed straight
            # away or goes through filters on the way.
            _walk(node, by_id, out, channel, [], set(), found, source=node)
    return _once_each(found)


def store_name(raw: str | None) -> str:
    """A repository name as it is filed: trimmed, squeezed, lowercased.

    So "News", "news" and " news " are one pile rather than three that look
    alike on the canvas. Said in one place because both ends have to agree on
    it — a Deposit and a Withdraw that disagreed would be two boxes that look
    joined and are not.
    """
    return " ".join((raw or "").split()).lower()[:60]


def _once_each(found: list[Route]) -> list[Route]:
    """Drop paths that are the same path twice.

    A channel may have two boxes on the canvas, wired down two routes that
    filter differently — which is the point of being allowed a second one.
    Two boxes wired the same way are the same path said twice, and the same
    video must not be weighed twice for one feed.
    """
    seen: set[
        tuple[int, int, str, tuple[int, ...], tuple[int, ...], tuple[int, ...]]
    ] = set()
    kept: list[Route] = []
    for path in found:
        signature = (
            path.channel.id,
            path.playlist.id if path.playlist is not None else 0,
            path.store,
            tuple(node.id for node in path.filters),
            tuple(node.id for node in path.sorts),
            # Two paths that differ only by which plugin boxes they pass are
            # two different paths: each asks a different question.
            tuple(node.id for node in path.checks),
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
    asked: list[GraphNode] | None = None,
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
    asked = asked or []

    for target_id in out.get(node.id, []):
        target = by_id.get(target_id)
        if target is None:
            continue
        if target.kind == "feed":
            if target.playlist is not None:
                found.append(
                    Route(
                        channel=channel,
                        playlist=target.playlist,
                        filters=list(carried),
                        sorts=list(ordered),
                        checks=list(asked),
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
                        checks=list(asked),
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
                asked + [target] if target.kind == "plugin" else asked,
            )


# -- when a channel is polled ----------------------------------------------

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
        due_at = trigger.get_next_fire_time(None, _aware(last_checked))
        return due_at is not None and due_at <= _aware(now)


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
        if start.kind == "trigger" and end.kind == "source":
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
    return _once_each(found)


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


# -- when a feed may be read -----------------------------------------------


def consumption(session: Session, owner: OwnerId = None) -> dict[int, list[GraphNode]]:
    """The triggers wired into each feed's second input, by playlist.

    A feed with none is always open. What these do is the opposite of what a
    trigger wired to a channel does: that one says when to go and fetch, this
    one says when you may sit down and read.
    """
    all_nodes, all_edges = load(session, owner)
    by_id = {node.id: node for node in all_nodes}

    wired: dict[int, list[GraphNode]] = {}
    for edge in all_edges:
        start, end = by_id.get(edge.source_pk), by_id.get(edge.target_pk)
        if start is None or end is None or not start.enabled:
            continue
        if start.kind == "trigger" and end.kind == "feed" and end.playlist_pk is not None:
            wired.setdefault(end.playlist_pk, []).append(start)
    return wired


@dataclass
class Window:
    """Whether a feed may be read now, and what follows from being let in."""

    open: bool
    #: Pulses whose sitting begins the moment the reader is let in, for the
    #: caller to stamp. Only ever acted on when the feed actually opens: a
    #: pulse must not spend its allowance while something else holds the feed
    #: shut anyway.
    starting: list[GraphNode] = field(default_factory=list)
    #: The soonest it could open again, when it is shut and that can be worked
    #: out. A lower bound where several triggers disagree, exact for one.
    opens_at: dt.datetime | None = None


def window_state(triggers: list[GraphNode], now: dt.datetime) -> Window:
    """Whether a feed may be read at this moment, and why not if not.

    Two kinds of trigger, combined the two ways they read:

    * **Schedules open times up.** Any one of them being in its window is
      enough, so a second schedule is a second chance to read — an *or*.
    * **Pulses narrow them.** Every one of them has to be in its window, so a
      second pulse is a further condition — an *and*.

    A kind nobody used says nothing rather than saying no: a feed with two
    schedules and no pulses is open when either schedule is, not never.
    """
    if not triggers:
        return Window(open=True)

    schedules = [node for node in triggers if node.trigger_kind == "schedule"]
    pulses = [node for node in triggers if node.trigger_kind != "schedule"]

    shut_at: list[dt.datetime] = []

    opened = True
    if schedules:
        opened = any(_came_round(node, now) for node in schedules)
        if not opened:
            # Any one of them is enough, so the soonest of them is the answer.
            soonest = [when for when in (_next_firing(node, now) for node in schedules) if when]
            if soonest:
                shut_at.append(min(soonest))

    narrowed = True
    starting: list[GraphNode] = []
    for node in pulses:
        allowed, begins = _sitting(node, now)
        if not allowed:
            narrowed = False
            when = _next_sitting(node, now)
            if when is not None:
                # Every pulse has to agree, so the last of them is the answer.
                shut_at.append(when)
        elif begins:
            starting.append(node)

    if opened and narrowed:
        return Window(open=True, starting=starting)
    return Window(open=False, opens_at=max(shut_at) if shut_at else None)


def is_open(triggers: list[GraphNode], now: dt.datetime) -> bool:
    """Whether a feed may be read, asked without letting anybody in.

    What the canvas draws on a feed box, where showing the state must not
    start a sitting that the reader never sat down for.
    """
    return window_state(triggers, now).open


def begin_sitting(session: Session, state: Window, now: dt.datetime) -> None:
    """Start the sittings this opening began, so they run out in their turn."""
    for node in state.starting:
        node.last_fired_at = now
    if state.starting:
        session.flush()


def _came_round(node: GraphNode, now: dt.datetime) -> bool:
    """Whether a schedule's window is open now.

    Asked the narrow way round: not "when did it last come round", which means
    walking back through firings, but "did it come round inside the last
    `window` minutes" — which is one question and one call.
    """
    window = max(1, node.duration_minutes or DEFAULT_DURATION_MINUTES)
    return _came_round_within(node.cron or DEFAULT_CRON, window, now)


def _next_firing(node: GraphNode, now: dt.datetime) -> dt.datetime | None:
    try:
        trigger = cron_trigger(node.cron or DEFAULT_CRON)
    except GraphError:
        return None
    # APScheduler is untyped here; it gives back an aware datetime or nothing.
    when: dt.datetime | None = trigger.get_next_fire_time(None, _aware(now))
    return when


def _sitting(node: GraphNode, now: dt.datetime) -> tuple[bool, bool]:
    """Whether this pulse lets you in, and whether that starts a new sitting.

    A pulse says how long you get and how often, and nothing about when. There
    is no clock time to anchor it to, so the sitting starts when you sit down:
    your ninety minutes a day begin at the first visit after the day is up,
    not at whatever hour the arithmetic happens to land on.

    That is the whole of the fix for the window that used to be measured from
    the Unix epoch — which put "90 minutes a day" at midnight UTC, an hour
    nobody chose and nothing on the canvas mentioned.
    """
    window = max(1, node.duration_minutes or DEFAULT_DURATION_MINUTES)
    gap = max(1, node.every_minutes or DEFAULT_EVERY_MINUTES)

    began = node.last_fired_at
    if began is None:
        return True, True  # never sat down: the first visit starts the first one

    since = _aware(now) - _aware(began)
    if since < dt.timedelta(minutes=window):
        return True, False  # still inside the sitting that is running
    if since >= dt.timedelta(minutes=gap):
        return True, True  # the gap has elapsed: the next one may start
    return False, False  # spent, and the gap has not come round yet


def _next_sitting(node: GraphNode, now: dt.datetime) -> dt.datetime | None:
    """When a spent pulse may be sat down to again."""
    if node.last_fired_at is None:
        return None
    gap = max(1, node.every_minutes or DEFAULT_EVERY_MINUTES)
    return _aware(node.last_fired_at) + dt.timedelta(minutes=gap)


def _came_round_within(expression: str, minutes: int, now: dt.datetime) -> bool:
    """Whether this cron fired at some point in the last `minutes`.

    A firing inside that stretch is a window that has not closed yet: it began
    at or after `now - minutes`, so it runs to at least `now`.
    """
    try:
        trigger = cron_trigger(expression)
    except GraphError:
        return False
    moment = _aware(now)
    began = trigger.get_next_fire_time(None, moment - dt.timedelta(minutes=minutes))
    return began is not None and began <= moment


def window_words(node: GraphNode) -> str:
    """What a trigger opens, said the way it reads on a feed."""
    window = max(1, node.duration_minutes or DEFAULT_DURATION_MINUTES)
    if node.trigger_kind == "schedule":
        return f"open {window} min from “{node.cron or DEFAULT_CRON}”"
    gap = max(1, node.every_minutes or DEFAULT_EVERY_MINUTES)
    return f"open {window} min in every {every_words(gap)}"


# -- what a filter is doing ------------------------------------------------


@dataclass
class Judged:
    """One item, and what this filter box does with it."""

    video_pk: int
    title: str
    kind: str
    passed: bool
    reason: str | None = None


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
    from . import sync as sync_service

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
    return found


# -- giving a group to somebody else ---------------------------------------

# Bumped if the shape changes in a way a reader would need to know about.
GROUP_FORMAT = 1


def export_group(session: Session, node_pk: int, owner: OwnerId = None) -> dict[str, Any]:
    """A group as a piece of setup somebody else can load.

    Positions are relative to the group's own corner, so it lands wherever it
    is dropped rather than on top of whatever is already at those coordinates.
    Channels travel as their YouTube ids, which mean the same thing on any
    machine; feeds travel as names, because a playlist id belongs to whoever
    owns the playlist and would be nobody else's to write to.
    """
    group = session.scalar(
        owned(select(GraphNode), GraphNode, owner).where(GraphNode.id == node_pk)
    )
    if group is None or group.kind != "group":
        raise GraphError("That node is not a group.")

    carried = inside(session, group, owner)
    refs = {node.id: index for index, node in enumerate(carried)}

    packed: list[dict[str, Any]] = []
    for node in carried:
        entry: dict[str, Any] = {
            "ref": refs[node.id],
            "kind": node.kind,
            "x": node.x - group.x,
            "y": node.y - group.y,
            "label": node.label,
            "enabled": node.enabled,
        }
        if node.kind == "source" and node.channel is not None:
            entry["channel_id"] = node.channel.channel_id
            entry["title"] = node.channel.title
        elif node.kind == "feed" and node.playlist is not None:
            entry["title"] = node.playlist.title
        elif node.kind == "filter":
            entry["rules"] = dict(node.overrides)
        elif node.kind == "sort":
            entry["sort_by"] = node.sort_by or DEFAULT_SORT_BY
            entry["sort_dir"] = node.sort_dir or "desc"
        elif node.kind == "trigger":
            entry["trigger_kind"] = node.trigger_kind or "pulse"
            entry["every_minutes"] = node.every_minutes
            entry["cron"] = node.cron
        packed.append(entry)

    return {
        "de_algo_group": GROUP_FORMAT,
        "name": group.label or "Group",
        "width": group.width or GROUP_SIZE[0],
        "height": group.height or GROUP_SIZE[1],
        "nodes": packed,
        "wires": [
            [refs[start], refs[end]]
            for start, end in _wires_within(session, carried, owner)
            if start in refs and end in refs
        ],
    }


def _wires_within(
    session: Session, carried: list[GraphNode], owner: OwnerId
) -> list[tuple[int, int]]:
    """Every wire with both ends inside the group. A wire out of it is not
    the group's to give away."""
    held = {node.id for node in carried}
    drawn: list[tuple[int, int]] = []
    for wire in wires(session, owner):
        start, end = int(wire["from"]), int(wire["to"])
        if start in held and end in held:
            drawn.append((start, end))
    return drawn


def import_group(
    session: Session,
    payload: Any,
    owner: OwnerId = None,
    *,
    x: int = 40,
    y: int = 40,
) -> GraphNode:
    """Load a group somebody else exported, beside whatever is already here.

    Channels are matched by their YouTube id and made if they are missing;
    feeds are always made, as feeds of this account's own. Nothing existing is
    changed: loading somebody's setup adds theirs, it does not replace yours.
    """
    if not isinstance(payload, dict) or "de_algo_group" not in payload:
        raise GraphError("That is not a De-Algo group file.")
    version = payload.get("de_algo_group")
    if not isinstance(version, int) or version > GROUP_FORMAT:
        raise GraphError(
            f"That group is format {version}, and this version of De-Algo reads {GROUP_FORMAT}."
        )

    group = add_group(
        session,
        owner,
        label=str(payload.get("name") or "Group"),
        x=x,
        y=y,
        width=int(payload.get("width") or GROUP_SIZE[0]),
        height=int(payload.get("height") or GROUP_SIZE[1]),
    )

    made: dict[int, GraphNode] = {}
    for entry in payload.get("nodes") or []:
        if not isinstance(entry, dict):
            continue
        node = _unpack(session, entry, owner, at=(x + int(entry.get("x") or 0),
                                                  y + int(entry.get("y") or 0)))
        if node is not None:
            made[int(entry.get("ref", -1))] = node
    session.flush()

    for pair in payload.get("wires") or []:
        if not isinstance(pair, list) or len(pair) != 2:
            continue
        start, end = made.get(pair[0]), made.get(pair[1])
        if start is None or end is None:
            continue
        try:
            connect(session, start, end, owner)
        except GraphError:
            continue  # a wire that makes no sense here is dropped, not fatal
    return group


def _unpack(
    session: Session, entry: dict[str, Any], owner: OwnerId, *, at: tuple[int, int]
) -> GraphNode | None:
    """One node out of a group file."""
    kind = entry.get("kind")
    label = str(entry.get("label") or "")
    x, y = at

    if kind == "source":
        channel_id = entry.get("channel_id")
        if not channel_id:
            return None
        channel = session.scalar(
            owned(select(Channel), Channel, owner).where(Channel.channel_id == channel_id)
        )
        if channel is None:
            # Made from the file rather than looked up: a UC id is enough to
            # watch a channel, and asking YouTube would make loading a group
            # need credentials it has no other use for.
            channel = Channel(
                owner_pk=owner,
                channel_id=str(channel_id),
                title=str(entry.get("title") or channel_id),
                enabled=False,
            )
            session.add(channel)
            session.flush()
            ordering.append(session, channel)
        return add_source(session, owner, channel=channel, x=x, y=y)

    if kind == "feed":
        from . import playlists as playlist_service

        playlist = playlist_service.create_generic(
            session, str(entry.get("title") or "Imported feed"), owner
        )
        return add_feed(session, playlist, owner, x=x, y=y)

    if kind == "filter":
        node = add_filter(session, owner, label=label or "Filter", x=x, y=y)
        rules = entry.get("rules")
        if isinstance(rules, dict):
            for name, value in rules.items():
                if name in FILTER_RULES:
                    setattr(node, name, value)
        return node

    if kind == "sort":
        return add_sort(
            session,
            owner,
            label=label,
            sort_by=str(entry.get("sort_by") or DEFAULT_SORT_BY),
            newest_first=str(entry.get("sort_dir") or "desc") == "desc",
            x=x,
            y=y,
        )

    if kind == "trigger":
        return add_trigger(
            session,
            owner,
            trigger_kind=str(entry.get("trigger_kind") or "pulse"),
            label=label,
            every_minutes=entry.get("every_minutes"),
            cron=entry.get("cron"),
            x=x,
            y=y,
        )
    return None


# What a filter file is allowed to set, so a stray key cannot reach a column
# that has nothing to do with filtering.
FILTER_RULES = (
    "skip_videos", "skip_shorts", "skip_live", "skip_posts",
    "title_include", "title_exclude",
    "min_duration_sec", "max_duration_sec", "max_per_run",
)


# -- trying it without running it ------------------------------------------


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
    channels: Collection[int] | None = None,
    pulls: Collection[int] | None = None,
) -> Trial:
    """Push recent items through the graph and say where they would land.

    Nothing is written and nothing is sent to YouTube: this answers "is this
    wired up the way I think" without waiting for a run, and without a run's
    consequences.

    ``channels`` narrows it to what one trigger sets off, which is how it is
    asked: a trigger is the thing that starts a run, so it is the thing worth
    asking what a run would do.

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

    for path in routes(session, owner):
        # A trial follows items to a feed. A path into a repository has no
        # feed to show them arriving at, and what happens to them there is
        # the Withdraw box's business.
        if path.playlist is None or not path.playlist.enabled:
            continue
        if channels is not None and path.channel.id not in channels:
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
                _note(trial.through, [node.id for node in path.filters] + [start.id], judged)
                landing.append((video, judged))
            else:
                _note(trial.held, [stopped_at], judged)
                # Everything before the box that stopped it did let it by.
                _note(trial.through, _before(stopped_at, path, start), judged)

        order = path.order
        if order is not None:
            landing.sort(key=lambda pair: _ranked(pair[0], order))

        # The sort box and the feed see the batch in the order it arrives.
        for _, judged in landing:
            _note(trial.through, [order.id] if order is not None else [], judged)
            _note(trial.through, [end.id], judged)

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
    from ..models import RepositoryItem

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
                _note(trial.through, [node.id for node in path.filters] + [box.id], judged)
                order = path.order
                _note(trial.through, [order.id] if order is not None else [], judged)
                _note(trial.through, [end.id], judged)
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
    from . import sync as sync_service

    def seen(passed: bool, reason: str | None) -> Judged:
        return Judged(
            video_pk=video.id,
            title=video.title or video.video_id,
            kind=video.kind,
            passed=passed,
            reason=reason,
        )

    # The channel's own settings first: if they refuse it, it never left.
    own = Route(channel=path.channel, playlist=path.playlist)
    refusal = sync_service._decide(video, own, None, settings)
    if not refusal.accept:
        return seen(False, refusal.reason), start.id

    for index, node in enumerate(path.filters):
        so_far = Route(
            channel=path.channel, playlist=path.playlist, filters=path.filters[: index + 1]
        )
        decision = sync_service._decide(video, so_far, None, settings)
        if not decision.accept:
            return seen(False, decision.reason), node.id

    decision = sync_service._decide(video, path, None, settings)
    return seen(decision.accept, decision.reason), start.id


def _before(stopped_at: int, path: Route, start: GraphNode) -> list[int]:
    """The boxes an item passed before the one that stopped it."""
    walked = [start.id] + [node.id for node in path.filters]
    return walked[: walked.index(stopped_at)] if stopped_at in walked else []


def _note(seen: dict[int, list[Judged]], node_ids: list[int], judged: Judged) -> None:
    for node_id in node_ids:
        seen.setdefault(node_id, []).append(judged)


def _ranked(video: Video, order: GraphNode) -> tuple[float, int]:
    """Where this video lands in a sorted batch, as the sort box sees it."""
    from . import sync as sync_service

    value = sync_service._sort_value(video, order.sort_by or DEFAULT_SORT_BY)
    return (-value if (order.sort_dir or "desc") == "desc" else value, video.id)


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

    # Every link a channel already had becomes a wire out of its box. The
    # wire is the truth now, so a setup that was never drawn has to be drawn
    # here or it would come out unwired.
    drawn = 0
    for channel in channels:
        start = made[("source", channel.id)]
        for playlist in channel.playlists:
            end = made.get(("feed", playlist.id))
            if end is None:
                continue
            session.add(GraphEdge(owner_pk=owner, source_pk=start.id, target_pk=end.id))
            drawn += 1
    session.flush()

    log.info(
        "laid out a graph from %d channel(s), %d feed(s) and %d link(s)",
        len(channels), len(playlists), drawn,
    )
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

    Every wire is an edge, including a source's. It used to be stored as a
    link between the *channel* and the feed, which meant two boxes for one
    channel could not be told apart: wiring either drew a wire from both, and
    unwiring either unwired both. A wire belongs to the box it was drawn
    from, so that a second box is a second box.
    """
    if source.id == target.id:
        raise GraphError("A node cannot feed itself.")
    if target.kind not in ALLOWED.get(source.kind, ()):
        raise GraphError(f"A {source.kind} cannot feed a {target.kind}.")

    fresh = source.kind == "source" and target.kind == "feed"
    if fresh:
        if source.channel is None or target.playlist is None:
            raise GraphError("That node no longer has anything behind it.")
        # A wire that could never carry anything, refused where it is drawn
        # rather than discovered sixty skipped items later.
        if not source.channel.publishable and not target.playlist.is_generic:
            raise GraphError(
                f"{target.playlist.title} is a YouTube playlist, and a YouTube playlist "
                "holds YouTube videos only. Wire this one to a feed that lives here — "
                "make a new feed and keep it generic."
            )

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
    if fresh and source.channel is not None and target.playlist is not None:
        refresh_membership(session, source.channel, owner)
        _bring_back_what_it_can_now_hold(session, source.channel, target.playlist, owner)
    return edge


def _bring_back_what_it_can_now_hold(
    session: Session, channel: Channel, playlist: Playlist, owner: OwnerId = None
) -> int:
    """Requeue items this source had nowhere to put.

    A source that is not YouTube wired only to YouTube playlists has every
    item turned away. Giving it a feed that can hold them should fill that
    feed, not leave the backlog stranded and wait for the next new post —
    the same courtesy turning a filter off already gets.
    """
    from . import sync as sync_service

    if not playlist.is_generic or channel.publishable:
        return 0

    stranded = list(
        session.scalars(
            owned(select(Video), Video, owner).where(
                Video.channel_pk == channel.id,
                Video.status == "skipped",
                Video.reason == sync_service.WRONG_KIND_OF_FEED,
            )
        )
    )
    for video in stranded:
        video.status = "pending"
        video.reason = None
        video.attempts = 0
        video.processed_at = None
    session.flush()
    return len(stranded)


def refresh_membership(
    session: Session, channel: Channel, owner: OwnerId = None
) -> None:
    """Work out again which feeds this channel fills, from the wires drawn.

    ``channel.playlists`` is what the rest of the app reads — the feed page,
    the backup, the sync engine — and it is now a view of the canvas rather
    than a thing anybody edits. One writer, so the two cannot disagree.

    Only the wires straight from a box to a feed count, which is what the
    pairing has always meant: a path that goes through a filter is a path,
    and `routes` is what asks about those.
    """
    by_playlist = {
        node.playlist_pk: node
        for node in nodes(session, owner)
        if node.kind == "feed" and node.playlist_pk
    }
    mine = [
        node.id
        for node in nodes(session, owner)
        if node.kind == "source" and node.channel_pk == channel.id
    ]
    if not mine:
        channel.playlists = []
        session.flush()
        return

    wired = {
        edge.target_pk
        for edge in edges(session, owner)
        if edge.source_pk in mine
    }
    feeds = [
        node.playlist
        for playlist_pk, node in by_playlist.items()
        if node.id in wired and node.playlist is not None
    ]
    channel.playlists = feeds
    session.flush()


def wires(session: Session, owner: OwnerId = None) -> list[dict[str, Any]]:
    """Every wire, in the one shape the canvas draws from.

    One kind now. A source's wire used to be synthesised from its channel's
    feeds, which is why two boxes for one channel showed the same wires.
    """
    _, all_edges = load(session, owner)

    return [
        {
            "id": f"edge:{edge.id}",
            "from": edge.source_pk,
            "to": edge.target_pk,
            "kind": "edge",
        }
        for edge in all_edges
    ]


def disconnect(session: Session, edge_pk: int, owner: OwnerId = None) -> bool:
    edge = session.scalar(owned(select(GraphEdge), GraphEdge, owner).where(GraphEdge.id == edge_pk))
    if edge is None:
        return False
    # Held before the row goes: afterwards there is nothing to ask which
    # channel's feeds have just changed.
    start = session.get(GraphNode, edge.source_pk)
    channel = start.channel if start is not None and start.kind == "source" else None
    session.delete(edge)
    session.flush()
    if channel is not None:
        refresh_membership(session, channel, owner)
    return True


def _still_drawn(session: Session, pk: int, what: str) -> bool:
    """Whether any node still stands for this channel or playlist."""
    column = GraphNode.channel_pk if what == "channel" else GraphNode.playlist_pk
    return session.scalar(select(GraphNode.id).where(column == pk).limit(1)) is not None


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


def add_plugin_node(
    session: Session,
    owner: OwnerId = None,
    *,
    ref: str,
    label: str = "",
    settings: dict[str, str] | None = None,
    x: int = COLUMN_X["filter"],
    y: int = 40,
) -> GraphNode:
    """A box a plugin put in the palette.

    Which box it is lives in `plugin_ref`, because the host has no column per
    plugin and never will: the fields are the plugin's to declare.
    """
    import json

    node = GraphNode(
        owner_pk=owner,
        kind="plugin",
        label=label or "",
        plugin_ref=ref,
        plugin_settings=json.dumps(settings) if settings else None,
        x=x,
        y=y,
    )
    session.add(node)
    session.flush()
    return node


def add_group(
    session: Session,
    owner: OwnerId = None,
    *,
    label: str = "",
    x: int = 40,
    y: int = 40,
    width: int = GROUP_SIZE[0],
    height: int = GROUP_SIZE[1],
) -> GraphNode:
    """A rectangle drawn behind the others. What it surrounds travels with it."""
    node = GraphNode(
        owner_pk=owner,
        kind="group",
        label=label,
        x=x,
        y=y,
        width=max(GROUP_LEAST[0], width),
        height=max(GROUP_LEAST[1], height),
    )
    session.add(node)
    session.flush()
    return node


def inside(session: Session, group: GraphNode, owner: OwnerId = None) -> list[GraphNode]:
    """What a group surrounds.

    Worked out from where things are rather than remembered, because that is
    how it is said: a node is in a group when the group is drawn around it,
    and dragging one out takes it out. Nothing is written when a node moves,
    so there is no membership to fall out of step with the drawing.

    A node counts as surrounded when its own corner is inside, which is the
    rule a reader applies at a glance and the one that survives a node being
    wider than it looks.
    """
    if group.kind != "group":
        return []
    right = group.x + (group.width or GROUP_SIZE[0])
    bottom = group.y + (group.height or GROUP_SIZE[1])
    return [
        node
        for node in nodes(session, owner)
        if node.id != group.id
        and node.kind != "group"  # a group inside a group would move twice
        and group.x <= node.x <= right
        and group.y <= node.y <= bottom
    ]


def move_group(
    session: Session, node_pk: int, x: int, y: int, owner: OwnerId = None
) -> list[GraphNode]:
    """Move a group, and everything it surrounds, by the same amount."""
    group = session.scalar(
        owned(select(GraphNode), GraphNode, owner).where(GraphNode.id == node_pk)
    )
    if group is None or group.kind != "group":
        raise GraphError("That node is not a group.")

    carried = inside(session, group, owner)
    across, down = int(x) - group.x, int(y) - group.y
    group.x, group.y = int(x), int(y)
    for node in carried:
        node.x += across
        node.y += down
    session.flush()
    return carried


def resize(
    session: Session, node_pk: int, width: int, height: int, owner: OwnerId = None
) -> bool:
    group = session.scalar(
        owned(select(GraphNode), GraphNode, owner).where(GraphNode.id == node_pk)
    )
    if group is None or group.kind != "group":
        return False
    group.width = max(GROUP_LEAST[0], int(width))
    group.height = max(GROUP_LEAST[1], int(height))
    session.flush()
    return True


def add_store(
    session: Session,
    owner: OwnerId = None,
    *,
    kind: str,
    repository: str = "",
    takes: int | None = None,
    x: int | None = None,
    y: int = 40,
) -> GraphNode:
    """A Deposit or a Withdraw box, both about one named repository.

    The name is what joins them: a Deposit and a Withdraw carrying the same
    name are two ends of one pile. It is filed lowercased, so a name typed
    two ways is still one repository.
    """
    if kind not in ("deposit", "withdraw"):
        raise GraphError(f"There is no {kind} box.")
    node = GraphNode(
        owner_pk=owner,
        kind=kind,
        repository=store_name(repository) or None,
        takes=takes if kind == "withdraw" else None,
        x=COLUMN_X[kind] if x is None else x,
        y=y,
    )
    session.add(node)
    session.flush()
    return node


def add_sort(
    session: Session,
    owner: OwnerId = None,
    *,
    label: str = "",
    sort_by: str = DEFAULT_SORT_BY,
    newest_first: bool = True,
    x: int = COLUMN_X["sort"],
    y: int = 40,
) -> GraphNode:
    node = GraphNode(
        owner_pk=owner,
        kind="sort",
        label=label,
        sort_by=check_sort_key(sort_by),
        sort_dir="desc" if newest_first else "asc",
        x=x,
        y=y,
    )
    session.add(node)
    session.flush()
    return node


def check_sort_key(key: str) -> str:
    known = {name for name, _, _, _ in SORT_KEYS}
    if key not in known:
        raise GraphError(f"There is nothing to sort by called “{key}”.")
    return key


def add_source(
    session: Session,
    owner: OwnerId = None,
    *,
    channel: Channel | None = None,
    source_kind: str = "",
    x: int = 0,
    y: int = 0,
) -> GraphNode:
    """A box for a channel — which may not have been named yet.

    A source box is dropped on the canvas first and told which source it is
    afterwards, by typing into it. Until then it stands for nothing, and
    everything that walks the graph skips it: an empty box cannot route
    anything, and saying so is better than refusing to make one.

    It does know which *kind* of somewhere it is for, because that is what
    was dragged out of the palette. That is the whole reason the box knows
    what to ask for: a Subreddit box asks for a subreddit.
    """
    node = GraphNode(
        owner_pk=owner,
        kind="source",
        channel_pk=channel.id if channel is not None else None,
        source_kind=(source_kind or "").strip() or None,
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
        raise GraphError("Only a channel node stands for a channel.")
    # The relationship, not only the key behind it: this node was loaded with
    # no channel, and setting the key alone leaves that stale until something
    # expires it — so the answer to this very request would still say empty.
    node.channel = channel
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
        raise GraphError("That node is not here.")

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

    # The wires went with it, so which feeds that channel fills has changed.
    if node.kind == "source" and channel is not None:
        refresh_membership(session, channel, owner)

    # Only if nothing else is still drawn around it. A channel may have two
    # nodes, and taking one off the canvas is rearranging the drawing rather
    # than saying goodbye to the channel.
    if node.kind == "source" and channel is not None and not _still_drawn(session, channel.id, "channel"):
        session.delete(channel)
    elif node.kind == "feed" and playlist is not None and not _still_drawn(session, playlist.id, "playlist"):
        session.delete(playlist)
    session.flush()
    return True
