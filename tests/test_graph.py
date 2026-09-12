"""The Configuration canvas: what is wired to what, and what gets through.

The graph is the truth about routing. These cover the part a list of targets
could never express — one channel reaching two feeds down paths that filter
differently — and the rules that keep the canvas honest.
"""

from __future__ import annotations

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


def test_only_filter_boxes_can_be_deleted_from_the_canvas(db):
    """A source box stands for a channel; deleting that is not a keystroke."""
    build(db)
    with db.session_scope() as session:
        graph.load(session)
        with pytest.raises(graph.GraphError):
            graph.remove(session, node_for(session, "source", "UCone").id)

        middle = graph.add_filter(session)
        assert graph.remove(session, middle.id) is True


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
