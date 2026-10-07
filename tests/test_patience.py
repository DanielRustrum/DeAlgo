"""Waiting when a host asks us to.

Reddit allows an unauthenticated reader about one request a window, and says
so on the *successful* response — `x-ratelimit-remaining: 0` with an
`x-ratelimit-reset` of half a minute. A reader that does not listen spends the
budget, gets refused, and deepens the block; one that listens simply waits.
"""

from __future__ import annotations

import datetime as dt

import httpx
import pytest

from pamphlets.sources import patience


@pytest.fixture(autouse=True)
def forget_waits():
    patience.forget()
    yield
    patience.forget()


def answer(url="https://www.reddit.com/r/python/.rss", status=200, **headers):
    return httpx.Response(
        status, headers=headers, request=httpx.Request("GET", url), text="<rss/>"
    )


def test_a_host_with_budget_left_is_not_waited_for():
    patience.note(answer(**{"x-ratelimit-remaining": "9", "x-ratelimit-reset": "36"}))
    assert patience.wait_for("https://www.reddit.com/r/python/.rss") == 0


def test_a_spent_budget_is_believed_on_a_successful_answer():
    """The whole point: it says so on the 200, so the request that would have
    been refused never happens."""
    patience.note(answer(**{"x-ratelimit-remaining": "0.0", "x-ratelimit-reset": "36"}))

    left = patience.wait_for("https://www.reddit.com/r/python/.rss")
    assert 30 < left <= 36

    with pytest.raises(patience.RateLimited) as refused:
        patience.hold("https://www.reddit.com/r/python/.rss")
    assert refused.value.host == "www.reddit.com"


def test_the_wait_covers_the_host_not_the_one_address():
    """A budget is per host. Another subreddit is the same budget."""
    patience.note(answer(**{"x-ratelimit-remaining": "0", "x-ratelimit-reset": "36"}))

    with pytest.raises(patience.RateLimited):
        patience.hold("https://www.reddit.com/r/ElectricalEngineering/.rss")
    # And somewhere else entirely is unaffected.
    patience.hold("https://example.com/feed")


def test_retry_after_in_seconds_is_obeyed():
    patience.note(answer(status=429, **{"retry-after": "90"}))
    assert 85 < patience.wait_for("https://www.reddit.com/r/python/.rss") <= 90


def test_retry_after_as_a_date_is_obeyed():
    soon = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=120)
    stamp = soon.strftime("%a, %d %b %Y %H:%M:%S GMT")
    patience.note(answer(status=429, **{"retry-after": stamp}))

    assert 100 < patience.wait_for("https://www.reddit.com/r/python/.rss") <= 121


def test_a_reset_given_as_a_moment_rather_than_a_gap_is_understood():
    """Some hosts count seconds to wait; others give the epoch second the
    budget returns. Told apart by size."""
    when = dt.datetime.now(dt.timezone.utc).timestamp() + 45
    patience.note(
        answer(**{"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(int(when))})
    )
    assert 35 < patience.wait_for("https://www.reddit.com/r/python/.rss") <= 46


def test_the_longest_wait_in_hand_wins():
    """A second opinion may extend a wait and must never cut one short."""
    patience.rest("https://www.reddit.com/r/python/.rss", 300)
    patience.rest("https://www.reddit.com/r/python/.rss", 5)

    assert patience.wait_for("https://www.reddit.com/r/python/.rss") > 250


def test_no_host_is_waited_for_longer_than_an_hour():
    """A header asking for a day is either misread or a host we should not be
    polling on a schedule at all."""
    patience.rest("https://www.reddit.com/r/python/.rss", 86400)

    assert patience.wait_for("https://www.reddit.com/r/python/.rss") <= patience.MOST_WE_WAIT


def test_a_bare_refusal_still_buys_a_pause():
    """Reddit answers 403 once a burst has spent the budget, and says nothing
    about when to come back. Asking straight again is what turns a busy minute
    into a block."""
    for status in patience.REFUSALS:
        patience.forget()
        patience.note(answer(status=status))
        left = patience.wait_for("https://www.reddit.com/r/python/.rss")
        assert left > 0, f"{status} bought no pause at all"
        assert left <= patience.AFTER_A_REFUSAL


def test_a_plain_failure_is_not_treated_as_a_rate_limit():
    """A 404 is not "come back later" — it is "there is nothing here", and
    waiting on it would hide a source that needs fixing."""
    patience.note(answer(status=404))
    assert patience.wait_for("https://www.reddit.com/r/python/.rss") == 0


def test_nonsense_headers_fall_back_rather_than_being_believed():
    """An unreadable Retry-After must not become "no wait at all" on a
    response that was a refusal."""
    for bad in ("soon", "", "-1"):
        patience.forget()
        patience.note(answer(status=429, **{"retry-after": bad}))
        assert patience.wait_for("https://www.reddit.com/r/python/.rss") > 0

    # But on a perfectly good answer, nonsense buys nothing.
    patience.forget()
    patience.note(answer(status=200, **{"x-ratelimit-remaining": "soon"}))
    assert patience.wait_for("https://www.reddit.com/r/python/.rss") == 0


def test_a_fetch_refuses_to_ask_a_host_that_is_still_waiting(monkeypatch):
    """What the second Backfill press does now: nothing at all, rather than a
    request everybody involved knows will be refused."""
    from pamphlets.sources import syndication

    asked = []

    class Client:
        def get(self, url, headers=None):
            asked.append(url)
            return answer(url=url, **{"x-ratelimit-remaining": "0", "x-ratelimit-reset": "36"})

    client = Client()
    syndication.fetch("https://www.reddit.com/r/python/.rss", client)
    assert len(asked) == 1

    with pytest.raises(patience.RateLimited):
        syndication.fetch("https://www.reddit.com/r/python/.rss", client)
    assert len(asked) == 1, "it asked again after being told the budget was spent"
