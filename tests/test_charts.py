"""Chart leaflets: a leaflet for each kind of chart, drawn by Chart.js.

Data comes straight from a source, an operation or a Transform box — or as
bars from a Format box — and the leaflet's own settings say where the rows
are, what labels a point, what number it shows and what splits it into
series. Which chart it is, is which leaflet it is; how it is drawn — across
or up, stacked, filled, a doughnut — is its own few choices. The page carries
each chart's data as JSON for Chart.js to draw in the theme's chart colours.
"""

from __future__ import annotations

import json
import re

import pytest

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


def test_a_chart_is_handed_to_chart_js_as_data_with_its_colours_as_slots():
    chart = charting.from_data(ROWS, said(kind="line", label="day", value="score", combine="sum",
                                          series="who", fill="area", stacking="stacked"))
    config = chart.config()
    assert config["type"] == "line" and config["style"] == {"fill": "area", "stacking": "stacked"}
    assert config["labels"] == ["2026-10-01", "2026-10-02", "2026-10-03"]
    assert config["series"][0] == {"name": "ana", "slot": 1, "values": [10, 6, 0]}
    # A slot, not a colour: the browser reads the theme's chart colour for it.
    assert "#" not in json.dumps(config)


def test_scatter_and_bubble_charts_place_a_point_for_each_row():
    rows = [{"when": f"2026-10-0{n}", "views": n * 10, "likes": n, "who": "ana" if n % 2 else "ben"}
            for n in range(1, 6)]
    scatter = charting.from_data(rows, said(kind="scatter", x="{{ views }}", y="likes", series="who"))
    assert [one.name for one in scatter.placed] == ["ana", "ben"]
    assert scatter.placed[0].points[0] == {"x": 10.0, "y": 1.0}
    bubble = charting.from_data(rows, said(kind="bubble", x="when", y="views", size="likes"))
    assert bubble.x_dates and bubble.placed[0].points[-1]["r"] == 20.0
    # Nothing chosen: the likeliest two, as a guess.
    guessed = charting.from_data(rows, said(kind="scatter"))
    assert guessed.guessed == "when along, views up" and guessed.drawn


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


def a_chart_from(session, source, kind="leaflet-bar", **settings):
    pamphlet = graph.add_pamphlet(session, label="Stats")
    chart = graph.add_piece(session, kind=kind, host=pamphlet)
    leaflets.save(chart, {f"leaflet_{k}": str(v) for k, v in settings.items()}, set())
    graph.connect(session, source, chart)
    return pamphlet, chart


def configs(page):
    """Every chart's data on a page, as Chart.js is handed it."""
    return [json.loads(found) for found in
            re.findall(r'<script type="application/json" data-chart-config>(.*?)</script>', page, re.S)]


def test_a_source_wires_straight_into_a_chart_and_is_drawn_as_it_says(client, db):
    with db.session_scope() as session:
        source = a_rest_source(session, ANSWER)
        pamphlet, _ = a_chart_from(session, source, "leaflet-pie", label="data.author",
                                   value="data.score", combine="sum", shape="doughnut")
        pamphlet_pk = pamphlet.id

    page = client.get(f"/pamphlets/{pamphlet_pk}").text
    assert 'class="chart-js is-pie"' in page and "<canvas" in page
    [config] = configs(page)
    assert config["type"] == "pie" and config["style"]["shape"] == "doughnut"
    assert config["labels"] == ["ana", "ben", "cy"] and config["series"][0]["values"] == [16, 4, 2]
    assert config["series"][0]["slots"] == [1, 2, 3]
    assert "sum data.score by data.author" in page


@pytest.mark.parametrize("kind", ["leaflet-bar", "leaflet-line", "leaflet-pie", "leaflet-radar",
                                  "leaflet-polar", "leaflet-scatter", "leaflet-bubble"])
def test_every_drawn_chart_hands_its_data_to_chart_js(client, db, kind):
    with db.session_scope() as session:
        source = a_rest_source(session, ANSWER)
        pamphlet, _ = a_chart_from(session, source, kind, label="data.author", series="data.flair",
                                   x="data.created_utc", y="data.score")
        pamphlet_pk = pamphlet.id
    page = client.get(f"/pamphlets/{pamphlet_pk}").text
    [config] = configs(page)
    assert config["type"] == charting.kind_of(kind)
    assert "As a table" not in page


def test_a_number_and_a_table_are_set_not_drawn(client, db):
    with db.session_scope() as session:
        source = a_rest_source(session, ANSWER)
        number, _ = a_chart_from(session, source, "leaflet-number", value="data.score", combine="sum")
        table, _ = a_chart_from(session, source, "leaflet-table", label="data.author")
        number_pk, table_pk = number.id, table.id
    assert '<p class="paper-figure">22</p>' in client.get(f"/pamphlets/{number_pk}").text
    page = client.get(f"/pamphlets/{table_pk}").text
    assert 'class="chart-plain"' in page and "<canvas" not in page


def test_a_chart_s_own_choices_are_kept_and_others_refused(db):
    with db.session_scope() as session:
        pamphlet = graph.add_pamphlet(session, label="Stats")
        bar = graph.add_piece(session, kind="leaflet-bar", host=pamphlet)
        leaflets.save(bar, {"leaflet_direction": "horizontal", "leaflet_stacking": "stacked"}, set())
        assert leaflets.settings(bar)["direction"] == "horizontal"
        with pytest.raises(graph.GraphError):
            leaflets.save(bar, {"leaflet_direction": "sideways"}, set())
        # A bar chart has no doughnut to choose: the setting is not one of its own.
        leaflets.save(bar, {"leaflet_shape": "doughnut"}, set())
        assert "shape" not in leaflets.settings(bar)


def test_the_editor_shows_the_data_and_the_chart_with_unsaved_settings(client, db):
    with db.session_scope() as session:
        source = a_rest_source(session, ANSWER)
        _, chart = a_chart_from(session, source)
        chart_pk = chart.id

    drawn = drawn_node(db, chart_pk)
    assert drawn["leaflet"]["wired"] and not drawn["leaflet"]["shapedBy"]
    assert [one["name"] for one in drawn["leaflet"]["styles"]] == ["direction", "stacking"]
    assert "say what each one is" in drawn["note"]

    seen = client.post(f"/graph/nodes/{chart_pk}/inspect", data={
        "leaflet_direction": "horizontal", "leaflet_label": "data.author",
    }).json()
    assert seen["input"]["count"] == 4 and seen["input"]["found_at"] == "data.children"
    assert "data.score" in [field["path"] for field in seen["input"]["fields"]]
    [config] = configs(seen["output"]["html"])
    assert config["style"]["direction"] == "horizontal" and config["labels"] == ["ana", "ben", "cy"]
    assert seen["output"]["rows"][0] == {"label": "ana", "how many": 2.0}
    assert not seen["output"]["error"]

    saved = client.post(f"/graph/nodes/{chart_pk}", data={
        "label": "", "leaflet_label": "data.author", "leaflet_limit": "5",
    }).json()
    note = next(n for n in saved["nodes"] if n["id"] == chart_pk)["note"]
    assert note == "how many by data.author"
    refused = client.post(f"/graph/nodes/{chart_pk}", data={"leaflet_direction": "sideways"})
    assert refused.status_code == 400


def test_a_format_box_still_shapes_and_the_chart_draws_its_bars_as_chosen(client, db):
    with db.session_scope() as session:
        source = a_rest_source(session, ANSWER)
        box = graph.add_format(session, label="Posts by author")
        formatting.save(box, {"format_label": "data.author"})
        graph.connect(session, source, box)
        pamphlet, chart = a_chart_from(session, box, "leaflet-line")
        pamphlet_pk, chart_pk = pamphlet.id, chart.id

    page = client.get(f"/pamphlets/{pamphlet_pk}").text
    assert "Posts by author" in page and configs(page)[0]["type"] == "line"
    drawn = drawn_node(db, chart_pk)
    assert drawn["leaflet"]["shapedBy"]
    assert drawn["note"] == "drawn as the Format box shapes it"


def test_with_nothing_wired_in_a_chart_draws_a_built_in_count(client, db):
    with db.session_scope() as session:
        pamphlet = graph.add_pamphlet(session, label="Stats")
        chart = graph.add_piece(session, kind="leaflet-pie", host=pamphlet)
        leaflets.save(chart, {"leaflet_chart": "feeds-held"}, set())
        number = graph.add_piece(session, kind="leaflet-number", host=pamphlet)
        pamphlet_pk = pamphlet.id
        assert leaflets.settings(number)["chart"] == "counts"
    page = client.get(f"/pamphlets/{pamphlet_pk}").text
    assert "What each feed holds" in page


def test_an_old_chart_leaflet_becomes_the_chart_it_drew(db):
    from pamphlets.db.migrations import charts_have_their_own_leaflets

    with db.session_scope() as session:
        pamphlet = graph.add_pamphlet(session, label="Stats")
        made = {}
        for drawn in ("column", "bar", "area", "pie", "number", "table"):
            node = GraphNode(kind="leaflet-chart", attached_to=pamphlet.id, attached_side="below",
                             leaflet=json.dumps({"kind": drawn, "label": "who", "title": drawn}))
            session.add(node)
            session.flush()
            made[drawn] = node.id
        counts = GraphNode(kind="leaflet-chart", attached_to=pamphlet.id, leaflet=json.dumps({"chart": "counts"}))
        session.add(counts)
        session.flush()
        made["counts"] = counts.id

    charts_have_their_own_leaflets()
    with db.session_scope() as session:
        turned = {drawn: session.get(GraphNode, pk) for drawn, pk in made.items()}
        assert turned["column"].kind == "leaflet-bar"
        assert leaflets.settings(turned["column"])["direction"] == "vertical"
        assert leaflets.settings(turned["bar"])["direction"] == "horizontal"
        area = leaflets.settings(turned["area"])
        assert turned["area"].kind == "leaflet-line" and area["fill"] == "area" and area["stacking"] == "stacked"
        assert [turned[k].kind for k in ("pie", "number", "table", "counts")] == [
            "leaflet-pie", "leaflet-number", "leaflet-table", "leaflet-number"]
        # What it showed is kept.
        assert leaflets.settings(turned["pie"])["label"] == "who"
        assert leaflets.settings(turned["pie"])["title"] == "pie"


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
