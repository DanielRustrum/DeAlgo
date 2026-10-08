"""The box editor: what comes into a box and what goes out of it.

Data boxes show their settings between the two, and their output follows
the settings sent, saved or not; sources, operations, repositories and
feeds show the two sides only.
"""

from __future__ import annotations

from pamphlets.services import graph
from pamphlets.services.graph import formatting, inspecting
from tests.test_format import ANSWER, TITLES, a_rest_source, client, media_source  # noqa: F401


def inspect(client, pk, **given):
    answer = client.post(f"/graph/nodes/{pk}/inspect", data=given)
    assert answer.status_code == 200, answer.text
    return answer.json()


def test_fields_are_every_path_with_its_kind_and_an_example():
    found = {one["path"]: one for one in inspecting.fields(
        [{"a": {"b": 1, "c": [1, 2]}, "when": "2026-10-08T10:00:00Z", "t": "x" * 100}]
    )}
    assert found["a.b"]["type"] == "number" and found["a.b"]["sample"] == 1
    assert found["a.c"]["type"] == "list" and found["when"]["type"] == "date"
    assert found["t"]["sample"].endswith("…") and len(found["t"]["sample"]) == 80


def test_a_side_finds_rows_in_an_answer_and_keeps_one_value_as_one():
    found = inspecting.side(ANSWER)
    assert found["count"] == 4 and found["found_at"] == "data.children"
    assert inspecting.side(7)["value"] == 7 and inspecting.side(None)["empty"]


def test_a_source_shows_what_it_gives(client, db):
    with db.session_scope() as session:
        pk = a_rest_source(session, ANSWER).id
    seen = inspect(client, pk)
    assert seen["input"] is None and seen["output"]["count"] == 4


def test_an_operation_shows_items_in_and_what_it_lets_through(client, db):
    with db.session_scope() as session:
        source = media_source(session, TITLES)
        middle = graph.add_filter(session)
        graph.add_piece(session, kind="has-words", host=middle).title_include = "cats"
        graph.connect(session, source, middle)
        pk = middle.id
        total = len(formatting.items_into(session, middle, None))
    seen = inspect(client, pk)
    assert seen["input"]["how"] == "items" and seen["input"]["count"] == total
    assert seen["output"]["count"] == 2


def test_a_format_box_shapes_with_settings_not_yet_saved(client, db):
    with db.session_scope() as session:
        source = a_rest_source(session, ANSWER)
        box = graph.add_format(session)
        graph.connect(session, source, box)
        pk = box.id
    seen = inspect(client, pk, format_label="data.author", format_value="data.score", format_combine="sum")
    assert seen["input"]["count"] == 4
    assert seen["output"]["rows"][0] == {"label": "ana", "value": 16}
    assert "chart" in seen["output"]["html"]


def test_a_transform_shows_its_count(client, db):
    with db.session_scope() as session:
        source = media_source(session, TITLES)
        box = graph.add_transform(session)
        graph.add_piece(session, kind="count", host=box)
        graph.connect(session, source, box)
        pk, total = box.id, len(formatting.items_into(session, box, None))
    seen = inspect(client, pk)
    assert seen["input"]["count"] == total
    assert seen["output"]["rows"] == [{"count": total}]
    assert seen["output"]["fields"][0]["path"] == "count"


def test_a_text_box_shows_what_it_reads_and_what_it_wrote(client, db):
    with db.session_scope() as session:
        source = media_source(session, TITLES)
        box = graph.add_text_box(session)
        box.written = "Cats, mostly."
        graph.connect(session, source, box)
        pk = box.id
    seen = inspect(client, pk)
    assert seen["input"]["how"] == "items" and seen["input"]["count"] > 0
    assert seen["output"]["text"] == "Cats, mostly."


def test_boxes_with_nothing_to_show_are_refused(client, db):
    with db.session_scope() as session:
        pk = graph.add_pamphlet(session, label="P").id
    assert client.post(f"/graph/nodes/{pk}/inspect").status_code == 404
