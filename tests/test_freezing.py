"""Frozen canvases: nothing inside one runs, however deep, until it thaws.

A box in a frozen canvas is off wherever anything asks whether a box is on —
triggers, polling, routes — but keeps its own switch, so thawing the canvas
puts everything back as it was.
"""

from __future__ import annotations

import pytest

from pamphlets.models import GraphNode
from pamphlets.services import graph
from pamphlets.services.graph import insides
from tests.test_canvases import in_canvas
from tests.test_graph import build, canvas, node_for  # noqa: F401


def _flow_inside(session, nested: bool = False):
    """A trigger, a source and a feed wired together inside a canvas — or
    inside a canvas inside it. Says the outer canvas and the boxes."""
    outer = graph.add_canvas(session, label="Outer")
    holder = outer
    if nested:
        with in_canvas(outer.id):
            holder = graph.add_canvas(session, label="Inner")
    source, feed = node_for(session, "source", "UCone"), node_for(session, "feed", "PLone")
    for wire in graph.edges(session, every=True, raw=True):
        session.delete(wire)
    source.inside_pk = feed.inside_pk = holder.id
    with in_canvas(holder.id):
        pulse = graph.add_trigger(session, trigger_kind="pulse", x=0, y=0)
    session.flush()
    graph.connect(session, pulse, source)
    graph.connect(session, source, feed)
    return outer, pulse, source, feed


@pytest.mark.parametrize("nested", [False, True])
def test_nothing_in_a_frozen_canvas_runs_and_thawing_puts_it_back(db, nested):
    build(db, channels=("UCone",), feeds=("PLone",))
    with db.session_scope() as session:
        outer, pulse, source, feed = _flow_inside(session, nested)
        channel = source.channel_pk
        assert channel in graph.polling_plan(session)
        assert any(route.playlist is not None for route in graph.routes(session))

        insides.freeze(session, outer.id, True)
        # No trigger fires for it, nothing is polled for it, nothing routed.
        assert channel not in graph.polling_plan(session)
        assert not any(route.playlist is not None for route in graph.routes(session))
        assert not pulse.enabled and pulse.frozen_by is outer
        with pytest.raises(graph.GraphError, match="frozen"):
            graph.pulse_targets(session, pulse.id)
        # Each box keeps its own switch.
        assert pulse.switched_on and source.switched_on and feed.switched_on

        insides.freeze(session, outer.id, False)
        assert channel in graph.polling_plan(session)
        assert pulse.enabled and pulse.frozen_by is None


def test_a_box_switched_off_stays_off_when_its_canvas_thaws(db):
    build(db, channels=("UCone",), feeds=("PLone",))
    with db.session_scope() as session:
        outer, pulse, _, _ = _flow_inside(session)
        pulse.enabled = False
        insides.freeze(session, outer.id, True)
        insides.freeze(session, outer.id, False)
        assert not pulse.enabled


def test_only_a_canvas_freezes(db):
    build(db, channels=(), feeds=())
    with db.session_scope() as session:
        relay = graph.add_relay(session)
        with pytest.raises(graph.GraphError):
            insides.freeze(session, relay.id, True)


def test_a_copied_canvas_stays_frozen_and_what_is_copied_out_runs(db):
    build(db, channels=(), feeds=())
    with db.session_scope() as session:
        outer = graph.add_canvas(session, label="Outer")
        with in_canvas(outer.id):
            keep = graph.add_filter(session, label="Keep")
        insides.freeze(session, outer.id, True)
        assert not keep.enabled
        made = graph.clipboard.paste(session, graph.clipboard.copy(session, [outer.id, keep.id]), x=0, y=0)
        copied = {node.kind: node for node in made}
        assert copied["canvas"].frozen
        # Pasted at the top, out of the frozen canvas: on, as it was switched.
        assert copied["filter"].inside_pk is None and copied["filter"].enabled


def test_the_canvas_freezes_through_its_api_and_says_so_inside(canvas, db):
    with db.session_scope() as session:
        outer = graph.add_canvas(session, label="Outer")
        with in_canvas(outer.id):
            keep = graph.add_filter(session, label="Keep")
        outer_pk, keep_pk = outer.id, keep.id
    answer = canvas.post(f"/graph/nodes/{outer_pk}/freeze", data={"frozen": "1"}).json()
    assert next(n for n in answer["nodes"] if n["id"] == outer_pk)["frozen"] is True
    inside = canvas.get(f"/api/graph?inside={outer_pk}").json()
    assert inside["trail"][-1]["frozen"] is True
    # Its own switch is what its panel shows: on, for when the canvas thaws.
    assert next(n for n in inside["nodes"] if n["id"] == keep_pk)["enabled"] is True
    with db.session_scope() as session:
        assert session.get(GraphNode, outer_pk).frozen
    canvas.post(f"/graph/nodes/{outer_pk}/freeze", data={"frozen": "0"})
    with db.session_scope() as session:
        assert not session.get(GraphNode, outer_pk).frozen
    assert canvas.post(f"/graph/nodes/{keep_pk}/freeze", data={"frozen": "1"}).status_code == 400
