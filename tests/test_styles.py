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
