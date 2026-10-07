"""Wires that say what they carry, one of each kind between two boxes."""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.schema import CreateIndex, CreateTable

from ...models import Base
from ..engine import get_engine

log = logging.getLogger(__name__)


def rebuild_edge_uniqueness() -> None:
    """A wire is unique per kind now, not per pair of boxes.

    `graph_edge` carries UNIQUE(source_pk, target_pk) inside its CREATE
    TABLE, which only a rebuild can change — done as `video`'s was (see
    uniqueness.py for why each pragma is there).
    """
    engine = get_engine()
    inspector = inspect(engine)
    if "graph_edge" not in set(inspector.get_table_names()):
        return
    old = {c["name"] for c in inspector.get_unique_constraints("graph_edge")}
    if "uq_edge_source_target" not in old:
        return  # already rebuilt, or created on the new shape

    table = Base.metadata.tables["graph_edge"]
    wanted = {column.name for column in table.columns}
    columns = [c["name"] for c in inspector.get_columns("graph_edge") if c["name"] in wanted]
    names = ", ".join(columns)
    statements = [str(CreateTable(table).compile(engine))]
    statements += [str(CreateIndex(index).compile(engine)) for index in table.indexes]

    log.info("rebuilding graph_edge so a wire is unique per kind")
    raw = engine.raw_connection()
    try:
        raw.driver_connection.isolation_level = None  # type: ignore[union-attr]
        cursor = raw.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.execute("PRAGMA legacy_alter_table=ON")
        cursor.execute("BEGIN")
        try:
            cursor.execute("ALTER TABLE graph_edge RENAME TO graph_edge_old")
            cursor.execute(statements[0])
            cursor.execute(f"INSERT INTO graph_edge ({names}) SELECT {names} FROM graph_edge_old")
            cursor.execute("DROP TABLE graph_edge_old")
            for statement in statements[1:]:
                cursor.execute(statement)
            cursor.execute("COMMIT")
        except Exception:
            cursor.execute("ROLLBACK")
            raise
        finally:
            cursor.execute("PRAGMA legacy_alter_table=OFF")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    finally:
        raw.close()


def wires_say_what_they_carry() -> None:
    """Wires drawn before they said: worked out from the boxes at each end,
    the way the canvas used to work them out every time it drew one."""
    engine = get_engine()
    if "carries" not in {c["name"] for c in inspect(engine).get_columns("graph_edge")}:
        return
    kinds = "SELECT id FROM graph_node WHERE kind"
    with engine.begin() as connection:
        changed = 0
        for carries, where in (
            ("signal", f"source_pk IN ({kinds} = 'trigger')"),
            ("page", f"source_pk IN ({kinds} = 'feed') "
                     f"AND target_pk IN ({kinds} IN ('leaflet-feed', 'leaflet-link'))"),
            ("data", f"(source_pk IN ({kinds} = 'format') OR target_pk IN ({kinds} = 'format'))"),
        ):
            changed += connection.execute(text(
                f"UPDATE graph_edge SET carries = '{carries}' "
                f"WHERE (carries IS NULL OR carries = 'content') AND {where}"
            )).rowcount
        connection.execute(text("UPDATE graph_edge SET carries = 'content' WHERE carries IS NULL"))
    if changed:
        log.info("%d wire(s) now say what they carry", changed)


def rest_sources_give_data() -> None:
    """A REST API source gives data only now. An item wire out of one becomes
    a data wire where what it goes into takes data, and goes otherwise —
    into a feed, say, which data never fills."""
    engine = get_engine()
    if "carries" not in {c["name"] for c in inspect(engine).get_columns("graph_edge")}:
        return
    rest = (
        "SELECT n.id FROM graph_node n LEFT JOIN channel c ON c.id = n.channel_pk "
        "WHERE n.kind = 'source' AND COALESCE(c.source_kind, n.source_kind) = 'rest'"
    )
    takers = "SELECT id FROM graph_node WHERE kind IN " \
        "('filter', 'sort', 'tag', 'decay', 'expire', 'format', 'transform')"
    with engine.begin() as connection:
        moved = connection.execute(text(
            f"UPDATE OR IGNORE graph_edge SET carries = 'data' WHERE carries = 'content' "
            f"AND source_pk IN ({rest}) AND target_pk IN ({takers})"
        )).rowcount
        gone = connection.execute(text(
            f"DELETE FROM graph_edge WHERE carries = 'content' AND source_pk IN ({rest})"
        )).rowcount
    if moved or gone:
        log.info("REST sources give data: %d wire(s) now carry data, %d taken out", moved, gone)
