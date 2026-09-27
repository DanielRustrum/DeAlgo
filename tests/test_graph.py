"""The Configuration canvas: what is wired to what, and what gets through.

The graph is the truth about routing. These cover the part a list of targets
could never express — one channel reaching two feeds down paths that filter
differently — and the rules that keep the canvas honest.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import shutil
import subprocess
import time

import pytest
from sqlalchemy import select

from dealgo.models import Channel, GraphEdge, GraphNode, Playlist
from fakes import unwire, wire
from dealgo.services import graph


def build(db, channels=("UCone",), feeds=("PLone",)):
    with db.session_scope() as session:
        for channel_id in channels:
            session.add(Channel(channel_id=channel_id, title=channel_id))
        for playlist_id in feeds:
            session.add(Playlist(playlist_id=playlist_id, title=playlist_id))
    return db


def node_for(session, kind, name):
    graph.load(session)  # the canvas draws itself the first time it is asked for
    for node in graph.nodes(session):
        if node.kind == kind and node.title == name:
            return node
    raise AssertionError(f"no {kind} called {name}")


def narrow(session, box, kind, value=None, **more):
    """Slot a condition under a box, the way dropping one out of the palette
    does. A filter carries no rule of its own: what it narrows by is the
    pieces under it, one per condition."""
    piece = graph.add_piece(session, kind=kind, host=box, **more)
    spec = graph.condition(kind)
    if spec is not None and value is not None:
        setattr(piece, spec.column, value)
    session.flush()
    return piece


# -- laying one out --------------------------------------------------------


def test_an_existing_setup_becomes_a_graph(db):
    """Nobody should have to build theirs again."""
    build(db, channels=("UCone", "UCtwo"), feeds=("PLone",))
    with db.session_scope() as session:
        channel = session.scalar(select(Channel).where(Channel.channel_id == "UCone"))
        playlist = session.scalar(select(Playlist))
        channel.playlists.append(playlist)

    with db.session_scope() as session:
        nodes, _ = graph.load(session)

    kinds = sorted(node.kind for node in nodes)
    assert kinds == ["feed", "source", "source"]
    # And the link it already had is a wire on the canvas.
    with db.session_scope() as session:
        assert len(graph.wires(session)) == 1


def test_boxes_are_not_stacked_on_each_other(db):
    build(db, channels=("UCone", "UCtwo"), feeds=("PLone", "PLtwo"))
    with db.session_scope() as session:
        nodes, _ = graph.load(session)

    places = [(node.x, node.y) for node in nodes]
    assert len(set(places)) == len(places)
    # Sources on the left of feeds, so the flow reads left to right.
    sources = [n.x for n in nodes if n.kind == "source"]
    feeds = [n.x for n in nodes if n.kind == "feed"]
    assert max(sources) < min(feeds)


def test_a_channel_added_later_gets_a_box(db):
    build(db)
    with db.session_scope() as session:
        graph.load(session)
    with db.session_scope() as session:
        session.add(Channel(channel_id="UClater", title="Later"))
    with db.session_scope() as session:
        nodes, _ = graph.load(session)

    assert "Later" in [node.title for node in nodes]
    # Unwired: appearing already connected would be a guess.
    with db.session_scope() as session:
        assert graph.wires(session) == []


def test_where_a_box_was_put_is_remembered(db):
    build(db)
    with db.session_scope() as session:
        node = graph.load(session)[0][0]
        graph.move(session, node.id, 321, 654)
        node_id = node.id

    with db.session_scope() as session:
        moved = session.get(GraphNode, node_id)
        assert (moved.x, moved.y) == (321, 654)


# -- what may be wired to what --------------------------------------------


def test_a_source_to_feed_wire_belongs_to_the_box_it_came_from(db):
    """It used to be stored against the channel, which meant two boxes for one
    channel could not be told apart. It is an edge like every other wire now,
    and the channel's own pairing is worked out from it."""
    build(db)
    with db.session_scope() as session:
        graph.load(session)
        source = node_for(session, "source", "UCone")
        feed = node_for(session, "feed", "PLone")

        edge = graph.connect(session, source, feed)

        assert edge is not None
        assert (edge.source_pk, edge.target_pk) == (source.id, feed.id)
        # And the pairing the rest of the app reads follows from it.
        assert source.channel.playlists == [feed.playlist]


def test_a_second_box_for_one_source_is_wired_on_its_own(db):
    """The whole point of being allowed a second one. Wiring either used to
    draw a wire from both, and unwiring either unwired both."""
    build(db)
    with db.session_scope() as session:
        graph.load(session)
        first = node_for(session, "source", "UCone")
        feed = node_for(session, "feed", "PLone")
        second = graph.add_source(session, channel=first.channel, source_kind="youtube")

        graph.connect(session, first, feed)

        drawn = [(w["from"], w["to"]) for w in graph.wires(session)]
        assert (first.id, feed.id) in drawn
        assert (second.id, feed.id) not in drawn

        # And the second can be wired to the same feed without disturbing it.
        graph.connect(session, second, feed)
        drawn = [(w["from"], w["to"]) for w in graph.wires(session)]
        assert (first.id, feed.id) in drawn
        assert (second.id, feed.id) in drawn


def test_unwiring_one_box_leaves_the_other_wired(db):
    build(db)
    with db.session_scope() as session:
        graph.load(session)
        first = node_for(session, "source", "UCone")
        feed = node_for(session, "feed", "PLone")
        second = graph.add_source(session, channel=first.channel, source_kind="youtube")
        graph.connect(session, first, feed)
        going = graph.connect(session, second, feed)

        assert going is not None
        graph.disconnect(session, going.id)

        drawn = [(w["from"], w["to"]) for w in graph.wires(session)]
        assert drawn == [(first.id, feed.id)]
        # Still feeding it, because one box still says so.
        assert first.channel.playlists == [feed.playlist]


def test_unwiring_the_last_box_stops_the_channel_feeding_it(db):
    build(db)
    with db.session_scope() as session:
        graph.load(session)
        source = node_for(session, "source", "UCone")
        feed = node_for(session, "feed", "PLone")
        edge = graph.connect(session, source, feed)

        assert edge is not None
        graph.disconnect(session, edge.id)

        assert source.channel.playlists == []


def test_filters_sit_between_and_are_edges(db):
    build(db)
    with db.session_scope() as session:
        graph.load(session)
        source = node_for(session, "source", "UCone")
        feed = node_for(session, "feed", "PLone")
        middle = graph.add_filter(session, label="No Shorts")

        assert graph.connect(session, source, middle) is not None
        assert graph.connect(session, middle, feed) is not None
        assert len(list(session.scalars(select(GraphEdge)))) == 2


@pytest.mark.parametrize("first,second", [("feed", "source"), ("feed", "filter")])
def test_wires_cannot_run_backwards(db, first, second):
    build(db)
    with db.session_scope() as session:
        graph.load(session)
        a = node_for(session, first, "PLone")
        b = node_for(session, second, "UCone") if second == "source" else graph.add_filter(session)
        with pytest.raises(graph.GraphError):
            graph.connect(session, a, b)


def test_a_box_cannot_feed_itself(db):
    build(db)
    with db.session_scope() as session:
        graph.load(session)
        middle = graph.add_filter(session)
        with pytest.raises(graph.GraphError):
            graph.connect(session, middle, middle)


def test_a_loop_is_refused(db):
    """Nothing would ever come out of one."""
    build(db)
    with db.session_scope() as session:
        graph.load(session)
        first = graph.add_filter(session, label="A")
        second = graph.add_filter(session, label="B")
        graph.connect(session, first, second)

        with pytest.raises(graph.GraphError) as raised:
            graph.connect(session, second, first)
        assert "loop" in str(raised.value)


def test_removing_a_channels_box_removes_the_channel(db):
    """The canvas is the whole configuration, so this is the only place left
    to remove one from — a box that stayed behind would be a channel nobody
    could reach."""
    build(db)
    with db.session_scope() as session:
        graph.load(session)
        assert graph.remove(session, node_for(session, "source", "UCone").id) is True
        assert session.scalars(select(Channel)).all() == []

        middle = graph.add_filter(session)
        assert graph.remove(session, middle.id) is True


def test_cron_counts_weekdays_the_way_cron_does(db):
    """APScheduler counts weekdays from Monday and cron counts them from
    Sunday. Anybody who has written a crontab means the second one."""
    from_sunday = dt.datetime(2026, 5, 1, 0, 0, tzinfo=dt.timezone.utc)

    def first_firing(expression):
        return graph.cron_trigger(expression).get_next_fire_time(None, from_sunday).strftime("%A")

    assert first_firing("0 9 * * 1") == "Monday"
    assert first_firing("0 9 * * 0") == "Sunday"
    assert first_firing("0 9 * * 7") == "Sunday"  # cron allows both
    assert first_firing("0 9 * * MON") == "Monday"
    assert first_firing("0 9 * * 1-5") == "Friday"  # the 1st is a Friday
    # A step counts from Sunday too: 0, 2, 4, 6 is Sun, Tue, Thu, Sat.
    assert first_firing("0 9 * * */2") == "Saturday"


def test_a_cron_expression_that_makes_no_sense_is_refused(db):
    for bad in ("", "0 9 * *", "0 9 * * funday", "0 9 * * 9", "0 9 * * */x"):
        with pytest.raises(graph.GraphError):
            graph.check_cron(bad)


# -- routing ---------------------------------------------------------------
#
# The thing a list of targets cannot express: one channel, two feeds, two sets
# of rules.


def test_a_direct_path_uses_the_channels_own_filters(db):
    build(db)
    with db.session_scope() as session:
        graph.load(session)
        source = node_for(session, "source", "UCone")
        source.channel.skip_shorts = True
        graph.connect(session, source, node_for(session, "feed", "PLone"))

    with db.session_scope() as session:
        paths = graph.routes(session)
        assert len(paths) == 1
        assert paths[0].effective()["skip_shorts"] is True
        assert paths[0].filters == []


def test_a_condition_overrides_only_what_it_sets(db):
    """The rest stays whatever the channel said — which is what makes a
    condition an override rather than a second set of settings to keep in
    step."""
    build(db)
    with db.session_scope() as session:
        graph.load(session)
        source = node_for(session, "source", "UCone")
        source.channel.min_duration_sec = 60
        source.channel.title_exclude = "trailer"

        middle = graph.add_filter(session, label="Long ones")
        narrow(session, middle, "longer-than", 1200)
        graph.connect(session, source, middle)
        graph.connect(session, middle, node_for(session, "feed", "PLone"))

    with db.session_scope() as session:
        rules = graph.routes(session)[0].effective()
        assert rules["min_duration_sec"] == 1200      # the piece's word
        assert rules["title_exclude"] == "trailer"    # the channel's, untouched


def test_one_channel_can_reach_two_feeds_by_different_rules(db):
    build(db, feeds=("PLall", "PLlong"))
    with db.session_scope() as session:
        graph.load(session)
        source = node_for(session, "source", "UCone")
        graph.connect(session, source, node_for(session, "feed", "PLall"))

        only_long = graph.add_filter(session, label="Long ones")
        narrow(session, only_long, "longer-than", 1200)
        graph.connect(session, source, only_long)
        graph.connect(session, only_long, node_for(session, "feed", "PLlong"))

    with db.session_scope() as session:
        by_feed = {path.playlist.playlist_id: path.effective() for path in graph.routes(session)}

    assert by_feed["PLall"]["min_duration_sec"] is None
    assert by_feed["PLlong"]["min_duration_sec"] == 1200


def test_filters_in_a_row_are_applied_in_order(db):
    """Nearest the feed has the last word."""
    build(db)
    with db.session_scope() as session:
        graph.load(session)
        source = node_for(session, "source", "UCone")
        first = graph.add_filter(session, label="First")
        narrow(session, first, "at-most", 5)
        second = graph.add_filter(session, label="Second")
        narrow(session, second, "at-most", 2)
        graph.connect(session, source, first)
        graph.connect(session, first, second)
        graph.connect(session, second, node_for(session, "feed", "PLone"))

    with db.session_scope() as session:
        assert graph.routes(session)[0].effective()["max_per_run"] == 2


def test_a_filter_wired_to_nothing_routes_nothing(db):
    build(db)
    with db.session_scope() as session:
        graph.load(session)
        middle = graph.add_filter(session)
        graph.connect(session, node_for(session, "source", "UCone"), middle)

    with db.session_scope() as session:
        assert graph.routes(session) == []


# -- through a real sync ---------------------------------------------------


def test_a_filter_node_changes_what_reaches_one_feed(world, db):
    """The whole point, end to end: the same upload lands in one feed and is
    turned away from the other, because of a box on the wire."""
    from dealgo.models import Placement, Video
    from dealgo.services import sync as sync_service
    from dealgo.plugins.publisher import VideoDetails
    from fakes import entry

    with db.session_scope() as session:
        db.get_settings(session).initial_backfill = 10
        # A second feed, reached through a filter that wants long videos only.
        long_only = Playlist(playlist_id="PLlong", title="Long ones")
        session.add(long_only)
        session.flush()

        graph.load(session)
        source = graph.nodes(session)[0]
        assert source.kind == "source"
        gate = graph.add_filter(session, label="20 minutes or more")
        narrow(session, gate, "longer-than", 1200)
        graph.connect(session, source, gate)
        feed_node = next(n for n in graph.nodes(session) if n.playlist_pk == long_only.id)
        graph.connect(session, gate, feed_node)

    world["entries"] = [entry("short1", 1), entry("long1", 2)]
    world["client"].details = {
        "short1": VideoDetails("short1", "A short one", 300, "none", "public"),
        "long1": VideoDetails("long1", "A long one", 2400, "none", "public"),
    }

    sync_service.run_sync()

    with db.session_scope() as session:
        landed: dict[str, set[str]] = {}
        for placement in session.scalars(select(Placement)):
            video = session.get(Video, placement.video_pk)
            playlist = session.get(Playlist, placement.playlist_pk)
            landed.setdefault(playlist.title, set()).add(video.video_id)

    # Everything reaches the plain feed; only the long one gets past the gate.
    assert landed["My Feed"] == {"short1", "long1"}
    assert landed["Long ones"] == {"long1"}


# -- triggers --------------------------------------------------------------
#
# A trigger box says when a channel is polled. The rule that matters most is
# the one about absence: a channel with no trigger wired keeps following the
# account's sync settings, because every setup that existed before triggers
# did has no trigger wired and must not quietly stop syncing.


def wire(session, source, target):
    graph.connect(session, source, target)


def test_a_trigger_sets_something_off_and_nothing_feeds_it(db):
    """Into a channel it says when to poll; into a Withdraw box it says when
    to pull. It carries no content either way, so nothing feeds it — and a
    feed is no longer one of the things it wires to."""
    build(db)
    with db.session_scope() as session:
        trigger = graph.add_trigger(session, trigger_kind="schedule")
        feed = node_for(session, "feed", "PLone")
        source = node_for(session, "source", "UCone")

        with pytest.raises(graph.GraphError):
            graph.connect(session, source, trigger)
        with pytest.raises(graph.GraphError):
            graph.connect(session, trigger, feed)
        assert graph.connect(session, trigger, source) is not None


def test_a_channel_with_no_trigger_keeps_the_accounts_own_settings(db):
    """The upgrade case: nothing wired means nothing changes."""
    build(db)
    with db.session_scope() as session:
        assert graph.polling_plan(session) == {}


def test_a_pulse_polls_its_channel_on_a_gap(db):
    build(db)
    with db.session_scope() as session:
        source = node_for(session, "source", "UCone")
        wire(session, graph.add_trigger(session, trigger_kind="pulse", every_minutes=15), source)

        plan = graph.polling_plan(session)
        assert [(w.kind, w.every_minutes) for w in plan[source.channel_pk]] == [("pulse", 15)]


def test_a_pulse_waits_out_its_gap_and_then_goes(db):
    when = graph.When(kind="pulse", every_minutes=30)
    now = dt.datetime(2026, 5, 1, 12, 0)

    assert when.due(None, now) is True  # never polled
    assert when.due(now - dt.timedelta(minutes=10), now) is False
    assert when.due(now - dt.timedelta(minutes=31), now) is True


def test_a_schedule_comes_round_when_its_cron_says(db):
    """Due once a firing time has passed, and not again until the next."""
    when = graph.When(kind="schedule", cron="0 9 * * *")  # 09:00 UTC daily
    morning = dt.datetime(2026, 5, 1, 9, 30)

    # Polled at 08:00, before today's 09:00 came round: due.
    assert when.due(dt.datetime(2026, 5, 1, 8, 0), morning) is True
    # Polled at 09:10, after it: not due again today.
    assert when.due(dt.datetime(2026, 5, 1, 9, 10), morning) is False


def test_a_cron_that_skips_days_is_honoured(db):
    """The whole reason for cron: "Mondays at nine" is not a gap in minutes."""
    when = graph.When(kind="schedule", cron="0 9 * * 1")  # Mondays
    monday = dt.datetime(2026, 5, 4, 9, 30)  # a Monday
    friday = dt.datetime(2026, 5, 8, 9, 30)

    assert when.due(dt.datetime(2026, 5, 4, 8, 0), monday) is True
    # Polled on Monday after it fired; Friday is not a Monday.
    assert when.due(dt.datetime(2026, 5, 4, 10, 0), friday) is False


def test_an_unreadable_cron_expression_never_stops_a_sync(db):
    """A saved expression that no longer parses is a bug to fix, not a reason
    to bring polling down."""
    when = graph.When(kind="schedule", cron="not a cron")
    assert when.due(dt.datetime(2026, 5, 1, 8, 0), dt.datetime(2026, 5, 1, 9, 30)) is False


def test_a_cron_expression_is_checked_before_it_is_kept(db):
    assert graph.check_cron("  0   9 * * *  ") == "0 9 * * *"
    with pytest.raises(graph.GraphError):
        graph.check_cron("0 99 * * *")
    with pytest.raises(graph.GraphError):
        graph.check_cron("")


def test_two_triggers_are_two_reasons_to_poll(db):
    """Any one of them saying yes is enough; they are not a negotiation."""
    build(db)
    with db.session_scope() as session:
        source = node_for(session, "source", "UCone")
        wire(session, graph.add_trigger(session, trigger_kind="pulse", every_minutes=600), source)
        wire(session, graph.add_trigger(session, trigger_kind="schedule", cron="0 9 * * *"), source)

        wired = graph.polling_plan(session)[source.channel_pk]
        assert sorted(w.kind for w in wired) == ["pulse", "schedule"]

        # The pulse's ten hours have not elapsed, but the schedule has come round.
        now = dt.datetime(2026, 5, 1, 9, 30)
        assert any(w.due(dt.datetime(2026, 5, 1, 8, 0), now) for w in wired)


def test_a_pulse_knows_which_channels_it_polls(db):
    build(db, channels=("UCone", "UCtwo"))
    with db.session_scope() as session:
        trigger = graph.add_trigger(session, trigger_kind="pulse")
        wire(session, trigger, node_for(session, "source", "UCone"))
        wanted = node_for(session, "source", "UCone").channel_pk

        assert graph.pulse_targets(session, trigger.id) == [wanted]


def test_a_trigger_goes_left_of_the_channels(db):
    build(db)
    with db.session_scope() as session:
        graph.load(session)
        for node in graph.nodes(session):
            if node.kind == "source":
                node.x = 600
        session.flush()

        trigger = graph.add_trigger(session, trigger_kind="schedule")
        assert trigger.x == graph.TRIGGER_COLUMN
        # Nothing moved: there was already room for it.
        assert [n.x for n in graph.nodes(session) if n.kind == "source"] == [600]


def test_the_canvas_slides_right_when_there_is_no_room_for_a_trigger(db):
    """A graph laid out before triggers existed has its channels hard against
    the left edge. Dropping a box on top of them is not an option, so the
    drawing moves instead — keeping every relative position."""
    build(db, channels=("UCone",), feeds=("PLone",))
    with db.session_scope() as session:
        graph.load(session)
        for node in graph.nodes(session):
            node.x = 50 if node.kind == "source" else 780
        session.flush()

        trigger = graph.add_trigger(session, trigger_kind="schedule")
        moved = {node.kind: node.x for node in graph.nodes(session) if node.kind != "trigger"}

        assert trigger.x == graph.TRIGGER_COLUMN
        # Everything shifted by the same amount, so the gaps are unchanged.
        assert moved["source"] - 50 == moved["feed"] - 780
        assert moved["source"] >= trigger.x + graph.TRIGGER_GAP


def test_only_the_first_trigger_moves_anything(db):
    build(db)
    with db.session_scope() as session:
        graph.load(session)
        graph.add_trigger(session, trigger_kind="schedule")
        settled = {node.id: node.x for node in graph.nodes(session)}

        second = graph.add_trigger(session, trigger_kind="pulse")
        assert all(node.x == settled[node.id] for node in graph.nodes(session)
                   if node.id in settled)
        # Stacked under the first rather than on top of it.
        assert second.y > 40


def test_a_trigger_can_be_taken_off_the_canvas(db):
    build(db)
    with db.session_scope() as session:
        trigger = graph.add_trigger(session, trigger_kind="pulse")
        assert graph.remove(session, trigger.id) is True


def test_a_trigger_is_a_pulse_or_a_schedule_and_nothing_else(db):
    build(db)
    with db.session_scope() as session:
        with pytest.raises(graph.GraphError):
            graph.add_trigger(session, trigger_kind="whenever")


def test_a_trigger_does_not_become_part_of_a_route(db):
    """It says when a channel runs, not where anything goes."""
    build(db)
    with db.session_scope() as session:
        source = node_for(session, "source", "UCone")
        feed = node_for(session, "feed", "PLone")
        graph.connect(session, source, feed)
        wire(session, graph.add_trigger(session, trigger_kind="schedule"), source)

        paths = graph.routes(session)
        assert len(paths) == 1
        assert paths[0].filters == []


# -- the canvas over HTTP --------------------------------------------------
#
# The browser only ever asks for the graph and posts one change at a time, and
# every answer is the whole graph again. These cover that contract: what the
# canvas draws from, and what it is refused.


@pytest.fixture
def canvas(db, monkeypatch):
    """The app, over a database holding one channel and one feed."""
    from fastapi.testclient import TestClient

    from dealgo import scheduler
    from dealgo.models import Video
    from dealgo.web import app as web_app

    monkeypatch.setattr(scheduler, "start", lambda: None)
    monkeypatch.setattr(scheduler, "shutdown", lambda: None)
    monkeypatch.setattr(scheduler, "next_run_time", lambda: None)
    monkeypatch.setattr(web_app, "init_db", lambda: None)

    with db.session_scope() as session:
        channel = Channel(channel_id="UCone", title="One Channel")
        playlist = Playlist(playlist_id="PLone", title="One Feed")
        session.add_all([channel, playlist])
        session.flush()
        session.add(
            Video(video_id="v1", channel_pk=channel.id, title="A clip", duration_sec=300,
                  status="pending")
        )

    with TestClient(web_app.app) as client:
        yield client


def boxes(payload, kind):
    return [node for node in payload["nodes"] if node["kind"] == kind]


def only(payload, kind):
    found = boxes(payload, kind)
    assert len(found) == 1, f"expected one {kind}, got {len(found)}"
    return found[0]


def test_the_canvas_asks_for_the_graph_and_gets_every_box(canvas):
    payload = canvas.get("/api/graph").json()
    assert [node["title"] for node in boxes(payload, "source")] == ["One Channel"]
    assert [node["title"] for node in boxes(payload, "feed")] == ["One Feed"]
    assert payload["wires"] == []


def test_a_box_says_what_it_is_underneath_its_name(canvas):
    payload = canvas.get("/api/graph").json()
    assert only(payload, "source")["note"].startswith("takes ")
    assert only(payload, "source")["detail"] == "/channels/1"
    assert only(payload, "feed")["detail"] == "/feeds/1"


def test_wiring_a_channel_to_a_feed_answers_with_the_whole_graph(canvas):
    graph_now = canvas.get("/api/graph").json()
    answer = canvas.post(
        "/graph/connect",
        data={"source": only(graph_now, "source")["id"], "target": only(graph_now, "feed")["id"]},
    )
    assert answer.status_code == 200
    wires = answer.json()["wires"]
    assert [wire["kind"] for wire in wires] == ["edge"]


def test_a_wire_that_makes_no_sense_is_refused_with_a_reason(canvas):
    graph_now = canvas.get("/api/graph").json()
    answer = canvas.post(
        "/graph/connect",
        data={"source": only(graph_now, "feed")["id"], "target": only(graph_now, "source")["id"]},
    )
    assert answer.status_code == 400
    assert "cannot feed" in answer.json()["error"]


def test_a_filter_can_be_dropped_in_and_wired_between_the_two(canvas):
    graph_now = canvas.post("/graph/nodes", data={"kind": "filter", "title": "No shorts", "x": 420, "y": 40}).json()
    source, feed = only(graph_now, "source"), only(graph_now, "feed")
    middle = only(graph_now, "filter")
    assert middle["title"] == "No shorts"

    canvas.post("/graph/connect", data={"source": source["id"], "target": middle["id"]})
    wires = canvas.post(
        "/graph/connect", data={"source": middle["id"], "target": feed["id"]}
    ).json()["wires"]
    assert sorted(wire["kind"] for wire in wires) == ["edge", "edge"]


def test_a_condition_keeps_what_it_is_given_and_a_blank_leaves_it_alone(canvas, db):
    """A condition carries exactly one thing, so the form sends one value and
    the piece's kind decides where it lands. A blank is "leave it to the
    channel" rather than zero."""
    graph_now = canvas.post("/graph/nodes", data={"kind": "filter", "title": "Trim"}).json()
    box_id = only(graph_now, "filter")["id"]

    made = canvas.post(
        "/graph/nodes",
        data={"kind": "longer-than", "attach_to": str(box_id)},
    ).json()
    piece_id = only(made, "longer-than")["id"]

    answer = canvas.post(
        f"/graph/nodes/{piece_id}",
        data={"label": "", "value": "10", "value_unit": "minutes"},
    )
    saved = only(answer.json(), "longer-than")
    assert saved["title"] == "Longer than"
    assert saved["note"] == "longer than 10 minutes"
    assert saved["condition"]["value"] == "10"
    assert saved["condition"]["unit"] == "minutes"

    with db.session_scope() as session:
        assert session.get(GraphNode, piece_id).min_duration_sec == 600

    # The box itself says what its pieces say, so the canvas reads without
    # anything being opened.
    assert only(answer.json(), "filter")["note"] == "longer than 10 minutes"

    blanked = canvas.post(f"/graph/nodes/{piece_id}", data={"value": "  "})
    assert only(blanked.json(), "longer-than")["note"] == "open it and say what"
    with db.session_scope() as session:
        assert session.get(GraphNode, piece_id).min_duration_sec is None


def test_a_condition_only_goes_under_the_box_it_belongs_to(canvas):
    """Refused at the drop rather than discovered later by a piece that
    quietly does nothing."""
    graph_now = canvas.post("/graph/nodes", data={"kind": "filter"}).json()
    box_id = only(graph_now, "filter")["id"]
    feed_id = only(graph_now, "feed")["id"]

    refused = canvas.post(
        "/graph/nodes", data={"kind": "order", "attach_to": str(box_id)}
    )
    assert refused.status_code == 400
    assert "Sort" in refused.json()["error"]

    refused = canvas.post(
        "/graph/nodes", data={"kind": "has-words", "attach_to": str(feed_id)}
    )
    assert refused.status_code == 400
    assert "Filter" in refused.json()["error"]


def test_a_box_can_be_taken_off_the_canvas_whatever_it_stands_for(canvas, db):
    """The canvas is the whole configuration now: there is no list left to
    remove a channel from, so removing the box removes the channel."""
    from dealgo.models import Channel as ChannelModel

    graph_now = canvas.post("/graph/nodes", data={"kind": "filter", "title": "Trim"}).json()

    left = canvas.post(f"/graph/nodes/{only(graph_now, 'filter')['id']}/delete").json()
    assert boxes(left, "filter") == []

    gone = canvas.post(f"/graph/nodes/{only(left, 'source')['id']}/delete").json()
    assert boxes(gone, "source") == []
    with db.session_scope() as session:
        assert session.scalars(select(ChannelModel)).all() == []


def test_where_a_box_was_dragged_to_is_remembered(canvas):
    node_id = only(canvas.get("/api/graph").json(), "source")["id"]
    assert canvas.post(f"/graph/nodes/{node_id}/move", data={"x": 33, "y": 77}).json() == {"moved": True}

    moved = only(canvas.get("/api/graph").json(), "source")
    assert (moved["x"], moved["y"]) == (33, 77)


def test_every_wire_comes_out_the_same_way(canvas):
    """There used to be two kinds and the route had to tell them apart. One
    kind now, so taking any of them out is the same act."""
    graph_now = canvas.post("/graph/nodes", data={"kind": "filter", "title": "Trim"}).json()
    source, feed, middle = only(graph_now, "source"), only(graph_now, "feed"), only(graph_now, "filter")

    canvas.post("/graph/connect", data={"source": source["id"], "target": feed["id"]})
    canvas.post("/graph/connect", data={"source": source["id"], "target": middle["id"]})
    wires = canvas.get("/api/graph").json()["wires"]

    assert {wire["kind"] for wire in wires} == {"edge"}
    left = wires
    for wire in wires:
        left = canvas.post("/graph/disconnect", data={"wire": wire["id"]}).json()["wires"]
    assert left == []


def test_the_canvas_is_the_whole_configuration_page(canvas):
    body = canvas.get("/channels").text
    assert "data-graph" in body
    assert "/static/graph.js" in body
    # The lists are gone: what was in them is on the canvas.
    assert 'id="channel-list"' not in body
    assert 'id="playlist-targets"' not in body


# -- making boxes ----------------------------------------------------------
#
# The canvas is the whole configuration, so everything that used to be a form
# in a list below it is done by dropping a box out of the palette.


def test_a_channel_box_arrives_empty_and_is_told_what_it_is(canvas, db):
    """You drop a channel box, then type the @handle into it. Until then it
    stands for nothing, which is a state the rest of the app must tolerate."""
    from dealgo.models import Channel as ChannelModel

    payload = canvas.post("/graph/nodes", data={"kind": "source", "source_kind": "youtube", "x": 40, "y": 60}).json()
    empty = [node for node in boxes(payload, "source") if node["detail"] is None]
    assert len(empty) == 1
    # Named after the kind it was dragged out as. There is no one Channel
    # box any more: you pick the kind by picking the box, and the box says
    # which it is while it waits to be filled in.
    assert empty[0]["title"] == "New YouTube channel"
    assert empty[0]["asks"] == {
        "kind": "youtube",
        "label": "YouTube channel",
        # The short one, for the word above the title on the box.
        "source": "YouTube",
        "example": "@handle, a channel URL, or a UC… id",
        "known": True,
    }
    assert "open it" in empty[0]["note"]
    assert (empty[0]["x"], empty[0]["y"]) == (40, 60)

    # It routes nothing and breaks nothing while it waits.
    assert canvas.get("/api/graph").status_code == 200
    with db.session_scope() as session:
        assert len(session.scalars(select(ChannelModel)).all()) == 1  # only the fixture's


def test_a_channel_that_youtube_does_not_have_is_refused_with_a_reason(canvas):
    payload = canvas.post(
        "/graph/nodes", data={"kind": "source", "source_kind": "youtube"}
    ).json()
    empty = [node for node in boxes(payload, "source") if node["detail"] is None][0]

    answer = canvas.post(f"/graph/nodes/{empty['id']}", data={"handle": "@nobody"})
    assert answer.status_code == 400
    assert answer.json()["error"]  # whatever YouTube said, said in words


def test_a_source_box_takes_somewhere_that_is_not_youtube(canvas, db, monkeypatch):
    """The whole point of the expansion: the box that used to mean "a YouTube
    channel" now means "somewhere that publishes", and says which."""
    from dealgo.models import Channel as ChannelModel
    from dealgo.sources import syndication

    monkeypatch.setattr(
        syndication,
        "fetch",
        lambda _url, _http: syndication.Feed(title="r/python", items=[]),
    )
    payload = canvas.post("/graph/nodes", data={"kind": "source", "source_kind": "reddit"}).json()
    empty = [node for node in boxes(payload, "source") if node["detail"] is None][0]

    answer = canvas.post(f"/graph/nodes/{empty['id']}", data={"handle": "r/python"})
    assert answer.status_code == 200

    filled = [node for node in boxes(answer.json(), "source") if node["id"] == empty["id"]][0]
    assert filled["detail"] is not None  # it stands for something now
    assert filled["note"] == "everything from Reddit"
    assert filled["channel"]["source"] == "Reddit"
    assert filled["channel"]["youtube"] is False

    with db.session_scope() as session:
        made = session.scalar(select(ChannelModel).where(ChannelModel.channel_id == "r/python"))
        assert made.source_kind == "reddit"
        assert made.source_url == "https://www.reddit.com/r/python/.rss"


def add_reddit(canvas, db, monkeypatch, *, items=()):
    """A subscribed Reddit source with a box on the canvas."""
    from dealgo.models import Channel as ChannelModel, Video as VideoModel
    from dealgo.services import sync as sync_service
    from dealgo.sources import syndication

    monkeypatch.setattr(
        syndication, "fetch", lambda _url, _http: syndication.Feed(title="r/python", items=[])
    )
    drawn = canvas.post("/graph/nodes", data={"kind": "source", "source_kind": "reddit"}).json()
    empty = [node for node in boxes(drawn, "source") if node["detail"] is None][0]
    canvas.post(f"/graph/nodes/{empty['id']}", data={"handle": "r/python"})

    with db.session_scope() as session:
        source = session.scalar(select(ChannelModel).where(ChannelModel.channel_id == "r/python"))
        for index, title in enumerate(items):
            session.add(VideoModel(
                video_id=f"item-{index}", channel_pk=source.id, kind="link", title=title,
                link=f"https://reddit.com/{index}", status="skipped",
                reason=sync_service.WRONG_KIND_OF_FEED,
            ))
    return empty["id"]


def test_a_source_that_is_not_youtube_cannot_be_wired_to_a_youtube_playlist(
    canvas, db, monkeypatch
):
    """Refused where the wire is drawn. It could never carry anything, and
    left to a run it says so only in sixty skip reasons nobody goes looking
    for."""
    reddit = add_reddit(canvas, db, monkeypatch)
    feed = only(canvas.get("/api/graph").json(), "feed")  # the fixture's real playlist

    answer = canvas.post("/graph/connect", data={"source": reddit, "target": feed["id"]})

    assert answer.status_code == 400
    said = answer.json()["error"]
    assert "YouTube playlist" in said
    assert "generic" in said  # and what to do instead


def test_wiring_it_to_a_feed_that_can_hold_it_brings_back_what_was_stranded(
    canvas, db, monkeypatch
):
    """Wiring it somewhere that works should fill that feed, not leave the
    backlog stranded waiting for the next new post."""
    from dealgo.models import Video as VideoModel

    reddit = add_reddit(canvas, db, monkeypatch, items=("One", "Two", "Three"))
    made = canvas.post("/graph/nodes", data={"kind": "feed", "title": "Reading"}).json()
    generic = [node for node in boxes(made, "feed") if node["title"] == "Reading"][0]

    answer = canvas.post("/graph/connect", data={"source": reddit, "target": generic["id"]})
    assert answer.status_code == 200

    with db.session_scope() as session:
        back = session.scalars(select(VideoModel).where(VideoModel.kind == "link")).all()
    assert [v.status for v in back] == ["pending"] * 3
    assert all(v.reason is None for v in back)


def test_a_youtube_source_wired_to_a_generic_feed_strands_nothing(canvas, db, monkeypatch):
    """The requeue is for items that had nowhere to go, not for everything a
    filter ever turned away."""
    from dealgo.models import Video as VideoModel

    with db.session_scope() as session:
        channel = session.scalars(select(Channel)).one()
        session.add(VideoModel(video_id="v9", channel_pk=channel.id, title="A short",
                               status="skipped", reason="Shorts are switched off"))

    made = canvas.post("/graph/nodes", data={"kind": "feed", "title": "Reading"}).json()
    generic = [node for node in boxes(made, "feed") if node["title"] == "Reading"][0]
    source = [node for node in boxes(made, "source") if node["title"] == "One Channel"][0]

    canvas.post("/graph/connect", data={"source": source["id"], "target": generic["id"]})

    with db.session_scope() as session:
        held = session.scalar(select(VideoModel).where(VideoModel.video_id == "v9"))
    assert held.status == "skipped"
    assert held.reason == "Shorts are switched off"


def test_a_source_already_watched_is_attached_however_it_was_written(canvas, db, monkeypatch):
    """A pasted URL and the r/ name that means the same thing are one source,
    so a second box for it wires to the same row rather than being refused."""
    from dealgo.models import Channel as ChannelModel
    from dealgo.sources import syndication

    monkeypatch.setattr(
        syndication,
        "fetch",
        lambda _url, _http: syndication.Feed(title="r/python", items=[]),
    )
    first = canvas.post("/graph/nodes", data={"kind": "source", "source_kind": "reddit"}).json()
    empty = [node for node in boxes(first, "source") if node["detail"] is None][0]
    canvas.post(f"/graph/nodes/{empty['id']}", data={"handle": "r/python"})

    second = canvas.post("/graph/nodes", data={"kind": "source", "source_kind": "reddit"}).json()
    other = [node for node in boxes(second, "source") if node["detail"] is None][0]
    answer = canvas.post(
        f"/graph/nodes/{other['id']}", data={"handle": "https://www.reddit.com/r/python/"}
    )
    assert answer.status_code == 200

    with db.session_scope() as session:
        rows = session.scalars(
            select(ChannelModel).where(ChannelModel.channel_id == "r/python")
        ).all()
    assert len(rows) == 1


def test_a_feed_box_makes_its_feed_at_once(canvas, db):
    """A name is all a feed inside De-Algo needs, so there is nothing to wait
    for — unlike a channel, which YouTube has to agree exists."""
    from dealgo.models import Playlist as PlaylistModel

    payload = canvas.post("/graph/nodes", data={"kind": "feed", "title": "Evening"}).json()
    made = [node for node in boxes(payload, "feed") if node["title"] == "Evening"]
    assert len(made) == 1
    assert made[0]["note"] == "generic"

    with db.session_scope() as session:
        titles = {p.title for p in session.scalars(select(PlaylistModel))}
    assert "Evening" in titles


def test_a_box_can_be_renamed_and_the_thing_behind_it_follows(canvas, db):
    """Renaming the box and renaming the feed are the same act: two names for
    one thing is how a canvas and the rest of an app drift apart."""
    from dealgo.models import Playlist as PlaylistModel

    feed = only(canvas.get("/api/graph").json(), "feed")
    renamed = canvas.post(f"/graph/nodes/{feed['id']}", data={"label": "Weeknights"}).json()

    assert only(renamed, "feed")["title"] == "Weeknights"
    with db.session_scope() as session:
        assert session.get(PlaylistModel, 1).title == "Weeknights"


def test_a_box_may_sit_anywhere_including_off_to_the_left(canvas):
    """The canvas has no edges, so a position is not clamped to a corner."""
    node_id = only(canvas.get("/api/graph").json(), "source")["id"]
    canvas.post(f"/graph/nodes/{node_id}/move", data={"x": -640, "y": -220})

    moved = only(canvas.get("/api/graph").json(), "source")
    assert (moved["x"], moved["y"]) == (-640, -220)


def test_a_channel_box_carries_what_the_channel_does(canvas, db):
    """The same things its own page says under "What it does", so the canvas
    is a place to work rather than a place to look before going elsewhere."""
    from dealgo.models import Video as VideoModel

    with db.session_scope() as session:
        channel = session.scalars(select(Channel)).one()
        channel.skip_shorts = True
        channel.min_pull_minutes = 60
        session.add(VideoModel(video_id="v9", channel_pk=channel.id, title="Placed",
                               status="added"))

    node = only(canvas.get("/api/graph").json(), "source")
    facts = node["channel"]
    assert facts["takes"] == {"videos": True, "shorts": False, "live": False, "posts": True}
    assert facts["placed"] == 1 and facts["pending"] == 1
    assert facts["checked"] is None  # never polled in this test
    # When it is next looked at belongs to the trigger, and is said once.
    assert "feeds" not in facts
    assert "interval" not in facts
    assert node["polled"]


def test_a_channels_switches_can_be_set_from_its_box(canvas, db):
    node_id = only(canvas.get("/api/graph").json(), "source")["id"]
    saved = canvas.post(
        f"/graph/nodes/{node_id}",
        data={"box_form": "1", "takes_videos": "1", "takes_posts": "1"},
    ).json()

    facts = only(saved, "source")["channel"]
    assert facts["takes"] == {"videos": True, "shorts": False, "live": False, "posts": True}


def test_a_channel_box_does_not_offer_to_set_its_own_interval(canvas, db):
    """A trigger wired into it decides when it is polled. An interval offered
    in two places is an interval that will disagree with itself."""
    from dealgo.models import Channel as ChannelModel

    with db.session_scope() as session:
        session.scalars(select(ChannelModel)).one().min_pull_minutes = 60

    node_id = only(canvas.get("/api/graph").json(), "source")["id"]
    canvas.post(
        f"/graph/nodes/{node_id}",
        data={"box_form": "1", "interval": "180", "takes_videos": "1"},
    )

    with db.session_scope() as session:
        assert session.scalars(select(ChannelModel)).one().min_pull_minutes == 60


def test_turning_a_switch_back_on_brings_back_what_it_skipped(canvas, db):
    """Through the same service the channel's own page uses. Writing the
    column directly would leave the skipped ones skipped for ever."""
    from dealgo.models import Video as VideoModel

    with db.session_scope() as session:
        channel = session.scalars(select(Channel)).one()
        channel.skip_shorts = True
        session.add(VideoModel(video_id="s1", channel_pk=channel.id, title="A short",
                               is_short=True, status="skipped", reason="Short (30s)"))

    node_id = only(canvas.get("/api/graph").json(), "source")["id"]
    canvas.post(
        f"/graph/nodes/{node_id}",
        data={"box_form": "1", "active": "1", "takes_videos": "1", "takes_shorts": "1",
              "takes_posts": "1"},
    )

    with db.session_scope() as session:
        brought_back = session.scalar(select(VideoModel).where(VideoModel.video_id == "s1"))
        assert brought_back.status == "pending"


def test_saving_a_box_without_touching_a_switch_requeues_nothing(canvas, db):
    """Each switch is only applied when the answer changed, so pressing Save
    after a rename does not drag back everything that was ever skipped."""
    from dealgo.models import Video as VideoModel

    with db.session_scope() as session:
        channel = session.scalars(select(Channel)).one()
        channel.skip_shorts = True
        session.add(VideoModel(video_id="s1", channel_pk=channel.id, title="A short",
                               is_short=True, status="skipped", reason="Short (30s)"))

    node_id = only(canvas.get("/api/graph").json(), "source")["id"]
    canvas.post(
        f"/graph/nodes/{node_id}",
        data={"box_form": "1", "label": "Renamed", "takes_videos": "1",
              "takes_posts": "1"},
    )

    with db.session_scope() as session:
        stayed = session.scalar(select(VideoModel).where(VideoModel.video_id == "s1"))
        assert stayed.status == "skipped"


def test_a_feed_box_carries_how_it_fills(canvas, db):
    """The same two things its own page calls Filling."""
    from dealgo.models import Playlist as PlaylistModel

    with db.session_scope() as session:
        playlist = session.scalars(select(PlaylistModel)).one()
        playlist.max_items = 50
        playlist.max_per_run = 3

    facts = only(canvas.get("/api/graph").json(), "feed")["feed"]
    assert facts == {
        "enabled": True, "max_items": 50, "max_per_run": 3, "generic": False,
        # Nothing on its second input, so it is always open.
        "windows": [], "open": True,
    }


def test_a_feeds_limits_can_be_set_from_its_box(canvas, db):
    from dealgo.models import Playlist as PlaylistModel

    node_id = only(canvas.get("/api/graph").json(), "feed")["id"]
    saved = canvas.post(
        f"/graph/nodes/{node_id}",
        data={"box_form": "1", "active": "1", "max_items": "80", "feed_max_per_run": "2"},
    ).json()

    assert only(saved, "feed")["feed"]["max_items"] == 80
    with db.session_scope() as session:
        playlist = session.scalars(select(PlaylistModel)).one()
        assert playlist.max_items == 80 and playlist.max_per_run == 2


def test_a_feed_can_be_stopped_from_filling(canvas, db):
    from dealgo.models import Playlist as PlaylistModel

    node_id = only(canvas.get("/api/graph").json(), "feed")["id"]
    canvas.post(f"/graph/nodes/{node_id}", data={"box_form": "1"})  # Active unticked

    with db.session_scope() as session:
        assert session.scalars(select(PlaylistModel)).one().enabled is False


def test_an_unreadable_limit_means_no_limit_not_a_limit_of_nothing(canvas, db):
    """Zero means no limit for both of these. Reading rubbish as a limit of
    zero would quietly stop the feed filling at all."""
    from dealgo.models import Playlist as PlaylistModel

    node_id = only(canvas.get("/api/graph").json(), "feed")["id"]
    canvas.post(
        f"/graph/nodes/{node_id}",
        data={"box_form": "1", "active": "1", "max_items": "lots", "feed_max_per_run": "-4"},
    )

    with db.session_scope() as session:
        playlist = session.scalars(select(PlaylistModel)).one()
        assert playlist.max_items == 0 and playlist.max_per_run == 0


def test_a_rename_cannot_stop_a_feed_filling(canvas, db):
    """The same hazard as the channel switches: an unticked box and an absent
    one arrive looking identical."""
    from dealgo.models import Playlist as PlaylistModel

    node_id = only(canvas.get("/api/graph").json(), "feed")["id"]
    canvas.post(f"/graph/nodes/{node_id}", data={"label": "Renamed"})

    with db.session_scope() as session:
        assert session.scalars(select(PlaylistModel)).one().enabled is True


def test_a_channel_box_does_not_offer_to_filter(canvas, db):
    """Narrowing by title or length is a filter box's job. Offering it here as
    well would be two places to look for one answer, and two places for them
    to disagree."""
    from dealgo.models import Channel as ChannelModel

    with db.session_scope() as session:
        session.scalars(select(ChannelModel)).one().title_include = "weekly"

    node = only(canvas.get("/api/graph").json(), "source")
    assert "rules" not in node["channel"]

    canvas.post(
        f"/graph/nodes/{node['id']}",
        data={"box_form": "1", "takes_videos": "1", "channel_title_include": "changed"},
    )
    with db.session_scope() as session:
        assert session.scalars(select(ChannelModel)).one().title_include == "weekly"


def test_a_channel_can_be_paused_from_its_box(canvas, db):
    """Pausing is the first thing to reach for when a channel is too much
    rather than the wrong kind, and its box is the only place left to do it."""
    from dealgo.models import Channel as ChannelModel

    node_id = only(canvas.get("/api/graph").json(), "source")["id"]
    canvas.post(
        f"/graph/nodes/{node_id}", data={"box_form": "1", "takes_videos": "1"}
    )  # Active unticked

    with db.session_scope() as session:
        assert session.scalars(select(ChannelModel)).one().enabled is False

    canvas.post(
        f"/graph/nodes/{node_id}",
        data={"box_form": "1", "active": "1", "takes_videos": "1"},
    )
    with db.session_scope() as session:
        assert session.scalars(select(ChannelModel)).one().enabled is True


def test_a_form_that_never_showed_a_switch_cannot_turn_it_off(canvas, db):
    """An unticked box sends nothing, so "off" and "not on this form" arrive
    looking identical. The form says which it is; without that marker a rename
    would switch off everything the channel takes."""
    from dealgo.models import Channel as ChannelModel

    with db.session_scope() as session:
        channel = session.scalars(select(ChannelModel)).one()
        channel.enabled = True
        channel.skip_shorts = False

    node_id = only(canvas.get("/api/graph").json(), "source")["id"]
    canvas.post(f"/graph/nodes/{node_id}", data={"label": "Just a rename"})

    with db.session_scope() as session:
        channel = session.scalars(select(ChannelModel)).one()
        assert channel.enabled is True
        assert channel.skip_shorts is False


# -- triggers over HTTP ----------------------------------------------------


def test_a_trigger_can_be_added_and_says_which_kind_it_is(canvas):
    payload = canvas.post("/graph/nodes", data={"kind": "pulse"}).json()
    box = only(payload, "trigger")
    assert box["trigger"]["kind"] == "pulse"
    assert box["note"] == "every 1 hour"  # sixty minutes, said the way it reads

    both = canvas.post("/graph/nodes", data={"kind": "schedule"}).json()
    assert [b["trigger"]["kind"] for b in boxes(both, "trigger")] == ["pulse", "schedule"]
    assert boxes(both, "trigger")[1]["note"] == "0 9 * * *"


def test_a_trigger_that_is_neither_is_refused(canvas):
    answer = canvas.post("/graph/nodes", data={"kind": "whenever"})
    assert answer.status_code == 400
    assert "no whenever node" in answer.json()["error"]


def test_a_pulse_keeps_the_gap_it_is_given(canvas):
    added = canvas.post("/graph/nodes", data={"kind": "pulse"}).json()
    node_id = only(added, "trigger")["id"]

    saved = canvas.post(
        f"/graph/nodes/{node_id}", data={"label": "Quarter hourly", "every_minutes": "15"}
    ).json()
    box = only(saved, "trigger")
    assert box["title"] == "Quarter hourly"
    assert box["trigger"]["every_minutes"] == 15
    assert box["note"] == "every 15 minutes"


def test_a_gap_reads_back_in_the_unit_it_needs_no_fraction_to_say(db):
    """The unit it was typed in is not stored, so the one that comes back is
    the one that says it whole: 120 is two hours, 90 is ninety minutes."""
    assert graph.split_every(120) == (2, "hours")
    assert graph.split_every(90) == (90, "minutes")
    assert graph.split_every(1440) == (1, "days")
    assert graph.split_every(10080) == (1, "weeks")
    assert graph.split_every(43200) == (1, "months")
    assert graph.split_every(1) == (1, "minutes")


def test_a_gap_is_stored_in_minutes_whatever_it_was_typed_in(db):
    assert graph.every_minutes_from(2, "hours") == 120
    assert graph.every_minutes_from(1, "weeks") == 10080
    # A unit nobody offered counts as minutes rather than as nothing.
    assert graph.every_minutes_from(5, "fortnights") == 5
    # Zero survives, because zero means something: every run there is. It is
    # not "as often as possible" — runs happen on the account's own clock.
    assert graph.every_minutes_from(0, "hours") == 0
    assert graph.every_words(0) == "run"


def test_a_gap_is_said_the_way_it_was_most_likely_meant(db):
    assert graph.every_words(60) == "1 hour"
    assert graph.every_words(120) == "2 hours"
    assert graph.every_words(90) == "90 minutes"


def test_a_pulse_takes_its_gap_in_whatever_unit_suits(canvas):
    added = canvas.post("/graph/nodes", data={"kind": "pulse"}).json()
    node_id = only(added, "trigger")["id"]

    saved = canvas.post(
        f"/graph/nodes/{node_id}",
        data={"box_form": "1", "active": "1", "every_minutes": "2", "every_unit": "days"},
    ).json()

    box = only(saved, "trigger")
    assert box["trigger"]["every_minutes"] == 2880
    assert box["trigger"]["every"]["amount"] == 2
    assert box["trigger"]["every"]["unit"] == "days"
    assert box["note"] == "every 2 days"


def test_a_pulse_with_no_unit_at_all_is_still_minutes(canvas):
    """An older form, or one that lost its dropdown, means what it always did."""
    added = canvas.post("/graph/nodes", data={"kind": "pulse"}).json()
    node_id = only(added, "trigger")["id"]

    saved = canvas.post(
        f"/graph/nodes/{node_id}",
        data={"box_form": "1", "active": "1", "every_minutes": "45"},
    ).json()
    assert only(saved, "trigger")["trigger"]["every_minutes"] == 45


def test_a_schedule_keeps_the_cron_it_is_given(canvas):
    added = canvas.post("/graph/nodes", data={"kind": "schedule"}).json()
    node_id = only(added, "trigger")["id"]

    saved = canvas.post(
        f"/graph/nodes/{node_id}", data={"label": "Weekdays", "cron": "30 7 * * 1-5"}
    ).json()
    box = only(saved, "trigger")
    assert box["title"] == "Weekdays"
    assert box["trigger"]["cron"] == "30 7 * * 1-5"
    assert box["note"] == "30 7 * * 1-5"
    # And it says when that actually comes round, because cron is easy to
    # get subtly wrong.
    assert box["trigger"]["next"] is not None


def test_a_cron_that_makes_no_sense_is_refused_with_a_reason(canvas):
    added = canvas.post("/graph/nodes", data={"kind": "schedule"}).json()
    node_id = only(added, "trigger")["id"]

    answer = canvas.post(f"/graph/nodes/{node_id}", data={"cron": "every tuesday"})
    assert answer.status_code == 400
    assert "five fields" in answer.json()["error"]


def test_a_pulse_wired_to_a_channel_says_so_on_the_channel(canvas):
    added = canvas.post("/graph/nodes", data={"kind": "pulse"}).json()
    trigger, source = only(added, "trigger"), only(added, "source")
    assert "Nothing polls this" in source["polled"]

    wired = canvas.post(
        "/graph/connect", data={"source": trigger["id"], "target": source["id"]}
    ).json()
    assert only(wired, "source")["polled"] == "Polled by a pulse every 1 hour."


def test_a_schedule_wired_to_a_channel_says_the_time(canvas):
    added = canvas.post("/graph/nodes", data={"kind": "schedule"}).json()
    trigger, source = only(added, "trigger"), only(added, "source")
    wired = canvas.post(
        "/graph/connect", data={"source": trigger["id"], "target": source["id"]}
    ).json()

    assert only(wired, "source")["polled"] == "Polled by a schedule on “0 9 * * *”."


def test_a_channel_under_two_triggers_names_them_both(canvas):
    added = canvas.post("/graph/nodes", data={"kind": "pulse"}).json()
    source = only(added, "source")
    canvas.post("/graph/connect", data={"source": only(added, "trigger")["id"],
                                        "target": source["id"]})
    more = canvas.post("/graph/nodes", data={"kind": "schedule"}).json()
    second = [b for b in boxes(more, "trigger") if b["trigger"]["kind"] == "schedule"][0]
    wired = canvas.post(
        "/graph/connect", data={"source": second["id"], "target": source["id"]}
    ).json()

    assert only(wired, "source")["polled"] == (
        "Polled by a pulse every 1 hour and a schedule on “0 9 * * *”."
    )


def test_a_reset_slotted_under_a_feed_opens_a_window_on_it(canvas):
    """When a feed may be read is a property of the feed now, slotted under
    it rather than arriving along a wire."""
    feed = only(canvas.get("/api/graph").json(), "feed")

    added = canvas.post(
        "/graph/nodes", data={"kind": "reset", "attach_to": feed["id"]}
    ).json()

    assert only(added, "feed")["feed"]["windows"] == ["another 30 minutes on “0 9 * * *”"]
    piece = boxes(added, "reset")[0]
    assert piece["piece"]["under"] == feed["id"]


def test_pressing_a_pulse_with_nothing_wired_to_it_says_so(canvas):
    added = canvas.post("/graph/nodes", data={"kind": "pulse"}).json()
    answer = canvas.post(f"/graph/nodes/{only(added, 'trigger')['id']}/fire")

    assert answer.status_code == 400
    assert "Nothing is wired" in answer.json()["error"]


def test_pressing_a_pulse_polls_what_it_is_wired_to(canvas, db, monkeypatch):
    """The polling itself runs in a thread; what is asserted here is what was
    asked for — which channels, forced, and for whose account."""
    from dealgo.web import app as web_app

    asked: dict[str, object] = {}

    class Recorder:
        def __init__(self, target, args, kwargs, daemon):
            asked["args"] = args
            asked["kwargs"] = kwargs

        def start(self):
            asked["started"] = True

    monkeypatch.setattr(web_app.threading, "Thread", Recorder)

    added = canvas.post("/graph/nodes", data={"kind": "pulse"}).json()
    trigger, source = only(added, "trigger"), only(added, "source")
    canvas.post("/graph/connect", data={"source": trigger["id"], "target": source["id"]})

    answer = canvas.post(f"/graph/nodes/{trigger['id']}/fire").json()
    assert answer["said"] == "Polling 1 channel…"
    assert asked["started"] is True
    assert asked["args"] == ("pulse",)
    assert asked["kwargs"]["force"] is True
    assert asked["kwargs"]["only"] == frozenset({1})
    # And the box remembers being pressed.
    assert only(answer, "trigger")["trigger"]["last_fired"] is not None


def test_a_trigger_can_be_taken_off_the_canvas_over_http(canvas):
    added = canvas.post("/graph/nodes", data={"kind": "pulse"}).json()
    left = canvas.post(f"/graph/nodes/{only(added, 'trigger')['id']}/delete").json()
    assert boxes(left, "trigger") == []


def test_the_palette_is_reachable_with_nothing_on_the_canvas(canvas, db):
    """A new account has an empty canvas. The palette lives inside it, so
    anything that hides an empty canvas leaves them nothing to add with."""
    from dealgo.models import Channel as ChannelModel, Playlist as PlaylistModel

    with db.session_scope() as session:
        for row in session.scalars(select(ChannelModel)):
            session.delete(row)
        for row in session.scalars(select(PlaylistModel)):
            session.delete(row)

    assert canvas.get("/api/graph").json()["nodes"] == []
    body = canvas.get("/channels").text
    assert 'data-palette="source"' in body
    # And the script is told never to hide the canvas that holds it.
    script = (
        pathlib.Path(__file__).resolve().parent.parent
        / "dealgo" / "web" / "static" / "graph.js"
    ).read_text()
    assert "canvas.hidden" not in script


def test_the_palette_offers_every_kind_of_node(canvas):
    body = canvas.get("/channels").text
    for kind in ("source", "feed", "filter", "sort", "pulse", "schedule"):
        assert f'data-palette="{kind}"' in body, f"the palette has no {kind}"


def test_the_palette_folds_away_what_is_optional(canvas):
    """A channel and a feed are what every graph is made of, so they are not
    filed under anything. The rest is folded, and folded shut: the panel
    should open as a short list rather than a long one."""
    body = canvas.get("/channels").text

    assert "<summary>Operations</summary>" in body
    assert "<summary>Triggers</summary>" in body
    # Operations, Jigsaw, Conditions, Triggers, Plugins, Layout. The plugins
    # one is there because a shipped plugin offers conditions; a plugin
    # offering none adds nothing.
    assert '<summary>Conditions</summary>' in body
    assert body.count('<details class="palette-group">') == 6
    assert "<summary>Plugins</summary>" in body
    assert "palette-group\" open" not in body

    # Channel and Feed are above the folds, not inside one.
    before = body.split('<details class="palette-group">', 1)[0]
    assert 'data-palette="source"' in before and 'data-palette="feed"' in before
    assert 'data-palette="filter"' not in before


def test_loading_a_group_is_asked_for_in_a_dialog(canvas):
    """Next to the button that adds one, because both put something on the
    canvas — and in a dialog, because a file picker sitting in a panel is a
    control nobody was looking for."""
    body = canvas.get("/channels").text
    assert "data-graph-load-open" in body
    assert '<dialog class="modal graph-load"' in body
    assert "data-graph-load-file" in body
    # And no longer loose in the palette.
    assert "palette-load" not in body


def test_adding_a_node_is_a_plus(canvas):
    """It sits over the drawing, and every pixel it takes is canvas."""
    body = canvas.get("/channels").text
    assert 'class="graph-add"' in body
    assert 'aria-label="Add a node"' in body
    assert "Add a box" not in body


# -- putting the batch in order --------------------------------------------


def test_a_sort_box_sits_on_the_path_and_says_which_way(db):
    build(db)
    with db.session_scope() as session:
        source = node_for(session, "source", "UCone")
        feed = node_for(session, "feed", "PLone")
        box = graph.add_sort(session)
        narrow(session, box, "order", sort_by="views")
        graph.connect(session, source, box)
        graph.connect(session, box, feed)

        path = graph.routes(session)[0]
        assert path.order is not None
        assert path.order.sort_by == "views"
        assert path.filters == []  # a sort narrows nothing


def test_a_sort_box_with_nothing_slotted_under_it_orders_nothing(db):
    """The same as a Filter with no conditions: a box that quietly did
    something without saying what on the canvas is a box you must open."""
    build(db)
    with db.session_scope() as session:
        source = node_for(session, "source", "UCone")
        feed = node_for(session, "feed", "PLone")
        box = graph.add_sort(session)
        graph.connect(session, source, box)
        graph.connect(session, box, feed)

        assert graph.routes(session)[0].order is None


def test_the_sort_nearest_the_feed_has_the_last_word(db):
    """As with filters: the one closest to the end is the one describing what
    actually arrives."""
    build(db)
    with db.session_scope() as session:
        source = node_for(session, "source", "UCone")
        feed = node_for(session, "feed", "PLone")
        first = graph.add_sort(session)
        narrow(session, first, "order", sort_by="published")
        second = graph.add_sort(session)
        narrow(session, second, "order", sort_by="likes")
        graph.connect(session, source, first)
        graph.connect(session, first, second)
        graph.connect(session, second, feed)

        assert graph.routes(session)[0].order.sort_by == "likes"


def test_a_switched_off_sort_stops_the_flow_like_any_other_box(db):
    build(db)
    with db.session_scope() as session:
        source = node_for(session, "source", "UCone")
        feed = node_for(session, "feed", "PLone")
        order = graph.add_sort(session)
        graph.connect(session, source, order)
        graph.connect(session, order, feed)
        order.enabled = False
        session.flush()

        assert graph.routes(session) == []


def test_a_sort_by_nothing_in_particular_is_refused(db):
    build(db)
    with db.session_scope() as session:
        with pytest.raises(graph.GraphError):
            graph.add_piece(session, kind="order", sort_by="vibes")


def test_a_sort_box_is_told_what_to_order_by_with_a_piece(canvas):
    added = canvas.post("/graph/nodes", data={"kind": "sort"}).json()
    box = only(added, "sort")
    assert box["sort"] is None
    assert box["note"] == "slot an Order under it"

    made = canvas.post(
        "/graph/nodes", data={"kind": "order", "attach_to": str(box["id"])}
    ).json()
    piece = only(made, "order")
    assert piece["sort"]["by"] == "published"
    assert piece["note"] == "Newest first"
    # And the box says what its piece says, without being opened.
    assert only(made, "sort")["note"] == "Newest first"

    saved = canvas.post(
        f"/graph/nodes/{piece['id']}",
        data={"box_form": "1", "active": "1", "sort_by": "duration", "sort_dir": "asc"},
    ).json()
    changed = only(saved, "order")
    assert changed["sort"] == {
        "by": "duration",
        "desc": False,
        "keys": changed["sort"]["keys"],
    }
    assert changed["note"] == "Shortest first"


def test_the_palette_offers_a_sort_box(canvas):
    assert 'data-palette="sort"' in canvas.get("/channels").text


# -- trying it without running it ------------------------------------------


def wire_trigger(canvas, channel="One Channel"):
    """A pulse wired to one channel, which is what a trial is asked of."""
    drawn = canvas.post("/graph/nodes", data={"kind": "pulse"}).json()
    trigger = boxes(drawn, "trigger")[-1]
    wanted = [node for node in boxes(drawn, "source") if node["title"] == channel][0]
    canvas.post("/graph/connect", data={"source": trigger["id"], "target": wanted["id"]})
    return trigger["id"]


def test_a_trial_says_where_everything_would_land(canvas, db):
    """A run with the consequences taken out: nothing is written, nothing is
    sent, and the answer is the same one a run would give."""
    from dealgo.models import Video as VideoModel

    with db.session_scope() as session:
        channel = session.scalars(select(Channel)).one()
        session.add(VideoModel(video_id="short1", channel_pk=channel.id, title="A short",
                               is_short=True, duration_sec=30, status="pending"))

    drawn = canvas.get("/api/graph").json()
    source, feed = only(drawn, "source"), only(drawn, "feed")
    canvas.post("/graph/connect", data={"source": source["id"], "target": feed["id"]})

    trial = canvas.get(f"/graph/nodes/{wire_trigger(canvas)}/test").json()

    # Every box carries its own share, so each can answer for itself.
    landing = trial["items"][str(feed["id"])]
    assert [item["title"] for item in landing["through"]] == ["A clip"]

    # The short was turned away by the channel's own settings, and it is the
    # channel's box that reports holding it.
    at_source = trial["items"][str(source["id"])]
    assert [item["title"] for item in at_source["held"]] == ["A short"]
    assert trial["nodes"][str(source["id"])] == {
        "state": "done", "count": 1, "stopped": 1, "ends": False, "trouble": None,
    }


def test_a_trial_says_a_reddit_thread_cannot_go_into_a_youtube_playlist(canvas, db):
    """Drawing that wire is refused now, but one drawn before it was — or one
    reached through a tag node — still has to be explained rather than left to
    fail at the insert. So the link is made in the database, the way the ones
    already out there were."""
    from dealgo.models import Video as VideoModel

    with db.session_scope() as session:
        source = Channel(
            channel_id="r/python", title="r/python", source_kind="reddit",
            source_url="https://www.reddit.com/r/python/.rss", enabled=True,
        )
        session.add(source)
        session.flush()
        session.add(VideoModel(
            video_id="item-abc", channel_pk=source.id, kind="link", title="A thread",
            link="https://reddit.com/r/python/comments/abc", status="pending",
        ))
        # The fixture's feed is a real YouTube playlist, which is the point.
        source.playlists.append(session.scalars(select(Playlist)).one())

    drawn = canvas.get("/api/graph").json()
    reddit = [node for node in boxes(drawn, "source") if node["title"] == "r/python"][0]

    trial = canvas.get(f"/graph/nodes/{wire_trigger(canvas, 'r/python')}/test").json()

    held = trial["items"][str(reddit["id"])]["held"]
    assert [item["title"] for item in held] == ["A thread"]
    assert "YouTube playlist" in held[0]["reason"]


def test_backfill_brings_back_what_was_passed_over_as_too_old(canvas, db, monkeypatch):
    """A poll takes what is new. Backfill takes everything the feed still
    lists, including what the first check set aside for predating the backfill
    window — which is what somebody means by "catch me up"."""
    from dealgo.models import Video as VideoModel
    from dealgo.services import sync as sync_service

    with db.session_scope() as session:
        channel = session.scalars(select(Channel)).one()
        for index in range(3):
            session.add(VideoModel(
                video_id=f"old{index}", channel_pk=channel.id, title=f"Old {index}",
                status="ignored", reason=sync_service.TOO_OLD,
            ))
        # Something a filter turned away is a different judgement, and reaching
        # further back is no argument against it.
        session.add(VideoModel(
            video_id="short1", channel_pk=channel.id, title="A short",
            status="skipped", reason="Shorts are switched off",
        ))

    trigger = wire_trigger(canvas)
    ran = []
    monkeypatch.setattr(sync_service, "run_sync", lambda *a, **k: ran.append((a, k)))

    answer = canvas.post(f"/graph/nodes/{trigger}/backfill")
    assert answer.status_code == 200
    assert "Reaching back" in answer.json()["said"]

    for _ in range(50):
        if ran:
            break
        time.sleep(0.02)
    assert ran[0][1]["reach_back"] == 0  # no count given: as far as the feeds go
    assert ran[0][0] == ("backfill",)


def test_running_a_trigger_normally_does_not_reach_back(canvas, db, monkeypatch):
    from dealgo.services import sync as sync_service

    trigger = wire_trigger(canvas)
    ran = []
    monkeypatch.setattr(sync_service, "run_sync", lambda *a, **k: ran.append((a, k)))

    canvas.post(f"/graph/nodes/{trigger}/fire")

    for _ in range(50):
        if ran:
            break
        time.sleep(0.02)
    assert ran[0][1]["reach_back"] is None


def test_a_feed_that_refuses_us_is_reported_as_that_not_as_stops_here(canvas, db, monkeypatch):
    """The whole complaint: a run that plainly happened said "stops here",
    which reads as a wiring fault you go looking for and never find."""
    import httpx

    from dealgo.services import sync as sync_service

    drawn = canvas.get("/api/graph").json()
    source, feed = only(drawn, "source"), only(drawn, "feed")
    canvas.post("/graph/connect", data={"source": source["id"], "target": feed["id"]})
    trigger = wire_trigger(canvas)

    def refused(_channel, _http):
        raise httpx.HTTPStatusError(
            "429", request=httpx.Request("GET", "https://example.test/feed"),
            response=httpx.Response(429, request=httpx.Request("GET", "https://example.test/feed")),
        )

    monkeypatch.setattr(sync_service, "_poll", refused)
    canvas.post(f"/graph/nodes/{trigger}/fire")

    for _ in range(100):
        state = canvas.get("/api/graph/run").json()
        if not state["running"] and state["stage"] == "done":
            break
        time.sleep(0.05)

    for node_id in (str(trigger), str(source["id"])):
        mark = state["nodes"][node_id]
        assert mark["trouble"] == "asked too often — it is rate limiting us", node_id
        assert mark["count"] == 0

    # And it is on the channel too, for somebody arriving later.
    with db.session_scope() as session:
        channel = session.scalars(select(Channel)).one()
    assert "rate limiting us" in channel.last_error


def test_a_feed_that_is_simply_gone_says_something_different(canvas, db, monkeypatch):
    """A 404 is not a 429: one is worth waiting out and the other is worth
    going to look at."""
    import httpx

    from dealgo.services import sync as sync_service

    trigger = wire_trigger(canvas)

    def gone(_channel, _http):
        request = httpx.Request("GET", "https://example.test/feed")
        raise httpx.HTTPStatusError("404", request=request, response=httpx.Response(404, request=request))

    monkeypatch.setattr(sync_service, "_poll", gone)
    canvas.post(f"/graph/nodes/{trigger}/fire")

    for _ in range(100):
        state = canvas.get("/api/graph/run").json()
        if not state["running"] and state["stage"] == "done":
            break
        time.sleep(0.05)

    assert state["nodes"][str(trigger)]["trouble"] == "no feed there any more"


def test_pressing_a_trigger_does_not_show_the_previous_runs_answer(canvas, db, monkeypatch):
    """A thread takes a moment to get going, and the canvas asks where the run
    is the instant the button answers. Without a claim it was told about the
    run before — which reads as this one having finished immediately, wearing
    the last one's marks."""
    import threading

    from dealgo.services import sync as sync_service

    trigger = wire_trigger(canvas)

    # A first run, so there is a finished one to be mistaken for the new one.
    monkeypatch.setattr(sync_service, "_poll", lambda *a: (_ for _ in ()).throw(RuntimeError("no")))
    canvas.post(f"/graph/nodes/{trigger}/fire")
    for _ in range(100):
        if not canvas.get("/api/graph/run").json()["running"]:
            break
        time.sleep(0.05)

    # The second one is held at the gate, so the only thing that can say it is
    # running is the claim the route made before starting the thread.
    held = threading.Event()
    monkeypatch.setattr(sync_service, "run_sync", lambda *a, **k: held.wait(5))

    canvas.post(f"/graph/nodes/{trigger}/fire")
    try:
        assert canvas.get("/api/graph/run").json()["running"] is True
    finally:
        held.set()


def test_a_run_that_never_got_going_does_not_hold_the_canvas_for_ever(canvas, monkeypatch):
    """The claim has to be given back however the run ends, or the canvas
    watches a run that threw on its way out of the door."""
    from dealgo.services import sync as sync_service

    trigger = wire_trigger(canvas)
    monkeypatch.setattr(
        sync_service, "_run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("fell over"))
    )

    canvas.post(f"/graph/nodes/{trigger}/fire")

    for _ in range(100):
        if not canvas.get("/api/graph/run").json()["running"]:
            break
        time.sleep(0.05)
    assert canvas.get("/api/graph/run").json()["running"] is False


def test_a_mirror_can_be_set_on_a_source_that_is_not_youtube(canvas, db, monkeypatch):
    from dealgo.models import Channel as ChannelModel

    reddit = add_reddit(canvas, db, monkeypatch)
    mirror = "https://openrss.org/reddit.com/r/python"

    answer = canvas.post(
        f"/graph/nodes/{reddit}", data={"box_form": "1", "active": "1", "mirror_url": mirror}
    )
    assert answer.status_code == 200

    filled = [n for n in boxes(answer.json(), "source") if n["id"] == reddit][0]
    assert filled["channel"]["mirror"] == mirror
    with db.session_scope() as session:
        source = session.scalar(select(ChannelModel).where(ChannelModel.channel_id == "r/python"))
    assert source.mirror_url == mirror


def test_a_mirror_has_to_be_a_web_address(canvas, db, monkeypatch):
    reddit = add_reddit(canvas, db, monkeypatch)

    answer = canvas.post(
        f"/graph/nodes/{reddit}",
        data={"box_form": "1", "active": "1", "mirror_url": "r/python somewhere"},
    )

    assert answer.status_code == 400
    assert "web address" in answer.json()["error"]


def test_clearing_the_mirror_puts_it_back_to_none(canvas, db, monkeypatch):
    from dealgo.models import Channel as ChannelModel

    reddit = add_reddit(canvas, db, monkeypatch)
    canvas.post(
        f"/graph/nodes/{reddit}",
        data={"box_form": "1", "active": "1", "mirror_url": "https://openrss.org/x"},
    )
    canvas.post(f"/graph/nodes/{reddit}", data={"box_form": "1", "active": "1", "mirror_url": ""})

    with db.session_scope() as session:
        source = session.scalar(select(ChannelModel).where(ChannelModel.channel_id == "r/python"))
    assert source.mirror_url is None


def test_the_backfill_button_asks_how_far_back_to_reach(canvas):
    """It is a different amount for a daily poster and a yearly one, so the
    person pressing it is asked rather than guessed at."""
    body = canvas.get("/channels").text

    assert "data-graph-reach" in body
    assert 'data-graph-reach-count' in body
    assert "How many of the latest" in body


def test_a_trial_writes_nothing(canvas, db):
    """The whole point: it answers the question without doing the thing."""
    from dealgo.models import Placement as PlacementModel, Video as VideoModel

    drawn = canvas.get("/api/graph").json()
    canvas.post(
        "/graph/connect",
        data={"source": only(drawn, "source")["id"], "target": only(drawn, "feed")["id"]},
    )
    with db.session_scope() as session:
        before = {v.video_id: v.status for v in session.scalars(select(VideoModel))}

    canvas.get(f"/graph/nodes/{wire_trigger(canvas)}/test")

    with db.session_scope() as session:
        after = {v.video_id: v.status for v in session.scalars(select(VideoModel))}
        assert after == before
        assert session.scalars(select(PlacementModel)).all() == []


def test_a_trial_names_the_filter_that_held_something(canvas, db):
    from dealgo.models import Video as VideoModel

    with db.session_scope() as session:
        channel = session.scalars(select(Channel)).one()
        session.add(VideoModel(video_id="short1", channel_pk=channel.id, title="A short",
                               is_short=True, duration_sec=30, status="pending"))
        channel.skip_shorts = False  # the channel lets them by; the filter will not

    added = canvas.post("/graph/nodes", data={"kind": "filter", "title": "No shorts"}).json()
    source, feed, middle = only(added, "source"), only(added, "feed"), only(added, "filter")
    canvas.post("/graph/connect", data={"source": source["id"], "target": middle["id"]})
    canvas.post("/graph/connect", data={"source": middle["id"], "target": feed["id"]})
    canvas.post(f"/graph/nodes/{middle['id']}",
                data={"box_form": "1", "active": "1", "label": "No shorts"})
    piece = only(
        canvas.post("/graph/nodes",
                    data={"kind": "lacks-words", "attach_to": str(middle["id"])}).json(),
        "lacks-words",
    )
    canvas.post(f"/graph/nodes/{piece['id']}", data={"value": "short"})

    trial = canvas.get(f"/graph/nodes/{wire_trigger(canvas)}/test").json()

    # The filter reports holding it, not the channel it came through, and not
    # the piece that says why — a condition is how a box is told, not a box.
    held = trial["items"][str(middle["id"])]["held"]
    assert [item["title"] for item in held] == ["A short"]
    assert held[0]["box"] == "No shorts"
    # It got past the channel on its way, and the channel is credited with it.
    assert trial["nodes"][str(source["id"])]["count"] == 2


def test_a_trial_puts_a_feeds_items_in_the_sorted_order(canvas, db):
    from dealgo.models import Video as VideoModel
    from dealgo.models import utcnow

    import datetime as dt

    with db.session_scope() as session:
        channel = session.scalars(select(Channel)).one()
        session.add(VideoModel(video_id="older", channel_pk=channel.id, title="Older",
                               duration_sec=600, status="pending",
                               published_at=utcnow() - dt.timedelta(days=2)))
        session.scalars(select(VideoModel)).all()[0].published_at = utcnow()

    added = canvas.post("/graph/nodes", data={"kind": "sort"}).json()
    source, feed, order = only(added, "source"), only(added, "feed"), only(added, "sort")
    canvas.post("/graph/connect", data={"source": source["id"], "target": order["id"]})
    canvas.post("/graph/connect", data={"source": order["id"], "target": feed["id"]})
    canvas.post(
        f"/graph/nodes/{order['id']}",
        data={"box_form": "1", "active": "1", "sort_by": "published", "sort_dir": "asc"},
    )

    trial = canvas.get(f"/graph/nodes/{wire_trigger(canvas)}/test").json()
    landing = trial["items"][str(feed["id"])]["through"]
    assert [item["title"] for item in landing] == ["Older", "A clip"]


def test_every_box_the_trial_touched_gets_its_own_share(canvas, db):
    """Asked while looking at a filter, the question is what that filter did —
    not what the trigger three wires back did."""
    from dealgo.models import Video as VideoModel

    with db.session_scope() as session:
        channel = session.scalars(select(Channel)).one()
        channel.skip_shorts = False
        session.add(VideoModel(video_id="short1", channel_pk=channel.id, title="A short",
                               is_short=True, duration_sec=30, status="pending"))

    added = canvas.post("/graph/nodes", data={"kind": "filter", "title": "No shorts"}).json()
    source, feed, middle = only(added, "source"), only(added, "feed"), only(added, "filter")
    canvas.post("/graph/connect", data={"source": source["id"], "target": middle["id"]})
    canvas.post("/graph/connect", data={"source": middle["id"], "target": feed["id"]})
    canvas.post(f"/graph/nodes/{middle['id']}",
                data={"box_form": "1", "active": "1", "label": "No shorts"})
    piece = only(
        canvas.post("/graph/nodes",
                    data={"kind": "lacks-words", "attach_to": str(middle["id"])}).json(),
        "lacks-words",
    )
    canvas.post(f"/graph/nodes/{piece['id']}", data={"value": "short"})
    trigger_id = wire_trigger(canvas)

    items = canvas.get(f"/graph/nodes/{trigger_id}/test").json()["items"]
    assert {str(source["id"]), str(middle["id"]), str(feed["id"]), str(trigger_id)} <= set(items)

    # The channel passed both; the filter passed one and held one; the feed
    # sees only what survived.
    assert len(items[str(source["id"])]["through"]) == 2
    assert len(items[str(middle["id"])]["through"]) == 1
    assert len(items[str(middle["id"])]["held"]) == 1
    assert len(items[str(feed["id"])]["through"]) == 1
    # And the trigger answers for the whole of it.
    assert len(items[str(trigger_id)]["through"]) == 1
    assert len(items[str(trigger_id)]["held"]) == 1


def test_a_box_the_trial_never_reached_carries_no_share(canvas, db):
    from dealgo.models import Playlist as PlaylistModel

    with db.session_scope() as session:
        session.add(PlaylistModel(playlist_id="PLidle", title="Idle"))

    drawn = canvas.get("/api/graph").json()
    canvas.post(
        "/graph/connect",
        data={"source": only(drawn, "source")["id"],
              "target": [n for n in boxes(drawn, "feed") if n["title"] == "One Feed"][0]["id"]},
    )
    trigger_id = wire_trigger(canvas)
    idle = [n for n in boxes(canvas.get("/api/graph").json(), "feed") if n["title"] == "Idle"][0]

    items = canvas.get(f"/graph/nodes/{trigger_id}/test").json()["items"]
    assert str(idle["id"]) not in items


def test_only_a_trigger_can_be_asked_what_a_run_would_do(canvas):
    """A trigger is what starts a run, so it is the thing worth asking."""
    drawn = canvas.get("/api/graph").json()
    refused = canvas.get(f"/graph/nodes/{only(drawn, 'source')['id']}/test")
    assert refused.status_code == 400
    assert "not a trigger" in refused.json()["error"]

    added = canvas.post("/graph/nodes", data={"kind": "pulse"}).json()
    lonely = canvas.get(f"/graph/nodes/{only(added, 'trigger')['id']}/test")
    assert lonely.status_code == 400
    assert "Nothing is wired" in lonely.json()["error"]


def test_a_switched_off_trigger_can_still_be_asked(canvas):
    """Being able to ask what it would do is most of the point of testing one,
    and refusing would be worst at the moment it is most wanted."""
    trigger_id = wire_trigger(canvas)
    canvas.post(f"/graph/nodes/{trigger_id}", data={"box_form": "1"})  # switched off

    assert canvas.get(f"/graph/nodes/{trigger_id}/test").status_code == 200


def test_a_trial_covers_only_the_channels_that_trigger_sets_off(canvas, db):
    from dealgo.models import Channel as ChannelModel, Playlist as PlaylistModel
    from dealgo.models import Video as VideoModel

    with db.session_scope() as session:
        other = ChannelModel(channel_id="UCother", title="Other")
        feed = session.scalars(select(PlaylistModel)).one()
        other.playlists.append(feed)
        session.add(other)
        session.flush()
        session.add(VideoModel(video_id="o1", channel_pk=other.id, title="Theirs",
                               status="pending"))

    drawn = canvas.get("/api/graph").json()
    mine = [n for n in boxes(drawn, "source") if n["title"] == "One Channel"][0]
    canvas.post("/graph/connect", data={"source": mine["id"], "target": only(drawn, "feed")["id"]})
    trigger_id = wire_trigger(canvas)

    trial = canvas.get(f"/graph/nodes/{trigger_id}/test").json()
    landing = trial["items"][str(only(drawn, "feed")["id"])]["through"]
    assert [item["title"] for item in landing] == ["A clip"]  # not "Theirs"


# -- switching a box off ---------------------------------------------------


def test_a_switched_off_filter_stops_the_flow(db):
    """Off is not "no opinion": nothing goes through it, so the path ends
    there rather than carrying on unfiltered."""
    build(db)
    with db.session_scope() as session:
        source = node_for(session, "source", "UCone")
        feed = node_for(session, "feed", "PLone")
        middle = graph.add_filter(session, label="Trim")
        graph.connect(session, source, middle)
        graph.connect(session, middle, feed)
        assert len(graph.routes(session)) == 1

        middle.enabled = False
        session.flush()
        assert graph.routes(session) == []


def test_a_switched_off_trigger_sets_nothing_off(db):
    build(db)
    with db.session_scope() as session:
        source = node_for(session, "source", "UCone")
        trigger = graph.add_trigger(session, trigger_kind="pulse", every_minutes=15)
        graph.connect(session, trigger, source)
        assert graph.polling_plan(session)

        trigger.enabled = False
        session.flush()
        # Back to the account's own settings, which is what no trigger means.
        assert graph.polling_plan(session) == {}


def test_a_switched_off_trigger_cannot_be_pressed(db):
    build(db)
    with db.session_scope() as session:
        trigger = graph.add_trigger(session, trigger_kind="pulse")
        graph.connect(session, trigger, node_for(session, "source", "UCone"))
        trigger.enabled = False
        session.flush()

        with pytest.raises(graph.GraphError):
            graph.pulse_targets(session, trigger.id)


def test_every_box_says_whether_it_is_on(canvas):
    added = canvas.post("/graph/nodes", data={"kind": "filter"}).json()
    canvas.post("/graph/nodes", data={"kind": "pulse"})
    drawn = canvas.get("/api/graph").json()["nodes"]

    assert {node["kind"] for node in drawn} >= {"source", "feed", "filter", "trigger"}
    assert all(node["enabled"] is True for node in drawn)

    # And each kind can be switched off, wherever it keeps the answer.
    for node in drawn:
        canvas.post(f"/graph/nodes/{node['id']}", data={"box_form": "1"})
    after = {node["id"]: node["enabled"] for node in canvas.get("/api/graph").json()["nodes"]}
    assert set(after.values()) == {False}
    assert added  # the filter was among them


def test_a_switched_off_filter_holds_everything_and_says_why(canvas, db):
    added = canvas.post("/graph/nodes", data={"kind": "filter", "title": "Trim"}).json()
    source, middle = only(added, "source"), only(added, "filter")
    canvas.post("/graph/connect", data={"source": source["id"], "target": middle["id"]})
    canvas.post(f"/graph/nodes/{middle['id']}", data={"box_form": "1"})  # switched off

    report = canvas.get(f"/graph/nodes/{middle['id']}/filtered").json()
    assert report["through"] == []
    assert [item["reason"] for item in report["held"]] == ["this filter is switched off"]


# -- what a filter catches -------------------------------------------------


def test_a_filter_says_what_it_lets_through_and_what_it_holds_back(canvas, db):
    """Worked out from the rules as they stand, over everything upstream —
    not a log, which would show what an older version of the rules did."""
    from dealgo.models import Video as VideoModel

    with db.session_scope() as session:
        channel_pk = session.scalars(select(Channel)).one().id
        session.add(VideoModel(video_id="short1", channel_pk=channel_pk, title="A short",
                               is_short=True, duration_sec=30, status="pending"))

    added = canvas.post("/graph/nodes", data={"kind": "filter", "title": "No shorts"}).json()
    source, middle = only(added, "source"), only(added, "filter")
    canvas.post("/graph/connect", data={"source": source["id"], "target": middle["id"]})
    canvas.post(f"/graph/nodes/{middle['id']}", data={"label": "No shorts", "skip_shorts": "1"})

    report = canvas.get(f"/graph/nodes/{middle['id']}/filtered").json()
    assert [item["title"] for item in report["through"]] == ["A clip"]
    held = report["held"]
    assert [item["title"] for item in held] == ["A short"]
    assert "short" in held[0]["reason"].lower()


def test_a_filter_wired_to_nothing_catches_nothing(canvas):
    added = canvas.post("/graph/nodes", data={"kind": "filter"}).json()
    report = canvas.get(f"/graph/nodes/{only(added, 'filter')['id']}/filtered").json()

    assert report["through"] == [] and report["held"] == []


def test_only_a_filter_is_asked_what_it_catches(canvas):
    source = only(canvas.get("/api/graph").json(), "source")
    answer = canvas.get(f"/graph/nodes/{source['id']}/filtered")

    assert answer.status_code == 400
    assert "filter node" in answer.json()["error"]


def test_an_earlier_filter_on_the_path_still_counts(canvas, db):
    """Two filters in a row: the second judges what the first let through, so
    its answer depends on the path, not just on its own rules."""
    from dealgo.models import Video as VideoModel

    with db.session_scope() as session:
        channel_pk = session.scalars(select(Channel)).one().id
        session.add(VideoModel(video_id="short1", channel_pk=channel_pk, title="A short",
                               is_short=True, duration_sec=30, status="pending"))

    first = canvas.post("/graph/nodes", data={"kind": "filter", "title": "First"}).json()
    first_id = [n for n in boxes(first, "filter") if n["title"] == "First"][0]["id"]
    second = canvas.post("/graph/nodes", data={"kind": "filter", "title": "Second"}).json()
    second_id = [n for n in boxes(second, "filter") if n["title"] == "Second"][0]["id"]
    source = only(second, "source")

    canvas.post("/graph/connect", data={"source": source["id"], "target": first_id})
    canvas.post("/graph/connect", data={"source": first_id, "target": second_id})
    # The first one blocks shorts; the second says nothing about them.
    canvas.post(f"/graph/nodes/{first_id}", data={"label": "First", "skip_shorts": "1"})

    report = canvas.get(f"/graph/nodes/{second_id}/filtered").json()
    assert [item["title"] for item in report["held"]] == ["A short"]


# -- watching a run go through ---------------------------------------------


def test_nothing_is_running_to_begin_with(canvas):
    answer = canvas.get("/api/graph/run").json()
    assert answer["running"] is False
    assert answer["nodes"] == {}


def test_a_run_says_which_box_it_is_working_on(canvas, db, monkeypatch):
    """The canvas draws from this, so what it names has to be boxes."""
    from dealgo.services import sync as sync_service

    with db.session_scope() as session:
        channel_pk = session.scalars(select(Channel)).one().id
        playlist_pk = session.scalars(select(Playlist)).one().id

    # The canvas is drawn first, as the browser does it: this route reports on
    # the boxes that exist rather than making any, since a GET should not
    # write.
    source = only(canvas.get("/api/graph").json(), "source")

    sync_service.claim(None, "pulse")
    sync_service._note(stage="polling", channel_pk=channel_pk)
    answer = canvas.get("/api/graph/run").json()
    assert answer["stage"] == "polling"
    assert answer["nodes"][str(source["id"])] == {"state": "busy", "count": 0, "stopped": 0, "ends": False, "trouble": None}

    # Finished with it, and a feed has taken something.
    sync_service._note_polled(channel_pk, 3)
    sync_service._note_placed(playlist_pk)
    sync_service._note(stage="filling")
    answer = canvas.get("/api/graph/run").json()
    feed = only(canvas.get("/api/graph").json(), "feed")

    # The channel found three; how many left it is a separate question, and
    # nothing has said yet, so none have.
    assert answer["nodes"][str(source["id"])]["stopped"] == 3
    assert answer["nodes"][str(feed["id"])] == {"state": "done", "count": 1, "stopped": 0, "trouble": None,
                                                "ends": False}


def test_a_filter_that_lets_nothing_through_is_where_the_flow_stops(world, db):
    """The run says which box the items stopped at, not just that they did."""
    from dealgo.models import Channel as ChannelModel
    from dealgo.services import graph, sync as sync_service
    from fakes import CHANNEL_ID, entry
    from dealgo.plugins.publisher import VideoDetails

    with db.session_scope() as session:
        graph.load(session)
        source = next(n for n in graph.nodes(session) if n.kind == "source")
        feed = next(n for n in graph.nodes(session) if n.kind == "feed")
        middle = graph.add_filter(session, label="Only long ones")
        narrow(session, middle, "longer-than", 3600)  # nothing will be this long
        graph.connect(session, source, middle)
        graph.connect(session, middle, feed)
        # The straight wire would let everything past the filter.
        for edge in graph.edges(session):
            if edge.source_pk == source.id and edge.target_pk == feed.id:
                graph.disconnect(session, edge.id)
        node_pk = middle.id

    world["entries"] = [entry("v0", minutes_ago=5)]
    world["client"].details = {"v0": VideoDetails("v0", "Video v0", 600, "none", "public")}
    sync_service.run_sync("pulse", force=True)

    state = sync_service.progress()
    assert state is not None
    assert state.through.get(node_pk, 0) == 0
    assert state.stopped.get(node_pk, 0) == 1


def test_a_channel_with_nothing_new_leaves_its_feed_alone(world, db):
    """The flow stops at the channel, so the boxes after it took no part in
    the run. Marking them would say the run did something there, and reading
    "nothing new" on a feed that was never reached is worse than reading
    nothing at all."""
    from dealgo.services import graph, sync as sync_service

    with db.session_scope() as session:
        graph.load(session)
        feed_pk = next(n for n in graph.nodes(session) if n.kind == "feed").id
        source_pk = next(n for n in graph.nodes(session) if n.kind == "source").id

    world["entries"] = []  # the channel has nothing new
    sync_service.run_sync("pulse", force=True)

    state = sync_service.progress()
    assert state is not None
    assert sum(state.polled.values()) == 0
    assert state.placed == {}

    # Which is what the canvas is told: the channel was polled, and nothing
    # downstream of it was touched.
    from dealgo.web import app as web_app

    with db.session_scope() as session:
        marks = web_app._run_marks(session, state, None)
    assert marks[str(source_pk)] == {"state": "done", "count": 0, "stopped": 0, "ends": False, "trouble": None}
    assert str(feed_pk) not in marks


def test_a_channel_that_turns_its_own_uploads_away_is_where_it_stops(world, db):
    """Found three, let none out: the channel's own settings are the reason,
    and the channel is the box to point at."""
    from dealgo.models import Channel as ChannelModel
    from dealgo.services import graph, sync as sync_service
    from dealgo.plugins.publisher import VideoDetails
    from fakes import entry

    with db.session_scope() as session:
        session.scalars(select(ChannelModel)).one().skip_videos = True
        graph.load(session)
        source_pk = next(n for n in graph.nodes(session) if n.kind == "source").id
        feed_pk = next(n for n in graph.nodes(session) if n.kind == "feed").id

    world["entries"] = [entry("v0", minutes_ago=5)]
    world["client"].details = {"v0": VideoDetails("v0", "Video v0", 600, "none", "public")}
    sync_service.run_sync("pulse", force=True)

    from dealgo.web import app as web_app

    state = sync_service.progress()
    with db.session_scope() as session:
        marks = web_app._run_marks(session, state, None)

    assert marks[str(source_pk)]["count"] == 0
    assert marks[str(source_pk)]["stopped"] == 1
    assert marks[str(source_pk)]["ends"] is True
    assert str(feed_pk) not in marks


def test_a_trigger_wired_to_a_switched_off_channel_says_it_stopped_there(canvas, db):
    """It never looked, so it cannot report having found nothing. The count
    is of its own channels, not of whatever else the run was doing."""
    from dealgo.models import Channel as ChannelModel
    from dealgo.services import sync as sync_service

    added = canvas.post("/graph/nodes", data={"kind": "pulse"}).json()
    trigger, source = only(added, "trigger"), only(added, "source")
    canvas.post("/graph/connect", data={"source": trigger["id"], "target": source["id"]})

    with db.session_scope() as session:
        channel_pk = session.scalars(select(ChannelModel)).one().id

    # The run polled nothing: its only channel is switched off.
    sync_service.claim(None, "pulse", trigger["id"])
    sync_service._note(stage="done", finished=True)
    idle = canvas.get("/api/graph/run").json()["nodes"][str(trigger["id"])]
    assert idle == {"state": "done", "count": 0, "stopped": 0, "ends": True, "trouble": None}

    # And when its channel was polled, it counts that one.
    sync_service.claim(None, "pulse", trigger["id"])
    sync_service._note_polled(channel_pk, 2)
    sync_service._note(stage="done", finished=True)
    ran = canvas.get("/api/graph/run").json()["nodes"][str(trigger["id"])]
    assert ran == {"state": "done", "count": 1, "stopped": 0, "trouble": None, "ends": False}


def test_a_trigger_does_not_count_channels_that_are_not_its_own(canvas, db):
    """Two triggers, one run: each says what it set off, not what the run did."""
    from dealgo.models import Channel as ChannelModel
    from dealgo.services import sync as sync_service

    with db.session_scope() as session:
        session.add(ChannelModel(channel_id="UCother", title="Other"))

    added = canvas.post("/graph/nodes", data={"kind": "pulse"}).json()
    trigger = only(added, "trigger")
    mine = [node for node in boxes(added, "source") if node["title"] == "One Channel"][0]
    canvas.post("/graph/connect", data={"source": trigger["id"], "target": mine["id"]})

    with db.session_scope() as session:
        others = session.scalar(select(ChannelModel.id).where(ChannelModel.channel_id == "UCother"))

    sync_service.claim(None, "pulse", trigger["id"])
    sync_service._note_polled(others, 7)  # somebody else's channel
    sync_service._note(stage="done", finished=True)

    idle = canvas.get("/api/graph/run").json()["nodes"][str(trigger["id"])]
    assert idle["count"] == 0 and idle["ends"] is True


def test_the_trigger_that_was_pressed_stays_lit_for_the_whole_run(canvas, db):
    """The run has to read as coming out of the box somebody pressed, not as
    starting in the middle of the drawing."""
    from dealgo.services import sync as sync_service

    added = canvas.post("/graph/nodes", data={"kind": "pulse"}).json()
    trigger, source = only(added, "trigger"), only(added, "source")
    canvas.post("/graph/connect", data={"source": trigger["id"], "target": source["id"]})

    sync_service.claim(None, "pulse", trigger["id"])
    sync_service._note(stage="polling")
    marks = canvas.get("/api/graph/run").json()["nodes"]
    assert marks[str(trigger["id"])] == {"state": "busy", "count": 0, "stopped": 0, "ends": False, "trouble": None}

    # It stops pulsing when the run ends, and keeps what it set off.
    sync_service._note(stage="done", finished=True)
    settled = canvas.get("/api/graph/run").json()["nodes"][str(trigger["id"])]
    assert settled["state"] == "done"


def test_pressing_a_pulse_tells_the_run_which_box_did_it(canvas, monkeypatch):
    from dealgo.web import app as web_app

    asked: dict[str, object] = {}

    class Recorder:
        def __init__(self, target, args, kwargs, daemon):
            asked["kwargs"] = kwargs

        def start(self) -> None:
            pass

    monkeypatch.setattr(web_app.threading, "Thread", Recorder)

    added = canvas.post("/graph/nodes", data={"kind": "pulse"}).json()
    trigger, source = only(added, "trigger"), only(added, "source")
    canvas.post("/graph/connect", data={"source": trigger["id"], "target": source["id"]})
    canvas.post(f"/graph/nodes/{trigger['id']}/fire")

    assert asked["kwargs"]["fired_by"] == trigger["id"]


def test_the_canvas_no_longer_offers_to_follow_one_item(canvas):
    body = canvas.get("/channels").text
    assert "data-graph-trace" not in body
    assert canvas.get("/graph/trace/1").status_code == 404


# -- the script that draws it ----------------------------------------------
#
# The drawing needs a browser. Everything it decides before drawing does not,
# and that is what these check: what the script accepts as a graph, and what
# it says after following an item.

HARNESS = pathlib.Path(__file__).resolve().parent / "graph_harness.js"
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")


@pytest.fixture(scope="module")
def canvas_report():
    result = subprocess.run(["node", str(HARNESS)], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


@needs_node
def test_the_script_survives_being_run_again(canvas_report):
    """htmx re-inserts it on every swap; a top-level const would throw."""
    assert canvas_report["runsTwice"] is True


@needs_node
def test_only_a_real_graph_is_drawn(canvas_report):
    """An error body is not a graph, and must not empty the canvas silently."""
    assert canvas_report["refusesAnError"] is None
    assert canvas_report["readsTheError"] == "A box cannot feed itself."
    assert len(canvas_report["readsAGraph"]["nodes"]) == 1
    assert canvas_report["dropsARubbishNode"]["nodes"] == []


@needs_node
def test_a_condition_piece_arrives_as_one_thing_to_fill_in(canvas_report):
    said = canvas_report["readsACondition"]
    assert said["label"] == "Longer than"
    assert said["field"] == "duration"
    assert said["value"] == "2" and said["unit"] == "minutes"
    # A unit that is not a string is not a unit.
    assert said["units"] == ["seconds", "minutes", "hours"]


@needs_node
def test_a_condition_the_payload_half_described_still_draws(canvas_report):
    """A field type nobody recognises is drawn as a line of text, because a
    field nobody can fill in is worse than one drawn plainly."""
    said = canvas_report["mendsAHalfCondition"]
    assert said["field"] == "text"
    assert said["under"] == "filter"
    assert said["label"] == "" and said["units"] == []


@needs_node
def test_a_piece_only_lights_up_the_boxes_it_belongs_under(canvas_report):
    """Said in the browser as well as on the server: a refusal you can see
    coming beats one that arrives after the drop."""
    said = canvas_report["slotsFor"]
    assert said["orderUnderSort"] is True
    assert said["orderUnderFilter"] is False
    assert said["wordsUnderFilter"] is True
    assert said["wordsUnderFeed"] is False
    # A plugin's condition goes where every other condition goes: there is no
    # plugin box for it to hang off.
    assert said["ruleUnderFilter"] is True
    assert said["ruleUnderFeed"] is False
    # The four older pieces say something about reading, which is a question
    # only a feed, a Decay and an Expire box ask.
    assert said["timerUnderFeed"] is True
    assert said["timerUnderFilter"] is False


@needs_node
def test_a_wire_runs_from_one_box_to_the_other(canvas_report):
    assert canvas_report["curve"]["starts"] and canvas_report["curve"]["ends"]


@needs_node
def test_each_box_says_which_of_the_four_it_is(canvas_report):
    """"Source" is the fallback these days: a source box that knows which
    kind it is says that instead, which is what `boxHeadings` covers."""
    assert canvas_report["labels"] == ["Trigger", "Source", "Filter", "Feed"]


@needs_node
def test_zooming_keeps_what_is_under_the_pointer_under_the_pointer(canvas_report):
    """Zooming about the corner instead would send the thing being looked at
    off the edge, which is the difference between a zoom and a surprise."""
    held = canvas_report["zoomHoldsThePointer"]
    assert held["before"] == held["after"]
    assert held["zoom"] == 2


@needs_node
def test_the_zoom_stops_at_both_ends(canvas_report):
    limits = canvas_report["zoomLimits"]
    assert canvas_report["zoomedRightIn"] == limits["most"]
    assert canvas_report["zoomedRightOut"] == limits["least"]


@needs_node
def test_the_canvas_reads_what_a_run_is_doing(canvas_report):
    """Boxes are marked from this, so a mark that cannot be read is a box that
    silently never lights up."""
    run = canvas_report["run"]
    assert run["running"] is True
    assert run["stage"] == "polling"
    # The rubbish entry is dropped rather than drawn as a blank mark.
    assert run["marks"] == [
        [3, {"state": "busy", "count": 0, "stopped": 0, "ends": False, "trouble": None}],
        [7, {"state": "done", "count": 2, "stopped": 0, "ends": False, "trouble": None}],
    ]


@needs_node
def test_a_run_that_is_not_one_is_refused(canvas_report):
    assert canvas_report["runRefusesRubbish"] is True


@needs_node
def test_the_run_lights_the_wire_out_of_the_box_it_is_working_on(canvas_report):
    """Pressing Run now on a trigger should show the run leaving it. Only the
    channel was ever marked busy, so the trigger's own wire stayed dark."""
    assert canvas_report["wiresLitByTheTrigger"] == ["edge:1"]


@needs_node
def test_a_wire_is_found_by_name_not_by_where_it_sits(canvas_report):
    """It used to be found as the sibling of its own hit area, which would
    stop working the day anything else was drawn between them."""
    assert '[data-line="edge:1"]' in canvas_report["wireSelectors"]


@needs_node
def test_a_box_that_passed_nothing_on_says_so(canvas_report):
    """Five different answers that all used to look like a blank box: this
    brought something, there was nothing to bring, something was held here,
    this never looked at all, and this looked and was turned away."""
    tallies = canvas_report["tallies"]
    assert tallies["idle"]["text"] == "stops here"
    assert tallies["found"]["text"] == "+3"
    assert tallies["empty"] == {"text": "nothing new", "muted": True, "end": False,
                                "deadEnd": False}
    assert tallies["blocked"]["text"] == "stops here · 4 held"
    # A quiet channel is not a dead end to be alarmed about: it is the usual
    # state of a channel, and it reads as such.
    assert tallies["barren"] == {"text": "nothing new", "muted": True, "end": False,
                                 "deadEnd": False}


@needs_node
def test_a_feed_that_turned_us_away_says_so_rather_than_stops_here(canvas_report):
    """The complaint this answers: a run that plainly happened reported "stops
    here", which reads as a wiring fault. The feed was rate limiting us — the
    one reading of a run you cannot check by looking at the canvas."""
    refused = canvas_report["tallies"]["refused"]

    assert refused["text"] == "asked too often — it is rate limiting us"
    # Not the warn colour a filter doing its job wears: this is a fault.
    assert refused["end"] is False
    assert refused["deadEnd"] is True


@needs_node
def test_a_mark_without_the_field_does_not_print_undefined(canvas_report):
    """`undefined !== null`, so asking the wrong question here put the word
    "undefined" on the canvas for every mark built anywhere that omits it."""
    assert canvas_report["tallies"]["oldShape"]["text"] == "stops here"


@needs_node
def test_the_box_the_flow_stops_at_is_marked_as_well_as_its_badge(canvas_report):
    """The badge answers "what happened here"; the outline answers "where do I
    look", which is the one you need before you know to read the badge."""
    assert canvas_report["tallies"]["blocked"]["deadEnd"] is True
    assert canvas_report["tallies"]["found"]["deadEnd"] is False


@needs_node
def test_a_box_the_run_has_not_finished_with_says_nothing_yet(canvas_report):
    """A count of zero while it is still being polled would be a lie."""
    assert canvas_report["tallies"]["working"] is None
    assert canvas_report["tallies"]["untouched"] is None


def test_what_a_filter_catches_opens_in_a_dialog(canvas):
    """A long list inside the box that opened it makes the box stop being a
    box on a canvas. A <dialog> is painted in the browser's top layer, so
    nothing on the canvas can clip it."""
    body = canvas.get("/channels").text
    assert "<dialog" in body and "data-graph-catch" in body
    assert 'class="modal graph-catch"' in body
    # And it is closable without JavaScript having to invent a way.
    assert "data-graph-catch-close" in body


@needs_node
def test_each_port_says_what_it_takes_or_gives(canvas_report):
    """Two things travel these wires — a signal to run, and the content being
    collected. A port that said nothing left the reader to guess which."""
    ports = canvas_report["ports"]
    assert "signal" in ports["triggerOut"] and "signal" in ports["channelIn"]
    assert "videos and posts" in ports["channelOut"]
    assert "got through" in ports["filterOut"]
    assert "end up" in ports["feedIn"]
    # Every port says something, and no two sides say the same thing.
    assert len(set(ports.values())) == len(ports)


@needs_node
def test_the_two_ends_are_named_after_what_is_being_sorted(canvas_report):
    """"Most first" means one thing for a duration and another for a date.
    Leaving it at that makes the reader work out which end they are picking."""
    ends = canvas_report["sortEnds"]
    assert ends["published"] == ["Newest first", "Oldest first"]
    assert ends["duration"] == ["Longest first", "Shortest first"]
    # A key the canvas has never heard of still gets usable words.
    assert ends["unknown"] == ["Most first", "Least first"]


@needs_node
def test_the_trial_is_shown_in_the_box_that_was_asked(canvas_report):
    """Not in a box of its own over the canvas: the answer is about one
    trigger, so it belongs in that trigger."""
    assert canvas_report["popoverTabs"] == ["Settings", "Test"]


@needs_node
def test_opening_a_test_tab_only_runs_a_trial_when_it_can(canvas_report):
    """A filter has a Test tab because a trial came through it, not because it
    can start one. Asking the server to test a filter is refused, and the
    refusal used to take the whole trial down with it."""
    runs = canvas_report["tabRuns"]
    assert runs["triggerWithNoTrial"] is True
    assert runs["triggerWithAnothers"] is True  # a different trigger's trial
    assert runs["triggerWithItsOwn"] is False   # already has the answer
    assert runs["filterShowingItsShare"] is False
    assert runs["goingBackToSettings"] is False
    assert runs["aBoxThatIsGone"] is False


@needs_node
def test_a_judged_item_shows_what_would_be_left_on_it(canvas_report):
    """A trial says what would happen, and what the boxes leave on an item
    is as much of that as which feed it lands in."""
    marks = canvas_report["judgedMarks"]

    assert marks["marked"] == ["“news”", "3 min · no pause"]
    # And nothing at all where the boxes said nothing, which is most items.
    assert marks["plain"] == []


@needs_node
def test_a_trial_is_numbered_and_a_filters_report_is_not(canvas_report):
    """A trial lists the batch in the order it would arrive, and on a sort box
    that order is the whole answer. A filter's two piles are not an order, so
    numbering them would imply one that is not there."""
    lists = canvas_report["lists"]
    assert lists["trial"] == {"tag": "ol", "className": "graph-sheet-list is-numbered"}
    assert lists["report"] == {"tag": "ul", "className": "graph-sheet-list"}


@needs_node
def test_a_press_in_a_panel_over_the_canvas_is_not_a_press_on_it(canvas_report):
    """The palette and the open node sit over the drawing rather than on it.
    Taking a press in one as a press on the canvas starts a pan — and swallows
    the fold or the field that was actually being pressed."""
    pressing = canvas_report["pressing"]
    assert pressing["palette"] is False
    assert pressing["openNode"] is False
    # And the canvas itself still pans, or the two above prove nothing.
    assert pressing["canvas"] is True


# -- when a feed may be read -----------------------------------------------
#
# Slotted under the feed rather than wired into it: when it may be read is a
# property of the feed, not something arriving along a wire. A Reset says
# when the window opens; a Timer says how long it stays open.


def piece(kind, **fields):
    from dealgo.models import GraphNode as Node

    return Node(kind=kind, enabled=True, **fields)


def test_a_feed_with_nothing_slotted_under_it_is_always_open(db):
    assert graph.is_open([], dt.datetime(2026, 5, 1, 3, 0)) is True


def test_a_timer_is_a_sitting_that_starts_when_you_sit_down(db):
    """There is no clock time in a Timer, so the sitting starts at the first
    visit rather than at whatever hour the arithmetic would land on — which
    is what "ninety minutes a day" means to the person who asked for it."""
    timer = piece("timer", duration_minutes=90)
    nightly = piece("reset", cron="0 0 * * *")
    now = dt.datetime(2026, 5, 1, 10, 0)

    first = graph.window_state([timer, nightly], now)
    assert first.open is True
    assert first.starting == [timer]  # this visit begins it

    timer.last_fired_at = dt.datetime(2026, 5, 1, 9, 30)
    assert graph.is_open([timer, nightly], now) is True  # half an hour in

    timer.last_fired_at = dt.datetime(2026, 5, 1, 7, 0)
    assert graph.is_open([timer, nightly], now) is False  # spent


def test_a_reset_gives_you_another_sitting_when_it_comes_round(db):
    timer = piece("timer", duration_minutes=90)
    nightly = piece("reset", cron="0 0 * * *")
    now = dt.datetime(2026, 5, 1, 10, 0)

    # Sat down yesterday evening, and midnight has been past since.
    timer.last_fired_at = dt.datetime(2026, 4, 30, 23, 0)
    state = graph.window_state([timer, nightly], now)

    assert state.open is True
    assert state.starting == [timer]


def test_a_timer_with_no_reset_gives_you_one_sitting_and_no_more(db):
    """Which is the honest answer: nothing on the canvas says when it would
    come back, so it does not pretend that it will."""
    timer = piece("timer", duration_minutes=30)
    now = dt.datetime(2026, 5, 1, 10, 0)
    assert graph.is_open([timer], now) is True

    timer.last_fired_at = dt.datetime(2026, 5, 1, 8, 0)
    state = graph.window_state([timer], now)

    assert state.open is False
    assert state.opens_at is None


def test_a_reset_with_no_timer_gives_the_usual_half_hour(db):
    nightly = piece("reset", cron="0 0 * * *")
    now = dt.datetime(2026, 5, 1, 10, 0)

    nightly.last_fired_at = dt.datetime(2026, 5, 1, 9, 50)
    assert graph.is_open([nightly], now) is True   # ten minutes in
    nightly.last_fired_at = dt.datetime(2026, 5, 1, 9, 0)
    assert graph.is_open([nightly], now) is False  # an hour ago, so spent


def test_the_timer_nearest_the_feed_has_the_last_word(db):
    """The same rule a filter nearest a feed lives by. `pieces_under` hands
    them over nearest first, so the first one is the one that counts."""
    nearest = piece("timer", duration_minutes=5)
    further = piece("timer", duration_minutes=180)
    nearest.last_fired_at = dt.datetime(2026, 5, 1, 9, 30)

    assert graph.is_open([nearest, further], dt.datetime(2026, 5, 1, 10, 0)) is False


def test_more_resets_are_more_chances_to_read(db):
    """Any one of them coming round is enough: a second Reset is a second
    chance, not a further condition."""
    timer = piece("timer", duration_minutes=30)
    morning = piece("reset", cron="0 9 * * *")
    evening = piece("reset", cron="0 18 * * *")
    timer.last_fired_at = dt.datetime(2026, 5, 1, 6, 0)  # spent long ago

    both = [timer, morning, evening]
    assert graph.is_open(both, dt.datetime(2026, 5, 1, 9, 5)) is True
    assert graph.is_open(both, dt.datetime(2026, 5, 1, 18, 5)) is True


def test_a_shut_feed_says_when_it_opens_again(db):
    timer = piece("timer", duration_minutes=30)
    morning = piece("reset", cron="0 9 * * *")
    timer.last_fired_at = dt.datetime(2026, 5, 1, 9, 0)

    state = graph.window_state([timer, morning], dt.datetime(2026, 5, 1, 12, 0))

    assert state.open is False
    assert state.opens_at is not None and state.opens_at.hour == 9


def test_asking_whether_a_feed_is_open_starts_nothing(db):
    """What the canvas draws on a feed box. Showing the state must not spend
    a sitting the reader never sat down for."""
    timer = piece("timer", duration_minutes=30)

    assert graph.is_open([timer], dt.datetime(2026, 5, 1, 10, 0)) is True
    assert timer.last_fired_at is None


# -- the hours a feed is allowed at all ------------------------------------


def test_alive_allows_only_the_stretch_of_day_it_names(db):
    day = piece("alive", alive_from="09:00", alive_to="17:00")

    assert graph.is_open([day], dt.datetime(2026, 5, 1, 12, 0)) is True
    assert graph.is_open([day], dt.datetime(2026, 5, 1, 8, 59)) is False
    # The far end is the moment it stops, not the last minute it allows.
    assert graph.is_open([day], dt.datetime(2026, 5, 1, 17, 0)) is False


def test_an_end_before_its_start_runs_through_midnight(db):
    """Which is how somebody writes "overnight" without being asked to say
    it as two stretches."""
    night = piece("alive", alive_from="22:00", alive_to="06:00")

    assert graph.is_open([night], dt.datetime(2026, 5, 1, 23, 0)) is True
    assert graph.is_open([night], dt.datetime(2026, 5, 1, 3, 0)) is True
    assert graph.is_open([night], dt.datetime(2026, 5, 1, 12, 0)) is False


def test_both_ends_the_same_is_any_time_of_day(db):
    """The reading that cannot accidentally shut a feed for ever, which the
    other one can."""
    always = piece("alive", alive_from="09:00", alive_to="09:00")

    assert graph.is_open([always], dt.datetime(2026, 5, 1, 3, 0)) is True


def test_alive_narrows_a_sitting_that_still_has_time_left(db):
    """It is about the hour rather than about a sitting, so being outside it
    shuts the feed whatever the other pieces worked out."""
    timer = piece("timer", duration_minutes=90)
    timer.last_fired_at = dt.datetime(2026, 5, 1, 3, 30)
    day = piece("alive", alive_from="09:00", alive_to="17:00")

    # Half an hour into ninety minutes, and it would be open on its own.
    assert graph.is_open([timer], dt.datetime(2026, 5, 1, 4, 0)) is True
    assert graph.is_open([timer, day], dt.datetime(2026, 5, 1, 4, 0)) is False


def test_a_feed_shut_by_the_hour_says_when_it_wakes(db):
    day = piece("alive", alive_from="09:00", alive_to="17:00")

    state = graph.window_state([day], dt.datetime(2026, 5, 1, 4, 0))

    assert state.open is False
    assert state.opens_at is not None and state.opens_at.hour == 9


def test_a_sitting_is_not_spent_against_an_hour_that_was_never_going_to_open(db):
    """Asked before the sitting, so arriving at four in the morning does not
    burn the day's ninety minutes on a feed that refused to open."""
    timer = piece("timer", duration_minutes=90)
    day = piece("alive", alive_from="09:00", alive_to="17:00")

    state = graph.window_state([timer, day], dt.datetime(2026, 5, 1, 4, 0))

    assert state.open is False
    assert state.starting == []


def test_more_alive_pieces_are_more_stretches(db):
    morning = piece("alive", alive_from="06:00", alive_to="09:00")
    evening = piece("alive", alive_from="18:00", alive_to="22:00")

    both = [morning, evening]
    assert graph.is_open(both, dt.datetime(2026, 5, 1, 7, 0)) is True
    assert graph.is_open(both, dt.datetime(2026, 5, 1, 19, 0)) is True
    assert graph.is_open(both, dt.datetime(2026, 5, 1, 12, 0)) is False


@pytest.mark.parametrize(
    ("typed", "stored"),
    [("9", "09:00"), ("9:5", "09:05"), ("09.05", "09:05"), ("0905", "09:05"),
     ("17:00", "17:00"), (" 7 ", "07:00")],
)
def test_a_time_is_taken_however_it_is_written_down(typed, stored):
    """A field asking for a time should take a time however somebody writes
    one, and store the one shape."""
    assert graph.clock_time(typed) == stored


@pytest.mark.parametrize("typed", ["24:00", "09:61", "noon", "", "-1"])
def test_something_that_is_not_a_time_is_not_one(typed):
    assert graph.clock_time(typed) == ""


# -- slotting pieces in ----------------------------------------------------


def test_a_piece_dropped_on_a_box_is_slotted_into_it(canvas):
    """Dropped rather than wired: the canvas says which box it landed on and
    the piece goes under it."""
    feed = only(canvas.get("/api/graph").json(), "feed")

    added = canvas.post(
        "/graph/nodes", data={"kind": "timer", "attach_to": feed["id"]}
    ).json()

    made = boxes(added, "timer")[0]
    assert made["piece"]["under"] == feed["id"]
    assert made["note"] == "30 minutes once you start reading"


def test_a_piece_already_on_the_canvas_can_be_slotted_in(canvas):
    """Dragged onto a slot rather than dropped out of the palette onto one.
    Without this a piece lying beside the box it belongs under could only be
    deleted and dragged out again."""
    feed = only(canvas.get("/api/graph").json(), "feed")
    loose = boxes(canvas.post("/graph/nodes", data={"kind": "timer"}).json(), "timer")[0]
    assert loose["piece"]["under"] is None

    answer = canvas.post(f"/graph/nodes/{loose['id']}/attach", data={"under": feed["id"]})

    assert answer.status_code == 200
    assert boxes(answer.json(), "timer")[0]["piece"]["under"] == feed["id"]
    assert only(answer.json(), "feed")["feed"]["windows"] == [
        "30 minutes once you start reading"
    ]


def test_a_slotted_piece_offers_a_way_out_of_its_slot(canvas):
    """Dragging it moves the assembly, so the way out is a button rather than
    a drag: without one a piece could only be deleted."""
    feed = only(canvas.get("/api/graph").json(), "feed")
    canvas.post("/graph/nodes", data={"kind": "timer", "attach_to": feed["id"]})

    body = canvas.get("/channels").text

    # The canvas builds the panel, so the word is in the script it draws with.
    assert "Take it out" in canvas.get("/static/graph.js").text
    assert "data-graph" in body


def test_a_slotted_piece_can_be_taken_back_out_from_the_canvas(canvas):
    feed = only(canvas.get("/api/graph").json(), "feed")
    piece = boxes(
        canvas.post("/graph/nodes", data={"kind": "timer", "attach_to": feed["id"]}).json(),
        "timer",
    )[0]

    answer = canvas.post(f"/graph/nodes/{piece['id']}/attach", data={"under": ""})

    assert boxes(answer.json(), "timer")[0]["piece"]["under"] is None
    assert only(answer.json(), "feed")["feed"]["windows"] == []


def test_a_piece_cannot_be_slotted_into_a_ring(canvas):
    """Refused at the moment of the drop rather than discovered by a chain
    that walks round for ever."""
    feed = only(canvas.get("/api/graph").json(), "feed")
    first = boxes(
        canvas.post("/graph/nodes", data={"kind": "timer", "attach_to": feed["id"]}).json(),
        "timer",
    )[0]
    second = boxes(
        canvas.post("/graph/nodes", data={"kind": "reset", "attach_to": first["id"]}).json(),
        "reset",
    )[0]

    answer = canvas.post(f"/graph/nodes/{first['id']}/attach", data={"under": second["id"]})

    assert answer.status_code == 400
    assert answer.json()["error"]


def test_a_piece_dropped_on_nothing_is_loose_and_says_so(canvas):
    """Not refused: a piece on the canvas is a thing you can pick up and put
    somewhere, and refusing the drop would leave nothing to pick up."""
    added = canvas.post("/graph/nodes", data={"kind": "reset"}).json()

    made = boxes(added, "reset")[0]
    assert made["piece"]["under"] is None
    assert made["note"] == "drop it on a box to slot it in"


def test_pieces_chain_from_the_canvas_and_both_reach_the_feed(canvas):
    feed = only(canvas.get("/api/graph").json(), "feed")
    timer = boxes(
        canvas.post("/graph/nodes", data={"kind": "timer", "attach_to": feed["id"]}).json(),
        "timer",
    )[0]

    added = canvas.post(
        "/graph/nodes", data={"kind": "reset", "attach_to": timer["id"]}
    ).json()

    assert boxes(added, "reset")[0]["piece"]["under"] == timer["id"]
    assert only(added, "feed")["feed"]["windows"] == [
        "30 minutes once you start reading",
        "another 30 minutes on “0 9 * * *”",
    ]


def test_what_a_timer_says_is_saved_from_its_panel(canvas):
    feed = only(canvas.get("/api/graph").json(), "feed")
    timer = boxes(
        canvas.post("/graph/nodes", data={"kind": "timer", "attach_to": feed["id"]}).json(),
        "timer",
    )[0]

    answer = canvas.post(
        f"/graph/nodes/{timer['id']}",
        data={"box_form": "1", "active": "1", "duration_minutes": "90"},
    )

    assert answer.status_code == 200
    assert only(answer.json(), "feed")["feed"]["windows"][0] == (
        "90 minutes once you start reading"
    )


def test_a_reset_that_is_not_a_cron_is_refused_with_a_reason(canvas):
    feed = only(canvas.get("/api/graph").json(), "feed")
    reset = boxes(
        canvas.post("/graph/nodes", data={"kind": "reset", "attach_to": feed["id"]}).json(),
        "reset",
    )[0]

    answer = canvas.post(
        f"/graph/nodes/{reset['id']}",
        data={"box_form": "1", "active": "1", "cron": "every tuesday-ish"},
    )

    assert answer.status_code == 400
    assert answer.json()["error"]


def test_the_palette_offers_the_pieces(canvas):
    body = canvas.get("/channels").text
    assert 'data-palette="timer"' in body
    assert 'data-palette="reset"' in body
    assert 'data-palette="alive"' in body
    assert "<summary>Jigsaw</summary>" in body


def test_an_alive_piece_is_set_from_its_panel(canvas):
    feed = only(canvas.get("/api/graph").json(), "feed")
    piece = boxes(
        canvas.post("/graph/nodes", data={"kind": "alive", "attach_to": feed["id"]}).json(),
        "alive",
    )[0]
    # Nothing said yet, so it allows everything: a piece just dropped in
    # changes nothing until it is told to.
    assert piece["note"] == "any time of day"

    answer = canvas.post(
        f"/graph/nodes/{piece['id']}",
        data={"box_form": "1", "active": "1", "alive_from": "9", "alive_to": "17:30"},
    )

    assert answer.status_code == 200
    assert boxes(answer.json(), "alive")[0]["note"] == "only between 09:00 and 17:30"
    assert only(answer.json(), "feed")["feed"]["windows"] == [
        "only between 09:00 and 17:30"
    ]


def test_a_time_that_is_not_one_is_refused_with_a_reason(canvas):
    feed = only(canvas.get("/api/graph").json(), "feed")
    piece = boxes(
        canvas.post("/graph/nodes", data={"kind": "alive", "attach_to": feed["id"]}).json(),
        "alive",
    )[0]

    answer = canvas.post(
        f"/graph/nodes/{piece['id']}",
        data={"box_form": "1", "active": "1", "alive_from": "lunchtime", "alive_to": "17:00"},
    )

    assert answer.status_code == 400
    assert "24-hour clock" in answer.json()["error"]


def test_all_three_pieces_read_as_one_sentence_on_the_feed(canvas):
    """Each says its own half, in the order they are asked: how long, when it
    comes back, and the hours it is allowed at all."""
    feed = only(canvas.get("/api/graph").json(), "feed")
    timer = boxes(
        canvas.post("/graph/nodes", data={"kind": "timer", "attach_to": feed["id"]}).json(),
        "timer",
    )[0]
    reset = boxes(
        canvas.post("/graph/nodes", data={"kind": "reset", "attach_to": timer["id"]}).json(),
        "reset",
    )[0]
    alive = boxes(
        canvas.post("/graph/nodes", data={"kind": "alive", "attach_to": reset["id"]}).json(),
        "alive",
    )[0]
    canvas.post(
        f"/graph/nodes/{alive['id']}",
        data={"box_form": "1", "active": "1", "alive_from": "09:00", "alive_to": "17:00"},
    )

    said = only(canvas.get("/api/graph").json(), "feed")["feed"]["windows"]

    assert said == [
        "30 minutes once you start reading",
        "another 30 minutes on “0 9 * * *”",
        "only between 09:00 and 17:00",
    ]


def test_a_piece_is_slotted_under_a_box_rather_than_wired_to_it(db):
    build(db)
    with db.session_scope() as session:
        feed = node_for(session, "feed", "PLone")
        made = graph.add_piece(session, kind="reset", host=feed, cron="0 9 * * *")

        assert made.attached_to == feed.id
        assert graph.consumption(session)[feed.playlist_pk] == [made]


def test_pieces_chain_and_the_chain_belongs_to_the_box(db):
    """A piece may be slotted under another, and what it changes is always
    the box at the top rather than the piece above it."""
    build(db)
    with db.session_scope() as session:
        feed = node_for(session, "feed", "PLone")
        first = graph.add_piece(session, kind="timer", host=feed, duration_minutes=5)
        second = graph.add_piece(session, kind="reset", host=first, cron="0 9 * * *")

        under = graph.consumption(session)[feed.playlist_pk]
        assert [one.id for one in under] == [first.id, second.id]
        assert graph.host_of(graph.nodes(session), second).id == feed.id


def test_a_piece_cannot_be_slotted_under_itself(db):
    build(db)
    with db.session_scope() as session:
        feed = node_for(session, "feed", "PLone")
        first = graph.add_piece(session, kind="timer", host=feed)
        second = graph.add_piece(session, kind="reset", host=first)

        with pytest.raises(graph.GraphError):
            graph.attach(session, first, second)


def test_a_box_is_not_a_piece(db):
    build(db)
    with db.session_scope() as session:
        feed = node_for(session, "feed", "PLone")
        source = node_for(session, "source", "UCone")

        with pytest.raises(graph.GraphError):
            graph.attach(session, source, feed)


def test_taking_out_a_middle_piece_closes_the_chain_up(db):
    """Taking one piece out is taking one piece out, not breaking the chain
    in half. What was below it would otherwise hang off a piece slotted into
    nothing, which is to say doing nothing at all."""
    build(db)
    with db.session_scope() as session:
        feed = node_for(session, "feed", "PLone")
        first = graph.add_piece(session, kind="timer", host=feed, duration_minutes=10)
        middle = graph.add_piece(session, kind="reset", host=first, cron="0 9 * * *")
        last = graph.add_piece(session, kind="reset", host=middle, cron="0 18 * * *")

        graph.detach(session, middle)

        under = graph.pieces_under(graph.nodes(session), feed.id)
        assert [one.id for one in under] == [first.id, last.id]
        assert middle.attached_to is None
        # And the feed still has a window, rather than losing the lot.
        assert graph.consumption(session)[feed.playlist_pk] != []


def test_deleting_a_middle_piece_does_not_take_the_rest_with_it(db):
    """The column carries a cascade on a database built from scratch, which
    would delete a Reset because a Timer above it was removed."""
    build(db)
    with db.session_scope() as session:
        feed = node_for(session, "feed", "PLone")
        first = graph.add_piece(session, kind="timer", host=feed)
        middle = graph.add_piece(session, kind="reset", host=first)
        last = graph.add_piece(session, kind="reset", host=middle, cron="0 18 * * *")
        ids = (feed.id, first.id, last.id)

    with db.session_scope() as session:
        graph.remove(session, middle.id)

    with db.session_scope() as session:
        feed_pk, first_pk, last_pk = ids
        assert session.get(GraphNode, last_pk) is not None
        under = graph.pieces_under(graph.nodes(session), feed_pk)
        assert [one.id for one in under] == [first_pk, last_pk]


def test_deleting_a_box_takes_its_pieces_with_it(db):
    """They describe that box. Left behind they would be slotted into
    nothing — litter on the canvas rather than a setting."""
    build(db)
    with db.session_scope() as session:
        feed = node_for(session, "feed", "PLone")
        graph.add_piece(session, kind="timer", host=feed)
        feed_pk = feed.id

    with db.session_scope() as session:
        graph.remove(session, feed_pk)

    with db.session_scope() as session:
        left = [one for one in graph.nodes(session) if one.kind in graph.JIGSAW]
        assert left == []


def test_a_piece_can_be_taken_back_out(db):
    build(db)
    with db.session_scope() as session:
        feed = node_for(session, "feed", "PLone")
        made = graph.add_piece(session, kind="reset", host=feed)

        assert graph.detach(session, made) is True
        assert graph.consumption(session) == {}


def test_a_switched_off_piece_is_no_window_at_all(db):
    build(db)
    with db.session_scope() as session:
        feed = node_for(session, "feed", "PLone")
        made = graph.add_piece(session, kind="reset", host=feed)
        assert graph.consumption(session)[feed.playlist_pk] != []

        made.enabled = False
        session.flush()
        assert graph.consumption(session) == {}


def test_a_trigger_can_no_longer_be_wired_to_a_feed(db):
    """That input is gone: when a feed may be read is slotted under it now."""
    build(db)
    with db.session_scope() as session:
        feed = node_for(session, "feed", "PLone")
        trigger = graph.add_trigger(session, trigger_kind="pulse")

        with pytest.raises(graph.GraphError):
            graph.connect(session, trigger, feed)


def test_a_shut_feed_says_it_is_shut_rather_than_going_quiet(canvas, db):
    """A feed that vanished would read as a feed that had gone."""
    from dealgo.models import Playlist as PlaylistModel, utcnow

    with db.session_scope() as session:
        graph.load(session)
        feed = next(n for n in graph.nodes(session) if n.kind == "feed")
        # A window that is never open: one minute a year, which has passed.
        made = graph.add_piece(session, kind="timer", host=feed, duration_minutes=1)
        # Sat down an hour ago, so the one minute is long spent.
        made.last_fired_at = utcnow() - dt.timedelta(hours=1)
        graph.add_piece(session, kind="reset", host=feed, cron="0 0 1 1 *")

    body = canvas.get("/feed").text
    assert "This feed is shut" in body
    assert "1 minute once you start reading" in body


# -- groups ----------------------------------------------------------------


def test_a_group_surrounds_whatever_is_drawn_inside_it(db):
    """Worked out from where things are rather than remembered: a node is in a
    group when the group is drawn around it, and dragging one out takes it
    out. Nothing is written when a node moves, so there is no membership to
    fall out of step with the drawing."""
    build(db)
    with db.session_scope() as session:
        source = node_for(session, "source", "UCone")
        feed = node_for(session, "feed", "PLone")
        source.x, source.y = 100, 100
        feed.x, feed.y = 900, 100
        session.flush()

        group = graph.add_group(session, x=50, y=50, width=400, height=300)
        assert [node.id for node in graph.inside(session, group)] == [source.id]


def test_moving_a_group_takes_what_it_surrounds_with_it(db):
    build(db)
    with db.session_scope() as session:
        source = node_for(session, "source", "UCone")
        source.x, source.y = 100, 100
        session.flush()
        group = graph.add_group(session, x=50, y=50, width=400, height=300)

        graph.move_group(session, group.id, 250, 150)
        assert (group.x, group.y) == (250, 150)
        assert (source.x, source.y) == (300, 200)  # the same 200, 100 along


def test_a_group_cannot_be_wired_to_anything(db):
    """It surrounds; it does not carry."""
    build(db)
    with db.session_scope() as session:
        group = graph.add_group(session)
        with pytest.raises(graph.GraphError):
            graph.connect(session, group, node_for(session, "feed", "PLone"))


def test_a_group_is_not_a_node_on_any_path(db):
    build(db)
    with db.session_scope() as session:
        source = node_for(session, "source", "UCone")
        feed = node_for(session, "feed", "PLone")
        graph.connect(session, source, feed)
        graph.add_group(session, x=0, y=0, width=2000, height=2000)

        assert len(graph.routes(session)) == 1


def test_a_group_can_be_given_away_and_loaded_back(db):
    """Channels travel as their YouTube ids, which mean the same thing on any
    machine. Feeds travel as names: a playlist id belongs to whoever owns the
    playlist and would be nobody else's to write to."""
    build(db)
    with db.session_scope() as session:
        source = node_for(session, "source", "UCone")
        feed = node_for(session, "feed", "PLone")
        source.x, source.y = 100, 100
        feed.x, feed.y = 400, 100
        session.flush()
        middle = graph.add_filter(session, label="No shorts", x=250, y=100)
        middle.skip_shorts = True
        graph.connect(session, source, middle)
        graph.connect(session, middle, feed)

        group = graph.add_group(session, label="My flow", x=50, y=50, width=600, height=300)
        packed = graph.export_group(session, group.id)

    assert packed["name"] == "My flow"
    assert {node["kind"] for node in packed["nodes"]} == {"source", "filter", "feed"}
    assert len(packed["wires"]) == 2
    # Relative to the group's own corner, so it lands where it is dropped.
    assert [node for node in packed["nodes"] if node["kind"] == "source"][0]["x"] == 50

    # Loaded into a second account, which has never heard of any of it.
    from dealgo.models import Channel as ChannelModel, Playlist as PlaylistModel
    from dealgo.services import accounts

    with db.session_scope() as session:
        friend = accounts.create_user(session, "friend", "their-password")
        session.flush()
        graph.import_group(session, packed, owner=friend.id, x=1000, y=1000)
        theirs_pk = friend.id

        theirs = graph.nodes(session, owner=theirs_pk)
        assert {node.kind for node in theirs} == {"group", "source", "filter", "feed"}
        assert len(graph.routes(session, owner=theirs_pk)) == 1

        # Their own copy of the channel, matched by its YouTube id.
        copied = session.scalar(
            select(ChannelModel).where(ChannelModel.owner_pk == theirs_pk)
        )
        assert copied.channel_id == "UCone"
        # And their own feed, made fresh rather than pointed at somebody else's.
        made = session.scalar(
            select(PlaylistModel).where(PlaylistModel.owner_pk == theirs_pk)
        )
        assert made.is_generic and made.title == "PLone"


def test_a_file_that_is_not_a_group_is_refused(db):
    build(db)
    with db.session_scope() as session:
        for rubbish in ({}, {"de_algo_group": 99}, []):
            with pytest.raises(graph.GraphError):
                graph.import_group(session, rubbish)


def test_a_wire_out_of_the_group_is_not_the_groups_to_give(db):
    """Half a wire in a file is a wire to nowhere on the other side."""
    build(db)
    with db.session_scope() as session:
        source = node_for(session, "source", "UCone")
        feed = node_for(session, "feed", "PLone")
        source.x, source.y = 100, 100
        feed.x, feed.y = 900, 100  # outside
        session.flush()
        graph.connect(session, source, feed)

        group = graph.add_group(session, x=50, y=50, width=300, height=300)
        packed = graph.export_group(session, group.id)

    assert [node["kind"] for node in packed["nodes"]] == ["source"]
    assert packed["wires"] == []


def test_a_group_can_be_made_moved_and_sized_from_the_canvas(canvas):
    added = canvas.post("/graph/nodes", data={"kind": "group", "x": 0, "y": 0}).json()
    group = only(added, "group")
    assert group["size"] == {"width": 520, "height": 300}
    assert group["note"] == "drag it to move everything in it"

    canvas.post(f"/graph/nodes/{group['id']}/resize", data={"width": 800, "height": 500})
    canvas.post(f"/graph/nodes/{group['id']}/move", data={"x": 30, "y": 40, "carries": "1"})

    moved = only(canvas.get("/api/graph").json(), "group")
    assert moved["size"] == {"width": 800, "height": 500}
    assert (moved["x"], moved["y"]) == (30, 40)


def test_a_group_is_exported_as_a_file_to_hand_over(canvas):
    added = canvas.post("/graph/nodes", data={"kind": "group", "title": "My flow"}).json()
    answer = canvas.get(f"/graph/nodes/{only(added, 'group')['id']}/export")

    assert answer.status_code == 200
    assert "de-algo-my-flow.json" in answer.headers["content-disposition"]
    assert answer.json()["de_algo_group"] == 1


def test_loading_a_group_adds_it_beside_what_is_already_here(canvas, db):
    from dealgo.models import Channel as ChannelModel

    packed = {
        "de_algo_group": 1,
        "name": "Theirs",
        "nodes": [
            {"ref": 0, "kind": "source", "x": 0, "y": 0,
             "channel_id": "UCgifted", "title": "A gift"},
            {"ref": 1, "kind": "feed", "x": 300, "y": 0, "title": "Their feed"},
        ],
        "wires": [[0, 1]],
    }
    before = len(canvas.get("/api/graph").json()["nodes"])

    answer = canvas.post(
        "/graph/groups",
        files={"file": ("group.json", json.dumps(packed), "application/json")},
        data={"x": "600", "y": "0"},
    )
    assert answer.status_code == 200
    drawn = answer.json()["nodes"]
    assert len(drawn) == before + 3  # the group, the channel, the feed

    with db.session_scope() as session:
        gifted = session.scalar(
            select(ChannelModel).where(ChannelModel.channel_id == "UCgifted")
        )
        # Paused until somebody wires it up and switches it on.
        assert gifted is not None and gifted.enabled is False


def test_a_file_that_is_not_json_at_all_is_refused(canvas):
    answer = canvas.post(
        "/graph/groups", files={"file": ("group.json", "not json", "application/json")}
    )
    assert answer.status_code == 400
    assert "readable JSON" in answer.json()["error"]


@needs_node
def test_a_group_can_be_pressed_like_any_other_node(canvas_report):
    """A group is drawn as a rectangle rather than a box, so it carries its
    own class. Looking only for the box's meant a group could not be pressed
    at all: not moved, not resized, not opened, and so not removed either."""
    targets = canvas_report["pressTargets"]
    assert targets["node"] == 4
    assert targets["group"] == 9
    assert targets["neither"] is None


def test_removing_a_group_leaves_what_it_surrounded(db):
    """It is a rectangle drawn around things, not a container holding them.
    Taking the rectangle away takes nothing else with it."""
    build(db)
    with db.session_scope() as session:
        source = node_for(session, "source", "UCone")
        source.x, source.y = 100, 100
        session.flush()
        group = graph.add_group(session, x=50, y=50, width=400, height=300)

        assert graph.remove(session, group.id) is True
        assert session.scalars(select(Channel)).all() != []
        assert [node.kind for node in graph.nodes(session)] == ["source", "feed"]


# -- more than one node for one channel ------------------------------------


def test_a_channel_already_watched_is_attached_rather_than_refused(canvas, db):
    """Two nodes for one channel is how it is wired down two paths that filter
    differently, which is worth being able to draw."""
    from dealgo.models import Channel as ChannelModel

    payload = canvas.post("/graph/nodes", data={"kind": "source", "source_kind": "reddit"}).json()
    empty = [node for node in boxes(payload, "source") if node["detail"] is None][0]

    saved = canvas.post(f"/graph/nodes/{empty['id']}", data={"handle": "UCone"}).json()
    assert [node["title"] for node in boxes(saved, "source")] == ["One Channel", "One Channel"]

    with db.session_scope() as session:
        # One channel, drawn twice — not two channels.
        assert len(session.scalars(select(ChannelModel)).all()) == 1


def test_the_same_path_twice_is_still_one_path(db):
    """Both nodes carry the channel's own feed links, so without care the
    same video would be weighed twice for one feed."""
    build(db)
    with db.session_scope() as session:
        first = node_for(session, "source", "UCone")
        feed = node_for(session, "feed", "PLone")
        graph.connect(session, first, feed)

        second = graph.add_source(session, channel=first.channel, x=60, y=400)
        session.flush()

        assert len(graph.routes(session)) == 1


def test_two_nodes_for_one_channel_can_filter_differently(db):
    build(db)
    with db.session_scope() as session:
        first = node_for(session, "source", "UCone")
        feed = node_for(session, "feed", "PLone")
        second = graph.add_source(session, channel=first.channel, x=60, y=400)
        middle = graph.add_filter(session, label="Trim")
        graph.connect(session, first, feed)
        graph.connect(session, second, middle)
        graph.connect(session, middle, feed)

        paths = graph.routes(session)
        assert len(paths) == 2
        assert sorted(len(path.filters) for path in paths) == [0, 1]


def test_taking_one_of_two_nodes_away_keeps_the_channel(db):
    """Taking a node off the canvas is rearranging the drawing, not saying
    goodbye to the channel."""
    build(db)
    with db.session_scope() as session:
        first = node_for(session, "source", "UCone")
        second = graph.add_source(session, channel=first.channel, x=60, y=400)
        session.flush()

        graph.remove(session, second.id)
        assert session.scalars(select(Channel)).all() != []

        # And the last one takes it with it, as it always did.
        graph.remove(session, first.id)
        assert session.scalars(select(Channel)).all() == []


# -- undo ------------------------------------------------------------------


@needs_node
def test_undo_keeps_the_last_few_actions_and_no_more(canvas_report):
    """Far enough to fix a mistake, not so far that it becomes a second
    history of the setup. The earliest fall off, not the latest."""
    assert canvas_report["undoStacked"] == ["the move", "the wire you drew"]
    assert canvas_report["undoCapped"]["held"] == canvas_report["undoDepth"]
    assert canvas_report["undoCapped"]["oldest"] == "step 20"


@needs_node
def test_undo_leaves_a_text_field_its_own_undo(canvas_report):
    """Ctrl+Z while typing a node's name is that field's undo. Taking it would
    make typing the one thing on this canvas that cannot be taken back."""
    assert canvas_report["undoTakesTheKey"]["canvas"] is True
    assert canvas_report["undoTakesTheKey"]["field"] is False


@needs_node
def test_undo_knows_what_appeared(canvas_report):
    """An added node or wire is found by comparing before with after, since
    the server answers with the whole graph rather than with what it made."""
    found = canvas_report["undoFinds"]
    assert found["node"] == 2
    assert found["wire"] == "edge:2"
    # Two at once is nobody's single action, so nothing is assumed.
    assert found["ambiguous"] is None


@needs_node
def test_dragging_one_of_several_picked_nodes_takes_the_rest(canvas_report):
    """Several nodes dragged by one of them keep their arrangement. A node
    picked on its own takes nothing, and a node that is not picked at all
    takes nothing either — however much else is."""
    travels = canvas_report["travelsWith"]
    assert travels["pickedPair"] == [2]
    assert travels["aloneNode"] == []
    assert travels["unpickedNode"] == []
    # A group still takes what it surrounds, picked or not.
    assert travels["group"] == [1, 2]


def test_the_canvas_offers_undo_and_says_how(canvas):
    body = canvas.get("/channels").text
    assert "data-graph-undo" in body
    assert "Ctrl+Z" in body
    assert "data-graph-picked" in body


@needs_node
def test_jumping_to_a_group_puts_it_in_the_middle_of_the_view(canvas_report):
    """The canvas goes on for ever, so a group dragged far enough out is one
    nobody can find by panning. Centring has to hold at any zoom: the pan is
    in screen pixels and the group's position is in the drawing's."""
    jump = canvas_report["jumpTo"]
    # A 400x200 group at (1000, 800) has its middle at (1200, 900); the middle
    # of an 800x600 canvas is (400, 300).
    assert jump["lifeSize"]["panX"] == 400 - 1200
    assert jump["lifeSize"]["panY"] == 300 - 900
    # Zoomed to 2x, the same point is twice as far into the drawing.
    assert jump["zoomedIn"]["panX"] == 400 - 1200 * 2
    assert jump["zoomedIn"]["panY"] == 300 - 900 * 2
    # And it is marked, so it can be told apart once it is on screen.
    assert jump["lifeSize"]["picked"] == [3]


def test_the_canvas_draws_its_groups_beneath_its_wires(canvas):
    """Three layers, bottom to top: groups, wires, nodes. A group is a
    background, so a wire crossing one is still the thing being pointed at."""
    body = canvas.get("/channels").text
    scene = body.split('data-graph-scene', 1)[1]
    assert scene.index("data-graph-groups") < scene.index("data-graph-wires")
    assert scene.index("data-graph-wires") < scene.index("data-graph-nodes")


def test_the_canvas_offers_a_way_back_to_each_group(canvas):
    body = canvas.get("/channels").text
    assert "data-graph-find" in body
    assert "data-graph-finder-list" in body
    assert "<h3>Groups</h3>" in body


@needs_node
def test_only_one_drawer_is_ever_out(canvas_report):
    """They share an edge now, and two drawers over one another is two drawers
    nobody asked for."""
    drawers = canvas_report["drawers"]
    assert drawers["afterPalette"] == {"palette": True, "finder": False}
    assert drawers["afterFinder"] == {"palette": False, "finder": True}


@needs_node
def test_pressing_a_slotted_piece_opens_the_piece(canvas_report):
    """Dragging one moves the assembly it is part of, which is right — but
    picking the dragged box on a press that went nowhere meant a slotted
    piece could not be opened at all. The feed opened instead."""
    assert canvas_report["pressingAPiece"]["opened"] == 8


@needs_node
def test_pieces_travel_with_the_box_they_are_slotted_into(canvas_report):
    """A piece has no position of its own worth keeping — it is drawn from
    its host's — so a box that moved and left its pieces behind was a box
    drawn without them."""
    went = canvas_report["following"]

    assert went["before"]["feed"] == {"left": "130px", "top": "88px"}
    assert went["before"]["timer"] == {"left": "130px", "top": "148px"}

    # Three hundred right and two hundred down, and the chain goes with it.
    assert went["after"]["feed"] == {"left": "430px", "top": "288px"}
    assert went["after"]["timer"] == {"left": "430px", "top": "348px"}
    assert went["after"]["reset"] == {"left": "430px", "top": "408px"}


@needs_node
def test_a_piece_goes_in_when_dropped_near_a_box_not_only_on_it(canvas_report):
    """Nobody aims at a one-pixel seam. Requiring the pointer to be over the
    box meant a piece dropped just below one — which is where it looks like
    it should go — lay on the canvas instead."""
    went = canvas_report["snapping"]

    assert went["onTheBox"] is True
    assert went["justUnder"] is True
    assert went["wellBelowAndAside"] is True
    # Not everywhere, though: a piece dropped across the canvas is a piece
    # somebody put down, not one they meant to slot in.
    assert went["farAway"] is False


@needs_node
def test_a_piece_is_drawn_tucked_under_the_box_it_is_slotted_into(canvas_report):
    """Stacked from the box's own coordinates. `offsetTop` is measured against
    whichever ancestor happens to be positioned, so a piece placed from it
    lands wherever that ancestor is rather than under its host."""
    where = canvas_report["slotting"]

    assert where["feed"] == {"left": "400px", "top": "100px", "piece": False}
    # Directly under it, and the second piece directly under the first.
    assert where["timer"] == {"left": "400px", "top": "160px", "piece": True}
    assert where["reset"] == {"left": "400px", "top": "220px", "piece": True}


@needs_node
def test_a_feed_has_one_input_and_not_two(canvas_report):
    """The second one took a trigger saying when the feed could be read. That
    is a Timer and a Reset slotted under it now, so the dot it arrived at has
    no reason to be there."""
    assert canvas_report["slotting"]["feedPorts"] == [
        "graph-port port-in carries-content"
    ]


@needs_node
def test_the_open_panel_follows_whichever_node_it_belongs_to(canvas_report):
    """Not only the node under the pointer: a group takes what it surrounds
    with it, and a selection takes the rest of itself, so the open one can be
    moving without being the one being dragged."""
    follows = canvas_report["panelFollows"]
    # Beside its node: 300 across plus the node's own width, and level with it.
    assert follows["itsNode"] == {"left": "530px", "top": "200px"}
    # Nothing open for that node, so nothing is moved.
    assert follows["anotherNode"] == {"left": None, "top": None}


# -- sources, and the tags they are grouped by -----------------------------


def test_a_channel_nodes_switch_still_pauses_the_channel(db):
    """The other kind answers for the channel behind it, as it always did."""
    from dealgo.models import Channel as ChannelModel
    from dealgo.web import app as web_app

    build(db)
    with db.session_scope() as session:
        source = node_for(session, "source", "UCone")
        web_app._switch(source, on=False)
        session.flush()
        assert session.scalars(select(ChannelModel)).one().enabled is False


def test_a_node_that_stands_for_nothing_yet_can_be_taken_away(canvas):
    """An empty source box names no source. Removing one should take the box
    and nothing else — there is nothing else."""
    added = canvas.post("/graph/nodes", data={"kind": "source", "source_kind": "reddit"}).json()
    empty = [node for node in boxes(added, "source") if node["detail"] is None][0]

    gone = canvas.post(f"/graph/nodes/{empty['id']}/delete")

    assert gone.status_code == 200
    assert empty["id"] not in [node["id"] for node in gone.json()["nodes"]]


@needs_node
def test_a_source_box_says_where_it_watches(canvas_report):
    """Not that it is a source box. Which of the kinds it is, is the thing
    somebody chose when they dragged it out — "Channel" said the same for a
    subreddit and a YouTube channel, and so said nothing at all."""
    heads = canvas_report["boxHeadings"]

    assert heads["reddit"] == "Reddit"
    assert heads["youtube"] == "YouTube"
    # Before it has been told which one, it still says which kind it is for.
    assert heads["emptyReddit"] == "Reddit"
    # And a box whose plugin has gone falls back to the plain word rather
    # than to nothing.
    assert heads["sourceWithNothingKnown"] == "Source"


@needs_node
def test_a_plugin_box_says_which_plugin_it_came_from(canvas_report):
    """More use than the word "plugin" over a name that is already its own."""
    assert canvas_report["boxHeadings"]["pluginBox"] == "YouTube"


@needs_node
def test_the_other_kinds_still_say_what_they_are(canvas_report):
    heads = canvas_report["boxHeadings"]

    assert heads["feed"] == "Feed"
    assert heads["pulse"] == "Pulse"


@needs_node
def test_removing_a_node_does_not_need_the_browsers_own_dialog(canvas_report):
    """`window.confirm` answers "no" and says nothing once a browser has been
    told to stop this page making dialogs — the tick that appears after a few
    in a row. A Remove button that asked with it did nothing at all: no
    question, no request, no error, for the rest of the tab's life. Everything
    else in the panel kept working, because nothing else asked first."""
    removing = canvas_report["removing"]

    assert removing["asked"] == "Stop watching A Channel?"
    assert removing["requests"] == ["/graph/nodes/7/delete"]


@needs_node
def test_removing_a_node_only_asks_where_something_is_at_stake(canvas_report):
    """An empty source box names no source. Asking "its history goes too" of
    a box with no history is a frightening question about nothing — and a
    question people answer no to, which is what it looked like to be unable
    to remove them."""
    asks = canvas_report["removalAsks"]
    assert asks["watchedChannel"].startswith("Stop watching")
    assert asks["feed"].startswith("Remove the feed")
    assert asks["emptyChannel"] == ""
    assert asks["filter"] == ""


def test_an_empty_channel_node_can_be_pointed_at_a_source_already_watched(canvas, db):
    """Needs no lookup and no credentials — and most of the time the channel
    is already on the Sources page anyway."""
    from dealgo.models import Channel as ChannelModel

    drawn = canvas.get("/api/graph").json()
    # Each carries its kind, so an empty box offers only the ones it could
    # actually be: a Subreddit box that offered a YouTube channel would be
    # offering something it cannot become.
    assert drawn["sources"] == [{"id": 1, "title": "One Channel", "kind": "youtube"}]

    added = canvas.post("/graph/nodes", data={"kind": "source", "source_kind": "reddit"}).json()
    empty = [node for node in boxes(added, "source") if node["detail"] is None][0]

    saved = canvas.post(
        f"/graph/nodes/{empty['id']}", data={"source_pk": "1"}
    ).json()
    pointed = [node for node in boxes(saved, "source") if node["id"] == empty["id"]][0]
    assert pointed["title"] == "One Channel"
    assert pointed["detail"] == "/channels/1"

    # One channel, drawn twice — not two channels.
    with db.session_scope() as session:
        assert len(session.scalars(select(ChannelModel)).all()) == 1


def test_a_source_that_is_not_yours_cannot_be_pointed_at(canvas):
    added = canvas.post("/graph/nodes", data={"kind": "source", "source_kind": "reddit"}).json()
    empty = [node for node in boxes(added, "source") if node["detail"] is None][0]

    answer = canvas.post(f"/graph/nodes/{empty['id']}", data={"source_pk": "999"})
    assert answer.status_code == 400
    assert "not here" in answer.json()["error"]


def test_a_node_that_already_names_a_channel_is_not_repointed(canvas):
    """Saving its panel is not a chance to quietly make it a different one."""
    named = only(canvas.get("/api/graph").json(), "source")
    saved = canvas.post(
        f"/graph/nodes/{named['id']}", data={"source_pk": "999", "label": "Renamed"}
    ).json()

    assert only(saved, "source")["title"] == "Renamed"


@needs_node
def test_searching_the_source_list_matches_the_way_the_app_does(canvas_report):
    """Every word, in any order, part of a word counting — the same as
    searching anywhere else here, so one habit serves the whole app."""
    searching = canvas_report["searching"]
    assert searching["partial"] is True
    assert searching["anyOrder"] is True
    assert searching["caseBlind"] is True
    assert searching["missingWord"] is False
    # Nothing typed, or only spaces, narrows nothing rather than everything.
    assert searching["empty"] is True
    assert searching["spacesOnly"] is True


# -- a source box is a box for one kind of somewhere -----------------------


def test_a_box_for_a_kind_nobody_provides_is_refused(canvas):
    """Refused where it is dragged out rather than discovered when nothing
    typed into it is ever accepted."""
    answer = canvas.post("/graph/nodes", data={"kind": "source", "source_kind": "gopher"})

    assert answer.status_code == 400
    assert "no source of that kind" in answer.json()["error"]


def test_a_source_box_with_no_kind_at_all_is_refused(canvas):
    """There is no generic source box. Dropping one with nothing to say what
    it watches would put a box on the canvas that can never be filled in."""
    answer = canvas.post("/graph/nodes", data={"kind": "source"})

    assert answer.status_code == 400


def test_a_box_reads_what_is_typed_the_way_its_own_kind_would(canvas, db, monkeypatch):
    """"python" is not a subreddit to anybody in general. It is one in a
    Subreddit box, which is the whole reason the box has a kind."""
    from dealgo.models import Channel as ChannelModel
    from dealgo.sources import syndication

    monkeypatch.setattr(
        syndication, "fetch", lambda _url, _http: syndication.Feed(title="r/python", items=[])
    )
    drawn = canvas.post(
        "/graph/nodes", data={"kind": "source", "source_kind": "reddit"}
    ).json()
    empty = [node for node in boxes(drawn, "source") if node["detail"] is None][0]

    answer = canvas.post(f"/graph/nodes/{empty['id']}", data={"handle": "python"})

    assert answer.status_code == 200
    with db.session_scope() as session:
        made = session.scalar(select(ChannelModel).where(ChannelModel.channel_id == "r/python"))
        assert made is not None and made.source_kind == "reddit"


def test_what_a_box_refuses_names_its_own_kind(canvas):
    drawn = canvas.post(
        "/graph/nodes", data={"kind": "source", "source_kind": "reddit"}
    ).json()
    empty = [node for node in boxes(drawn, "source") if node["detail"] is None][0]

    answer = canvas.post(f"/graph/nodes/{empty['id']}", data={"handle": "!!!"})

    assert answer.status_code == 400
    assert "Reddit" in answer.json()["error"]


def test_a_box_from_before_kinds_still_draws_and_can_be_pointed_somewhere(canvas, db):
    """Nothing makes one any more, but a canvas built earlier may hold one and
    must not become unreadable because of it."""
    from dealgo.models import GraphNode

    with db.session_scope() as session:
        session.add(GraphNode(kind="source", x=0, y=0))

    payload = canvas.get("/api/graph").json()
    stale = [
        node for node in boxes(payload, "source")
        if node["detail"] is None and node["asks"] is not None and node["asks"]["kind"] == ""
    ]

    assert len(stale) == 1
    assert stale[0]["title"] == "New channel"


def test_a_box_whose_plugin_was_switched_off_says_so(canvas, db, monkeypatch):
    """Rather than drawing a box that silently refuses everything typed in."""
    from dealgo.models import GraphNode

    with db.session_scope() as session:
        session.add(GraphNode(kind="source", source_kind="gopher", x=0, y=0))

    payload = canvas.get("/api/graph").json()
    lost = [
        node for node in boxes(payload, "source")
        if node["asks"] is not None and node["asks"]["kind"] == "gopher"
    ][0]

    assert lost["asks"]["known"] is False
