"""Wires drawn from boxes rather than stored against channels, and the tag boxes that went."""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text

from ..engine import get_engine

log = logging.getLogger(__name__)


def wires_belong_to_boxes() -> None:
    """Turn every channel-to-feed link into a wire drawn from a box.

    A source's wire used to be stored against its channel, so two boxes for
    one channel could not be told apart: wiring either drew a wire from both.
    Now a wire belongs to the box it came from.

    Every box for that channel gets one, because that is exactly what was on
    screen before — the canvas looks the same afterwards, and the boxes can
    now be unwired separately, which is the whole point.

    Runs once in effect: afterwards the edges exist, and the insert skips
    anything already there.
    """
    engine = get_engine()
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if not {"channel_playlist", "graph_node", "graph_edge"} <= tables:
        return

    with engine.begin() as connection:
        # Every (source box, feed box) pair the old links imply that has no wire yet.
        drawn = connection.execute(text("""
            SELECT DISTINCT s.id, f.id, s.owner_pk
            FROM channel_playlist cp
            JOIN graph_node s ON s.kind = 'source' AND s.channel_pk = cp.channel_pk
            JOIN graph_node f ON f.kind = 'feed'   AND f.playlist_pk = cp.playlist_pk
            WHERE NOT EXISTS (
                SELECT 1 FROM graph_edge e
                WHERE e.source_pk = s.id AND e.target_pk = f.id
            )
        """)).fetchall()
        for source_pk, target_pk, owner_pk in drawn:
            connection.execute(
                text(
                    "INSERT INTO graph_edge (owner_pk, source_pk, target_pk) "
                    "VALUES (:owner, :source, :target)"
                ),
                {"owner": owner_pk, "source": source_pk, "target": target_pk},
            )
    if drawn:
        log.info("drew %d source wire(s) from the boxes they belong to", len(drawn))


def retire_tag_nodes() -> None:
    """Take away the boxes that stood for a tag.

    A source box names one source now. A box that named a tag would survive
    the column being dropped as a box standing for nothing at all — an empty
    box nobody put there and nobody can fill in — so it goes with the feature
    it belonged to. Its wires go with it: an edge to a node that is not there
    is worse than no edge.

    Runs before the column is dropped, because afterwards there is no way
    left to tell which boxes those were.
    """
    engine = get_engine()
    inspector = inspect(engine)
    if "graph_node" not in set(inspector.get_table_names()):
        return
    if "tag" not in {c["name"] for c in inspector.get_columns("graph_node")}:
        return

    with engine.begin() as connection:
        # The source boxes that stood for a tag rather than a source.
        retiring = [
            row[0]
            for row in connection.execute(
                text("SELECT id FROM graph_node WHERE kind = 'source' AND tag IS NOT NULL")
            )
        ]
        if not retiring:
            return
        # Their wires first, then the boxes themselves.
        marks = ", ".join(str(int(one)) for one in retiring)
        connection.execute(
            text(f"DELETE FROM graph_edge WHERE source_pk IN ({marks}) OR target_pk IN ({marks})")
        )
        connection.execute(text(f"DELETE FROM graph_node WHERE id IN ({marks})"))
    log.info("removed %d tag node(s); source boxes name one source now", len(retiring))
