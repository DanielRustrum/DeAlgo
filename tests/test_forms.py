"""Forms: a Form leaflet, the Input pieces under it, and the Input source
that takes what is sent from the queue they share."""

from __future__ import annotations

import pytest

from pamphlets.models import Channel, FormSubmission, GraphNode
from pamphlets.services import graph
from pamphlets.services.graph import forms, leaflets
from tests.test_graph import build, canvas  # noqa: F401


def _form(session, queue="feedback"):
    paper = graph.add_pamphlet(session, label="Paper")
    form = graph.add_piece(session, kind="leaflet-form", host=paper)
    leaflets.save(form, {"leaflet_queue": queue, "leaflet_heading": "Tell us"}, set())
    return paper, form


def _field(session, kind, host, **said):
    node = graph.add_piece(session, kind=kind, host=host)
    forms.save_field(node, {f"field_{k}": str(v) for k, v in said.items()} | {"field_form": "1"})
    return node


def test_fields_stack_under_a_form_leaflet_and_nowhere_else(db):
    build(db, channels=(), feeds=())
    with db.session_scope() as session:
        _, form = _form(session)
        name = _field(session, "input-text", form, name="name", label="Your name", required="1")
        # Slotted under the first field, it is the second.
        email = _field(session, "input-text", name, name="email", pattern=r"[^@]+@[^@]+")
        assert [one.id for one in forms.fields_of(graph.nodes(session), form)] == [name.id, email.id]
        assert forms.form_of(graph.nodes(session), email).id == form.id
        assert graph.piece_note(email, None) == "“Email” · text · matches /[^@]+@[^@]+/"
        keep = graph.add_filter(session, label="Keep")
        with pytest.raises(graph.GraphError, match="Form leaflet"):
            graph.add_piece(session, kind="input-text", host=keep)


def test_a_field_refuses_settings_it_cannot_use(db):
    build(db, channels=(), feeds=())
    with db.session_scope() as session:
        _, form = _form(session)
        node = graph.add_piece(session, kind="input-choice", host=form)
        with pytest.raises(graph.GraphError, match="name"):
            forms.save_field(node, {"field_name": "9 lives"})
        with pytest.raises(graph.GraphError, match="regular expression"):
            forms.save_field(node, {"field_pattern": "(unclosed"})
        with pytest.raises(graph.GraphError, match="choose"):
            forms.save_field(node, {"field_options": "  \n "})


def test_what_is_sent_is_checked_against_every_field(db):
    build(db, channels=(), feeds=())
    with db.session_scope() as session:
        _, form = _form(session)
        _field(session, "input-text", form, name="code", required="1", pattern=r"[A-Z]{2}\d{4}", hint="Two capitals, four digits.")
        _field(session, "input-number", form, name="age", min="18", max="120")
        _field(session, "input-date", form, name="when")
        _field(session, "input-choice", form, name="size", options="Small\nLarge")
        _field(session, "input-check", form, name="agree", required="1")
        fields = forms.fields_of(graph.nodes(session), form)

        values, wrong = forms.check(fields, {"code": "ab12", "age": "9", "when": "soon", "size": "Huge"})
        assert wrong == {
            "code": "Two capitals, four digits.", "age": "At least 18.", "when": "That is not a date.",
            "size": "Choose one of these.", "agree": "Tick this to send the form.",
        }
        values, wrong = forms.check(fields, {"code": "AB1234", "age": "40", "when": "2026-10-25", "size": "Large", "agree": "yes"})
        assert wrong == {}
        assert values == {"code": "AB1234", "age": "40", "when": "2026-10-25", "size": "Large", "agree": "yes"}
        assert forms.check(fields, {"agree": "yes"})[1] == {"code": "This needs filling in."}


def test_an_input_source_takes_its_queue_once_titled_by_the_field_it_says(db):
    from pamphlets.services import channels as channel_service
    from pamphlets.services.sync import polling

    build(db, channels=(), feeds=())
    with db.session_scope() as session:
        _, form = _form(session, queue="Feedback")
        assert leaflets.settings(form)["queue"] == "feedback"
        forms.submit(session, None, form, {"name": "Ada", "topic": "Charts"})
        forms.submit(session, None, form, {"name": "Grace", "topic": "Compilers"})
        channel = channel_service.add_source(session, "feedback", None, within="input")
        assert (channel.source_kind, channel.channel_id) == ("input", "input:feedback")
        channel.source_options = '{"title_field": "topic"}'

        taken = polling._read_queue(channel)
        assert [item.title for item in taken.items] == ["Charts", "Compilers"]
        assert "name: Ada" in (taken.items[0].summary or "")
        assert polling._read_queue(channel).items == []  # each once
        # Its { } port still lists every one.
        box = graph.add_source(session, channel=channel)
        assert [row["name"] for row in graph.formatting.data_for(session, box)] == ["Grace", "Ada"]


def test_a_form_on_a_pamphlet_is_sent_or_shown_again_with_what_is_wrong(canvas, db):
    with db.session_scope() as session:
        paper, form = _form(session)
        _field(session, "input-text", form, name="email", label="Email", required="1", pattern=r"[^@\s]+@[^@\s]+")
        paper_pk, form_pk = paper.id, form.id
    page = canvas.get(f"/pamphlets/{paper_pk}").text
    assert f'action="/pamphlets/{paper_pk}/forms/{form_pk}"' in page and 'name="email"' in page

    wrong = canvas.post(f"/pamphlets/{paper_pk}/forms/{form_pk}", data={"email": "not an address"})
    assert wrong.status_code == 200 and "That is not in the form this asks for." in wrong.text
    assert 'value="not an address"' in wrong.text

    sent = canvas.post(f"/pamphlets/{paper_pk}/forms/{form_pk}", data={"email": "ada@example.org"}, follow_redirects=False)
    assert sent.status_code in (302, 303)
    with db.session_scope() as session:
        kept = session.query(FormSubmission).one()
        assert (kept.queue, forms.values_of(kept)) == ("feedback", {"email": "ada@example.org"})


def test_the_canvas_makes_and_saves_forms_and_inputs(canvas, db):
    with db.session_scope() as session:
        paper = graph.add_pamphlet(session, label="Paper")
        paper_pk = paper.id
    made = canvas.post("/graph/nodes", data={"kind": "leaflet-form", "attach_to": str(paper_pk), "x": "0", "y": "0"}).json()
    form = next(n for n in made["nodes"] if n["kind"] == "leaflet-form")
    canvas.post(f"/graph/nodes/{form['id']}", data={"label": "", "leaflet_queue": "Ideas"})
    made = canvas.post("/graph/nodes", data={"kind": "input-number", "attach_to": str(form["id"]), "x": "0", "y": "0"}).json()
    field = next(n for n in made["nodes"] if n["kind"] == "input-number")
    saved = canvas.post(f"/graph/nodes/{field['id']}", data={
        "label": "", "field_form": "1", "field_name": "votes", "field_label": "Votes", "field_min": "1", "field_required": "1",
    }).json()
    shown = next(n for n in saved["nodes"] if n["id"] == field["id"])
    assert shown["field"]["name"] == "votes" and shown["field"]["required"] is True
    assert "“Votes” · number · required" in shown["note"]
    assert next(n for n in saved["nodes"] if n["id"] == form["id"])["note"] == "sends into “ideas”"
    with db.session_scope() as session:
        assert session.get(GraphNode, field["id"]).attached_to == form["id"]


def test_a_copied_form_keeps_its_fields(db):
    build(db, channels=(), feeds=())
    with db.session_scope() as session:
        paper, form = _form(session)
        _field(session, "input-text", form, name="email", required="1", pattern=r".+@.+")
        made = graph.clipboard.paste(session, graph.clipboard.copy(session, [paper.id]), x=0, y=600)
        copied = next(one for one in made if one.kind == "leaflet-form")
        fields = forms.fields_of(graph.nodes(session), copied)
        assert [(forms.field(one)["name"], forms.field(one)["pattern"]) for one in fields] == [("email", ".+@.+")]
        assert leaflets.settings(copied)["queue"] == "feedback"
