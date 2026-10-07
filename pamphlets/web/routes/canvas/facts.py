"""What each kind of box shows about itself, worked out for the canvas."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from .... import sources
from ....models import (
    Channel,
    GraphNode,
    Video,
    utcnow,
)
from ....plugins import registry
from ....services import graph as graph_service
from ....services import sync as sync_service
from ....services.scope import OwnerId, owned
from ...contexts import feed_window_words
from ...templates import Context


def box_title(node: GraphNode, asks: Context | None) -> str:
    """What a box calls itself on the canvas."""
    if asks is None or not asks.get("label"):
        return node.title
    return f"New {asks['label']}"


def store_facts(session: Session, node: GraphNode, owner: OwnerId) -> Context:
    """What a Deposit or Withdraw box is about, and how full it is.

    The count is the useful fact on both: on a Deposit it says how much has
    piled up, and on a Withdraw it says how much the next pull would find.
    """
    name = graph_service.store_name(node.repository)
    return {
        "name": name,
        "waiting": sync_service.waiting_in(session, name, owner) if name else 0,
        # Withdraw boxes only. 0 means everything waiting.
        "takes": node.takes or 0,
        "pulls": node.kind == "withdraw",
    }


def asks_for(node: GraphNode) -> Context | None:
    """What an empty source box is for, and what to type into it.

    None for a tag box and for one that already has its channel: neither is
    asking anything. A box from before sources had kinds has no kind to
    report, and the canvas offers it the one thing that still makes sense —
    something already being watched.
    """
    if node.channel_pk:
        return None
    wanted = (node.source_kind or "").strip()
    if not wanted:
        return {
            "kind": "", "label": "", "source": "", "example": "", "known": False, "colour": "",
        }
    known = sources.describe(wanted)
    return {
        "kind": wanted,
        "label": known.noun or known.label,
        # The short one, for the word above the title on the box. A filled
        # box reads the same thing off its channel.
        "source": known.label,
        "example": known.example,
        "colour": known.colour,
        # False when the plugin that offered this kind has been switched off
        # or removed, which is worth saying rather than drawing an empty box
        # that refuses everything typed into it.
        "known": any(one.name == wanted for one in sources.all_kinds()),
    }


def every_words_for(node: GraphNode) -> Context:
    """A Timer's amount and unit, and the units it could be said in."""
    amount, unit = graph_service.split_every(
        node.duration_minutes or graph_service.DEFAULT_DURATION_MINUTES
    )
    return {
        "amount": amount,
        "unit": unit,
        "units": [
            {"name": name, "label": label}
            for name, _, label in graph_service.EVERY_UNITS
        ],
    }


def every_parts(node: GraphNode) -> Context:
    """A pulse's gap as an amount, a unit, and the units it could be said in."""
    amount, unit = graph_service.split_every(
        node.every_minutes or graph_service.DEFAULT_EVERY_MINUTES
    )
    return {
        "amount": amount,
        "unit": unit,
        "units": [
            {"name": name, "label": label} for name, _, label in graph_service.EVERY_UNITS
        ],
    }


def next_firing(node: GraphNode) -> str | None:
    """When a schedule next comes round, so the box can be checked at a glance.

    A cron expression is easy to get subtly wrong, and the honest way to show
    what one means is to say when it would actually go off.
    """
    if node.trigger_kind != "schedule":
        return None
    try:
        trigger = graph_service.cron_trigger(node.cron or graph_service.DEFAULT_CRON)
    except graph_service.GraphError:
        return None
    when = trigger.get_next_fire_time(None, dt.datetime.now(dt.timezone.utc))
    return when.isoformat() if when is not None else None


def is_on(node: GraphNode) -> bool:
    """Whether this box is doing anything.

    Both halves have to say so. The box's own switch is what one box says;
    the channel or playlist behind it is whether there is anything to say it
    about — a box for a channel nobody watches does nothing however it is
    switched, and a second box for the same channel can be off while this
    one is on.
    """
    if not node.enabled:
        return False
    if node.kind == "source":
        return node.channel.enabled if node.channel is not None else False
    if node.kind == "feed":
        return node.playlist.enabled if node.playlist is not None else False
    return True


def feed_facts(node: GraphNode, windows: list[GraphNode]) -> Context | None:
    """How a feed fills: whether it is taking anything, and how much.

    The same two things its own page calls Filling. Read off the box's own
    playlist rather than counted, so there is no query per feed.
    """
    playlist = node.playlist
    if playlist is None:
        return None
    return {
        "enabled": playlist.enabled,
        "max_items": playlist.max_items,
        "max_per_run": playlist.max_per_run,
        "generic": playlist.is_generic,
        # When it may be read. Empty means always, which is what a feed with
        # no pieces slotted under it has always been.
        "windows": feed_window_words(windows),
        "open": graph_service.is_open(windows, utcnow()),
    }


def channel_facts(session: Session, owner: OwnerId) -> dict[int, Context]:
    """What each channel does, for the box that stands for it.

    What it takes, when it was last looked at, and how much it has placed.
    Not what it fills: the wires out of the box already say that, and saying
    it twice invites the two to disagree. Counted for every channel at once
    rather than per box, which would be one pair of queries per box.
    """
    def tally(*conditions: ColumnElement[bool]) -> dict[int, int]:
        """How many items meet `conditions`, per source."""
        rows = session.execute(
            owned(select(Video.channel_pk, func.count(Video.id)), Video, owner)
            .where(*conditions)
            .group_by(Video.channel_pk)
        )
        return {channel_pk: held for channel_pk, held in rows if channel_pk is not None}

    placed = tally(Video.status == "added")
    pending = tally(Video.status == "pending")

    channels = session.scalars(owned(select(Channel), Channel, owner))
    return {
        channel.id: {
            # What kind of somewhere it is.
            "source": sources.describe(channel.source_kind).label,
            # The colour its plugin chose, for the bar down the box.
            "colour": sources.describe(channel.source_kind).colour,
            # Whether a second address for its feed is worth offering.
            "mirrors": sources.describe(channel.source_kind).mirrors,
            "feed_url": channel.feed_url,
            "mirror": channel.mirror_url,
            # What to paste, for the kinds where somebody is known to publish
            # the same feed. A field you have to go and research is a field
            # nobody fills in.
            "mirror_hint": sources.suggest_mirror(channel.source_kind, channel.channel_id),
            # The kinds of content its plugin says it publishes, each with
            # whether this source takes it. Empty: it takes everything.
            "takes": [
                {"name": one.name, "label": one.label, "on": one.name not in left_out}
                for one in channel.takes
                for left_out in (channel.left_out_names,)
            ],
            # When it is next looked at is the trigger's business, and the
            # channel's own gap only applies while none is wired — so the box
            # says when it last happened and leaves the rest to `polled`.
            "enabled": channel.enabled,
            # A REST API source's mapping, for its box to show and change.
            # Its header's value never leaves the server: only whether one is set.
            "rest": (
                {
                    **sources.rest.Mapping.loads(channel.source_options).public(),
                    "has_key": bool(sources.rest.Mapping.loads(channel.source_options).header_value),
                    "error": channel.last_error or "",
                }
                if channel.source_kind == "rest" else None
            ),
            "checked": _instant(channel.last_checked_at),
            "placed": placed.get(channel.id, 0),
            "pending": pending.get(channel.id, 0),
        }
        for channel in channels
    }


def _instant(when: dt.datetime | None) -> str | None:
    """Naive UTC in the database becomes an instant the browser can read.

    Not the ``stamp`` filter above, which formats for a page; this is for the
    canvas, which does its own formatting on the reader's own clock.
    """
    return None if when is None else when.replace(tzinfo=dt.timezone.utc).isoformat()


def how_polled(node: GraphNode, plan: dict[int, list[graph_service.When]]) -> str:
    """What decides when this channel is polled, in a sentence.

    Worth spelling out on the box rather than leaving to be inferred from the
    wires: a channel with nothing wired to it and one with a trigger wired
    look much the same on a canvas and are polled on different clocks.
    """
    wired = None if node.channel_pk is None else plan.get(node.channel_pk)
    if not wired:
        return "Nothing polls this. Wire a trigger into it, or it just sits here."
    return "Polled by " + _join_clauses([_when_clause(when) for when in wired]) + "."


def _when_clause(when: graph_service.When) -> str:
    """One trigger's schedule, as a clause: "a pulse every 2 hours"."""
    if when.kind == "schedule":
        return f"a schedule on “{when.cron or graph_service.DEFAULT_CRON}”"
    gap = when.every_minutes or graph_service.DEFAULT_EVERY_MINUTES
    return f"a pulse every {graph_service.every_words(gap)}"


def _join_clauses(parts: list[str]) -> str:
    """Clauses joined as "a, b and c"."""
    if len(parts) <= 2:
        return " and ".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def known_tags(session: Session, nodes: list[GraphNode], owner: OwnerId) -> list[str]:
    """Every tag there is to ask for: what the Tag boxes put on, and what
    anything already carries, marked by a box or by hand. Offered under a
    tag condition so one can be picked rather than remembered."""
    found = {graph_service.tag_name(node.marks) for node in nodes if node.kind == "tag"}
    for said in session.scalars(
        owned(select(Video.tags).distinct(), Video, owner).where(Video.tags.is_not(None))
    ):
        found.update(graph_service.tag_names(said))
    found.discard("")
    return sorted(found)


def condition_facts(node: GraphNode, tags: list[str] | None = None) -> Context | None:
    """What one condition piece is, and what it is set to.

    None for anything that is not one. The shape is the same for every
    condition — a label, a kind of field, and what is in it — so the canvas
    draws them all one way and none of them needs code of its own.
    """
    spec = graph_service.condition(node.kind)
    if spec is None:
        return None
    raw = getattr(node, spec.column, None)
    amount, unit = (
        graph_service.split_length(int(raw))
        if spec.field == "duration" and raw
        else ("", graph_service.LENGTH_UNITS[1][0])
    )
    return {
        "kind": node.kind,
        "label": spec.label,
        "blurb": spec.blurb,
        "field": spec.field,
        "asks": spec.asks,
        "under": spec.under,
        "value": "" if raw is None else str(amount if spec.field == "duration" else raw),
        "unit": unit,
        "units": [name for name, _ in graph_service.LENGTH_UNITS],
        "says": graph_service.condition_words(node),
        # A tag condition offers what there is to pick from.
        "choices": (tags or []) if spec.field == "tags" else [],
    }


def orders(node: GraphNode) -> bool:
    """Whether this piece is what puts a batch in order.

    The app's own Order piece, or a plugin's ordering — both are slotted
    under a Sort and both answer where an item goes, so the panel asks them
    the same thing.
    """
    if node.kind == "order":
        return True
    if node.kind != graph_service.RULE:
        return False
    found = registry.current().augmentation(node.plugin_ref or "")
    return found is not None and found.orders


def plugin_facts(node: GraphNode) -> Context | None:
    """What a plugin's condition asks, and what its fields are set to.

    None when the plugin is switched off or gone: the piece stays drawn and
    stops narrowing anything, and the canvas says which plugin it is waiting
    for rather than showing an empty form.
    """
    ref = node.plugin_ref or ""
    box = registry.current().augmentation(ref)
    was = sync_service.plugin_settings(node)
    if box is None:
        plugin_id = ref.split(":", 1)[0] if ":" in ref else ref
        return {"ref": ref, "missing": plugin_id or "a plugin", "fields": [], "blurb": ""}
    return {
        "ref": ref,
        "missing": None,
        "blurb": box.blurb,
        "plugin": box.plugin,
        # Which of the app's boxes it slots under, so a loose one can say
        # where it goes rather than leaving somebody to try it and find out.
        "under": box.under,
        "fields": [
            {
                "name": one.name,
                "label": one.label,
                "type": one.type,
                "value": was.get(one.name, one.default),
                "placeholder": one.placeholder,
            }
            for one in box.fields
        ],
    }
