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
