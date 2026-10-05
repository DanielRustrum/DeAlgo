"""The Configuration canvas: boxes, pieces and wires."""

from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, owner_column
from .feed import Playlist
from .source import Channel

#: What each condition piece is called. Here rather than in the graph
#: service because a box has to be able to say what it is without anything
#: else being loaded — a model that could not name itself would be a model
#: you cannot read a row of. The graph service builds its table of
#: conditions from this, so the words are written once.
CONDITION_LABELS: dict[str, str] = {
    "has-words": "Title has",
    "lacks-words": "Title lacks",
    "longer-than": "Longer than",
    "shorter-than": "Shorter than",
    "carrying": "Has tag",
    "lacks-tag": "Lacks tag",
    "at-most": "At most",
    "order": "Order",
}


class GraphNode(Base):
    """One box on the Configuration canvas.

    Three kinds, and they differ in what they point at rather than in how they
    are drawn:

    * ``source`` stands for a Channel — where things come from.
    * ``feed`` stands for a Playlist — where they end up.
    * ``group`` stands for nothing either, and is not on any path. It is a
      rectangle drawn behind the others: what it surrounds travels with it,
      and can be exported as a piece of setup to give to somebody else.
    * ``sort`` stands for nothing either. It sits on the path and decides the
      order the batch reaches the feed in — by when a thing was published, how
      long it is, or how many have watched it.
    * ``trigger`` stands for nothing either. It wires into a channel's input
      and says when that channel is polled: every so often (``pulse``) or at a
      time of day (``schedule``). A channel with no trigger wired keeps
      following the account's own sync settings, exactly as before.

      Wired into a feed's second input instead, it says when that feed may be
      read — a window that opens when the trigger comes round and lasts for
      its duration. A feed with none is always open.
    * ``filter`` stands for nothing else at all. It sits on the path between
      them and narrows what gets through, and its columns are the channel's
      own filter columns over again: NULL means "leave the channel's answer
      alone", anything else overrides it for paths through this node.

    Positions live here because where someone put a box is part of what they
    built, and a graph that rearranges itself on every load is unreadable.
    """

    __tablename__ = "graph_node"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_pk: Mapped[Optional[int]] = owner_column()
    kind: Mapped[str] = mapped_column(String(8), index=True)

    # Filter and trigger boxes only. A source or feed box is switched on and
    # off through the channel or playlist behind it, because that is where
    # every other part of the app reads it from.
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    x: Mapped[int] = mapped_column(Integer, default=0)
    y: Mapped[int] = mapped_column(Integer, default=0)
    # Group nodes only: the rest are drawn at whatever size their contents
    # need, and a width on one of those would be a second opinion about it.
    width: Mapped[Optional[int]] = mapped_column(Integer)
    height: Mapped[Optional[int]] = mapped_column(Integer)
    # Group nodes only: held where it is, so pressing it pans the canvas rather
    # than dragging the group and everything it surrounds out of place.
    # A database default too: rows written by raw SQL (migrations, imports) leave it out.
    locked: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))

    # Which part of a group file this box is, so loading a newer copy of the
    # same file can find it again and update it rather than add a second.
    # On a group, the file's own id. Nothing for a box nobody exported.
    group_key: Mapped[Optional[str]] = mapped_column(String(40))
    # Group nodes only: the file it was loaded from, and when, for the panel
    # to say and for "Update from file" to offer.
    imported_from: Mapped[Optional[str]] = mapped_column(String(255))
    imported_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)

    channel_pk: Mapped[Optional[int]] = mapped_column(
        ForeignKey("channel.id", ondelete="CASCADE"), index=True
    )
    playlist_pk: Mapped[Optional[int]] = mapped_column(
        ForeignKey("playlist.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(120), default="")

    # Condition pieces only. Every one nullable: NULL is "inherit", which is
    # what makes a condition an override rather than a replacement.
    #
    # One piece uses one of these, and which one is the piece's kind. They
    # sat on the Filter box itself once, which meant a canvas of boxes all
    # saying "Filter" and no way to tell them apart without opening each.
    title_include: Mapped[Optional[str]] = mapped_column(Text)
    title_exclude: Mapped[Optional[str]] = mapped_column(Text)
    # Only items carrying one of these tags get past, and none carrying one
    # of `untagged`: each a comma-separated list. A Tag box earlier on the
    # path, or a hand in the feed, is what puts one on.
    tagged: Mapped[Optional[str]] = mapped_column(String(400))
    untagged: Mapped[Optional[str]] = mapped_column(String(400))
    # Tag boxes: what this one marks whatever comes through it with.
    marks: Mapped[Optional[str]] = mapped_column(String(40))
    min_duration_sec: Mapped[Optional[int]] = mapped_column(Integer)
    max_duration_sec: Mapped[Optional[int]] = mapped_column(Integer)
    max_per_run: Mapped[Optional[int]] = mapped_column(Integer)

    # Plugin condition pieces only. Which condition this is, written
    # "<plugin>:<node>", and whatever its fields were set to as JSON. Stored
    # as the plugin's own names rather than columns of our own, because the
    # fields are the plugin's to declare and a column per field is not a
    # thing a plugin can ask for.
    plugin_ref: Mapped[Optional[str]] = mapped_column(String(80))
    plugin_settings: Mapped[Optional[str]] = mapped_column(Text)

    # Augmentations only: the box this one is slotted under. An augmentation
    # has one host and no wires — it changes what it is attached to rather
    # than sitting on a path. They chain, and a chain belongs to whatever is
    # at the top of it: what one changes is always the box, never the piece
    # above it.
    attached_to: Mapped[Optional[int]] = mapped_column(
        ForeignKey("graph_node.id", ondelete="CASCADE"), index=True
    )

    # Deposit and Withdraw boxes only: which repository this one is about.
    # A label two boxes agree on rather than a row of its own, so typing the
    # same name into a second box is how you join them up.
    repository: Mapped[Optional[str]] = mapped_column(String(60))
    # Withdraw boxes only: how many to take each time it is triggered. None
    # or 0 means everything waiting, which is what an empty field says.
    takes: Mapped[Optional[int]] = mapped_column(Integer)

    # Alive pieces only: the two ends of the stretch of the day this one
    # allows, as "HH:MM" in UTC — the same clock the cron fields are read on.
    # Text rather than minutes-since-midnight, so what is stored is what was
    # typed and a row can be read without doing arithmetic first.
    alive_from: Mapped[Optional[str]] = mapped_column(String(5))
    alive_to: Mapped[Optional[str]] = mapped_column(String(5))

    # Source boxes only: which kind of somewhere this box is for. Set when it
    # is dragged out, because there is no one Channel box any more — you pick
    # the kind by picking the box, and an empty box has to remember which one
    # it is between being dropped and being filled in. Once it has a channel
    # the channel's own kind is the truth and this is only how it started.
    source_kind: Mapped[Optional[str]] = mapped_column(String(24))

    # Sort nodes only: what to order the batch by, and which way round.
    sort_by: Mapped[Optional[str]] = mapped_column(String(16))
    sort_dir: Mapped[Optional[str]] = mapped_column(String(4))

    # Trigger nodes only. A "pulse" carries the gap it wants in minutes; a
    # "schedule" carries a cron expression, read in UTC — UTC because that is
    # what every other instant in this file is, and a stored local time would
    # mean something different after a clock change.
    trigger_kind: Mapped[Optional[str]] = mapped_column(String(10))
    every_minutes: Mapped[Optional[int]] = mapped_column(Integer)
    # How long a window this trigger opens when it is wired to a feed's second
    # input. Only read there: wired to a channel it says when to poll, which
    # is an instant rather than a stretch of time.
    duration_minutes: Mapped[Optional[int]] = mapped_column(Integer)
    cron: Mapped[Optional[str]] = mapped_column(String(120))
    # When this trigger last came round: set by the Fire button, and — for a
    # pulse on a feed's second input — by sitting down to read, which is what
    # starts that stretch. One column because it is one fact: a trigger wired
    # to both a channel and a feed goes off for both at once.
    last_fired_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime)

    channel: Mapped[Optional[Channel]] = relationship()
    playlist: Mapped[Optional[Playlist]] = relationship()

    @property
    def title(self) -> str:
        """What the box says on it.

        A renamed box keeps its own name, whatever the thing behind it is
        called. Renaming a channel or a feed writes through to that thing as
        well, so this is only the last word for boxes that stand for nothing.
        """
        if self.label:
            return self.label
        if self.kind == "source" and self.channel is not None:
            return self.channel.title or self.channel.channel_id
        if self.kind == "feed" and self.playlist is not None:
            return self.playlist.title or self.playlist.playlist_id
        if self.kind == "trigger":
            return "Schedule" if self.trigger_kind == "schedule" else "Pulse"
        if self.kind == "sort":
            return "Sort"
        if self.kind == "timer":
            return "Timer"
        if self.kind == "reset":
            return "Reset"
        if self.kind == "alive":
            return "Alive"
        if self.kind == "lock":
            return "Lock"
        if self.kind == "after-watch":
            return "After watching"
        if self.kind in ("deposit", "withdraw"):
            # Named after the repository it is about: two Deposit boxes only
            # mean the same thing when they carry the same name, so the name
            # is the useful half of what to call them.
            named = (self.repository or "").strip()
            doing = "Deposit" if self.kind == "deposit" else "Withdraw"
            return f"{doing}: {named}" if named else doing
        if self.kind == "tag":
            # Named after the tag it puts on, for the same reason a Deposit
            # box is named after its repository: on a canvas with three of
            # them, which one this is, is the useful half.
            named = (self.marks or "").strip()
            return f"Tag: {named}" if named else "Tag"
        if self.kind == "decay":
            return "Decay"
        if self.kind == "expire":
            return "Expire"
        if self.kind == "group":
            return "Group"
        if self.kind == "rule":
            # From the piece's own name rather than from the registry: a model
            # that had to ask which plugins are loaded in order to say what a
            # piece is called would be a model that cannot be read on its own.
            # "shape:not-shouting" reads back as "Not shouting".
            named = (self.plugin_ref or "").split(":")[-1].replace("-", " ").replace("_", " ")
            return named[:1].upper() + named[1:] if named else "Rule"
        # A condition piece. Its name is the whole of what it is — a box
        # saying "Filter" told you nothing, a piece saying "Longer than"
        # tells you what that box does without opening it.
        named = CONDITION_LABELS.get(self.kind, "")
        if named:
            return named
        # An empty box, waiting to be told what it stands for. Named after
        # the kind it was dragged out as, so a canvas with three empty boxes
        # on it says which is which.
        if self.kind == "source":
            named = (self.source_kind or "").strip()
            return f"New {named}" if named else "New channel"
        return "New feed" if self.kind == "feed" else "Filter"

    @property
    def overrides(self) -> dict[str, object]:
        """Only what this node actually decides, so "inherit" stays visible.

        Read off a condition piece now rather than off a filter box: a piece
        carries exactly one of these, which is what makes it one condition.
        """
        named = (
            "title_include", "title_exclude", "tagged", "untagged",
            "min_duration_sec", "max_duration_sec", "max_per_run",
        )
        return {name: getattr(self, name) for name in named if getattr(self, name) is not None}


class GraphEdge(Base):
    """A wire from one box to another.

    Direction matters: things flow from ``source_pk`` to ``target_pk``. What
    is a legal pairing is the graph service's business, not the schema's —
    the schema only refuses the same wire twice.
    """

    __tablename__ = "graph_edge"
    __table_args__ = (UniqueConstraint("source_pk", "target_pk", name="uq_edge_source_target"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_pk: Mapped[Optional[int]] = owner_column()
    source_pk: Mapped[int] = mapped_column(
        ForeignKey("graph_node.id", ondelete="CASCADE"), index=True
    )
    target_pk: Mapped[int] = mapped_column(
        ForeignKey("graph_node.id", ondelete="CASCADE"), index=True
    )

    source: Mapped[GraphNode] = relationship(foreign_keys=[source_pk])
    target: Mapped[GraphNode] = relationship(foreign_keys=[target_pk])
