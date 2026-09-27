"""The Configuration canvas: what is wired to what.

The graph is the truth about routing. A video leaves a source node, follows
wires, and lands in every feed node it can reach — narrowed on the way by any
filter node it passes through.

Three rules make it comprehensible:

* **A channel's own filters are the default.** They apply on every path out of
  that channel, exactly as they did before there was a graph.
* **A filter node overrides, it does not replace.** Anything it leaves unset
  stays whatever the channel said. So a channel can take long videos
  everywhere except down one particular wire, without its settings being
  duplicated.
* **A box says on the canvas what it does.** A Filter narrows by the condition
  pieces slotted under it, one piece per condition, and a Sort orders by the
  Order piece under it. The rules sat in the boxes' own popovers once, which
  meant a canvas of boxes all reading "Filter" and no way to tell them apart
  without opening each one. A condition that is a fact about one service —
  whether a video is a Short — belongs to the plugin that knows what those
  words mean, and is a piece under that plugin's box instead.

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
import json
import logging
from collections.abc import Collection
from dataclasses import dataclass, field
from typing import Any

from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..models import (
    CONDITION_LABELS, Channel, GraphEdge, GraphNode, Playlist, Settings, Video,
    to_naive_utc, utcnow,
)
from . import ordering
from .scope import OwnerId, owned

log = logging.getLogger(__name__)

KINDS = (
    "trigger", "source", "filter", "sort", "feed", "group",
    # A repository, from its two ends. A Deposit ends a path the way a feed
    # does; a Withdraw starts one the way a source does. Together they let
    # every source funnel into one place and be pulled from when a pipeline
    # is ready, instead of each source pushing on its own schedule.
    "deposit", "withdraw",
    # Boxes that mark what passes through them rather than narrowing it.
    # Each says something about an item that the rest of the app reads
    # later: how long you get with it, how long it belongs in a feed, what
    # it is called.
    "decay", "expire", "tag",
    # Augmentations. These are not on any path and have no wires: each is
    # slotted under a box and changes what that box does. They chain, and a
    # chain belongs to the box at the top of it.
    "timer", "reset", "alive", "lock",
    # Conditions: one piece per thing a Filter narrows by, and one for what
    # a Sort orders by. Listed by hand rather than spread from `CONDITIONS`
    # so that this tuple stays the one readable list of what a box can be.
    "has-words", "lacks-words", "longer-than", "shorter-than",
    "carrying", "at-most", "order",
    # A condition a plugin declared, slotted under a Filter box like any
    # other condition. A plugin has no box of its own: it adds to what the
    # app's own boxes can be told, rather than standing beside them.
    "rule",
)

@dataclass(frozen=True)
class Condition:
    """One thing a Filter or a Sort box can be told, as a piece.

    A rule used to be a field in a box's popover, which meant a box said
    "Filter" and you had to open it to find out what it filtered. A piece
    says what it is on the canvas, and a box narrowing three ways is three
    pieces rather than one form filled in three places.

    Each keeps its value in the column that rule always used, so nothing is
    stored twice and a box from before this converts into pieces rather than
    being read two ways.

    Only what is true of any item at all is here. Anything that is a fact
    about one service — whether a video is a Short, how many have watched it —
    belongs to the plugin that knows what those words mean, and is offered as
    a piece under that plugin's box instead. See `RULE`.
    """

    kind: str
    label: str
    blurb: str
    #: Which box it goes under: a Filter narrows, a Sort orders.
    under: str
    #: The column it writes, which is the same column that rule lived in when
    #: it was a field on the box.
    column: str
    #: How the panel asks for it, and what to call the field.
    field: str
    asks: str


CONDITIONS: tuple[Condition, ...] = (
    Condition(
        "has-words", CONDITION_LABELS["has-words"], "Only what matches this.", "filter",
        "title_include", "text", "Words, or /a regex/",
    ),
    Condition(
        "lacks-words", CONDITION_LABELS["lacks-words"], "Holds anything that matches this.", "filter",
        "title_exclude", "text", "Words, or /a regex/",
    ),
    Condition(
        "longer-than", CONDITION_LABELS["longer-than"], "Holds anything shorter.", "filter",
        "min_duration_sec", "duration", "How long",
    ),
    Condition(
        "shorter-than", CONDITION_LABELS["shorter-than"], "Holds anything longer.", "filter",
        "max_duration_sec", "duration", "How long",
    ),
    Condition(
        "carrying", CONDITION_LABELS["carrying"], "Only what a Tag box earlier put a mark on.",
        "filter", "tagged", "text", "This tag",
    ),
    Condition(
        "at-most", CONDITION_LABELS["at-most"], "How many may get through in one run.", "filter",
        "max_per_run", "number", "Per run",
    ),
    Condition(
        "order", CONDITION_LABELS["order"], "What to put the batch in order by.", "sort",
        "sort_by", "order", "By",
    ),
)

CONDITION_KINDS: tuple[str, ...] = tuple(one.kind for one in CONDITIONS)

#: A condition that belongs to a plugin rather than to the host. One kind
#: rather than one per condition, because which conditions exist depends on
#: which plugins are loaded and the host cannot have a column for each: which
#: one this piece is lives in `plugin_ref`, exactly as it did when the same
#: thing was a box of its own.
RULE = "rule"


def condition(kind: str) -> Condition | None:
    return next((one for one in CONDITIONS if one.kind == kind), None)


def conditions_for(kind: str) -> tuple[Condition, ...]:
    """The pieces that may be slotted under a box of this kind."""
    return tuple(one for one in CONDITIONS if one.under == kind)


def filter_rules(pieces: list[GraphNode]) -> dict[str, Any]:
    """What the condition pieces under a Filter box narrow by.

    `pieces` comes nearest-first, and the one nearest the box has the last
    word — the same rule a filter nearest a feed already lives by. So they
    are read from the far end back.
    """
    said: dict[str, Any] = {}
    for piece in reversed(pieces):
        if piece.kind in CONDITION_KINDS and piece.enabled:
            said.update(piece.overrides)
    return said


#: The box kinds that read what is slotted under them. A feed reads a Timer
#: as a sitting and a Reset as when it comes back; a Decay reads a Timer as
#: time with one item and a Lock as "and you cannot pause it"; an Expire
#: reads a Timer as a lifetime. A Filter reads conditions — the app's own and
#: whatever ones the plugins declared — and a Sort reads an Order.
#: Every other kind ignores a piece entirely, which is why only these are
#: drawn with somewhere for one to go.
SLOTTED = ("feed", "decay", "expire", "filter", "sort")

#: The boxes that mark what goes through them. On a path like a filter, but
#: they turn nothing away — what they do shows up after the item has landed.
STAMPS = ("decay", "expire", "tag")

#: The augmentations, as against the boxes. An augmentation is not on any
#: path and has no wires: it is slotted under a box and changes what that box
#: does. Kept in one tuple so "is this an augmentation" is one question asked
#: in one place.
#:
#: Called a piece throughout the code, which is what one of them is on the
#: canvas — it is drawn with a tab and a notch and interlocks with whatever it
#: is slotted into. "Augmentation" is what the kind of thing is called;
#: "piece" is what one looks like.
AUGMENTATIONS: tuple[str, ...] = (
    ("timer", "reset", "alive", "lock") + CONDITION_KINDS + (RULE,)
)

#: Which boxes each augmentation may be slotted under. An Alive under a
#: Filter would be a piece nobody ever reads, so it is refused at the drop
#: rather than discovered later by a box that quietly does nothing.
#:
#: This is the one answer: the palette prints it on every row, the canvas
#: lights up the boxes it names while a piece is dragged, and `attach`
#: refuses anything else. Three places saying different things is how you
#: end up able to drop something where it will never be read.
PIECE_HOSTS: dict[str, tuple[str, ...]] = {
    # A Timer is an amount of time and means something different in each:
    # a sitting, how long you get with one item, how long an item stays.
    "timer": ("feed", "decay", "expire"),
    # The other three are about reading a feed, and only a feed reads them.
    "reset": ("feed",),
    "alive": ("feed",),
    # And a Lock is about a Decay's Timer being one you cannot pause.
    "lock": ("decay",),
    **{one.kind: (one.under,) for one in CONDITIONS},
}

#: What each box is called where one is named out loud.
BOX_NAMES: dict[str, str] = {
    "feed": "Feed", "filter": "Filter", "sort": "Sort",
    "decay": "Decay", "expire": "Expire",
}


def hosts_for(kind: str, ref: str = "") -> tuple[str, ...]:
    """Which boxes an augmentation of this kind may be slotted under.

    A plugin's is asked of the plugin rather than read off the table: what
    it goes under is the plugin's to declare, and a Filter and a Sort ask
    different enough questions that one answering either would do nothing
    under the other.

    Empty where there is nothing to say — this is not an augmentation, or it
    is one whose plugin is switched off. An empty answer is not a refusal:
    see `attach`, which takes it as "no opinion" rather than "nowhere".
    """
    if kind != RULE:
        return PIECE_HOSTS.get(kind, ())
    from ..plugins import registry

    found = registry.current().augmentation(ref)
    # Its plugin is switched off or gone. It narrows nothing while that is
    # true, and refusing to move it as well would be twice the punishment
    # for something that is not the canvas's fault.
    return () if found is None else (found.under,)


def host_boxes(kind: str, ref: str = "") -> list[dict[str, str]]:
    """Where one goes, as the boxes themselves: their kind and their name.

    Named rather than described, because a list of names is what the reader
    is actually going to look for in the palette — and because two of them
    read no worse than one, where a sentence has to choose between "or" and
    "and" for something that is neither.
    """
    return [
        {"kind": one, "label": BOX_NAMES.get(one, one.title())}
        for one in hosts_for(kind, ref)
    ]


def piece_hosts(piece: GraphNode) -> tuple[str, ...] | None:
    """Which boxes this particular piece may be slotted under.

    None means nothing is known about where it goes, which is not the same
    as nowhere: a piece whose plugin is switched off would otherwise be
    unmovable as well as inert.
    """
    found = hosts_for(piece.kind, piece.plugin_ref or "")
    return found or None

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
MIDDLE = ("filter", "sort", "decay", "expire", "tag")
#: Where a path may end: a feed, or a repository to be pulled from later.
ENDS = ("feed", "deposit")

ALLOWED: dict[str, tuple[str, ...]] = {
    # A group is not on any path: it surrounds, it does not carry.
    "group": (),
    # Into a channel it says when to poll; into a feed it says when that feed
    # may be read; into a withdraw it says when to pull. A trigger carries no
    # content any of those ways.
    # A feed used to take one too, on a second input, to say when it could
    # be read. That is a Timer and a Reset slotted under it now: it is a
    # property of the feed rather than something arriving along a wire.
    "trigger": ("source", "withdraw"),
    "source": MIDDLE + ENDS,
    "filter": MIDDLE + ENDS,
    "sort": MIDDLE + ENDS,
    # A withdraw stands where a source stands: it starts a path, and what
    # comes out of it has already been through whatever filtered it on the
    # way in.
    "withdraw": MIDDLE + ENDS,
    "feed": (),
    # The end of the line. What is in it comes out through a Withdraw box,
    # which is a path of its own rather than a continuation of this one.
    "deposit": (),
    # A piece is slotted, not wired. Nothing runs into or out of one.
    "timer": (),
    "reset": (),
    "alive": (),
    "lock": (),
    "has-words": (),
    "lacks-words": (),
    "longer-than": (),
    "shorter-than": (),
    "carrying": (),
    "at-most": (),
    "order": (),
    "rule": (),
    # They mark what passes and pass it on, so they sit where a filter sits.
    "decay": MIDDLE + ENDS,
    "expire": MIDDLE + ENDS,
    "tag": MIDDLE + ENDS,
}

#: What an Alive piece allows when nobody has said. All day, so a piece just
#: dropped in changes nothing until it is told to.
DEFAULT_ALIVE = ("00:00", "00:00")

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

#: How a length of video is asked for, and what each unit is in seconds.
#: Short units, because "longer than" is usually about minutes rather than
#: about days, which is what the other unit list is for.
LENGTH_UNITS: tuple[tuple[str, int], ...] = (
    ("seconds", 1), ("minutes", 60), ("hours", 3600),
)


def seconds_from(amount: int, unit: str) -> int:
    """An amount and a unit as the seconds to store."""
    size = next((size for name, size in LENGTH_UNITS if name == unit), 1)
    return max(1, amount) * size


def split_length(seconds: int) -> tuple[int, str]:
    """The seconds back as the largest unit they divide into evenly."""
    for name, size in reversed(LENGTH_UNITS):
        if seconds >= size and seconds % size == 0:
            return seconds // size, name
    return seconds, "seconds"


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
        # A box that is switched off is out of the graph. Said of the box and
        # not only of the channel, because a channel may be drawn twice and
        # switching one box off must not take the other with it.
        if node.kind != "source" or not node.enabled:
            continue
        for channel in channels_of(session, node, owner):
            # Every path out of this box, whether it reaches a feed straight
            # away or goes through filters on the way.
            _walk(node, by_id, out, channel, [], set(), found, source=node)
    return _once_each(_slot_in(found, all_nodes))


def clock_time(raw: str | None) -> str:
    """A time of day as "HH:MM", or "" if that is not what it is.

    Forgiving about what is typed and strict about what is stored: "9",
    "9:5", "09.05" and "0905" all become "09:05", because a field asking for
    a time should take a time however somebody writes one down.
    """
    said = "".join((raw or "").split())
    if not said:
        return ""
    for mark in (":", ".", "h"):
        said = said.replace(mark, ":")
    hours, _, minutes = said.partition(":")
    if not minutes and len(hours) == 4 and hours.isdigit():
        hours, minutes = hours[:2], hours[2:]   # "0905"
    if not hours.isdigit() or (minutes and not minutes.isdigit()):
        return ""
    hour, minute = int(hours), int(minutes or 0)
    if hour > 23 or minute > 59:
        return ""
    return f"{hour:02d}:{minute:02d}"


def _minutes_of(said: str | None) -> int | None:
    """A stored "HH:MM" as minutes since midnight."""
    tidy = clock_time(said)
    if not tidy:
        return None
    hours, _, minutes = tidy.partition(":")
    return int(hours) * 60 + int(minutes)


def alive_now(piece: GraphNode, now: dt.datetime) -> bool:
    """Whether this Alive piece allows the moment it is asked about.

    Read on the clock rather than from when anybody sat down, so it is the
    one piece with an opinion about the hour of the day. A stretch that ends
    before it begins runs through midnight, which is how somebody writes
    "overnight" without being asked to say it twice.

    Two ends the same is the whole day — the reading that cannot accidentally
    shut a feed for ever, which the other one can.
    """
    begins = _minutes_of(piece.alive_from)
    ends = _minutes_of(piece.alive_to)
    if begins is None or ends is None or begins == ends:
        return True
    minute = _aware(now).hour * 60 + _aware(now).minute
    if begins < ends:
        return begins <= minute < ends
    return minute >= begins or minute < ends


def store_name(raw: str | None) -> str:
    """A repository name as it is filed: trimmed, squeezed, lowercased.

    So "News", "news" and " news " are one pile rather than three that look
    alike on the canvas. Said in one place because both ends have to agree on
    it — a Deposit and a Withdraw that disagreed would be two boxes that look
    joined and are not.
    """
    return " ".join((raw or "").split()).lower()[:60]


def _slot_in(found: list[Route], all_nodes: list[GraphNode]) -> list[Route]:
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
    return _once_each(_slot_in(found, all_nodes))


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


def attach(
    session: Session, piece: GraphNode, host: GraphNode, owner: OwnerId = None
) -> GraphNode:
    """Slot an augmentation under a box, or under another one.

    Refused where it would make no sense, said at the moment of the drop
    rather than discovered later by a piece that quietly does nothing.
    """
    if piece.kind not in AUGMENTATIONS:
        raise GraphError(f"A {piece.kind} box is not an augmentation.")
    if piece.id == host.id:
        raise GraphError("A piece cannot be slotted under itself.")
    if host.kind == "group":
        raise GraphError("A group is a background, not something to slot into.")

    # Where this kind of piece is allowed to end up. A chain belongs to the
    # box at the top of it, so what matters is that box and not whatever the
    # piece was dropped directly onto.
    wanted = piece_hosts(piece)
    if wanted is not None:
        landing = host if host.kind not in AUGMENTATIONS else host_of(nodes(session, owner), host)
        if landing is None or landing.kind not in wanted:
            named = " or a ".join(one.capitalize() for one in wanted)
            raise GraphError(f"{piece.title} goes under a {named} box.")

    # No rings. Walking up from the host must not arrive back at the piece.
    seen = {piece.id}
    walk: GraphNode | None = host
    while walk is not None:
        if walk.id in seen:
            raise GraphError("That would slot a piece under itself.")
        seen.add(walk.id)
        walk = session.get(GraphNode, walk.attached_to) if walk.attached_to else None

    piece.attached_to = host.id
    session.flush()
    return piece


def detach(session: Session, piece: GraphNode) -> bool:
    """Take a piece out of whatever it was slotted under.

    What was under it closes up behind it. Taking the middle piece out of a
    chain is taking one piece out, not breaking the chain in half: everything
    below it would otherwise be hanging off a piece that is slotted into
    nothing, which is to say doing nothing at all.
    """
    if piece.attached_to is None:
        return False
    _close_up(session, piece)
    piece.attached_to = None
    session.flush()
    return True


def _close_up(session: Session, piece: GraphNode) -> None:
    """Move whatever is under a piece up to whatever the piece was under.

    Said in one place because both ways of taking a piece out of a chain —
    unslotting it and deleting it — have to do it, and a chain that healed
    one way and not the other would be worse than one that never healed.
    """
    for below in session.scalars(
        select(GraphNode).where(GraphNode.attached_to == piece.id)
    ):
        below.attached_to = piece.attached_to
    session.flush()


def pieces_under(all_nodes: list[GraphNode], host_pk: int) -> list[GraphNode]:
    """Every augmentation in the chain under one box, nearest first.

    A chain rather than a list: a piece may be slotted under another, and all
    of them belong to the box at the top. Nearest first because that is the
    order they are read in — the one closest to the box has the last word,
    the same rule a filter nearest a feed lives by.
    """
    below: dict[int, list[GraphNode]] = {}
    for node in all_nodes:
        if node.kind in AUGMENTATIONS and node.attached_to is not None:
            below.setdefault(node.attached_to, []).append(node)

    found: list[GraphNode] = []
    queue = list(below.get(host_pk, []))
    seen: set[int] = set()
    while queue:
        piece = queue.pop(0)
        if piece.id in seen:
            continue  # a ring somebody built before this refused to make one
        seen.add(piece.id)
        found.append(piece)
        queue.extend(below.get(piece.id, []))
    return found


def host_of(all_nodes: list[GraphNode], piece: GraphNode) -> GraphNode | None:
    """The box at the top of a piece's chain, which is what it changes."""
    by_id = {node.id: node for node in all_nodes}
    seen: set[int] = {piece.id}
    walk = by_id.get(piece.attached_to) if piece.attached_to else None
    while walk is not None and walk.kind in AUGMENTATIONS:
        if walk.id in seen:
            return None
        seen.add(walk.id)
        walk = by_id.get(walk.attached_to) if walk.attached_to else None
    return walk


def consumption(session: Session, owner: OwnerId = None) -> dict[int, list[GraphNode]]:
    """The augmentations slotted under each feed, by playlist.

    A feed with none is always open. What these do is the opposite of what a
    trigger wired to a channel does: that one says when to go and fetch,
    these say when you may sit down and read.
    """
    all_nodes, _ = load(session, owner)
    under: dict[int, list[GraphNode]] = {}
    for node in all_nodes:
        if node.kind != "feed" or node.playlist_pk is None:
            continue
        pieces = [one for one in pieces_under(all_nodes, node.id) if one.enabled]
        if pieces:
            under.setdefault(node.playlist_pk, []).extend(pieces)
    return under


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


def window_state(pieces: list[GraphNode], now: dt.datetime) -> Window:
    """Whether a feed may be read at this moment, and why not if not.

    Two pieces, each answering half of it:

    * **Timer says how long you get**, counted from when you sit down. There
      is no clock time in it, so the sitting starts at the first visit rather
      than at whatever hour the arithmetic would otherwise land on — which is
      what "ninety minutes a day" means to the person who asked for it.
    * **Reset says when you get another.** A cron: the sitting is re-armed the
      next time it comes round. Any one of several is enough, so a second
      Reset is a second chance to read rather than a further condition.
    * **Alive says when the feed is allowed at all.** A stretch of the day,
      read on the clock. It narrows whatever the other two worked out: a
      sitting with time left on it is still no good at four in the morning.
      Several are several stretches — any one of them allowing it is enough.

    A Timer with no Reset gives you one sitting and no more, and says so.
    A Reset with no Timer gives the usual half hour each time it comes round.
    The Timer nearest the feed has the last word, which is the rule a filter
    nearest a feed already lives by.
    """
    if not pieces:
        return Window(open=True)

    timers = [node for node in pieces if node.kind == "timer"]
    resets = [node for node in pieces if node.kind == "reset"]
    living = [node for node in pieces if node.kind == "alive"]

    # Asked first, and on its own terms: it is about the hour rather than
    # about a sitting, so being outside it is a shut feed whatever else the
    # pieces say — and a sitting must not be spent against a feed that was
    # never going to open.
    if living and not any(alive_now(node, now) for node in living):
        return Window(open=False, opens_at=_next_alive(living, now))

    if not timers and not resets:
        return Window(open=True)

    # Nearest first, so the first Timer in the chain is the one that counts.
    window = max(1, timers[0].duration_minutes or DEFAULT_DURATION_MINUTES) if timers else (
        DEFAULT_DURATION_MINUTES
    )
    # The piece that remembers when the sitting began. A Timer if there is
    # one, since that is the piece the sitting belongs to; otherwise the
    # Reset, which is then keeping the time for a sitting of the usual length.
    anchor = timers[0] if timers else resets[0]

    began = anchor.last_fired_at
    if began is None:
        # Never sat down. This visit starts the first sitting.
        return Window(open=True, starting=[anchor])

    if _aware(now) - _aware(began) < dt.timedelta(minutes=window):
        return Window(open=True)  # still inside the sitting

    # Spent. It comes back when a Reset next comes round.
    if not resets:
        return Window(open=False)

    if any(_fired_between(node.cron or DEFAULT_CRON, began, now) for node in resets):
        return Window(open=True, starting=[anchor])

    soonest = [when for when in (_next_firing(node, now) for node in resets) if when]
    return Window(open=False, opens_at=min(soonest) if soonest else None)


def _next_alive(pieces: list[GraphNode], now: dt.datetime) -> dt.datetime | None:
    """When the next of these stretches begins, so a shut feed can say.

    The soonest of them, since any one allowing it is enough. Walked forward
    a minute at a time would be simpler and slower; this works out each
    beginning directly and takes the nearest.
    """
    moment = _aware(now)
    soonest: dt.datetime | None = None
    for piece in pieces:
        begins = _minutes_of(piece.alive_from)
        if begins is None:
            continue
        today = moment.replace(
            hour=begins // 60, minute=begins % 60, second=0, microsecond=0
        )
        when = today if today > moment else today + dt.timedelta(days=1)
        if soonest is None or when < soonest:
            soonest = when
    return soonest


def _fired_between(expression: str, since: dt.datetime, now: dt.datetime) -> bool:
    """Whether this cron came round after `since` and no later than now.

    Which is the question a spent sitting asks: not "is it in a window" but
    "has it been re-armed since I last sat down".
    """
    try:
        trigger = cron_trigger(expression)
    except GraphError:
        return False
    moment = _aware(now)
    # Strictly after: the firing that started this sitting is not a reason to
    # start another one, and `get_next_fire_time` counts `since` itself.
    came: dt.datetime | None = trigger.get_next_fire_time(None, _aware(since))
    while came is not None and came <= _aware(since):
        came = trigger.get_next_fire_time(came, came + dt.timedelta(seconds=1))
    return came is not None and came <= moment


def is_open(pieces: list[GraphNode], now: dt.datetime) -> bool:
    """Whether a feed may be read, asked without letting anybody in.

    What the canvas draws on a feed box, where showing the state must not
    start a sitting that the reader never sat down for.
    """
    return window_state(pieces, now).open


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


def piece_note(piece: GraphNode, host: GraphNode | None) -> str:
    """What a piece does, said in the terms of what it is slotted into.

    A Timer says an amount and nothing about what it is an amount of: under
    a feed it is a sitting, under a Decay box it is how long you get with
    one item, under an Expire box it is how long that item stays. The piece
    carries the number; the box it is in is what the number means.
    """
    said = piece_words(piece)
    if piece.kind != "timer":
        return said

    if host is None:
        return said
    if host.kind == "decay":
        return f"{said} with each one"
    if host.kind == "expire":
        return f"gone {said} after it arrives"
    return f"{said} once you start reading"


def length_words(seconds: int) -> str:
    """A stretch of a video, said the way somebody would say it out loud."""
    if seconds < 60:
        return f"{seconds}s"
    return every_words(max(1, round(seconds / 60)))


def condition_words(piece: GraphNode) -> str:
    """What one condition piece narrows by, in its own words.

    A condition nobody has filled in yet says so rather than saying nothing:
    an empty "Title has" narrows nothing at all, and a piece that looked
    busy while doing nothing would be the worst of both.
    """
    spec = condition(piece.kind)
    if spec is None:
        return ""
    if piece.kind == "order":
        return sort_words(
            piece.sort_by or DEFAULT_SORT_BY, (piece.sort_dir or "desc") == "desc"
        )
    value = getattr(piece, spec.column, None)
    if value is None or value == "":
        return "open it and say what"
    if piece.kind == "has-words":
        return f"title has “{value}”"
    if piece.kind == "lacks-words":
        return f"title lacks “{value}”"
    if piece.kind == "longer-than":
        return f"longer than {length_words(int(value))}"
    if piece.kind == "shorter-than":
        return f"shorter than {length_words(int(value))}"
    if piece.kind == "carrying":
        return f"tagged “{tag_name(str(value))}”"
    return f"{int(value)} per run"


def stamp_words(node: GraphNode, pieces: list[GraphNode]) -> str:
    """What a marking box does, in the words that belong to it.

    A Timer slotted under one says an amount and nothing about what it is an
    amount of; the box it is slotted into is what turns it into a sentence.
    """
    if node.kind == "tag":
        named = tag_name(node.marks)
        return f"marks it “{named}”" if named else "open it and give it a tag"

    minutes = _timer_minutes(pieces)
    if minutes is None:
        return "slot a Timer under it to say how long"
    if node.kind == "decay":
        locked = any(one.kind == "lock" and one.enabled for one in pieces)
        return every_words(minutes) + " with each one" + (", no pausing" if locked else "")
    return "gone " + every_words(minutes) + " after it arrives"


def piece_words(piece: GraphNode, window: int | None = None) -> str:
    """What one augmentation does, in the words that belong to it.

    A Timer reads differently depending on what it is slotted into — how
    long a sitting lasts, how long you get with one item, how long an item
    stays — so the host is asked for the sentence and this says the amount.
    """
    if piece.kind in CONDITION_KINDS:
        return condition_words(piece)
    if piece.kind == "lock":
        return "cannot be paused"
    if piece.kind == "alive":
        begins = clock_time(piece.alive_from)
        ends = clock_time(piece.alive_to)
        if not begins or not ends or begins == ends:
            return "any time of day"
        return f"only between {begins} and {ends}"
    if piece.kind == "timer":
        minutes = max(1, piece.duration_minutes or DEFAULT_DURATION_MINUTES)
        return every_words(minutes)
    held = window if window is not None else DEFAULT_DURATION_MINUTES
    return f"another {every_words(max(1, held))} on “{piece.cron or DEFAULT_CRON}”"


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
    return _slot_in(found, all_nodes)


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
        if node.attached_to is not None and node.attached_to in refs:
            # A piece travels as what it is slotted under, not as where it
            # happens to lie: the assembly is the thing being handed over.
            entry["under"] = refs[node.attached_to]
        if node.kind == "source" and node.channel is not None:
            entry["channel_id"] = node.channel.channel_id
            entry["title"] = node.channel.title
        elif node.kind == "feed" and node.playlist is not None:
            entry["title"] = node.playlist.title
        elif node.kind in CONDITION_KINDS:
            # A condition carries one value, in the column that rule lives
            # in. Written under its own name so the file reads as what it is.
            spec = condition(node.kind)
            if spec is not None:
                entry["value"] = getattr(node, spec.column, None)
            entry["sort_dir"] = node.sort_dir or "desc"
        elif node.kind == RULE:
            entry["plugin_ref"] = node.plugin_ref or ""
            entry["plugin_settings"] = node.plugin_settings or ""
        elif node.kind == "timer":
            entry["duration_minutes"] = node.duration_minutes
        elif node.kind == "reset":
            entry["cron"] = node.cron
        elif node.kind == "alive":
            entry["alive_from"] = node.alive_from or ""
            entry["alive_to"] = node.alive_to or ""
        elif node.kind == "tag":
            entry["marks"] = node.marks or ""
        elif node.kind in ("deposit", "withdraw"):
            entry["repository"] = node.repository or ""
            entry["takes"] = node.takes
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

    # Slotted in once every box exists, because a piece may be exported
    # before what it goes under. A piece that refuses to go where the file
    # says is left lying on the canvas rather than dropped.
    for entry in payload.get("nodes") or []:
        if not isinstance(entry, dict) or "under" not in entry:
            continue
        piece = made.get(int(entry.get("ref", -1)))
        host = made.get(int(entry.get("under", -1)))
        if piece is None or host is None:
            continue
        try:
            attach(session, piece, host, owner)
        except GraphError:
            continue
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
        # A format-1 file kept every rule on the box. They are pieces now, so
        # the file is unpacked into pieces — the same conversion the database
        # got, said once more for a file somebody exported before it.
        rules = entry.get("rules")
        if isinstance(rules, dict):
            under: GraphNode = node
            for spec in conditions_for("filter"):
                said = rules.get(spec.column)
                if said is None or said == "":
                    continue
                under = add_piece(
                    session, owner, kind=spec.kind, host=under, x=x, y=y + 60
                )
                setattr(under, spec.column, said)
        return node

    if kind == "sort":
        node = add_sort(session, owner, label=label, x=x, y=y)
        if "sort_by" in entry:
            add_piece(
                session, owner, kind="order", host=node, x=x, y=y + 60,
                sort_by=str(entry.get("sort_by") or DEFAULT_SORT_BY),
                newest_first=str(entry.get("sort_dir") or "desc") == "desc",
            )
        return node

    if kind in CONDITION_KINDS:
        piece = add_piece(
            session, owner, kind=kind, x=x, y=y,
            sort_by=str(entry.get("value") or DEFAULT_SORT_BY),
            newest_first=str(entry.get("sort_dir") or "desc") == "desc",
        )
        said = condition(kind)
        if said is not None and kind != "order" and entry.get("value") not in (None, ""):
            setattr(piece, said.column, entry.get("value"))
        return piece

    if kind in AUGMENTATIONS:
        return add_piece(
            session, owner, kind=kind, x=x, y=y,
            duration_minutes=entry.get("duration_minutes"),
            cron=str(entry.get("cron") or "") or None,
            alive=(str(entry.get("alive_from") or ""), str(entry.get("alive_to") or "")),
            ref=str(entry.get("plugin_ref") or ""),
        )

    if kind in ("deposit", "withdraw"):
        return add_store(
            session, owner, kind=kind,
            repository=str(entry.get("repository") or ""),
            takes=entry.get("takes"), x=x, y=y,
        )

    if kind in STAMPS:
        return add_stamp(
            session, owner, kind=kind, marks=str(entry.get("marks") or ""), x=x, y=y
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
# that has nothing to do with filtering. A format-1 file's rules are read
# against this before being unpacked into pieces.
FILTER_RULES = tuple(one.column for one in CONDITIONS if one.under == "filter")


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
    from ..models import RepositoryItem

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
    from . import sync as sync_service

    def seen(passed: bool, reason: str | None) -> Judged:
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
    refusal = sync_service._decide(video, own, None, settings)
    if not refusal.accept:
        return seen(False, refusal.reason), start.id

    for index, node in enumerate(path.filters):
        so_far = Route(
            channel=path.channel, playlist=path.playlist,
            filters=path.filters[: index + 1], slots=path.slots,
        )
        decision = sync_service._decide(video, so_far, None, settings)
        if not decision.accept:
            return seen(False, decision.reason), node.id

    decision = sync_service._decide(video, path, None, settings)
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
    for node_id in node_ids:
        seen.setdefault(node_id, []).append(judged)


def _ranked(video: Video, order: GraphNode) -> tuple[float, int]:
    """Where this video lands in a sorted batch, as the sort box sees it."""
    from . import sync as sync_service

    value = sync_service.ordering_value(video, order)
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


def add_stamp(
    session: Session,
    owner: OwnerId = None,
    *,
    kind: str,
    marks: str = "",
    x: int | None = None,
    y: int = 40,
) -> GraphNode:
    """A box that marks what passes through it rather than narrowing it."""
    if kind not in STAMPS:
        raise GraphError(f"There is no {kind} box.")
    node = GraphNode(
        owner_pk=owner,
        kind=kind,
        marks=tag_name(marks) or None if kind == "tag" else None,
        x=COLUMN_X["filter"] if x is None else x,
        y=y,
    )
    session.add(node)
    session.flush()
    return node


def tag_name(raw: str | None) -> str:
    """A tag as it is filed: trimmed, squeezed, lowercased.

    The same treatment a repository name gets, and for the same reason — a
    Tag box and a Filter box that disagreed about capitals would be two
    boxes that look joined up and are not.
    """
    return " ".join((raw or "").split()).lower()[:40]


def pieces_of(session: Session, owner: OwnerId = None) -> Any:
    """A way to ask what is slotted under a box, read once for a whole run.

    Handed to the `stamped_*` readers rather than each of them walking the
    canvas again: a fill pass asks about the same boxes once per item.
    """
    all_nodes = nodes(session, owner)
    return lambda node: pieces_under(all_nodes, node.id)


def stamped_seconds(stamps: list[GraphNode], pieces_for: Any) -> int | None:
    """How long a Decay box on this path gives you with an item, in seconds.

    The shortest of them where several disagree: a Decay box is a limit, and
    two limits mean the tighter one. None when no Decay box said anything,
    which leaves the account's own setting alone.
    """
    shortest: int | None = None
    for node in stamps:
        if node.kind != "decay" or not node.enabled:
            continue
        minutes = _timer_minutes(pieces_for(node))
        if minutes is None:
            continue
        seconds = max(1, minutes * 60)
        shortest = seconds if shortest is None else min(shortest, seconds)
    return shortest


def stamped_locked(stamps: list[GraphNode], pieces_for: Any) -> bool:
    """Whether any Decay box on this path was told its time cannot be held.

    A Lock piece under it. Any one of them saying so is enough: a stretch
    that can be paused somewhere else is not a stretch you cannot pause.
    """
    for node in stamps:
        if node.kind != "decay" or not node.enabled:
            continue
        if any(one.kind == "lock" and one.enabled for one in pieces_for(node)):
            return True
    return False


def stamped_life(stamps: list[GraphNode], pieces_for: Any) -> int | None:
    """How long an Expire box on this path lets an item stay, in minutes.

    The shortest again, and for the same reason.
    """
    shortest: int | None = None
    for node in stamps:
        if node.kind != "expire" or not node.enabled:
            continue
        minutes = _timer_minutes(pieces_for(node))
        if minutes is None:
            continue
        shortest = minutes if shortest is None else min(shortest, minutes)
    return shortest


def stamp_marks(stamps: list[GraphNode], pieces_for: Any) -> list[str]:
    """What these boxes would leave on an item, said the way they say it.

    The same words the boxes themselves carry, so a trial and the canvas
    agree about what is going to happen — and the same words a card shows
    afterwards, so it is recognisable when it gets there.
    """
    said = [f"“{one}”" for one in stamped_tags(stamps)]

    seconds = stamped_seconds(stamps, pieces_for)
    if seconds is not None:
        spoken = f"{seconds}s" if seconds < 60 else f"{round(seconds / 60)} min"
        said.append(spoken + (" · no pause" if stamped_locked(stamps, pieces_for) else ""))

    minutes = stamped_life(stamps, pieces_for)
    if minutes is not None:
        said.append(f"gone {every_words(minutes)} after it arrives")
    return said


def stamped_tags(stamps: list[GraphNode]) -> list[str]:
    """Every tag the boxes on this path put on what passes."""
    found: list[str] = []
    for node in stamps:
        if node.kind != "tag" or not node.enabled:
            continue
        named = tag_name(node.marks)
        if named and named not in found:
            found.append(named)
    return found


def _timer_minutes(pieces: list[GraphNode]) -> int | None:
    """What the Timer slotted under a box says, in minutes.

    The nearest one, the same rule a Timer under a feed lives by. None when
    there is no Timer: a Decay or Expire box with nothing slotted into it
    has been put on the canvas and not yet told anything.
    """
    for piece in pieces:
        if piece.kind == "timer" and piece.enabled:
            return max(1, piece.duration_minutes or DEFAULT_DURATION_MINUTES)
    return None


def add_piece(
    session: Session,
    owner: OwnerId = None,
    *,
    kind: str,
    host: GraphNode | None = None,
    duration_minutes: int | None = None,
    cron: str | None = None,
    alive: tuple[str, str] | None = None,
    ref: str = "",
    settings: dict[str, str] | None = None,
    sort_by: str = "",
    newest_first: bool = True,
    x: int = 0,
    y: int = 0,
) -> GraphNode:
    """An augmentation, slotted under a box if one was named.

    Its own position is kept for the moment it is unslotted: a piece that is
    attached is drawn under its host and does not use it, but a piece nobody
    has slotted anywhere has to be somewhere.

    A condition piece starts empty, which is a condition that narrows
    nothing: it is dropped on a box first and told what it means second, the
    same way a Tag box is dropped before it is named.
    """
    if kind not in AUGMENTATIONS:
        raise GraphError(f"There is no {kind} piece.")
    if kind == RULE and not ref:
        raise GraphError("A plugin condition has to say which one it is.")
    ends = alive or DEFAULT_ALIVE
    piece = GraphNode(
        owner_pk=owner,
        kind=kind,
        duration_minutes=duration_minutes if kind == "timer" else None,
        cron=(cron or DEFAULT_CRON) if kind == "reset" else None,
        alive_from=clock_time(ends[0]) if kind == "alive" else None,
        alive_to=clock_time(ends[1]) if kind == "alive" else None,
        plugin_ref=ref or None if kind == RULE else None,
        plugin_settings=(
            json.dumps(settings) if kind == RULE and settings else None
        ),
        sort_by=check_sort_key(sort_by or DEFAULT_SORT_BY) if kind == "order" else None,
        sort_dir=("desc" if newest_first else "asc") if kind == "order" else None,
        x=x,
        y=y,
    )
    session.add(piece)
    session.flush()
    if host is not None:
        # A piece has to exist before it can be slotted in — it is found by
        # id — so a refused drop has to take it away again. Otherwise saying
        # "that goes under a Sort" would leave the thing it refused lying on
        # the canvas, which is a refusal that did half of what was asked.
        try:
            attach(session, piece, host, owner)
        except GraphError:
            session.delete(piece)
            session.flush()
            raise
    return piece


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
    x: int = COLUMN_X["sort"],
    y: int = 40,
) -> GraphNode:
    """A Sort box, which orders by whatever Order piece is slotted under it.

    It carries no key of its own: a box that ordered by something without
    saying so on the canvas was a box you had to open to read.
    """
    node = GraphNode(owner_pk=owner, kind="sort", label=label, x=x, y=y)
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
    """Rename a box, and the thing behind it if this is its only box.

    A box that stands for a channel or a feed writes the new name through, so
    the rest of the app agrees with the canvas. The sync engine only fills in
    a channel's title when it is blank, so a rename is not undone by the next
    poll.

    Only while it is the only box for that thing, though. A channel may be
    drawn twice — two boxes, wired down two paths that filter differently —
    and writing through would then rename the other box as well. Two boxes
    that rename each other are one box in two places, which is the opposite
    of why you drew the second.
    """
    node = session.scalar(owned(select(GraphNode), GraphNode, owner).where(GraphNode.id == node_pk))
    if node is None:
        raise GraphError("That node is not here.")

    wanted = " ".join(name.split())
    node.label = wanted
    if wanted and stands_alone(session, node, owner):
        if node.kind == "source" and node.channel is not None:
            node.channel.title = wanted
        elif node.kind == "feed" and node.playlist is not None:
            node.playlist.title = wanted
    session.flush()
    return node


def stands_alone(session: Session, node: GraphNode, owner: OwnerId = None) -> bool:
    """Whether this is the only box on the canvas for the thing behind it.

    Which decides what a box is allowed to write through to that thing: with
    one box the canvas and the channel are the same thing said twice, and
    with two they are not.
    """
    if node.kind == "source" and node.channel_pk is not None:
        column, wanted = GraphNode.channel_pk, node.channel_pk
    elif node.kind == "feed" and node.playlist_pk is not None:
        column, wanted = GraphNode.playlist_pk, node.playlist_pk
    else:
        return False
    others = session.scalar(
        owned(select(func.count()).select_from(GraphNode), GraphNode, owner).where(
            column == wanted, GraphNode.id != node.id
        )
    )
    return not others


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

    if node.kind in AUGMENTATIONS:
        # The chain closes up behind it. The column carries a cascade on a
        # database built from scratch, which would take everything below it
        # as well — silently deleting a Reset because a Timer above it was
        # removed.
        _close_up(session, node)
    else:
        # A box's pieces describe that box, so they go with it rather than
        # being left on the canvas slotted into nothing. Said here rather
        # than left to the cascade, which a column added to an existing
        # database does not carry.
        for piece in pieces_under(nodes(session, owner), node.id):
            session.delete(piece)
        session.flush()

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
