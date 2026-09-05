from __future__ import annotations

import pytest

from dealgo.services.filters import evaluate, format_duration, validate_pattern


def test_a_normal_upload_is_accepted():
    assert evaluate(title="A long essay", duration_sec=1200, live_state="none").accept


def test_shorts_are_skipped_by_default():
    decision = evaluate(title="quick clip", duration_sec=45, live_state="none")
    assert not decision.accept
    assert "Short" in decision.reason


def test_shorts_threshold_is_configurable():
    assert evaluate(title="clip", duration_sec=120, live_state="none").accept
    assert not evaluate(title="clip", duration_sec=120, live_state="none", shorts_max_seconds=180).accept


def test_live_and_premieres_are_skipped():
    assert not evaluate(title="stream", duration_sec=7200, live_state="live").accept
    assert not evaluate(title="premiere", duration_sec=600, live_state="upcoming").accept
    assert evaluate(title="stream", duration_sec=7200, live_state="live", skip_live=False).accept


def test_title_patterns_are_case_insensitive():
    assert not evaluate(title="Weekly PODCAST", duration_sec=600, live_state="none", title_exclude="podcast").accept
    assert evaluate(title="Deep dive", duration_sec=600, live_state="none", title_include="deep").accept
    assert not evaluate(title="Deep dive", duration_sec=600, live_state="none", title_include="^news").accept


def test_duration_bounds():
    assert not evaluate(title="x", duration_sec=100, live_state="none", min_duration_sec=300).accept
    assert not evaluate(title="x", duration_sec=9000, live_state="none", max_duration_sec=3600).accept


def test_unknown_duration_does_not_block_a_video():
    # Without API access there is no duration, and guessing would be worse.
    assert evaluate(title="x", duration_sec=None, live_state=None).accept


def test_validate_pattern_rejects_bad_regex():
    validate_pattern("valid.*", "Title")
    with pytest.raises(ValueError):
        validate_pattern("([unclosed", "Title")


def test_format_duration():
    assert format_duration(None) == "—"
    assert format_duration(253) == "4:13"
    assert format_duration(3723) == "1:02:03"


def test_shorts_are_caught_without_a_duration():
    # No API credentials means no duration, but the feed still flags Shorts.
    decision = evaluate(title="clip", duration_sec=None, live_state=None, is_short=True)
    assert not decision.accept and decision.reason == "Short"
    assert evaluate(title="clip", duration_sec=None, live_state=None, is_short=True, skip_shorts=False).accept


def test_a_long_video_linked_as_a_short_is_still_a_short():
    assert not evaluate(title="clip", duration_sec=170, live_state="none", is_short=True).accept


def test_ordinary_uploads_can_be_rejected_on_their_own():
    decision = evaluate(title="An essay", duration_sec=1200, live_state="none", skip_videos=True)
    assert not decision.accept and decision.reason == "regular video"


def test_switching_off_ordinary_uploads_leaves_the_other_kinds():
    # A Short and a stream are not ordinary uploads, so their own switches rule.
    assert evaluate(
        title="clip", duration_sec=30, live_state="none", skip_videos=True, skip_shorts=False
    ).accept
    assert evaluate(
        title="stream", duration_sec=7200, live_state="live", skip_videos=True, skip_live=False
    ).accept


def test_every_upload_falls_into_exactly_one_kind():
    kinds = [
        dict(title="x", duration_sec=30, live_state="none"),                  # Short
        dict(title="x", duration_sec=1200, live_state="none"),                # ordinary
        dict(title="x", duration_sec=7200, live_state="live"),                # broadcast
    ]
    # With everything switched off, all three are rejected — one reason each.
    reasons = {
        evaluate(**kind, skip_shorts=True, skip_live=True, skip_videos=True).reason
        for kind in kinds
    }
    assert len(reasons) == 3
