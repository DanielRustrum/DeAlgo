"""Uniqueness that follows the owner, so two accounts may follow the same thing."""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.schema import CreateIndex, CreateTable

from ...models import Base
from ..engine import get_engine

log = logging.getLogger(__name__)


# Uniqueness that used to be global and is now per owner. Each was declared
# `unique=True, index=True`, so SQLite holds it as a plain index that can be
# swapped — no table rebuild for these three.
_REPLACED_INDEXES: tuple[tuple[str, str, str], ...] = (
    ("channel", "ix_channel_channel_id", "channel_id"),
    ("playlist", "ix_playlist_playlist_id", "playlist_id"),
)


def scope_uniqueness_to_owners() -> None:
    """Two accounts may track the same channel, so uniqueness follows the owner.

    COALESCE stands in for the implicit owner, because SQL counts NULLs as
    distinct and a plain UNIQUE(owner_pk, …) would let duplicates through.
    """
    engine = get_engine()
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    with engine.begin() as connection:
        for table, old_index, column in _REPLACED_INDEXES:
            if table not in tables:
                continue
            names = {index["name"] for index in inspector.get_indexes(table)}
            if old_index in names:
                connection.execute(text(f"DROP INDEX {old_index}"))
                # Keep a non-unique one: the column is still looked up by value.
                connection.execute(text(f"CREATE INDEX {old_index} ON {table} ({column})"))
                log.info("uniqueness on %s.%s now follows the owner", table, column)
            wanted = f"uq_{table}_owner_{column}"
            if wanted not in names:
                connection.execute(
                    text(
                        f"CREATE UNIQUE INDEX IF NOT EXISTS {wanted}"
                        f" ON {table} (COALESCE(owner_pk, 0), {column})"
                    )
                )


def rebuild_video_uniqueness() -> None:
    """The one uniqueness rule that cannot be swapped.

    `video` carries UNIQUE(video_id) inside its CREATE TABLE, and SQLite can
    only change that by building the table again.

    Two pragmas make this safe, and both are needed:

    * `legacy_alter_table=ON`, because since SQLite 3.25 a RENAME rewrites
      other tables' references to follow it — `placement` would end up
      pointing at `video_old`, and every one of its rows would be left
      dangling the moment that table was dropped.
    * `foreign_keys=OFF`, so the copy is not checked row by row against a
      table that is mid-rebuild.

    Neither takes effect inside a transaction, which is why this works the
    driver directly rather than going through SQLAlchemy's transactions.
    """
    engine = get_engine()
    inspector = inspect(engine)
    if "video" not in set(inspector.get_table_names()):
        return
    if "uq_video_video_id" not in {c["name"] for c in inspector.get_unique_constraints("video")}:
        return  # already rebuilt, or created on the new shape

    table = Base.metadata.tables["video"]
    # Only what both shapes have: an old database can carry columns the model
    # dropped long ago, and the new table has ones it has never seen.
    wanted = {column.name for column in table.columns}
    columns = [c["name"] for c in inspector.get_columns("video") if c["name"] in wanted]
    names = ", ".join(columns)
    statements = [str(CreateTable(table).compile(engine))]
    statements += [str(CreateIndex(index).compile(engine)) for index in table.indexes]

    log.info("rebuilding video so its uniqueness follows the owner")
    raw = engine.raw_connection()
    try:
        # Manual transactions, so the pragmas land outside one. The pooled
        # wrapper does not declare the driver's own attribute, which is what
        # this reaches through to.
        raw.driver_connection.isolation_level = None  # type: ignore[union-attr]
        cursor = raw.cursor()
        cursor.execute("PRAGMA foreign_keys=OFF")
        cursor.execute("PRAGMA legacy_alter_table=ON")
        cursor.execute("BEGIN")
        try:
            cursor.execute("ALTER TABLE video RENAME TO video_old")
            cursor.execute(statements[0])       # the table, without its indexes
            cursor.execute(f"INSERT INTO video ({names}) SELECT {names} FROM video_old")
            # Index names are unique across the database and a rename does not
            # change them, so the old ones have to go before the new ones can
            # be made. Dropping the old table takes them with it.
            cursor.execute("DROP TABLE video_old")
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
