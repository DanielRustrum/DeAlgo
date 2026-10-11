"""The canvas's editor: what comes into a box and what goes out of it.

Opened on a data box — Transform, Format, Text, a Chart leaflet — it shows
three panes: what arrived, the box's settings, and what it gives out with
those settings, saved or not. On a source, an operation, a repository or a
feed it shows the two outer panes only; those are set in their own panel.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .... import outgoing
from ....db import session_scope
from ....models import GraphNode
from ....services import charting, writing
from ....services import graph as graph_service
from ....services.graph import formatting, inspecting
from ....services.graph.inspecting import side
from ....services.graph.templating import fill
from ....services.scope import OwnerId, owned
from ....sources import rest
from ...responses import owner_of
from ...templates import TEMPLATES

router = APIRouter()

#: Boxes the editor opens on, and whether their settings are in it.
WITH_SETTINGS = ("transform", "format", "text", "leaflet-chart")
WITHOUT_SETTINGS = ("source", *inspecting.OPERATIONS, "deposit", "withdraw", "feed")


@router.post("/graph/nodes/{node_pk}/inspect")
async def graph_inspect(request: Request, node_pk: int) -> JSONResponse:
    """A box's input and output, with the settings sent rather than those
    saved: `format_*` for a Format box, `leaflet_*` for a Chart leaflet."""
    owner = owner_of(request)
    given = {key: str(value).strip() for key, value in (await request.form()).items()}
    with session_scope() as session:
        node = session.scalar(
            owned(select(GraphNode), GraphNode, owner).where(GraphNode.id == node_pk)
        )
        if node is None or node.kind not in WITH_SETTINGS + WITHOUT_SETTINGS:
            return JSONResponse({"error": "That box has nothing to show here."}, status_code=404)
        problem = read_rest_once(session, node, owner)
        answer = inspect(session, node, owner, given)
        if problem:
            answer["problem"] = problem
        # What each setting with a {{ field }} in it comes to, read from
        # what came in: shown under the setting, as it is typed.
        written = {key: value for key, value in given.items() if "{{" in value}
        if written:
            arrived = raw_input(session, node, owner)
            answer["filled"] = {key: fill(value, arrived) for key, value in written.items()}
        return JSONResponse(answer)


def raw_input(session: Session, node: GraphNode, owner: OwnerId) -> Any:
    """What reaches a box, as it is: what its {{ fields }} are read from."""
    if node.kind == "source":
        return formatting.data_for(session, node)
    if node.kind == "format":
        return formatting.data_into(session, node, owner)
    if node.kind == "leaflet-chart":
        from ..pamphlets import wired_into

        box = wired_into(session, owner, node)
        if box is None:
            return None
        if box.kind == "format":
            return formatting.data_into(session, box, owner)
        return formatting.data_out(session, box, owner)
    return inspecting.arriving(session, node, owner)[0]


def read_rest_once(session: Session, node: GraphNode, owner: OwnerId) -> str:
    """Read a REST source behind this box once, if it has never kept an
    answer, so there is something to show straight away. Says why not."""
    source = node if node.kind == "source" else formatting.data_source(session, node, owner)
    channel = source.channel if source is not None and source.kind == "source" else None
    if channel is None or channel.source_kind != "rest" or channel.raw_snapshot:
        return ""
    try:
        with outgoing.client() as http:
            found = rest.read(channel.feed_url, rest.Mapping.loads(channel.source_options), http)
    except Exception as exc:  # refused, unreachable, not JSON
        return f"Could not read it: {exc}"
    from ....services.sync.polling import keep_snapshot

    keep_snapshot(channel, found.data)
    return ""


def inspect(session: Session, node: GraphNode, owner: OwnerId, given: dict[str, str]) -> dict[str, Any]:
    """Both sides of one box, by kind."""
    kind = node.kind
    off = "" if node.enabled else "Switched off: it passes nothing on."

    if kind == "source":
        rest_source = node.channel is not None and node.channel.source_kind == "rest"
        out = formatting.data_for(session, node)
        return {"input": None, "output": side(
            out, "data" if rest_source else "items",
            "Nothing has come in yet: it is read when it is next checked." if out is None else off,
        )}

    if kind in inspecting.OPERATIONS:
        value, how = inspecting.arriving(session, node, owner)
        return {
            "input": side(value, how or "data", _nothing(how)),
            "output": side(formatting.data_out(session, node, owner), how or "data", off),
        }

    if kind in ("deposit", "withdraw"):
        value, how = inspecting.arriving(session, node, owner)
        return {
            "input": side(value, how or "items", _nothing(how)),
            "output": side(formatting.repository_rows(session, node, owner), "items",
                           "What is waiting in its repository."),
        }

    if kind == "feed":
        value, how = inspecting.arriving(session, node, owner)
        return {"input": side(value, how or "items", _nothing(how)), "output": None}

    if kind == "transform":
        value, how = inspecting.arriving(session, node, owner)
        return {
            "input": side(value, how or "data", _nothing(how)),
            "output": side(formatting.transformed(session, node, owner), "data", off),
        }

    if kind == "text":
        value, how = inspecting.arriving(session, node, owner)
        return {
            "input": side(value, how or "data", _nothing(how)),
            "output": {
                "how": "text", "text": node.written or "",
                "at": node.written_at.isoformat() + "Z" if node.written_at else None,
                "error": writing.last_error(node),
            },
        }

    if kind == "format":
        return _format(session, node, owner, given)
    return _chart(session, node, owner, given)


def _nothing(how: str) -> str:
    return "" if how else "Nothing is wired in."


def _format(session: Session, node: GraphNode, owner: OwnerId, given: dict[str, str]) -> dict[str, Any]:
    spec = formatting.settings(node)
    for key, wanted in given.items():
        if key.startswith("format_") and key[7:] in spec:
            spec[key[7:]] = wanted
    if not str(spec.get("limit", "")).isdigit():
        spec["limit"] = formatting.DEFAULTS["limit"]
    value = formatting.data_into(session, node, owner)
    shaped = formatting.shape(value, spec)
    across = spec.get("draw") == "across" or (spec.get("draw") == "auto" and shaped.across)
    chart = charting.from_bars(shaped.bars, "column" if across else "bar", formatting.words(node))
    output = side([{"label": bar.long, "value": bar.value} for bar in shaped.bars], "data")
    output["error"] = shaped.error
    output["html"] = _drawn(chart, "") if shaped.bars else ""
    return {"input": side(value, "data", "" if value is not None else "Nothing is wired in."),
            "output": output}


def _chart(session: Session, node: GraphNode, owner: OwnerId, given: dict[str, str]) -> dict[str, Any]:
    from ..pamphlets import chart_for, wired_into

    said = graph_service.leaflets.settings(node)
    for key, wanted in given.items():
        if key.startswith("leaflet_") and key[8:] in said:
            said[key[8:]] = wanted
    if not str(said.get("limit", "")).isdigit():
        said["limit"] = charting.SPEC_DEFAULTS["limit"]

    box = wired_into(session, owner, node)
    if box is None:
        value: Any = None
        note = "Nothing is wired in, so it draws one of the built-in counts. Wire data into its { } port to chart that."
    elif box.kind == "format":
        shaped = formatting.shape(formatting.data_into(session, box, owner), formatting.settings(box))
        value = [{"label": bar.long, "value": bar.value} for bar in shaped.bars]
        note = "Shaped by the Format box wired in."
    else:
        value = formatting.data_out(session, box, owner)
        note = ""

    label, chart, _counts = chart_for(session, owner, node, said)
    output = side(_chart_rows(chart), "data")
    output["html"] = _drawn(chart, label) if chart is not None else ""
    # The chart says its own trouble; said again above it, it is said twice.
    output["error"] = chart.error if chart is not None and not output["html"] else ""
    output["label"] = label
    output["suggested"] = chart.suggested if chart is not None else []
    output["guessed"] = chart.guessed if chart is not None else ""
    if chart is not None and chart.guessed:
        output["note"] = (f"A guess, while nothing is chosen: one for each {chart.guessed}. "
                          "Say what each one is in the settings.")
    return {"input": side(value, "data", note), "output": output,
            "shaped": box is not None and box.kind == "format"}


def _chart_rows(chart: charting.Chart | None) -> Any:
    """A chart's numbers as rows: a point each, a column per series."""
    if chart is None:
        return None
    if chart.figure is not None and not chart.series:
        return chart.figure
    return [
        {"label": category.long, **{series.name: series.values[index] for series in chart.series}}
        for index, category in enumerate(chart.categories)
    ]


def _drawn(chart: charting.Chart, label: str) -> str:
    """The chart alone: the editor shows its numbers in its own Table view."""
    return TEMPLATES.get_template("_chart.html").render(chart=chart, chart_label=label, folded=False)
