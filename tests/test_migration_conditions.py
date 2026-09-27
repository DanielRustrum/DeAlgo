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


def test_the_content_switches_become_youtube_conditions_under_the_same_box(db):
    """They were never general. A Short, a premiere and a community post are
    YouTube's own distinctions, so they belong to the plugin that knows what
    those words mean — and they were that box's rules, so they stay that box's
    rules. Nothing is rewired."""
    box_pk, _, feed_pk = a_canvas(db)
    as_it_was(db, box_pk, skip_shorts=1, skip_live=1)

    db.init_db()

    with db.session_scope() as session:
        every = graph.nodes(session)
        assert [one.plugin_ref for one in graph.pieces_under(every, box_pk)] == [
            "youtube:no-shorts", "youtube:no-live",
        ]
        drawn = {(edge.source_pk, edge.target_pk) for edge in graph.edges(session)}
        assert (box_pk, feed_pk) in drawn


def test_a_filter_that_said_nothing_about_content_gets_no_youtube_condition(db):
    box_pk, _, _ = a_canvas(db)
    as_it_was(db, box_pk, title_include="cats")

    db.init_db()

    assert [kind for kind, _ in pieces_under(db, box_pk)] == ["has-words"]


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


def a_plugin_box(db, ref: str, settings: str | None = None) -> int:
    """A plugin box of whichever shape, the way an older install has it.

    Raw SQL because there is no such kind any more: a plugin has no box, so
    the service has nothing that makes one.
    """
    with db.get_engine().begin() as connection:
        return int(
            connection.execute(
                text(
                    "INSERT INTO graph_node (owner_pk, kind, enabled, label, x, y, "
                    "plugin_ref, plugin_settings) "
                    "VALUES (NULL, 'plugin', 1, '', 420, 40, :ref, :said)"
                ),
                {"ref": ref, "said": settings},
            ).lastrowid
        )


def test_a_plugin_box_that_was_one_question_becomes_a_filter_carrying_it(db):
    """A plugin box used to *be* the question. A plugin has no box now: it
    adds to what a Filter can be told, so the box becomes a Filter and the
    question becomes a condition under it."""
    a_canvas(db)
    old_pk = a_plugin_box(db, "shape:not-shouting", '{"most": "70"}')

    db.init_db()

    with db.session_scope() as session:
        box = session.get(GraphNode, old_pk)
        assert box.kind == "filter"
        assert box.plugin_ref is None and box.plugin_settings is None
        piece = graph.pieces_under(graph.nodes(session), old_pk)[0]
        assert piece.kind == "rule"
        assert piece.plugin_ref == "shape:not-shouting"
        # Whatever its fields were set to travels with the question.
        assert piece.plugin_settings == '{"most": "70"}'


def test_a_plugin_box_that_stood_for_the_plugin_becomes_a_filter_too(db):
    """The second shape, from the one release that had it: the box was the
    plugin and its questions were already pieces. They stay where they are."""
    a_canvas(db)
    old_pk = a_plugin_box(db, "shape")
    with db.get_engine().begin() as connection:
        connection.execute(
            text(
                "INSERT INTO graph_node (owner_pk, kind, enabled, label, x, y, "
                "attached_to, plugin_ref) "
                "VALUES (NULL, 'rule', 1, '', 420, 100, :host, 'shape:has-words')"
            ),
            {"host": old_pk},
        )

    db.init_db()

    with db.session_scope() as session:
        assert session.get(GraphNode, old_pk).kind == "filter"
        assert [kind for kind, _ in pieces_under(db, old_pk)] == ["rule"]


def test_a_box_keeps_its_wires_through_the_conversion(db):
    """It stays where it was and keeps what it was joined to: the canvas has
    to look the same afterwards."""
    _, _, feed_pk = a_canvas(db)
    with db.session_scope() as session:
        source_pk = next(one for one in graph.nodes(session) if one.kind == "source").id
    old_pk = a_plugin_box(db, "shape:has-words")
    with db.get_engine().begin() as connection:
        for start, end in ((source_pk, old_pk), (old_pk, feed_pk)):
            connection.execute(
                text(
                    "INSERT INTO graph_edge (owner_pk, source_pk, target_pk) "
                    "VALUES (NULL, :start, :end)"
                ),
                {"start": start, "end": end},
            )

    db.init_db()

    with db.session_scope() as session:
        drawn = {(edge.source_pk, edge.target_pk) for edge in graph.edges(session)}
    assert (source_pk, old_pk) in drawn and (old_pk, feed_pk) in drawn


# -- folding the pair back together ---------------------------------------
#
# One release put a plugin's condition in a box of its own, wired in after the
# Filter whose switches it came from. Converting that box to a Filter would
# leave two boxes saying "Filter" in a row where one would do.


def a_pair(db, *, extra_wire: bool = False, on_the_filter: bool = False):
    """Filter → plugin box → feed, the shape that release produced."""
    box_pk, _, feed_pk = a_canvas(db)
    if on_the_filter:
        with db.session_scope() as session:
            graph.add_piece(session, kind="has-words", host=session.get(GraphNode, box_pk))
    # The box that stood for the plugin, with its question already a piece.
    later = a_plugin_box(db, "shape")
    with db.get_engine().begin() as connection:
        connection.execute(
            text(
                "INSERT INTO graph_node (owner_pk, kind, enabled, label, x, y, "
                "attached_to, plugin_ref) "
                "VALUES (NULL, 'rule', 1, '', 0, 0, :host, 'shape:not-shouting')"
            ),
            {"host": later},
        )
        # The filter reached the feed; now it reaches the new box instead.
        connection.execute(
            text("UPDATE graph_edge SET target_pk = :later WHERE source_pk = :box"),
            {"later": later, "box": box_pk},
        )
        connection.execute(
            text(
                "INSERT INTO graph_edge (owner_pk, source_pk, target_pk) "
                "VALUES (NULL, :start, :end)"
            ),
            {"start": later, "end": feed_pk},
        )
        if extra_wire:
            # Something else reaches the second box as well, so folding it into
            # the first would put that path through the first box's conditions.
            source_pk = connection.execute(
                text("SELECT id FROM graph_node WHERE kind = 'source'")
            ).scalar()
            connection.execute(
                text(
                    "INSERT INTO graph_edge (owner_pk, source_pk, target_pk) "
                    "VALUES (NULL, :start, :end)"
                ),
                {"start": source_pk, "end": later},
            )
    return box_pk, later, feed_pk


def test_the_pair_is_folded_back_into_one_filter(db):
    box_pk, later_pk, feed_pk = a_pair(db)

    db.init_db()

    with db.session_scope() as session:
        assert session.get(GraphNode, later_pk) is None
        assert [one.plugin_ref for one in graph.pieces_under(graph.nodes(session), box_pk)] == [
            "shape:not-shouting"
        ]
        drawn = {(edge.source_pk, edge.target_pk) for edge in graph.edges(session)}
    # What the second box reached, the first reaches now.
    assert (box_pk, feed_pk) in drawn
    assert not any(later_pk in pair for pair in drawn)


def test_a_box_something_else_reaches_is_left_where_it_is(db):
    """Folding it would put that other path through the first box's
    conditions, which is a rewired graph rather than a tidier one."""
    box_pk, later_pk, _ = a_pair(db, extra_wire=True)

    db.init_db()

    with db.session_scope() as session:
        assert session.get(GraphNode, later_pk).kind == "filter"
        assert pieces_under(db, box_pk) == []


def test_a_filter_that_carries_its_own_conditions_is_not_folded_into(db):
    """Two chains of conditions are two boxes' worth of narrowing, and the
    order they are read in is part of what they mean."""
    box_pk, later_pk, _ = a_pair(db, on_the_filter=True)

    db.init_db()

    with db.session_scope() as session:
        assert session.get(GraphNode, later_pk).kind == "filter"
        assert [kind for kind, _ in pieces_under(db, box_pk)] == ["has-words"]


def test_folding_twice_changes_nothing(db):
    box_pk, later_pk, feed_pk = a_pair(db)

    db.init_db()
    db.init_db()

    with db.session_scope() as session:
        assert [one.plugin_ref for one in graph.pieces_under(graph.nodes(session), box_pk)] == [
            "shape:not-shouting"
        ]
        drawn = [(edge.source_pk, edge.target_pk) for edge in graph.edges(session)]
    assert drawn.count((box_pk, feed_pk)) == 1
