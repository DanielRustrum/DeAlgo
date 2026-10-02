"""Testing a flow without running it, and what a Filter is holding back."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ....db import get_settings, session_scope
from ....models import (
    GraphNode,
    SyncRun,
    utcnow,
)
from ....services import graph as graph_service
from ....services import runlog
from ....services.scope import OwnerId, owned
from ...responses import owner_of
from ...templates import Context
from .running import mark_box

router = APIRouter()


@router.get("/graph/nodes/{node_pk}/test")
def graph_try(request: Request, node_pk: int) -> JSONResponse:
    """What this trigger's run would do, without doing it.

    Asked of a trigger because a trigger is what starts a run: it already
    knows which channels it sets off, and those are the ones worth asking
    about. The boxes are marked exactly as a real run marks them, so the
    drawing says the same thing either way — the difference is that nothing
    is written and nothing reaches YouTube.
    """
    owner = owner_of(request)
    with session_scope() as session:
        node = session.scalar(
            owned(select(GraphNode), GraphNode, owner).where(GraphNode.id == node_pk)
        )
        if node is None or node.kind != "trigger":
            return JSONResponse({"error": "That node is not a trigger."}, status_code=400)

        # The boxes, not the channels behind them: a channel drawn twice is
        # one channel and two boxes, and this trigger reaches one of them.
        reaches = graph_service.wired_sources(session, node, owner)
        # The other half of what a trigger can set off. A trigger wired only
        # to a Withdraw box has plenty to say about what a run would do, and
        # asking only about channels answered that it had nothing.
        pulls = [one.id for one in graph_service.wired_withdrawals(session, node, owner)]
        if not reaches and not pulls:
            return JSONResponse(
                {"error": "Nothing is wired to that trigger yet."}, status_code=400
            )

        trial = graph_service.try_it(
            session, get_settings(session, owner), owner,
            sources=reaches, pulls=pulls,
        )
        boxes = {entry.id: entry for entry in graph_service.nodes(session, owner)}

        # Every box the trial touched carries its own share of it, so each can
        # answer for itself rather than sending the reader back to the trigger.
        touched = set(trial.through) | set(trial.held)
        marks = {
            str(node_id): mark_box(
                len(trial.through.get(node_id, [])), len(trial.held.get(node_id, []))
            )
            for node_id in touched
        }
        items: dict[str, Context] = {
            str(node_id): {
                "through": [_judged(item) for item in trial.through.get(node_id, [])],
                "held": [
                    {**_judged(item), "box": boxes[node_id].title if node_id in boxes else ""}
                    for item in trial.held.get(node_id, [])
                ],
            }
            for node_id in touched
        }

        # The trigger that was asked answers for the whole of it.
        items[str(node.id)] = {
            "through": [
                _judged(item)
                for node_id, landing in trial.through.items()
                if node_id in boxes and boxes[node_id].kind == "feed"
                for item in landing
            ],
            "held": [
                {**_judged(item), "box": boxes[node_id].title if node_id in boxes else ""}
                for node_id, holding in trial.held.items()
                for item in holding
            ],
        }
        # The trigger answers for the whole of it: what arrived at a feed,
        # and what was stopped anywhere along the way. Counting the channels
        # it reaches said nothing at all about a trigger wired to a Withdraw
        # box, which reaches none.
        mine = items[str(node.id)]
        landed, stopped = len(mine["through"]), len(mine["held"])
        marks.setdefault(
            str(node.id), mark_box(landed or len(reaches), stopped)
        )

        _log_the_trial(session, node, trial, boxes, owner)

        return JSONResponse({"trigger": node.title, "nodes": marks, "items": items})


def _log_the_trial(
    session: Session,
    node: GraphNode,
    trial: graph_service.Trial,
    boxes: dict[int, GraphNode],
    owner: OwnerId,
) -> None:
    """Write a trial into the log like any other run.

    A trial writes nothing to a feed and sends nothing to YouTube, and that is
    the whole point of it — but "I pressed Test and it said nothing useful" is
    a thing that happens, and it is answered by the same log that answers it
    for a real run. The row says it wrote nothing, so nobody reads it as one.
    """
    run = SyncRun(
        owner_pk=owner,
        trigger="test",
        started_at=utcnow(),
        finished_at=utcnow(),
        forced=False,
        ok=True,
    )
    session.add(run)
    session.flush()

    pen = runlog.Pen(session, run.id, owner)
    pen.at("trial")
    pen.write(f"Test of {node.title} — nothing was written and nothing was sent.")

    landed = held = 0
    for node_id, through in sorted(trial.through.items()):
        box = boxes.get(node_id)
        if box is None or box.kind != "feed":
            continue
        landed += len(through)
        pen.write(f"{len(through)} would land here", about=box.title)
    for node_id, holding in sorted(trial.held.items()):
        box = boxes.get(node_id)
        held += len(holding)
        for item in holding:
            pen.write(
                f"would be held — {item.reason or 'filtered out'}",
                about=f"{box.title if box else '?'} · {item.title}",
                level="warn",
            )

    run.discovered = landed + held
    run.added = landed
    run.skipped = held
    run.message = f"Trial: {landed} would land, {held} would be held back."
    runlog.prune(session, owner)


@router.get("/graph/nodes/{node_pk}/filtered")
def graph_filter_report(request: Request, node_pk: int) -> JSONResponse:
    """What this filter box lets through, and what it holds back."""
    owner = owner_of(request)
    with session_scope() as session:
        try:
            through, held = graph_service.filter_report(
                session, node_pk, get_settings(session, owner), owner
            )
        except graph_service.GraphError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(
            {
                "through": [_judged(item) for item in through],
                "held": [_judged(item) for item in held],
            }
        )


def _judged(item: graph_service.Judged) -> Context:
    return {
        "id": item.video_pk,
        "title": item.title,
        "kind": item.kind,
        "reason": item.reason,
        # What the boxes on this path would leave on it. A trial says what
        # would happen, and these are as much of that as which feed it
        # lands in.
        "marks": item.marks,
    }
