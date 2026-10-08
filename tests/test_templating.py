"""`{{ field }}` in settings: fields of the data beside static text."""

from __future__ import annotations

from pamphlets.services import charting, graph
from pamphlets.services.graph import formatting, leaflets
from pamphlets.services.graph.templating import fill, path_of
from tests.test_format import ANSWER, a_rest_source, client, spec  # noqa: F401


def test_a_path_setting_reads_braces_or_a_bare_path():
    assert path_of("{{ data.author }}") == "data.author"
    assert path_of("{{data.author}}") == "data.author"
    assert path_of("data.author") == "data.author"
    assert path_of("") == "" and path_of(None) == ""


def test_words_have_their_fields_filled_from_the_data_or_its_first_row():
    assert fill("Videos this week: {{ count }}", {"count": 8}) == "Videos this week: 8"
    assert fill("Newest: {{ data.author }}", ANSWER) == "Newest: ana"
    assert fill("{{ nowhere }}!", {"count": 8}) == "!"
    assert fill("No fields here", None) == "No fields here"
    assert fill("{{ n }}", [{"n": 1234.0}]) == "1,234"


def test_charts_and_format_boxes_read_fields_in_braces():
    chart = charting.from_data(ANSWER, {"label": "{{ data.author }}", "value": "{{data.score}}",
                                        "combine": "sum"})
    assert [c.long for c in chart.categories] == ["ana", "ben", "cy"]
    shaped = formatting.shape(ANSWER, spec(label="{{ data.author }}"))
    assert [(bar.label, bar.value) for bar in shaped.bars] == [("ana", 2), ("ben", 1), ("cy", 1)]
    assert charting.words({"label": "{{ data.author }}"}) == "columns of how many by data.author"


def test_a_chart_heading_says_what_the_data_says(client, db):
    with db.session_scope() as session:
        source = a_rest_source(session, ANSWER)
        pamphlet = graph.add_pamphlet(session, label="P")
        chart = graph.add_piece(session, kind="leaflet-chart", host=pamphlet)
        leaflets.save(chart, {"leaflet_title": "First up: {{ data.author }}",
                              "leaflet_label": "{{ data.author }}"}, set())
        graph.connect(session, source, chart)
        pamphlet_pk, chart_pk = pamphlet.id, chart.id

    assert "First up: ana" in client.get(f"/pamphlets/{pamphlet_pk}").text
    seen = client.post(f"/graph/nodes/{chart_pk}/inspect", data={
        "leaflet_title": "By {{ data.author }} and co", "leaflet_label": "{{ data.author }}",
    }).json()
    assert seen["filled"] == {"leaflet_title": "By ana and co", "leaflet_label": "ana"}
