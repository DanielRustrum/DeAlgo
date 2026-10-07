"""Notices, out of the way of the page.

Two sorts, and they behave differently because they mean different things. A
*passing* one reports something that just happened and goes by itself. A
*standing* one reports a condition — no Google account, a guessable admin
password — which is still true after you look away, so it waits.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from pamphlets.models import OAuthToken, Playlist

HARNESS = pathlib.Path(__file__).resolve().parent / "toast_harness.js"
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")


@pytest.fixture(scope="module")
def report():
    result = subprocess.run(["node", str(HARNESS)], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


@pytest.fixture
def client(db, monkeypatch):
    from pamphlets import scheduler
    from pamphlets.web import app as web_app

    monkeypatch.setattr(scheduler, "start", lambda: None)
    monkeypatch.setattr(scheduler, "shutdown", lambda: None)
    monkeypatch.setattr(scheduler, "next_run_time", lambda: None)
    monkeypatch.setattr(web_app, "init_db", lambda: None)

    with TestClient(web_app.app) as test_client:
        yield test_client


# -- how each sort behaves -------------------------------------------------


@needs_node
def test_something_that_just_happened_goes_by_itself(report):
    """It has been read by the time it is read."""
    assert report["passing"]["timerCount"] == 1
    assert report["passing"]["secondsUntilGone"] == 7


@needs_node
def test_a_standing_condition_waits_to_be_dealt_with(report):
    """A warning that disappears on a timer is a warning nobody acts on."""
    assert report["standing"]["timerCount"] == 0
    assert report["standing"]["hasCloseButton"] is True


@needs_node
def test_dismissing_a_standing_one_is_remembered_for_the_session(report):
    """For the session and not for ever: a warning you can permanently
    silence by accident is one that will be silenced by accident. Settings
    holds the real off switch."""
    assert report["dismissRemembers"]["memory"] == {"toast:weak-password": "gone"}


@needs_node
def test_one_already_dismissed_does_not_come_back_this_session(report):
    assert report["alreadyDismissed"]["removed"] is True


@needs_node
def test_a_passing_one_leaves_nothing_remembered(report):
    """It has no identity worth keeping: the next one is a different message
    about a different thing."""
    assert report["dismissPassing"]["memory"] == {}


@needs_node
def test_storage_that_throws_does_not_break_the_notice(report):
    """A private window and blocked site data both throw on access rather
    than on use. The toast still shows and still closes; the dismissal simply
    does not outlive the page."""
    assert report["storageBlocked"]["shown"] is True
    assert report["storageBlocked"]["going"] is True


@needs_node
def test_running_the_script_again_does_not_restart_anything(report):
    """htmx re-runs it on every boosted navigation. A second close button, or
    a second timer on a toast already counting down, would both show."""
    assert report["runTwice"]["children"] == 1
    assert report["runTwice"]["timerCount"] == 1


@needs_node
def test_it_notices_messages_that_arrive_without_a_page_load(report):
    """The flash is swapped out of band by almost every form on the site."""
    assert "htmx:oobAfterSwap" in report["listensFor"]


# -- where they are on the page --------------------------------------------


def test_notices_are_out_of_the_way_of_the_page(client):
    """They used to push the thing you came for down the screen on every
    single load."""
    body = client.get("/").text

    assert 'class="toasts"' in body
    head, rest = body.split('<div class="toasts"', 1)
    # After the content, not before it: with no CSS they are a footnote
    # rather than a wall.
    assert "</main>" in head


def test_a_standing_notice_says_which_one_it_is(client, db):
    """So dismissing it can be remembered, and so a test can name it without
    naming how it is drawn."""
    with db.session_scope() as session:
        session.add(Playlist(playlist_id="PLreal", title="A YouTube feed", enabled=True))

    body = client.get("/").text

    assert 'data-toast="no-sign-in"' in body


def test_a_passing_message_is_marked_as_passing(client):
    # Any route that redirects carrying a complaint; this one is reliably
    # not found, whatever else is on the canvas.
    answer = client.get("/channels/99999", follow_redirects=True)

    assert "data-toast-passing" in answer.text
    assert "toast-bad" in answer.text


def test_a_notice_with_nothing_to_say_shows_nothing(client, db):
    """The region is always there, for messages that arrive later. It is what
    is inside it that is conditional."""
    with db.session_scope() as session:
        session.add(OAuthToken(provider="youtube", id=1, access_token="tok", account_title="Someone"))

    body = client.get("/").text

    assert 'class="toasts"' in body
    assert 'data-toast="no-sign-in"' not in body
