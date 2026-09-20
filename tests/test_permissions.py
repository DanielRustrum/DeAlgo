"""What a plugin may ask for beyond the table it starts with.

A plugin begins with nothing. Everything past that is asked for by name and
granted by a person, and what is granted is simply what gets put in its
environment — a plugin without the network permission does not find a locked
door, it finds no door.
"""

from __future__ import annotations

import httpx
import pytest

from dealgo.plugins import permissions


def a_client(answers):
    """An httpx client that answers from memory, and records what was asked."""
    asked: list[str] = []

    class Client:
        def get(self, url):
            asked.append(url)
            status, body = answers.get(url, (404, b""))
            return httpx.Response(status, request=httpx.Request("GET", url), content=body)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    return asked, (lambda: Client())


@pytest.fixture(autouse=True)
def forget_waits():
    from dealgo.sources import patience

    patience.forget()
    yield
    patience.forget()


# -- what a grant puts in reach --------------------------------------------


def test_nothing_granted_means_nothing_at_all():
    assert permissions.capabilities("x", frozenset()) == {}


def test_each_grant_brings_exactly_one_thing():
    given = permissions.capabilities("x", frozenset({"clock", "log", "network"}))

    assert sorted(given) == ["clock", "log", "net"]


def test_a_name_nobody_wrote_down_brings_nothing():
    assert permissions.capabilities("x", frozenset({"telepathy"})) == {}


def test_an_unknown_permission_still_describes_itself():
    """A plugin asking for something this version has no name for has to draw
    on the page rather than vanishing from it."""
    said = permissions.describe("telepathy")

    assert said.name == "telepathy"
    assert "does not know" in said.means
    assert said.caution


# -- fetching --------------------------------------------------------------


def test_a_plugin_fetches_through_the_host():
    asked, client = a_client({"https://example.com/a": (200, b"hello")})
    net = permissions.capabilities("Asker", frozenset({"network"}), client)["net"]

    assert net.get("https://example.com/a") == "hello"
    assert asked == ["https://example.com/a"]


def test_a_plugins_fetch_waits_when_a_host_asked_it_to():
    """Through the same `patience` De-Algo's own requests use, so a plugin
    cannot spend a rate-limit budget behind the back of the thing tracking
    it."""
    from dealgo.sources import patience

    body = (200, b"<rss/>")
    asked, client = a_client({"https://www.reddit.com/r/x/.rss": body})
    net = permissions.capabilities("Asker", frozenset({"network"}), client)["net"]

    patience.rest("https://www.reddit.com/r/x/.rss", 60)
    assert net.get("https://www.reddit.com/r/x/.rss") is None
    assert asked == [], "it asked anyway"


def test_a_plugins_fetch_feeds_what_it_learns_back_to_patience():
    from dealgo.sources import patience

    url = "https://www.reddit.com/r/x/.rss"

    class Limiting:
        def get(self, url):
            return httpx.Response(
                200,
                headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "40"},
                request=httpx.Request("GET", url),
                content=b"ok",
            )

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    net = permissions.capabilities("Asker", frozenset({"network"}), lambda: Limiting())["net"]
    net.get(url)

    assert patience.wait_for(url) > 0, "what it learned was kept to itself"


def test_a_plugin_cannot_fetch_something_that_is_not_a_web_address():
    asked, client = a_client({})
    net = permissions.capabilities("Asker", frozenset({"network"}), client)["net"]

    assert net.get("file:///etc/passwd") is None
    assert net.get("/data/dealgo.sqlite3") is None
    assert net.get("") is None
    assert asked == []


def test_a_plugin_cannot_fetch_for_ever():
    """A plugin resolving a handle needs one request. A plugin walking a site
    needs a different design."""
    answers = {f"https://example.com/{i}": (200, b"x") for i in range(20)}
    asked, client = a_client(answers)
    net = permissions.capabilities("Asker", frozenset({"network"}), client)["net"]

    for i in range(20):
        net.get(f"https://example.com/{i}")

    assert len(asked) == permissions.MOST_REQUESTS


def test_something_too_large_is_refused_rather_than_held():
    asked, client = a_client(
        {"https://example.com/big": (200, b"x" * (permissions.MOST_BYTES + 10))}
    )
    net = permissions.capabilities("Asker", frozenset({"network"}), client)["net"]

    assert net.get("https://example.com/big") is None


def test_a_page_that_is_not_there_is_nothing_rather_than_an_error():
    """A plugin is a filter, and a filter that throws because a site was down
    is a filter that stops a sync."""
    asked, client = a_client({})
    net = permissions.capabilities("Asker", frozenset({"network"}), client)["net"]

    assert net.get("https://example.com/gone") is None


def test_a_client_that_explodes_is_nothing_too():
    def explodes():
        raise RuntimeError("no network at all")

    net = permissions.capabilities("Asker", frozenset({"network"}), explodes)["net"]

    assert net.get("https://example.com/a") is None


# -- the quiet ones --------------------------------------------------------


def test_the_clock_says_the_time_and_nothing_else_about_the_machine():
    import datetime as dt

    clock = permissions.capabilities("x", frozenset({"clock"}))["clock"]
    now = clock.now()

    assert abs(now - dt.datetime.now(dt.timezone.utc).timestamp()) < 5
    assert not hasattr(clock, "sleep")


def test_a_plugins_log_line_is_bounded(caplog):
    """A log line is not a place to put a feed."""
    logger = permissions.capabilities("Noisy", frozenset({"log"}))["log"]

    with caplog.at_level("INFO"):
        logger.info("x" * 5000)

    assert len(caplog.records) == 1
    assert len(caplog.records[0].getMessage()) < 800
    assert "Noisy" in caplog.records[0].getMessage()
