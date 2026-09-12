"""The stylesheet is generated. These tests keep the copy in the repo honest.

The container ships the compiled CSS and never runs a compiler, so a partial
edited without rebuilding would look fine in the tests and wrong in the app.
"""

from __future__ import annotations

import pytest

from dealgo.web import styles

sass = pytest.importorskip("sass", reason="libsass is a build-time dependency")


def test_the_committed_stylesheet_matches_its_sources():
    assert styles.TARGET.read_text() == styles.compile_css(), (
        "static/app.css is out of date with web/scss/ — run `make css`."
    )


def test_every_partial_is_reachable_from_the_entry_point():
    """A partial nobody imports is dead weight that still looks live."""
    entry = styles.SOURCE.read_text()
    partials = sorted(p.stem.lstrip("_") for p in styles.SOURCE.parent.glob("_*.scss"))
    unused = [name for name in partials if f'@import "{name}"' not in entry]
    assert unused == []


def test_the_compiled_file_says_not_to_edit_it():
    assert "do not edit" in styles.TARGET.read_text()[:400]


def squashed() -> str:
    """The compiled stylesheet with its whitespace taken out.

    It is minified, so matching on layout would be testing the compiler
    rather than the rule.
    """
    import re

    return re.sub(r"\s+", "", styles.TARGET.read_text())


def test_a_wire_can_be_clicked_through_the_layer_of_boxes():
    """The boxes are painted over the wires and cover the whole canvas, so
    without this a click aimed at a wire lands on the empty layer instead —
    which looks exactly like a wire that cannot be picked, with nothing in the
    console to say why."""
    css = squashed()
    assert ".graph-nodes{" in css
    assert "pointer-events:none" in css.split(".graph-nodes{", 1)[1].split("}", 1)[0]
    # And the parts that do answer say so, since the rule above is inherited.
    assert ".graph-node,.graph-cut{pointer-events:auto}" in css
    assert "pointer-events:stroke" in css.split(".graph-wire-hit{", 1)[1].split("}", 1)[0]


def test_the_open_box_takes_its_own_clicks():
    """A click inside the open box must reach the field it landed on. The
    layer it sits in passes pointers through, so it has to opt back in — and
    without that, typing into it closes it."""
    css = squashed()
    body = css.split(".graph-pop{", 1)[1].split("}", 1)[0]
    assert "pointer-events:auto" in body


def test_the_add_button_sits_on_the_canvas():
    """It makes something that lands on the canvas, so it lives there."""
    css = squashed()
    assert ".graph-overlay{" in css
    assert "position:absolute" in css.split(".graph-overlay{", 1)[1].split("}", 1)[0]


def test_the_canvas_is_as_wide_as_the_window():
    """The canvas is the configuration page, not an illustration in it, so it
    breaks out of the column the rest of the app reads in."""
    css = squashed()
    panel = css.split(".graph-panel{", 1)[1].split("}", 1)[0]
    assert "margin-inline:calc(50% - 50vw + 16px)".replace(" ", "") in panel


def test_the_page_cannot_scroll_sideways():
    """100vw counts a vertical scrollbar and the layout does not, so the
    gutter has to be wide enough to swallow one."""
    css = squashed()
    panel = css.split(".graph-panel{", 1)[1].split("}", 1)[0]
    gutter = panel.split("50vw+", 1)[1].split("px", 1)[0]
    assert int(gutter) >= 16


def test_nothing_is_held_back_for_a_panel_beside_the_canvas():
    """The detail panel moved onto the canvas. The column that had been kept
    for it stayed behind in the grid, taking 300px of canvas with it — width
    that nothing was drawn in and nothing explained."""
    css = squashed()
    frame = css.split(".graph-frame{", 1)[1].split("}", 1)[0]
    assert "grid-template-columns" not in frame


def test_the_modal_close_button_is_styled_as_one():
    """It was an <a> in the wizard this style came from; it is a <button> now,
    and a button carries a border and a background unless told otherwise."""
    css = squashed()
    rule = css.split(".modal-close{", 1)[1].split("}", 1)[0]
    assert "border:none" in rule and "background:none" in rule


def test_the_two_sides_of_a_filter_are_told_apart_by_colour():
    """Which side is which is the first thing to read, and it should not need
    reading: green is what got through, red is what did not."""
    css = squashed()
    assert ".graph-sheet-part.is-through .graph-sheet-name{color:var(--ok)}".replace(" ", "") in css
    assert ".graph-sheet-part.is-held .graph-sheet-name{color:var(--bad)}".replace(" ", "") in css


def test_the_two_sides_sit_next_to_each_other():
    """They are read against each other — the question is always why that one
    is over there and not over here."""
    css = squashed()
    body = css.split(".graph-catch .modal-body{".replace(" ", ""), 1)[1].split("}", 1)[0]
    assert "grid-template-columns:minmax(0,1fr)minmax(0,1fr)" in body


def test_a_long_title_cannot_push_the_dialog_wider_than_itself():
    """A bare 1fr will not shrink below its content, so one long title widens
    the column past the dialog and the ellipsis never gets a width to work
    against. Every column here has to be allowed to shrink."""
    css = squashed()
    for rule in css.split(".graph-catch .modal-body{".replace(" ", ""))[1:]:
        assert "minmax(0,1fr)" in rule.split("}", 1)[0]
    assert ".graph-sheet-part,.graph-sheet-row,.graph-sheet-list{min-width:0}" in css


def test_the_page_can_be_held_still():
    """One class, used by everything that opens over the page: the tab drawer
    and the modal both need the page behind them to stay put."""
    assert ".page-held{overflow:hidden}" in squashed()


def test_a_switched_off_box_looks_switched_off():
    """It is still drawn, still wired and still draggable — it simply does
    nothing, and a box that does nothing should not look like one that does."""
    css = squashed()
    rule = css.split(".graph-node.is-off{", 1)[1].split("}", 1)[0]
    assert "opacity:" in rule


def test_a_ports_dot_sits_on_the_edge_it_wires_from():
    """Wires are drawn to and from the box's edge, so a dot centred anywhere
    else leaves a visible gap between the wire and the thing it comes out of."""
    css = squashed()
    assert ".port-in{left:-8px}" in css and ".port-out{right:-8px}" in css
    # Which means the dot is 16px across: half of it either side of the edge.
    port = css.split(".graph-port{", 1)[1].split("}", 1)[0]
    assert "width:16px" in port


def test_a_numbered_list_keeps_its_numbers_inside_the_box():
    """The browser's own markers sit outside the content box and wander as the
    count reaches ten, which in a 380px panel pushes them off the edge."""
    css = squashed()
    assert ".graph-sheet-list.is-numbered{counter-reset:landing}" in css
    marker = css.split(".graph-sheet-list.is-numbered .graph-sheet-row::before{".replace(" ", ""), 1)
    assert "position:absolute" in marker[1].split("}", 1)[0]


def test_the_add_button_is_round_and_has_no_words_to_wrap():
    """A plus over the drawing: every pixel it takes is a pixel of canvas."""
    css = squashed()
    rule = css.split(".graph-add{", 1)[1].split("}", 1)[0]
    assert "border-radius:50%" in rule
    assert "width:34px" in rule and "height:34px" in rule


def test_both_drawers_come_from_the_same_edge():
    """One habit to learn rather than two, and neither can cover the other
    because only one is ever out."""
    css = squashed()
    for drawer in (".graph-palette{", ".graph-finder{"):
        rule = css.split(drawer, 1)[1].split("}", 1)[0]
        assert "right:0" in rule, drawer


def test_a_group_is_drawn_under_the_wires_it_surrounds():
    """A group covers a large area. Above the wires, it swallowed the clicks
    meant for every wire crossing it — and a wire nobody can click is a wire
    nobody can take out."""
    css = squashed()
    order = [
        css.index(".graph-groups{"),
        css.index(".graph-wires{"),
        css.index(".graph-nodes{"),
    ]
    # Later rules do not decide this — the layers are separate elements in
    # document order — but the three must exist for that order to hold.
    assert all(place > 0 for place in order)
    assert "pointer-events:none" in css.split(".graph-nodes{", 1)[1].split("}", 1)[0]
