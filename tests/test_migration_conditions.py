"""Carrying a canvas whose boxes held their own rules onto pieces.

A Filter box used to hold every rule at once, which meant a canvas of boxes
all saying "Filter" and no way to tell them apart without opening each one.
A rule is a jigsaw piece now, one per condition.

These run against a database put back into that shape — the rule columns on
the box, and a plugin box that is one of its plugin's questions — which is
what an install created before this change actually looks like on disk.
"""

from __future__ import annotations

from sqlalchemy import select, text

from dealgo.models import Channel, GraphNode, Playlist
from dealgo.services import graph


def a_canvas(db):
    """Source → filter → feed, plus a sort box, and nothing slotted anywhere."""
    with db.session_scope() as session:
        session.add(Channel(channel_id="UCone", title="One"))
        session.add(Playlist(playlist_id="PLone", title="One"))
    with db.session_scope() as session:
        graph.load(session)
        source = next(n for n in graph.nodes(session) if n.kind == "source")
        feed = next(n for n in graph.nodes(session) if n.kind == "feed")
        box = graph.add_filter(session, label="Trim")
        sorting = graph.add_sort(session, label="Order")
        graph.connect(session, source, box)
        graph.connect(session, box, feed)
        for edge in graph.edges(session):
            if edge.source_pk == source.id and edge.target_pk == feed.id:
                graph.disconnect(session, edge.id)
        return box.id, sorting.id, feed.id


def as_it_was(db, node_pk: int, **columns) -> None:
    """Write the rule back onto the box, the way an older install has it.

    Raw SQL because the model has no such attributes any more: the point of
    the migration is that the columns are still there and the meaning has
    moved off them. The four content switches are gone from the table as
    well, so they are put back first — a fresh test database is built from the
    current models, and what an older install has on disk is what is wanted.
    """
    from sqlalchemy import inspect

    engine = db.get_engine()
    here = {c["name"] for c in inspect(engine).get_columns("graph_node")}
    with engine.begin() as connection:
        for name in columns:
            if name not in here:
                connection.execute(
                    text(f"ALTER TABLE graph_node ADD COLUMN {name} BOOLEAN")
                )
        said = ", ".join(f"{name} = :{name}" for name in columns)
        connection.execute(
            text(f"UPDATE graph_node SET {said} WHERE id = :pk"),
            {**columns, "pk": node_pk},
        )


def pieces_under(db, host_pk: int):
    with db.session_scope() as session:
        every = graph.nodes(session)
        return [(one.kind, one.id) for one in graph.pieces_under(every, host_pk)]


# -- a filter's own rules --------------------------------------------------


def test_each_rule_a_filter_held_becomes_a_piece_under_it(db):
    box_pk, _, _ = a_canvas(db)
    as_it_was(
        db, box_pk,
        title_include="cats", title_exclude="trailer",
        min_duration_sec=600, max_per_run=3,
    )

    db.init_db()

    kinds = [kind for kind, _ in pieces_under(db, box_pk)]
    assert kinds == ["has-words", "lacks-words", "longer-than", "at-most"]
    with db.session_scope() as session:
        found = {one.kind: one for one in graph.pieces_under(graph.nodes(session), box_pk)}
        assert found["has-words"].title_include == "cats"
        assert found["lacks-words"].title_exclude == "trailer"
        assert found["longer-than"].min_duration_sec == 600
        assert found["at-most"].max_per_run == 3


def test_the_converted_rules_still_narrow_the_same_path(db):
    """The whole point: the canvas looks different and does the same thing."""
    box_pk, _, _ = a_canvas(db)
    as_it_was(db, box_pk, min_duration_sec=1200)

    db.init_db()

    with db.session_scope() as session:
        assert graph.routes(session)[0].effective()["min_duration_sec"] == 1200


def test_the_box_stops_carrying_the_rule_itself(db):
    """Two places to read one rule would be one place too many."""
    box_pk, _, _ = a_canvas(db)
    as_it_was(db, box_pk, title_include="cats")

    db.init_db()

    with db.get_engine().begin() as connection:
        left = connection.execute(
            text("SELECT title_include FROM graph_node WHERE id = :pk"), {"pk": box_pk}
        ).scalar()
    assert left is None


def test_converting_twice_does_not_double_the_pieces(db):
    """Every start runs the migrations, so a second run has to find nothing
    left to do."""
    box_pk, _, _ = a_canvas(db)
    as_it_was(db, box_pk, title_include="cats")

    db.init_db()
    db.init_db()

    assert [kind for kind, _ in pieces_under(db, box_pk)] == ["has-words"]


def test_a_filter_that_said_nothing_gets_no_pieces(db):
    """It narrowed nothing before and narrows nothing now."""
    box_pk, _, _ = a_canvas(db)

    db.init_db()

    assert pieces_under(db, box_pk) == []


# -- the four content switches --------------------------------------------


def test_the_content_switches_become_a_youtube_box_on_the_path(db):
    """They were never general. A Short, a premiere and a community post are
    YouTube's own distinctions, so they belong to the plugin that knows what
    those words mean."""
    box_pk, _, feed_pk = a_canvas(db)
    as_it_was(db, box_pk, skip_shorts=1, skip_live=1)

    db.init_db()

    with db.session_scope() as session:
        every = graph.nodes(session)
        box = next(one for one in every if one.kind == "plugin")
        assert box.plugin_ref == "youtube"
        assert [one.plugin_ref for one in graph.pieces_under(every, box.id)] == [
            "youtube:no-shorts", "youtube:no-live",
        ]

        # Wired in after the filter, keeping what the filter reached.
        drawn = {(edge.source_pk, edge.target_pk) for edge in graph.edges(session)}
        assert (box_pk, box.id) in drawn
        assert (box.id, feed_pk) in drawn
        assert (box_pk, feed_pk) not in drawn


def test_a_filter_that_said_nothing_about_content_gets_no_youtube_box(db):
    box_pk, _, _ = a_canvas(db)
    as_it_was(db, box_pk, title_include="cats")

    db.init_db()

    with db.session_scope() as session:
        assert [one for one in graph.nodes(session) if one.kind == "plugin"] == []


def test_the_youtube_box_holds_what_the_switch_held(db):
    """Asked of the plugin rather than of the host, and answering the same."""
    from dealgo.plugins import registry

    found = registry.current()
    item = {"source": "youtube", "kind": "video", "is_short": True, "live": ""}

    assert found.keeps("youtube:no-shorts", item, {}) is False
    assert found.keeps("youtube:no-shorts", {**item, "is_short": False}, {}) is True


# -- a sort box -----------------------------------------------------------


def test_what_a_sort_box_ordered_by_becomes_an_order_piece(db):
    _, sort_pk, _ = a_canvas(db)
    as_it_was(db, sort_pk, sort_by="duration", sort_dir="asc")

    db.init_db()

    with db.session_scope() as session:
        piece = graph.pieces_under(graph.nodes(session), sort_pk)[0]
        assert piece.kind == "order"
        assert piece.sort_by == "duration" and piece.sort_dir == "asc"

    with db.get_engine().begin() as connection:
        left = connection.execute(
            text("SELECT sort_by FROM graph_node WHERE id = :pk"), {"pk": sort_pk}
        ).scalar()
    assert left is None


def test_a_sort_box_converted_once_is_not_converted_again(db):
    _, sort_pk, _ = a_canvas(db)
    as_it_was(db, sort_pk, sort_by="views", sort_dir="desc")

    db.init_db()
    db.init_db()

    assert [kind for kind, _ in pieces_under(db, sort_pk)] == ["order"]


# -- a plugin box that was one of its plugin's questions ------------------


def test_an_old_plugin_box_becomes_a_box_for_the_plugin_and_a_condition(db):
    """A plugin box used to *be* the question. Now the box is the plugin and
    the questions are pieces, which is what lets one box ask three things."""
    a_canvas(db)
    with db.session_scope() as session:
        old = graph.add_plugin_node(session, ref="shape:not-shouting", label="Not shouting")
        old.plugin_settings = '{"most": "70"}'
        session.flush()
        old_pk = old.id

    db.init_db()

    with db.session_scope() as session:
        box = session.get(GraphNode, old_pk)
        assert box.kind == "plugin" and box.plugin_ref == "shape"
        assert box.plugin_settings is None
        piece = graph.pieces_under(graph.nodes(session), old_pk)[0]
        assert piece.kind == "rule"
        assert piece.plugin_ref == "shape:not-shouting"
        # Whatever its fields were set to travels with the question.
        assert piece.plugin_settings == '{"most": "70"}'


def test_a_plugin_box_already_converted_is_left_alone(db):
    a_canvas(db)
    with db.session_scope() as session:
        box = graph.add_plugin_node(session, ref="shape")
        graph.add_piece(session, kind="rule", host=box, ref="shape:has-words")
        box_pk = box.id

    db.init_db()

    assert [kind for kind, _ in pieces_under(db, box_pk)] == ["rule"]


def test_a_box_keeps_its_wires_through_the_conversion(db):
    """It stays where it was and keeps what it was joined to: the canvas has
    to look the same afterwards."""
    _, _, feed_pk = a_canvas(db)
    with db.session_scope() as session:
        source = next(one for one in graph.nodes(session) if one.kind == "source")
        old = graph.add_plugin_node(session, ref="shape:has-words")
        graph.connect(session, source, old)
        graph.connect(session, old, session.get(GraphNode, feed_pk))
        old_pk, source_pk = old.id, source.id

    db.init_db()

    with db.session_scope() as session:
        drawn = {(edge.source_pk, edge.target_pk) for edge in graph.edges(session)}
    assert (source_pk, old_pk) in drawn and (old_pk, feed_pk) in drawn
