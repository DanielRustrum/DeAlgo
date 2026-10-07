"""Text boxes: a language model writing from what comes in, for a Text leaflet.

No model is called here: Claude's client and an OpenAI-style server are both
stood in for, so what is tested is what is sent, what is kept, and what a
page shows.
"""

from __future__ import annotations

import datetime as dt
import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from dealgo.models import Channel, GraphNode, Video, utcnow
from dealgo.services import graph, writing


def a_media_source(session, count=3):
    channel = Channel(channel_id="UCw", title="Science Weekly")
    session.add(channel)
    session.flush()
    for n in range(count):
        session.add(Video(video_id=f"w{n}", channel_pk=channel.id, title=f"Story {n}",
                          status="added", body="x" * 1000, published_at=utcnow()))
    session.flush()
    return graph.add_source(session, channel=channel)


def choose(session, provider="anthropic", **said):
    account = __import__("dealgo.db", fromlist=["get_settings"]).get_settings(session)
    account.ai_provider = provider
    account.ai_model = said.get("model")
    account.ai_base_url = said.get("base_url")
    account.ai_key = said.get("key", "sk-test")
    return account


# -- what goes, and what comes back ----------------------------------------------------


def test_the_material_is_the_first_rows_each_cut_and_counted():
    rows = [{"title": f"T{n}", "body": "y" * 900, "empty": ""} for n in range(5)]
    said, total, sent = writing.material(rows, 3)
    parsed = json.loads(said)
    assert (total, sent) == (5, 3) and len(parsed) == 3
    assert "empty" not in parsed[0] and parsed[0]["body"].endswith("…")
    assert len(parsed[0]["body"]) == writing.TEXT_PER_ITEM + 1
    assert writing.material(7, 3) == ("7", 1, 1)


def test_written_text_is_set_as_paragraphs_subheads_and_lists():
    text = "Good morning.\nStill the same paragraph.\n\n## What stands out\n- One\n- Two\nAfter."
    assert writing.blocks(text) == [
        ("p", "Good morning. Still the same paragraph."),
        ("h", "What stands out"),
        ("ul", ["One", "Two"]),
        ("p", "After."),
    ]


def fake_claude(monkeypatch, *, text="Written.", stop="end_turn"):
    seen = {}

    class Messages:
        def create(self, **kwargs):
            seen.update(kwargs)
            return SimpleNamespace(
                stop_reason=stop,
                content=[SimpleNamespace(type="thinking", thinking=""),
                         SimpleNamespace(type="text", text=text)],
            )

    class Client:
        def __init__(self, **kwargs):
            seen["client"] = kwargs
            self.beta = SimpleNamespace(messages=Messages())

    monkeypatch.setattr(writing.anthropic, "Anthropic", Client)
    return seen


def test_claude_is_asked_through_its_sdk_with_a_fallback(monkeypatch):
    seen = fake_claude(monkeypatch)
    model = writing.Model("anthropic", "claude-opus-5-5", "", "sk-test")
    assert writing.write(model, "Sum it up.", "[]", counted=(0, 0)) == "Written."
    assert seen["model"] == "claude-opus-5-5" and seen["client"]["api_key"] == "sk-test"
    assert seen["fallbacks"] == "default" and seen["betas"] == ["server-side-fallback-2026-07-01"]
    assert seen["output_config"] == {"effort": "medium"} and "thinking" not in seen
    assert "Sum it up." in seen["messages"][0]["content"] and seen["system"] == writing.SYSTEM


def test_a_proxy_address_is_not_sent_the_fallback_and_a_refusal_is_said(monkeypatch):
    seen = fake_claude(monkeypatch, stop="refusal")
    model = writing.Model("anthropic", "claude-opus-5-5", "https://proxy.example", "")
    with pytest.raises(writing.WritingError, match="declined"):
        writing.write(model, "x", "[]", counted=(0, 0))
    assert "fallbacks" not in seen and seen["client"]["base_url"] == "https://proxy.example"


def test_an_open_weight_server_is_asked_over_the_chat_api():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "From llama."}}]})

    model = writing.Model("compatible", "llama3.1", "http://localhost:11434/v1/", "")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert writing._chat(model, "asked", client) == "From llama."
    assert seen["url"] == "http://localhost:11434/v1/chat/completions" and seen["auth"] is None
    assert seen["body"]["model"] == "llama3.1"
    assert [m["role"] for m in seen["body"]["messages"]] == ["system", "user"]

    refused = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401)))
    with pytest.raises(writing.WritingError, match="refused the key"):
        writing._chat(writing.Model("openai", "gpt-x", "", "k"), "asked", refused)
    with pytest.raises(writing.WritingError, match="where your model"):
        writing._chat(writing.Model("compatible", "m", "", ""), "asked", refused)


# -- Settings → AI model ----------------------------------------------------------------


@pytest.fixture
def client(db, monkeypatch):
    from dealgo import scheduler
    from dealgo.web import app as web_app

    monkeypatch.setattr(scheduler, "start", lambda: None)
    monkeypatch.setattr(scheduler, "shutdown", lambda: None)
    monkeypatch.setattr(scheduler, "next_run_time", lambda: None)
    monkeypatch.setattr(web_app, "init_db", lambda: None)
    with TestClient(web_app.app) as test_client:
        yield test_client


def test_the_settings_page_keeps_a_key_it_never_shows(client, db, monkeypatch):
    from dealgo.db import get_settings

    client.post("/settings/ai", data={"provider": "anthropic", "model": "", "key": "sk-secret"})
    page = client.get("/settings/ai").text
    assert "sk-secret" not in page and "a key is saved" in page and "claude-opus-5-5" in page

    # Saved again with the field blank, the key stays; told to forget, it goes.
    client.post("/settings/ai", data={"provider": "anthropic", "model": "claude-sonnet-5-5"})
    with db.session_scope() as session:
        account = get_settings(session)
        assert account.ai_key == "sk-secret" and account.ai_model == "claude-sonnet-5-5"
    client.post("/settings/ai", data={"provider": "anthropic", "forget_key": "1"})
    with db.session_scope() as session:
        assert get_settings(session).ai_key is None

    monkeypatch.setattr(writing, "write", lambda *a, **k: "Ready to write.")
    assert client.post("/settings/ai/try").json()["said"] == "Ready to write."
    refused = client.post("/settings/ai", data={"provider": "compatible", "model": ""},
                          follow_redirects=False)
    assert refused.status_code == 303 and "say+which+model" in refused.headers["location"].lower()


def test_a_key_is_not_in_a_backup(client, db):
    client.post("/settings/ai", data={"provider": "anthropic", "key": "sk-secret"})
    assert "sk-secret" not in client.get("/settings/backup").text


# -- the box --------------------------------------------------------------------------


def test_a_text_box_writes_from_what_comes_in_onto_a_text_leaflet(client, db, monkeypatch):
    asked = {}

    def pretend(model, instructions, material_json, *, counted):
        asked.update(instructions=instructions, material=json.loads(material_json), counted=counted)
        return "Three stories came in.\n\n- Story 0\n- Story 1"

    monkeypatch.setattr(writing, "write", pretend)
    with db.session_scope() as session:
        choose(session)
        source = a_media_source(session)
        box = graph.add_text_box(session, label="Briefing")
        writing.save(box, {"writing_instructions": "Brief me.", "writing_items": "2"})
        pamphlet = graph.add_pamphlet(session, label="Morning")
        leaflet = graph.add_piece(session, kind="leaflet-text", host=pamphlet)
        graph.connect(session, source, box)                 # items in
        graph.connect(session, box, leaflet)                # words out
        kinds = {w["to"]: w["kind"] for w in graph.wires(session)}
        assert kinds[box.id] == "edge" and kinds[leaflet.id] == "page"
        box_pk, pamphlet_pk = box.id, pamphlet.id

        # Nothing but a Text box writes onto a Text leaflet.
        with pytest.raises(graph.GraphError):
            graph.connect(session, source, leaflet)

    answer = client.post(f"/graph/nodes/{box_pk}/write").json()
    drawn = next(node for node in answer["nodes"] if node["id"] == box_pk)
    assert drawn["note"].startswith("wrote") and drawn["writing"]["error"] == ""
    assert asked["instructions"] == "Brief me." and asked["counted"] == (3, 2)
    assert asked["material"][0]["title"] in ("Story 0", "Story 1", "Story 2")

    page = client.get(f"/pamphlets/{pamphlet_pk}").text
    assert "Three stories came in." in page and "<li>Story 1</li>" in page and "Briefing" in page


def test_without_a_model_or_anything_in_it_says_why(db):
    from dealgo.db import get_settings

    with db.session_scope() as session:
        box = graph.add_text_box(session)
        done = writing.run(session, box, None, get_settings(session))
        assert "Settings → AI model" in done.error
        choose(session)
        done = writing.run(session, box, None, get_settings(session))
        assert "Nothing has come in" in done.error
        assert writing.last_error(box) == done.error


def test_a_failure_keeps_the_last_good_writing(db, monkeypatch):
    from dealgo.db import get_settings

    with db.session_scope() as session:
        choose(session)
        box = graph.add_text_box(session)
        graph.connect(session, a_media_source(session), box)
        monkeypatch.setattr(writing, "write", lambda *a, **k: "First.")
        writing.run(session, box, None, get_settings(session))

        def broken(*a, **k):
            raise writing.WritingError("Could not reach Anthropic.")

        monkeypatch.setattr(writing, "write", broken)
        done = writing.run(session, box, None, get_settings(session))
        assert box.written == "First." and done.error == "Could not reach Anthropic."


def test_a_box_set_to_write_hourly_writes_on_a_run(world, db, monkeypatch):
    from dealgo.services import sync as sync_service

    monkeypatch.setattr(writing, "write", lambda *a, **k: "On the hour.")
    with db.session_scope() as session:
        choose(session)
        hourly = graph.add_text_box(session, label="Hourly")
        writing.save(hourly, {"writing_refresh": "hourly"})
        by_hand = graph.add_text_box(session, label="By hand")
        source = session.scalar(select(GraphNode).where(GraphNode.kind == "source"))
        graph.connect(session, source, hourly)
        graph.connect(session, source, by_hand)
        world["entries"] = []

    sync_service.run_sync("manual", force=True)
    with db.session_scope() as session:
        boxes = {n.label: n for n in session.scalars(select(GraphNode).where(GraphNode.kind == "text"))}
        assert boxes["By hand"].written is None
        # Nothing came in on this run, so the hourly box says so rather than writing.
        assert boxes["Hourly"].written is None and "Nothing has come in" in writing.last_error(boxes["Hourly"])
        assert writing.due(boxes["Hourly"], utcnow())

        boxes["Hourly"].written_at = utcnow() - dt.timedelta(minutes=10)
        assert not writing.due(boxes["Hourly"], utcnow())
