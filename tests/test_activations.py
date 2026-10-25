"""Activation triggers and the Activate boxes that set them off.

An Activation is a trigger on no clock, taking parameters. An Activate box
ends a path; once per run that reaches it, it sets its Activation off with
values filled from what reached it. The flow the Activation starts reads
them as {{ params.name }}, and from its { } port.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest

from pamphlets.models import GraphNode, Video, utcnow
from pamphlets.services import graph
from pamphlets.services.graph import activations
from pamphlets.services.graph.templating import fill
from tests.test_canvases import in_canvas
from tests.test_graph import build, canvas, node_for  # noqa: F401


def _activation(session, *names_and_defaults):
    node = graph.add_trigger(session, trigger_kind="activation", x=0, y=0)
    activations.set_params(node, [n for n, _ in names_and_defaults], [d for _, d in names_and_defaults])
    return node


def test_an_activation_takes_parameters_and_fires_on_no_clock(db):
    build(db, channels=(), feeds=())
    with db.session_scope() as session:
        node = _activation(session, ("city", "Phoenix"), ("days", "3"))
        assert node.title == "Activation"
        assert activations.params(node) == [{"name": "city", "default": "Phoenix"}, {"name": "days", "default": "3"}]
        assert activations.last(node) == {"city": "Phoenix", "days": "3"}
        assert not graph.When(kind="activation").due(None, utcnow())
        with pytest.raises(graph.GraphError):
            activations.set_params(node, ["9lives"], [""])
        with pytest.raises(graph.GraphError):
            activations.set_params(node, ["a", "a"], ["", ""])
        # Set off: its parameters only, the rest at their defaults.
        assert activations.set_off(node, {"city": "Tucson", "stray": "x"}) == {"city": "Tucson", "days": "3"}
        assert activations.as_row(node) == [{"city": "Tucson", "days": "3"}]


def test_only_an_activation_gives_data_and_an_activate_box_ends_a_path(db):
    build(db, channels=("UCone",), feeds=())
    with db.session_scope() as session:
        source = node_for(session, "source", "UCone")
        node = _activation(session, ("city", ""))
        pulse = graph.add_trigger(session, trigger_kind="pulse", x=0, y=0)
        shaper = graph.add_format(session, label="Shape")
        box = graph.add_activate(session, label="Go")
        assert graph.connect(session, node, source).carries == "signal"
        assert graph.connect(session, node, shaper).carries == "data"
        with pytest.raises(graph.GraphError, match="Only an Activation"):
            graph.connect(session, pulse, shaper, carries="data")
        assert graph.connect(session, source, box).carries == "content"
        # What it gives is what its Activation's flow sends back: data.
        assert graph.connect(session, box, shaper).carries == "data"
        with pytest.raises(graph.GraphError):
            graph.connect(session, box, source)
        # What its { } port gives: its values, as one row.
        assert graph.formatting.data_out(session, node, None) == [{"city": ""}]


def test_what_reaches_an_activate_box_sets_its_activation_off_once(db):
    build(db, channels=("UCone",), feeds=())
    with db.session_scope() as session:
        source = node_for(session, "source", "UCone")
        keep = graph.add_filter(session, label="Keep")
        graph.add_piece(session, kind="has-words", host=keep)
        keep_piece = next(p for p in graph.nodes(session) if p.kind == "has-words")
        keep_piece.title_include = "storm"
        box = graph.add_activate(session, label="Go")
        graph.connect(session, source, keep)
        graph.connect(session, keep, box)
        # Elsewhere — another canvas, even — the Activation it sets off.
        room = graph.add_canvas(session, label="Elsewhere")
        with in_canvas(room.id):
            target = _activation(session, ("headline", ""), ("place", "home"))
        activations.set_activate(session, box, target.id, {"headline": "News: {{ title }}"})
        since = utcnow() - dt.timedelta(seconds=1)
        channel = source.channel
        session.add_all([
            Video(video_id="a", channel_pk=channel.id, title="Sunny all week", discovered_at=utcnow(),
                  published_at=utcnow()),
            Video(video_id="b", channel_pk=channel.id, title="A storm is coming", discovered_at=utcnow(),
                  published_at=utcnow() - dt.timedelta(hours=1)),
        ])
        session.flush()

        fired = activations.fire_reached(session, None, since, None)
        assert fired == [target.id]
        assert activations.last(target) == {"headline": "News: A storm is coming", "place": "home"}
        # Nothing new since: nothing reaches it, and it is not set off again.
        assert activations.fire_reached(session, None, utcnow() + dt.timedelta(seconds=1), None) == []


def test_the_flow_an_activation_starts_reads_its_values(db):
    build(db, channels=("UCone",), feeds=())
    with db.session_scope() as session:
        source = node_for(session, "source", "UCone")
        node = _activation(session, ("topic", "rivers"))
        writer = graph.add_text_box(session, label="Writer")
        graph.connect(session, node, source)
        graph.connect(session, source, writer)
        activations.set_off(node, {"topic": "storms"})
        values = activations.params_for(session, writer)
        assert values == {"topic": "storms"}
        assert activations.started_by(session, writer) == [node.id]
        assert fill("Write about {{ params.topic }}", [], values) == "Write about storms"
        # An Activate box's own values can read the flow's: chains carry them on.
        box = graph.add_activate(session, label="Pass on")
        graph.connect(session, source, box)
        assert activations.params_for(session, box) == {"topic": "storms"}


def test_a_copy_keeps_parameters_and_points_at_the_copied_activation(db):
    build(db, channels=(), feeds=())
    with db.session_scope() as session:
        node = _activation(session, ("city", "Phoenix"))
        box = graph.add_activate(session, label="Go")
        activations.set_activate(session, box, node.id, {"city": "{{ title }}"})
        made = graph.clipboard.paste(session, json.loads(json.dumps(graph.clipboard.copy(session, [node.id, box.id]))), x=0, y=500)
        copies = {one.kind: one for one in made}
        assert copies["trigger"].trigger_kind == "activation"
        assert activations.params(copies["trigger"]) == [{"name": "city", "default": "Phoenix"}]
        assert activations.target_of(session, copies["activate"]).id == copies["trigger"].id
        assert activations.values_of(copies["activate"]) == {"city": "{{ title }}"}
        # Copied alone, it still sets off the one it did.
        alone = graph.clipboard.paste(session, graph.clipboard.copy(session, [box.id]), x=0, y=900)
        assert activations.target_of(session, alone[0]).id == node.id


def test_the_canvas_makes_and_saves_them(canvas, db):
    made = canvas.post("/graph/nodes", data={"kind": "activation", "x": "0", "y": "0"}).json()
    activation = next(n for n in made["nodes"] if n["kind"] == "trigger" and n["trigger"]["kind"] == "activation")
    saved = canvas.post(f"/graph/nodes/{activation['id']}",
                        data={"label": "", "param_name": ["city", "days"], "param_default": ["Phoenix", "3"]}).json()
    shown = next(n for n in saved["nodes"] if n["id"] == activation["id"])
    assert [p["name"] for p in shown["activation"]["params"]] == ["city", "days"]
    assert "takes city, days" in shown["note"]
    made = canvas.post("/graph/nodes", data={"kind": "activate", "x": "0", "y": "0"}).json()
    box = next(n for n in made["nodes"] if n["kind"] == "activate")
    assert [c["id"] for c in box["activate"]["choices"]] == [activation["id"]]
    saved = canvas.post(f"/graph/nodes/{box['id']}", data={
        "label": "", "activate_target": str(activation["id"]), "activate_value_city": "{{ title }}",
    }).json()
    shown = next(n for n in saved["nodes"] if n["id"] == box["id"])
    assert shown["activate"]["target"] == activation["id"]
    assert shown["activate"]["values"] == {"city": "{{ title }}"}
    assert shown["note"] == "sets off “Activation”"
    with db.session_scope() as session:
        assert session.get(GraphNode, box["id"]).kind == "activate"


def test_a_run_starts_the_flows_it_set_off_and_a_ring_stops_five_deep(db, monkeypatch):
    from pamphlets.services.sync import run as running
    from pamphlets.services.sync.result import SyncResult

    build(db, channels=("UCone",), feeds=())
    with db.session_scope() as session:
        source = node_for(session, "source", "UCone")
        node = _activation(session)
        graph.connect(session, node, source)
        node_pk, channel_pk, box_pk = node.id, source.channel_pk, source.id

    asked = []

    def ran(session, http, trigger, **given):
        asked.append((trigger, given.get("only"), given.get("sources"), given.get("fired_by")))
        # Every run sets the same Activation off again: a ring.
        return SyncResult(ok=True, activated=[node_pk])

    monkeypatch.setattr(running, "_run", ran)
    running.run_sync("manual")
    assert asked[0][0] == "manual"
    assert asked[1] == ("activation", frozenset({channel_pk}), frozenset({box_pk}), node_pk)
    assert len(asked) == 1 + activations.MOST_DEPTH


def test_a_return_box_sends_what_reaches_it_back_to_the_activate_box(db):
    build(db, channels=("UCone",), feeds=())
    with db.session_scope() as session:
        source = node_for(session, "source", "UCone")
        # The flow an Activation starts, ending in a Return box…
        target = _activation(session, ("city", ""))
        keep = graph.add_filter(session, label="Keep")
        back = graph.add_return(session, label="Back")
        graph.connect(session, target, source)
        graph.connect(session, source, keep)
        assert graph.connect(session, keep, back).carries == "content"
        # …and, elsewhere, the Activate box that set it off.
        caller = graph.add_activate(session, label="Ask")
        activations.set_activate(session, caller, target.id, {})
        charted = graph.add_format(session, label="Shape")
        assert graph.connect(session, caller, charted).carries == "data"
        session.add(Video(video_id="a", channel_pk=source.channel_pk, title="Came through", published_at=utcnow()))
        session.flush()

        # Set off by hand, there is nobody to send back to.
        activations.set_off(target, {})
        assert activations.send_back(session, None, target.id) == 0
        # Set off by the Activate box, what reached Back goes back to it.
        activations.set_off(target, {"city": "Tucson"}, by=caller.id)
        assert activations.send_back(session, None, target.id) == 1
        came = graph.formatting.data_out(session, caller, None)
        assert [row["title"] for row in came] == ["Came through"]
        assert activations.returned_at(caller) is not None


def test_data_wired_into_a_return_box_goes_back_as_it_is(db):
    build(db, channels=(), feeds=())
    with db.session_scope() as session:
        target = _activation(session, ("topic", "rivers"))
        back = graph.add_return(session, label="Back")
        graph.connect(session, target, back)  # its values, as data, straight back
        caller = graph.add_activate(session, label="Ask")
        activations.set_activate(session, caller, target.id, {"topic": "storms"})
        activations.set_off(target, {"topic": "storms"}, by=caller.id)
        assert activations.send_back(session, None, target.id) == 1
        assert activations.returned(caller) == [{"topic": "storms"}]
