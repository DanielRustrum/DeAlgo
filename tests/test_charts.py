"""Chart leaflets: wired data organised in their dialog, drawn as they say.

Data comes straight from a source, an operation or a Transform box — or as
bars from a Format box — and the leaflet's own settings say where the rows
are, what labels a point, what number it shows and what splits it into
series; and whether it is columns, bars, a line, a stacked area, a pie, one
number or a table.
"""

from __future__ import annotations

import json

from pamphlets.models import GraphNode
from pamphlets.services import charting, graph
from pamphlets.services.graph import formatting, leaflets
from tests.test_format import ANSWER, a_rest_source, client  # noqa: F401 — the fixture

ROWS = [
    {"day": "2026-10-01", "who": "ana", "score": 10},
    {"day": "2026-10-01", "who": "ben", "score": 4},
    {"day": "2026-10-02", "who": "ana", "score": 6},
    {"day": "2026-10-03", "who": "cy", "score": 2},
]


def said(**given):
    return {**charting.SPEC_DEFAULTS, **given}


# -- organising --------------------------------------------------------------------


def test_rows_are_counted_by_a_label():
    chart = charting.from_data(ROWS, said(label="who"))
    assert [c.long for c in chart.categories] == ["ana", "ben", "cy"]
    assert chart.single and chart.series[0].values == [2, 1, 1]
    assert set(chart.fields) == {"day", "score", "who"} and chart.rows == 4


def test_a_series_splits_each_point():
    chart = charting.from_data(ROWS, said(label="day", value="score", combine="sum", series="who"))
    assert [s.name for s in chart.series] == ["ana", "ben", "cy"]
    assert [s.slot for s in chart.series] == [1, 2, 3]
    # Nothing added up on a day is none that day…
    assert chart.series[0].values == [10, 6, 0]
    assert chart.series[2].values == [0, 0, 2]
    # …but an average of nothing is a gap, not a zero.
    averaged = charting.from_data(ROWS, said(label="day", value="score", combine="average", series="who"))
    assert averaged.series[0].values == [10, 6, None]


def test_more_than_five_series_fold_into_other_in_the_sixth_colour():
    rows = [{"x": "a", "s": name, "n": n} for n, name in enumerate("abcdefg", start=1)]
    chart = charting.from_data(rows, said(label="x", value="n", combine="sum", series="s"))
    assert [s.name for s in chart.series] == ["g", "f", "e", "d", "c", "Other"]
    assert chart.series[-1].slot == 6 and chart.series[-1].values == [1 + 2]


def test_points_are_ordered_and_limited():
    chart = charting.from_data(ROWS, said(label="who", value="score", combine="sum",
                                          sort="value-asc", limit=2))
    assert [c.long for c in chart.categories] == ["cy", "ben"]


def test_one_number_from_rows_or_from_a_count():
    total = charting.from_data(ROWS, said(kind="number", value="score", combine="sum"))
    assert total.figure == 22
    assert charting.from_data(7, said()).figure == 7 and charting.from_data(7, said()).kind == "number"
    counted = charting.from_data({"count": 8}, said(kind="pie"))
    assert counted.kind == "number" and counted.figure == 8 and counted.measure == "count"


def test_it_says_what_is_missing():
    # Nothing worth guessing a label from — every row its own title — says so.
    unique = [{"title": f"t{n}"} for n in range(6)]
    assert "each point is" in charting.from_data(unique, said()).error
    assert "number" in charting.from_data(ROWS, said(label="who", combine="sum")).error
    assert "Nothing has come in" in charting.from_data(None, said()).error


def test_lines_break_at_gaps_and_areas_stack():
    gappy = charting.from_data(ROWS, said(kind="line", label="day", value="score",
                                          combine="average", series="who"))
    assert len(gappy.line_segments(gappy.series[0])) == 1
    assert gappy.line_segments(gappy.series[2]) == [f"{gappy.x(2):.1f},{gappy.y(2)}"]
    assert gappy.alone(gappy.series[2], 2) and not gappy.alone(gappy.series[0], 0)
    chart = charting.from_data(ROWS, said(kind="line", label="day", value="score",
                                          combine="sum", series="who"))
    assert chart.top == 10
    # Stacked, the top is the tallest stack: 10 + 4 on the first day.
    chart.kind = "area"
    assert chart.top == 20
    assert chart.area_path(0).startswith("M") and chart.area_path(0).endswith("Z")


def test_a_pie_is_the_largest_five_and_other():
    rows = [{"x": name, "n": n} for n, name in enumerate("abcdefg", start=1)]
    chart = charting.from_data(rows, said(kind="pie", label="x", value="n", combine="sum"))
    slices = chart.slices()
    assert [one.name for one in slices] == ["g", "f", "e", "d", "c", "Other"]
    assert slices[-1].value == 3 and slices[-1].slot == 6
    assert round(sum(one.share for one in slices)) == 100
    whole = charting.from_data([{"x": "a"}], said(kind="pie", label="x")).slices()
    assert len(whole) == 1 and whole[0].share == 100


# -- on the page and on the canvas -------------------------------------------------


def drawn_node(db, pk):
    """One node as the canvas draws it."""
    from pamphlets.web.routes.canvas.payload import graph_payload

    with db.session_scope() as session:
        return next(n for n in graph_payload(session, None)["nodes"] if n["id"] == pk)


def a_chart_from(session, source, **settings):
    pamphlet = graph.add_pamphlet(session, label="Stats")
    chart = graph.add_piece(session, kind="leaflet-chart", host=pamphlet)
    leaflets.save(chart, {f"leaflet_{k}": str(v) for k, v in settings.items()}, set())
    graph.connect(session, source, chart)
    return pamphlet, chart


def test_a_source_wires_straight_into_a_chart_and_is_drawn_as_it_says(client, db):
    with db.session_scope() as session:
        source = a_rest_source(session, ANSWER)
        pamphlet, _ = a_chart_from(session, source, kind="pie", label="data.author",
                                   value="data.score", combine="sum")
        pamphlet_pk = pamphlet.id

    page = client.get(f"/pamphlets/{pamphlet_pk}").text
    assert 'class="chart is-pie"' in page
    assert "ana · 16 (72.7%)" in page
    assert "pie of sum data.score by data.author" in page


def test_every_kind_draws(client, db):
    with db.session_scope() as session:
        source = a_rest_source(session, ANSWER)
        pamphlet, chart = a_chart_from(session, source, label="data.author",
                                       series="data.flair")
        pamphlet_pk, chart_pk = pamphlet.id, chart.id

    for kind, mark in (("column", "chart-bar"), ("bar", "chart-row"), ("line", "chart-line"),
                       ("area", "chart-band"), ("pie", "chart-slice"), ("table", "chart-plain")):
        with db.session_scope() as session:
            node = session.get(GraphNode, chart_pk)
            leaflets.save(node, {"leaflet_kind": kind}, set())
        page = client.get(f"/pamphlets/{pamphlet_pk}").text
        assert mark in page, kind
        # More than one series: always a legend.
        if kind != "pie":
            assert "chart-legend" in page, kind


def test_the_editor_shows_the_data_and_the_chart_with_unsaved_settings(client, db):
    with db.session_scope() as session:
        source = a_rest_source(session, ANSWER)
        _, chart = a_chart_from(session, source)
        chart_pk = chart.id

    drawn = drawn_node(db, chart_pk)
    assert drawn["leaflet"]["wired"] and not drawn["leaflet"]["shapedBy"]
    assert {"name": "line", "label": "Line"} in drawn["leaflet"]["kinds"]
    assert "organise the data" in drawn["note"]

    seen = client.post(f"/graph/nodes/{chart_pk}/inspect", data={
        "leaflet_kind": "bar", "leaflet_label": "data.author",
    }).json()
    assert seen["input"]["count"] == 4 and seen["input"]["found_at"] == "data.children"
    assert "data.score" in [field["path"] for field in seen["input"]["fields"]]
    assert "chart-row" in seen["output"]["html"] and "ana · 2" in seen["output"]["html"]
    assert seen["output"]["rows"][0] == {"label": "ana", "how many": 2.0}
    assert not seen["output"]["error"]

    saved = client.post(f"/graph/nodes/{chart_pk}", data={
        "label": "", "leaflet_kind": "line", "leaflet_label": "data.author", "leaflet_limit": "5",
    }).json()
    note = next(n for n in saved["nodes"] if n["id"] == chart_pk)["note"]
    assert note == "line of how many by data.author"
    refused = client.post(f"/graph/nodes/{chart_pk}", data={"leaflet_kind": "radar"})
    assert refused.status_code == 400


def test_a_format_box_still_shapes_and_the_chart_draws_its_bars_as_chosen(client, db):
    with db.session_scope() as session:
        source = a_rest_source(session, ANSWER)
        box = graph.add_format(session, label="Posts by author")
        formatting.save(box, {"format_label": "data.author"})
        graph.connect(session, source, box)
        pamphlet, chart = a_chart_from(session, box, kind="line")
        pamphlet_pk, chart_pk = pamphlet.id, chart.id

    page = client.get(f"/pamphlets/{pamphlet_pk}").text
    assert "Posts by author" in page and "chart-line" in page
    drawn = drawn_node(db, chart_pk)
    assert drawn["leaflet"]["shapedBy"]
    assert drawn["note"] == "Line drawn as the Format box shapes it"


def test_with_nothing_wired_in_the_built_in_counts_take_a_type_too(client, db):
    with db.session_scope() as session:
        pamphlet = graph.add_pamphlet(session, label="Stats")
        chart = graph.add_piece(session, kind="leaflet-chart", host=pamphlet)
        chart.leaflet = json.dumps({"chart": "feeds-held"})
        assert leaflets.settings(chart)["kind"] == "bar"
        leaflets.save(chart, {"leaflet_kind": "pie"}, set())
        assert leaflets.settings(chart)["kind"] == "pie"


def test_it_suggests_fields_that_repeat_and_dates_by_day_and_guesses_one():
    rows = [{"id": f"v{n}", "title": f"Video {n}", "kind": "video" if n % 3 else "short",
             "source": "Channel 5", "published": f"2026-10-0{n + 1}T18:50:37Z", "watched": n % 2 == 0}
            for n in range(6)]
    picks = [pick["label"] for pick in charting.suggest(rows)]
    # Repeating words first, then dates by day; ids and titles never.
    assert picks[0] == "kind" and "published by day" in picks
    assert not {"id", "title"} & set(picks)

    guessed = charting.from_data(rows, said())
    assert guessed.guessed == "kind" and not guessed.error
    assert [c.long for c in guessed.categories] == ["short", "video"]
    # Chosen, it is not a guess.
    assert charting.from_data(rows, said(label="{{ source }}")).guessed == ""


def test_the_editor_says_when_the_chart_is_a_guess(client, db):
    with db.session_scope() as session:
        source = a_rest_source(session, ANSWER)
        _, chart = a_chart_from(session, source)
        chart_pk = chart.id
    seen = client.post(f"/graph/nodes/{chart_pk}/inspect").json()["output"]
    assert seen["guessed"] and "A guess" in seen["note"] and "chart" in seen["html"]
    assert seen["suggested"] and not seen["error"]
