"""Setting a trigger off, and marking the canvas while its run is going."""

from __future__ import annotations

import threading

from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ....db import session_scope
from ....models import (
    GraphNode,
    utcnow,
)
from ....services import graph as graph_service
from ....services import sync as sync_service
from ....services.scope import OwnerId, owned
from ...responses import owner_of
from ...templates import Context
from .payload import graph_payload

router = APIRouter()


@router.post("/graph/nodes/{node_pk}/fire")
def graph_fire(request: Request, node_pk: int) -> JSONResponse:
    """Press a trigger: poll the channels it is wired to, and only those.

    Forced, because pressing it is the whole schedule — a gap that has not
    elapsed is not a reason to ignore somebody's finger. It runs in a thread
    like every other sync, so the answer comes back before the polling does.
    """
    return _set_off(request, node_pk, reach_back=None)


@router.post("/graph/nodes/{node_pk}/backfill")
def graph_backfill(request: Request, node_pk: int, count: str = Form("")) -> JSONResponse:
    """The same, running through the latest ``count`` posts of each source.

    A poll takes what is new. This takes that many whatever their age, and
    brings back what an earlier run passed over for being older than the
    backfill window allowed — which is what somebody means by "catch me up".

    An unreadable count means as far as the feeds go, which is the most the
    button could ever have done and so cannot surprise anybody.
    """
    wanted = count.strip()
    return _set_off(request, node_pk, reach_back=int(wanted) if wanted.isdigit() else 0)


def _set_off(request: Request, node_pk: int, *, reach_back: int | None) -> JSONResponse:
    """Set a trigger off by hand, polling only what it is wired to."""
    owner = owner_of(request)
    with session_scope() as session:
        try:
            targets = graph_service.pulse_targets(session, node_pk, owner)
        except graph_service.GraphError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        node = session.scalar(
            owned(select(GraphNode), GraphNode, owner).where(GraphNode.id == node_pk)
        )
        # The boxes themselves, as well as the channels behind them. Polling
        # is a question about a channel — one poll however many boxes draw it
        # — and filing is a question about a box, because each starts a path
        # of its own. A trigger reaches one of them, not both.
        boxes = (
            graph_service.wired_sources(session, node, owner) if node is not None else []
        )
        # A trigger may be wired to sources, to Withdraw boxes, or to both.
        # Pulling needs no network and no quota, so it happens here rather
        # than in the thread — and a trigger wired only to a Withdraw box has
        # something to do without a sync running at all.
        pulling = (
            graph_service.wired_withdrawals(session, node, owner) if node is not None else []
        )
        if not targets and not pulling:
            return JSONResponse(
                {"error": "Nothing is wired to that trigger yet."}, status_code=400
            )

        if node is not None:
            node.last_fired_at = utcnow()
        session.flush()
        payload = graph_payload(session, owner)
        pulled = [one.id for one in pulling]

    if sync_service.is_running():
        return JSONResponse({**payload, "said": "A sync is already running."})

    # Claimed here rather than in the thread: the canvas asks where the run
    # has got to as soon as this answers, and a thread takes a moment to get
    # going. Without the claim it would be told about the previous run, which
    # reads as this one having finished instantly.
    trigger = "pulse" if reach_back is None else "backfill"
    if not targets:
        # Nothing to poll, so nothing to run in a thread: pull now and answer
        # with what came out.
        with session_scope() as session:
            said = sync_service.withdraw_now(session, pulled, owner)
            payload = graph_payload(session, owner)
        return JSONResponse({**payload, "said": said})

    token = sync_service.claim(owner, trigger, node_pk)
    threading.Thread(
        target=sync_service.run_sync,
        args=(trigger,),
        kwargs={
            "force": True,
            "owner": owner,
            "only": frozenset(targets),
            "sources": frozenset(boxes),
            "fired_by": node_pk,
            "reach_back": reach_back,
            "withdrawals": pulled,
            "token": token,
        },
        daemon=True,
    ).start()
    where = f"{len(targets)} channel{'s' if len(targets) != 1 else ''}"
    if reach_back is None:
        said = f"Polling {where}…"
    elif reach_back > 0:
        said = f"Reaching back through the latest {reach_back} of {where}…"
    else:
        said = f"Reaching back as far as {where} still list…"
    return JSONResponse({**payload, "said": said})


@router.get("/api/graph/run")
def graph_run_state(request: Request) -> JSONResponse:
    """Where the run in flight has got to, said in boxes rather than rows.

    The canvas asks for this while something is running, so the drawing can
    show the work moving through it instead of going still for a minute and
    then changing all at once.

    It reports on the boxes that exist rather than drawing any: this is asked
    for once a second, and a GET that writes to the database is a poor thing
    to run on a timer.
    """
    owner = owner_of(request)
    state = sync_service.progress()
    running = sync_service.is_running()
    if state is None or (state.owner != owner and state.owner is not None):
        return JSONResponse({"running": running, "stage": None, "nodes": {}})

    with session_scope() as session:
        marks = _run_marks(session, state, owner)

    return JSONResponse(
        {
            # A claimed run counts as running even before its thread has taken
            # the lock, so the canvas follows it from the first moment rather
            # than deciding on its first look that it was already over. Whose
            # run it is was settled above.
            "running": running or not state.finished,
            "stage": state.stage,
            "trigger": state.trigger,
            "nodes": marks,
        }
    )


def _run_marks(
    session: Session, state: sync_service.RunProgress, owner: OwnerId
) -> dict[str, Context]:
    """What the run did at each box it actually reached.

    Reached means something arrived, not that a wire leads there. A channel
    that found nothing sends nothing on, so the boxes after it took no part in
    the run and are left unmarked — which is how the drawing says the flow
    stopped at the channel.
    """
    boxes = graph_service.nodes(session, owner)
    set_off = _trigger_targets(session, boxes, owner)
    # Which channels each source node stands for: one for a channel node, and
    # however many carry the tag for a tag node.
    stands_for = {
        node.id: [channel.id for channel in graph_service.channels_of(session, node, owner)]
        for node in boxes
        if node.kind == "source"
    }

    marks: dict[str, Context] = {}
    for node in boxes:
        mark = _mark_for(node, state, set_off.get(node.id, []), stands_for.get(node.id, []))
        if mark is not None:
            marks[str(node.id)] = mark

    # Whatever is happening this second outranks whatever came before it.
    for node_id, channels in stands_for.items():
        if state.channel_pk is not None and state.channel_pk in channels:
            marks[str(node_id)] = _busy()
    if state.fired_by is not None and not state.finished:
        marks[str(state.fired_by)] = _busy()
    return marks


def _trigger_targets(
    session: Session, boxes: list[GraphNode], owner: OwnerId
) -> dict[int, list[int]]:
    """The channels each trigger box is wired to, by trigger node id."""
    by_id = {node.id: node for node in boxes}
    wired: dict[int, list[int]] = {}
    for edge in graph_service.edges(session, owner):
        start, end = by_id.get(edge.source_pk), by_id.get(edge.target_pk)
        if start is None or end is None or start.kind != "trigger":
            continue
        if end.kind == "source":
            # A tag node is several channels, and a trigger on it sets off all
            # of them.
            for channel in graph_service.channels_of(session, end, owner):
                wired.setdefault(start.id, []).append(channel.id)
    return wired


def _busy() -> Context:
    """The mark for a box the run is working on now."""
    # The same shape as a finished mark, so the canvas reads one kind of thing.
    return {"state": "busy", "count": 0, "stopped": 0, "ends": False, "trouble": None}


def _mark_for(
    node: GraphNode,
    state: sync_service.RunProgress,
    targets: list[int],
    stands_for: list[int],
) -> Context | None:
    """One box's share of the run, or None if nothing of the run got to it.

    ``count`` is what left the box and ``stopped`` is what it held. A box that
    held things and passed none on is where the flow ended, and says so.
    """
    if node.kind == "trigger":
        if node.id != state.fired_by:
            return None
        # Its own channels, not the run's: a trigger wired to a channel that
        # is switched off set nothing off, however busy the rest of the run
        # was, and saying "nothing new" would credit it with a look it never
        # took.
        reached = [channel_pk for channel_pk in targets if channel_pk in state.polled]
        if reached:
            return mark_box(len(reached), 0)
        # It went, and could not get in. That is a different thing from a
        # trigger that never set off, and the two used to read the same.
        failed = [why for pk, why in state.unreachable.items() if pk in targets]
        if failed:
            return mark_box(0, 0, ends=True, trouble=_one_voice(failed))
        return mark_box(0, 0, ends=True)

    if node.kind == "source":
        # Every channel it stands for, added up: a tag node is one box over
        # several channels, and reports what all of them did.
        polled = [channel_pk for channel_pk in stands_for if channel_pk in state.polled]
        if not polled:
            failed = [why for pk, why in state.unreachable.items() if pk in stands_for]
            if failed:
                return mark_box(0, 0, ends=True, trouble=_one_voice(failed))
            return None
        found = sum(state.polled.get(channel_pk, 0) for channel_pk in polled)
        left = sum(state.left.get(channel_pk, 0) for channel_pk in polled)
        return mark_box(left, max(0, found - left))

    if node.kind == "filter":
        passed = state.through.get(node.id, 0)
        held = state.stopped.get(node.id, 0)
        # Nothing came either way: the flow never got this far.
        return mark_box(passed, held) if passed or held else None

    taken = state.placed.get(node.playlist_pk or 0, 0)
    return mark_box(taken, 0) if taken else None


def _one_voice(reasons: list[str]) -> str:
    """One line for however many channels failed the same way."""
    first = reasons[0]
    rest = len(reasons) - 1
    return first if rest == 0 else f"{first} (and {rest} more like it)"


def mark_box(
    count: int, stopped: int, *, ends: bool | None = None, trouble: str | None = None
) -> Context:
    """One box's answer. ``ends`` is worked out unless a box knows better.

    A filter knows it ended the flow because it held things back. A trigger
    knows because nothing it is wired to was polled, and it has nothing to
    hold — so it says so rather than being read as having found nothing.

    ``trouble`` is why it could not look at all, which is a third thing again:
    not "nothing was there" and not "this is where it stopped", but "it went
    and could not get in".
    """
    stopping = (count == 0 and stopped > 0) if ends is None else ends
    return {
        "state": "done",
        "count": count,
        "stopped": stopped,
        "ends": stopping,
        "trouble": trouble,
    }
