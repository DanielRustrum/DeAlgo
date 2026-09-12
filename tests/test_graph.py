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

import pytest
from sqlalchemy import select

from dealgo.models import Channel, GraphEdge, GraphNode, Playlist
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


def test_a_source_to_feed_wire_is_the_link_itself(db):
    """Drawn on the canvas, it shows up on the channel's own page too."""
    build(db)
    with db.session_scope() as session:
        graph.load(session)
        source = node_for(session, "source", "UCone")
        feed = node_for(session, "feed", "PLone")
        edge = graph.connect(session, source, feed)

        assert edge is None                       # a link, not an edge
        assert source.channel.playlists == [feed.playlist]


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


def test_a_filter_node_overrides_only_what_it_sets(db):
    """The rest stays whatever the channel said — which is what makes it an
    override rather than a second set of settings to keep in step."""
    build(db)
    with db.session_scope() as session:
        graph.load(session)
        source = node_for(session, "source", "UCone")
        source.channel.skip_shorts = True
        source.channel.title_exclude = "trailer"

        middle = graph.add_filter(session, label="Shorts welcome")
        middle.skip_shorts = False
        graph.connect(session, source, middle)
        graph.connect(session, middle, node_for(session, "feed", "PLone"))

    with db.session_scope() as session:
        rules = graph.routes(session)[0].effective()
        assert rules["skip_shorts"] is False          # the node's word
        assert rules["title_exclude"] == "trailer"    # the channel's, untouched


def test_one_channel_can_reach_two_feeds_by_different_rules(db):
    build(db, feeds=("PLall", "PLlong"))
    with db.session_scope() as session:
        graph.load(session)
        source = node_for(session, "source", "UCone")
        graph.connect(session, source, node_for(session, "feed", "PLall"))

        only_long = graph.add_filter(session, label="Long ones")
        only_long.min_duration_sec = 1200
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
        first.max_per_run = 5
        second = graph.add_filter(session, label="Second")
        second.max_per_run = 2
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
    from dealgo.youtube.api import VideoDetails
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
        gate.min_duration_sec = 1200
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


def test_a_trigger_can_only_feed_a_channel(db):
    build(db)
    with db.session_scope() as session:
        trigger = graph.add_trigger(session, trigger_kind="schedule")
        feed = node_for(session, "feed", "PLone")
        source = node_for(session, "source", "UCone")

        with pytest.raises(graph.GraphError):
            graph.connect(session, trigger, feed)
        with pytest.raises(graph.GraphError):
            graph.connect(session, source, trigger)
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
    assert [wire["kind"] for wire in wires] == ["link"]


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


def test_a_filter_keeps_the_rules_it_is_given_and_inherits_the_blanks(canvas, db):
    graph_now = canvas.post("/graph/nodes", data={"kind": "filter", "title": "Trim"}).json()
    node_id = only(graph_now, "filter")["id"]

    answer = canvas.post(
        f"/graph/nodes/{node_id}",
        data={"label": "Long ones", "skip_shorts": "1", "min_duration_sec": "600",
              "skip_live": "", "title_include": "  "},
    )
    saved = only(answer.json(), "filter")
    assert saved["title"] == "Long ones"
    assert saved["overrides"] == {"skip_shorts": True, "min_duration_sec": 600}

    with db.session_scope() as session:
        node = session.get(GraphNode, node_id)
        assert node.skip_shorts is True
        assert node.skip_live is None  # blank means "leave it to the channel"
        assert node.title_include is None


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


def test_both_kinds_of_wire_come_out_the_same_way(canvas):
    graph_now = canvas.post("/graph/nodes", data={"kind": "filter", "title": "Trim"}).json()
    source, feed, middle = only(graph_now, "source"), only(graph_now, "feed"), only(graph_now, "filter")

    canvas.post("/graph/connect", data={"source": source["id"], "target": feed["id"]})
    canvas.post("/graph/connect", data={"source": source["id"], "target": middle["id"]})
    wires = {wire["kind"]: wire["id"] for wire in canvas.get("/api/graph").json()["wires"]}

    left = canvas.post("/graph/disconnect", data={"wire": wires["link"]}).json()["wires"]
    assert [wire["kind"] for wire in left] == ["edge"]

    nothing = canvas.post("/graph/disconnect", data={"wire": wires["edge"]}).json()["wires"]
    assert nothing == []


def test_following_an_item_says_where_it_went_and_why(canvas, db):
    graph_now = canvas.get("/api/graph").json()
    source, feed = only(graph_now, "source"), only(graph_now, "feed")
    canvas.post("/graph/connect", data={"source": source["id"], "target": feed["id"]})

    trace = canvas.get("/graph/trace/1").json()
    assert trace["item"]["title"] == "A clip"
    assert len(trace["steps"]) == 1
    assert trace["steps"][0]["accepted"] is True
    assert trace["steps"][0]["nodes"] == [source["id"], feed["id"]]

    with db.session_scope() as session:
        session.get(Channel, 1).skip_videos = True

    blocked = canvas.get("/graph/trace/1").json()["steps"][0]
    assert blocked["accepted"] is False
    assert "video" in blocked["reason"].lower()


def test_following_an_item_lights_the_wires_it_actually_travelled(canvas):
    """The trace names wires by the ids the canvas draws them under. Made-up
    ids would light nothing, and look exactly like a path nobody took."""
    added = canvas.post("/graph/nodes", data={"kind": "filter", "title": "Trim"}).json()
    source, feed, middle = only(added, "source"), only(added, "feed"), only(added, "filter")
    canvas.post("/graph/connect", data={"source": source["id"], "target": middle["id"]})
    canvas.post("/graph/connect", data={"source": middle["id"], "target": feed["id"]})

    drawn = {wire["id"] for wire in canvas.get("/api/graph").json()["wires"]}
    step = canvas.get("/graph/trace/1").json()["steps"][0]

    assert step["nodes"] == [source["id"], middle["id"], feed["id"]]
    assert len(step["wires"]) == 2
    assert set(step["wires"]) <= drawn, "the trace named wires that are not on the canvas"


def test_following_an_item_nobody_owns_is_a_flat_no(canvas):
    assert canvas.get("/graph/trace/999").status_code == 404


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

    payload = canvas.post("/graph/nodes", data={"kind": "source", "x": 40, "y": 60}).json()
    empty = [node for node in boxes(payload, "source") if node["detail"] is None]
    assert len(empty) == 1
    assert empty[0]["title"] == "New channel"
    assert "@handle" in empty[0]["note"]
    assert (empty[0]["x"], empty[0]["y"]) == (40, 60)

    # It routes nothing and breaks nothing while it waits.
    assert canvas.get("/api/graph").status_code == 200
    with db.session_scope() as session:
        assert len(session.scalars(select(ChannelModel)).all()) == 1  # only the fixture's


def test_a_channel_that_youtube_does_not_have_is_refused_with_a_reason(canvas):
    payload = canvas.post("/graph/nodes", data={"kind": "source"}).json()
    empty = [node for node in boxes(payload, "source") if node["detail"] is None][0]

    answer = canvas.post(f"/graph/nodes/{empty['id']}", data={"handle": "@nobody"})
    assert answer.status_code == 400
    assert answer.json()["error"]  # whatever YouTube said, said in words


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


# -- triggers over HTTP ----------------------------------------------------


def test_a_trigger_can_be_added_and_says_which_kind_it_is(canvas):
    payload = canvas.post("/graph/nodes", data={"kind": "pulse"}).json()
    box = only(payload, "trigger")
    assert box["trigger"]["kind"] == "pulse"
    assert box["note"] == "every 60 minutes"  # the default, until it is changed

    both = canvas.post("/graph/nodes", data={"kind": "schedule"}).json()
    assert [b["trigger"]["kind"] for b in boxes(both, "trigger")] == ["pulse", "schedule"]
    assert boxes(both, "trigger")[1]["note"] == "0 9 * * *"


def test_a_trigger_that_is_neither_is_refused(canvas):
    answer = canvas.post("/graph/nodes", data={"kind": "whenever"})
    assert answer.status_code == 400
    assert "no whenever box" in answer.json()["error"]


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
    assert "account's sync settings" in source["polled"]

    wired = canvas.post(
        "/graph/connect", data={"source": trigger["id"], "target": source["id"]}
    ).json()
    assert only(wired, "source")["polled"] == "Polled by a pulse every 60 minutes."


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
        "Polled by a pulse every 60 minutes and a schedule on “0 9 * * *”."
    )


def test_a_trigger_cannot_be_wired_to_a_feed(canvas):
    added = canvas.post("/graph/nodes", data={"kind": "pulse"}).json()
    answer = canvas.post(
        "/graph/connect",
        data={"source": only(added, "trigger")["id"], "target": only(added, "feed")["id"]},
    )
    assert answer.status_code == 400
    assert "cannot feed" in answer.json()["error"]


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


def test_the_palette_offers_every_kind_of_box(canvas):
    body = canvas.get("/channels").text
    for kind in ("source", "feed", "filter", "pulse", "schedule"):
        assert f'data-palette="{kind}"' in body, f"the palette has no {kind}"


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
def test_a_filter_shows_only_what_it_actually_decides(canvas_report):
    assert canvas_report["keepsOnlyRealOverrides"] == {"skip_shorts": True, "min_duration_sec": 600}


@needs_node
def test_a_wire_runs_from_one_box_to_the_other(canvas_report):
    assert canvas_report["curve"]["starts"] and canvas_report["curve"]["ends"]


@needs_node
def test_each_box_says_which_of_the_four_it_is(canvas_report):
    assert canvas_report["labels"] == ["Trigger", "Channel", "Filter", "Feed"]


@needs_node
def test_a_schedules_clock_survives_the_trip_to_utc_and_back(canvas_report):
    """It is stored in UTC and typed on the viewer's clock, so the conversion
    runs on every save. An hour lost in it would move somebody's schedule."""
    assert canvas_report["clockRoundTrip"] == canvas_report["clockRoundTripWanted"]
    assert canvas_report["clockReads"] == len("09:00")


@needs_node
def test_the_verdict_counts_the_paths_and_gives_the_reasons(canvas_report):
    assert "got into 1 of 2 paths" in canvas_report["landedSome"]
    assert "Short (30s)" in canvas_report["landedSome"]
    assert "nowhere to go" in canvas_report["landedNowhere"]
    # Two paths, one reason: saying it twice reads as two different problems.
    assert canvas_report["saysEachReasonOnce"].count("Short (30s)") == 1
