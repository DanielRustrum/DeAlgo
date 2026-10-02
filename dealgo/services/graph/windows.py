"""When a feed may be read: the Timer, Reset and Alive pieces under it."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ...models import (
    GraphNode,
)
from ..scope import OwnerId
from .canvas import load
from .cron import cron_trigger
from .errors import GraphError
from .pieces import pieces_under
from .units import DEFAULT_CRON, DEFAULT_DURATION_MINUTES, as_aware, minutes_of


def alive_now(piece: GraphNode, now: dt.datetime) -> bool:
    """Whether this Alive piece allows the moment it is asked about.

    Read on the clock rather than from when anybody sat down, so it is the
    one piece with an opinion about the hour of the day. A stretch that ends
    before it begins runs through midnight, which is how somebody writes
    "overnight" without being asked to say it twice.

    Two ends the same is the whole day — the reading that cannot accidentally
    shut a feed for ever, which the other one can.
    """
    begins = minutes_of(piece.alive_from)
    ends = minutes_of(piece.alive_to)
    if begins is None or ends is None or begins == ends:
        return True
    minute = as_aware(now).hour * 60 + as_aware(now).minute
    if begins < ends:
        return begins <= minute < ends
    return minute >= begins or minute < ends


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

    if as_aware(now) - as_aware(began) < dt.timedelta(minutes=window):
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
    moment = as_aware(now)
    soonest: dt.datetime | None = None
    for piece in pieces:
        begins = minutes_of(piece.alive_from)
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
    moment = as_aware(now)
    # Strictly after: the firing that started this sitting is not a reason to
    # start another one, and `get_next_fire_time` counts `since` itself.
    came: dt.datetime | None = trigger.get_next_fire_time(None, as_aware(since))
    while came is not None and came <= as_aware(since):
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


def _next_firing(node: GraphNode, now: dt.datetime) -> dt.datetime | None:
    """When a Reset's cron next comes round after `now`, or None."""
    try:
        trigger = cron_trigger(node.cron or DEFAULT_CRON)
    except GraphError:
        return None
    # APScheduler is untyped here; it gives back an aware datetime or nothing.
    when: dt.datetime | None = trigger.get_next_fire_time(None, as_aware(now))
    return when
