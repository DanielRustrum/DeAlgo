"""The host's own rules, and YouTube's kinds of content, which are its plugin's.

The host narrows by title and length, and leaves out whatever kind of content
a source says it does not take. Which kind an item is — a Short, a broadcast
— is the YouTube plugin's `classify` to say, so those cases are asked of it.
"""

from __future__ import annotations

import pytest

from pamphlets.plugins import registry
from pamphlets.plugins.capabilities import acting_for
from pamphlets.services import plugin_settings
from pamphlets.services.filters import evaluate, format_duration, validate_pattern


# -- the host's rules ------------------------------------------------------------


def test_a_normal_item_is_accepted():
    assert evaluate(title="A long essay", duration_sec=1200).accept


def test_a_kind_its_source_leaves_out_is_held_in_its_own_words():
    decision = evaluate(title="quick clip", duration_sec=45, left_out="Shorts")
    assert not decision.accept and decision.reason == "Shorts"


def test_title_patterns_are_case_insensitive():
    assert not evaluate(title="Weekly PODCAST", duration_sec=600, title_exclude="podcast").accept
    assert evaluate(title="Deep dive", duration_sec=600, title_include="deep").accept
    assert not evaluate(title="Deep dive", duration_sec=600, title_include="^news").accept


def test_duration_bounds():
    assert not evaluate(title="x", duration_sec=100, min_duration_sec=300).accept
    assert not evaluate(title="x", duration_sec=9000, max_duration_sec=3600).accept


def test_unknown_duration_does_not_block_an_item():
    # Without API access there is no duration, and guessing would be worse.
    assert evaluate(title="x", duration_sec=None).accept


def test_validate_pattern_rejects_bad_regex():
    validate_pattern("valid.*", "Title")
    with pytest.raises(ValueError):
        validate_pattern("([unclosed", "Title")


def test_format_duration():
    assert format_duration(None) == "—"
    assert format_duration(253) == "4:13"
    assert format_duration(3723) == "1:02:03"


# -- YouTube's kinds, which its plugin sorts ----------------------------------------


def kind_of(**item) -> str | None:
    shown = {"title": "x", "kind": "video", "hint": "", "duration": 0, "live": "", **item}
    return registry.current().classify("youtube", shown, None)


def test_youtube_says_which_kind_each_item_is(db):
    assert kind_of(duration=1200) == "videos"
    assert kind_of(duration=45) == "shorts"
    assert kind_of(duration=7200, live="live") == "live"
    assert kind_of(duration=600, live="upcoming") == "live"
    assert kind_of(kind="post") == "posts"


def test_a_short_is_caught_without_a_duration(db):
    """No API credentials means no duration, but the feed still links Shorts as such."""
    assert kind_of(duration=0, hint="shorts") == "shorts"


def test_a_long_video_linked_as_a_short_is_still_a_short(db):
    assert kind_of(duration=170, hint="shorts") == "shorts"


def test_what_counts_as_a_short_is_each_accounts_own(db):
    assert kind_of(duration=120) == "videos"
    plugin_settings.save("youtube", "user", None, {"shorts_max_seconds": "180"})
    with acting_for(None):
        assert kind_of(duration=120) == "shorts"


def test_youtube_declares_its_kinds_and_which_start_off():
    takes = registry.current().takes("youtube")
    assert [(one.name, one.off, one.extras) for one in takes] == [
        ("videos", False, False),
        ("shorts", True, False),
        ("live", True, False),
        ("posts", False, True),
    ]


def test_a_source_that_declares_no_kinds_is_never_sorted(db):
    assert registry.current().classify("reddit", {"title": "x"}, None) is None
