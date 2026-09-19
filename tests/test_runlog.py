"""The record of what each run did.

The counts on a run say how much happened. The log says what, in what order,
and which of the several things that can go quiet went quiet — and it says
who started it, which is the first question anybody asks of a line in a log.
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from dealgo.models import Channel, Playlist, RunEvent, SyncRun, Video, utcnow
from dealgo.services import runlog
from tests.test_graph import canvas  # noqa: F401


@pytest.fixture
def client(db, monkeypatch):
    from dealgo import scheduler
    from dealgo.web import app as web_app

    monkeypatch.setattr(scheduler, "start", lambda: None)
    monkeypatch.setattr(scheduler, "shutdown", lambda: None)
    monkeypatch.setattr(scheduler, "next_run_time", lambda: None)
    monkeypatch.setattr(web_app, "init_db", lambda: None)

    with db.session_scope() as session:
        session.add_all([
            Channel(channel_id="UCone", title="One Channel"),
            Playlist(playlist_id="generic:one", title="One Feed"),
        ])

    with TestClient(web_app.app) as test_client:
        yield test_client


def a_run(db, *, trigger="scheduled", ok=True, finished=True, lines=()):
    with db.session_scope() as session:
        run = SyncRun(
            trigger=trigger, started_at=utcnow(), ok=ok,
            finished_at=utcnow() if finished else None,
        )
        session.add(run)
        session.flush()
        pen = runlog.Pen(session, run.id)
        for message in lines:
            pen.write(message)
        return run.id


# -- who started it --------------------------------------------------------


def test_a_run_knows_whether_a_person_started_it():
    """The distinction the log exists to draw."""
    for trigger in ("pulse", "backfill", "test", "manual", "cli"):
        assert SyncRun(trigger=trigger).by_hand is True, trigger
    assert SyncRun(trigger="scheduled").by_hand is False


def test_each_way_of_starting_one_is_named_after_the_thing_pressed():
    """"pulse" is what the code calls it; "Run now" is what the button says,
    and the button is what the reader remembers pressing."""
    assert SyncRun(trigger="pulse").how == "Run now"
    assert SyncRun(trigger="backfill").how == "Backfill"
    assert SyncRun(trigger="test").how == "Test"
    assert SyncRun(trigger="scheduled").how == "On a schedule"


def test_a_trigger_nobody_has_named_is_shown_as_itself():
    """A row written by a later version should still draw on an earlier one."""
    assert SyncRun(trigger="something-new").how == "something-new"
    assert SyncRun(trigger="something-new").by_hand is False


def test_only_a_trial_claims_to_have_written_nothing():
    assert SyncRun(trigger="test").wrote_nothing is True
    assert SyncRun(trigger="pulse").wrote_nothing is False


# -- writing it ------------------------------------------------------------


def test_lines_keep_the_order_they_were_written_in(db):
    """Several can share a timestamp, and a log whose order depends on how
    fast the clock ticks is not a log."""
    run_pk = a_run(db, lines=[f"line {i}" for i in range(5)])

    with db.session_scope() as session:
        lines = runlog.lines_for(session, run_pk)
    assert [line.message for line in lines] == [f"line {i}" for i in range(5)]
    assert [line.seq for line in lines] == [1, 2, 3, 4, 5]


def test_one_run_cannot_fill_the_database(db):
    """A run over a hundred channels with a filter on each would otherwise
    write tens of thousands of lines."""
    run_pk = a_run(db, lines=[f"line {i}" for i in range(runlog.MOST_LINES + 50)])

    with db.session_scope() as session:
        lines = runlog.lines_for(session, run_pk)
    assert len(lines) == runlog.MOST_LINES, "the cap is the whole cost of a run"
    assert "were not kept" in lines[-1].message
    assert lines[-1].level == "warn"


def test_a_quiet_pen_writes_nothing(db):
    """So a path with no run behind it needs no "if the log exists" at every
    line."""
    pen = runlog.Quiet()
    pen.write("this goes nowhere")
    pen.bad("so does this")

    with db.session_scope() as session:
        assert session.scalars(select(RunEvent)).all() == []


def test_old_runs_lose_their_detail_but_keep_their_counts(db):
    """A log nobody trims is a log that eventually is the database."""
    for index in range(runlog.RUNS_WITH_DETAIL + 6):
        a_run(db, lines=[f"run {index}"])

    with db.session_scope() as session:
        dropped = runlog.prune(session)
        kept = {run_pk for run_pk in runlog.counted(session)}
        runs = session.scalars(select(SyncRun)).all()

    assert dropped == 6
    assert len(kept) == runlog.RUNS_WITH_DETAIL
    # The runs themselves stay: one row each, and the record of what this
    # install has done.
    assert len(runs) == runlog.RUNS_WITH_DETAIL + 6


# -- reading it ------------------------------------------------------------


def test_the_log_opens_from_the_canvas(client):
    """It is read while looking at the canvas that caused it, so walking away
    to a page of its own was the wrong way round."""
    canvas = client.get("/channels").text

    assert "data-graph-log-open" in canvas   # the button on the overlay
    assert "data-graph-log" in canvas        # and the box it opens
    # And it is no longer a place of its own.
    assert 'href="/log"' not in client.get("/").text
    assert client.get("/log").status_code == 404


def test_a_run_says_how_it_was_started(client, db):
    a_run(db, trigger="backfill", lines=["read 25 from the feed"])

    body = client.get("/partials/log").text

    assert "Backfill" in body
    assert "read 25 from the feed" in body


def test_the_log_can_be_narrowed_to_what_a_person_started(client, db):
    a_run(db, trigger="scheduled", lines=["the clock did this"])
    a_run(db, trigger="pulse", lines=["a finger did this"])

    by_hand = client.get("/partials/log?show=hand").text
    assert "a finger did this" in by_hand
    assert "the clock did this" not in by_hand

    by_clock = client.get("/partials/log?show=clock").text
    assert "the clock did this" in by_clock
    assert "a finger did this" not in by_clock


def test_the_log_can_be_narrowed_to_what_went_wrong(client, db):
    a_run(db, trigger="pulse", ok=True, lines=["this one was fine"])
    a_run(db, trigger="pulse", ok=False, lines=["this one was not"])

    body = client.get("/partials/log?show=trouble").text

    assert "this one was not" in body
    assert "this one was fine" not in body


def test_a_run_still_going_is_not_counted_as_trouble(client, db):
    """It has not failed yet; it has not finished."""
    a_run(db, trigger="pulse", ok=False, finished=False, lines=["still at it"])

    assert "still at it" not in client.get("/partials/log?show=trouble").text
    assert "still going" in client.get("/partials/log").text


def test_a_nonsense_filter_falls_back_to_everything(client, db):
    a_run(db, trigger="pulse", lines=["something happened"])

    assert "something happened" in client.get("/partials/log?show=nonsense").text


def test_a_run_whose_detail_was_pruned_says_so(client, db):
    a_run(db, trigger="pulse")  # no lines at all

    body = client.get("/partials/log").text

    assert "No detail kept for this one" in body


def test_with_nothing_run_it_says_where_to_start(client):
    body = client.get("/partials/log").text

    assert "Nothing has run yet" in body
    assert "Run now" in body


# -- what a real run leaves behind -----------------------------------------


def test_a_run_writes_down_what_it_did_to_each_source(world, db):
    """The point of the whole thing: not "3 added" but which source brought
    what, and which of them went quiet and why."""
    from dealgo.services import sync as sync_service

    sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        run = session.scalars(select(SyncRun).order_by(SyncRun.id.desc())).first()
        lines = runlog.lines_for(session, run.id)

    assert run.trigger == "manual" and run.by_hand is True
    said = [line.message for line in lines]
    assert said[0].startswith("By hand"), said[0]
    assert any("read " in line and "from the feed" in line for line in said), said
    assert said[-1].startswith("Finished:"), said[-1]
    # And every line is filed under the part of the run it happened in —
    # reading feeds, then deciding, then filing.
    assert {line.stage for line in lines} >= {"polling", "filling", "done"}
    # In that order: a log whose stages interleave is a log nobody can skim.
    order = ["starting", "polling", "sorting", "filling", "done"]
    seen = [line.stage for line in lines]
    assert seen == sorted(seen, key=order.index)


def test_a_source_that_could_not_be_read_says_so_in_the_log(world, db, monkeypatch):
    """A run that polled nothing and a run that could not get in look the
    same in the counts and different in the log, which is the point."""
    import httpx

    from dealgo.services import sync as sync_service

    def refused(_channel, _http):
        request = httpx.Request("GET", "https://example.test/feed")
        raise httpx.HTTPStatusError(
            "429", request=request, response=httpx.Response(429, request=request)
        )

    monkeypatch.setattr(sync_service, "_poll", refused)
    sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        run = session.scalars(select(SyncRun).order_by(SyncRun.id.desc())).first()
        lines = runlog.lines_for(session, run.id)

    trouble = [line for line in lines if line.level == "bad"]
    assert trouble, [line.message for line in lines]
    assert "asked too often" in trouble[0].message
    assert trouble[0].about  # and which source it was about


def test_a_run_prunes_the_detail_of_older_ones(world, db):
    """Housekeeping happens as part of a run, so there is no separate thing
    to remember to schedule."""
    from dealgo.services import sync as sync_service

    for _ in range(runlog.RUNS_WITH_DETAIL + 3):
        a_run(db, lines=["old noise"])

    sync_service.run_sync("manual", force=True)

    with db.session_scope() as session:
        assert len(runlog.counted(session)) <= runlog.RUNS_WITH_DETAIL


def test_a_trial_is_logged_as_a_run_that_wrote_nothing(canvas, db):
    """"I pressed Test and it said nothing useful" is answered by the same
    log that answers it for a real run."""
    from tests.test_graph import boxes, only, wire_trigger

    drawn = canvas.get("/api/graph").json()
    source, feed = only(drawn, "source"), only(drawn, "feed")
    canvas.post("/graph/connect", data={"source": source["id"], "target": feed["id"]})
    trigger = wire_trigger(canvas)

    canvas.get(f"/graph/nodes/{trigger}/test")

    with db.session_scope() as session:
        run = session.scalars(select(SyncRun).order_by(SyncRun.id.desc())).first()
        lines = runlog.lines_for(session, run.id)

    assert run.trigger == "test"
    assert run.by_hand is True
    assert run.wrote_nothing is True
    assert "nothing was written" in lines[0].message

    # And it says so on the page, so nobody reads it as a real run.
    assert "wrote nothing" in canvas.get("/partials/log").text
