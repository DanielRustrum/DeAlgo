"""Engine, session factory, and first-run schema creation."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any
from typing import Iterator

from sqlalchemy import create_engine, event, inspect, text, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import CreateIndex, CreateTable

from .config import CONFIG
from .models import Base, OAuthToken, Settings, utcnow

log = logging.getLogger(__name__)

_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


def _connect_args(url: str) -> dict[str, Any]:
    if url.startswith("sqlite"):
        # The scheduler thread and the request threads share one engine.
        return {"check_same_thread": False, "timeout": 30}
    return {}


def get_engine() -> Engine:
    global _engine, _SessionFactory
    if _engine is None:
        _engine = create_engine(
            CONFIG.database_url,
            future=True,
            connect_args=_connect_args(CONFIG.database_url),
        )
        if CONFIG.database_url.startswith("sqlite"):

            @event.listens_for(_engine, "connect")
            def _set_sqlite_pragmas(dbapi_conn: Any, _record: Any) -> None:  # pragma: no cover - driver glue
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA foreign_keys=ON")
                cur.close()

        _SessionFactory = sessionmaker(bind=_engine, future=True, expire_on_commit=False)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    get_engine()
    assert _SessionFactory is not None
    return _SessionFactory


@contextmanager
def session_scope() -> Iterator[Session]:
    """Session that commits on success and rolls back on error."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# Columns added after the first release. ``create_all`` only makes missing
# tables, so an existing database needs them added by hand; each is nullable or
# defaulted, which is what makes a plain ADD COLUMN safe.
_ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("video", "is_short", "BOOLEAN NOT NULL DEFAULT 0"),
    ("video", "watched_at", "DATETIME"),
    ("sync_run", "removed", "INTEGER NOT NULL DEFAULT 0"),
    ("oauth_token", "refresh_error", "TEXT"),
    ("channel", "priority", "INTEGER NOT NULL DEFAULT 0"),
    ("channel", "min_pull_minutes", "INTEGER NOT NULL DEFAULT 0"),
    ("channel", "backfill_days", "INTEGER"),
    ("channel", "skip_videos", "BOOLEAN NOT NULL DEFAULT 0"),
    ("channel", "description", "TEXT"),
    ("channel", "skip_posts", "BOOLEAN NOT NULL DEFAULT 0"),
    ("video", "kind", "VARCHAR(8) NOT NULL DEFAULT 'video'"),
    ("video", "body", "TEXT"),
    ("video", "images", "TEXT"),
    ("settings", "post_seconds", "INTEGER NOT NULL DEFAULT 30"),
    ("playlist", "priority", "INTEGER NOT NULL DEFAULT 0"),
    ("playlist", "max_per_run", "INTEGER NOT NULL DEFAULT 0"),
    ("playlist", "tags", "TEXT"),
    ("playlist", "view_order", "VARCHAR(8) NOT NULL DEFAULT 'oldest'"),
    ("playlist", "view_show", "VARCHAR(10) NOT NULL DEFAULT 'unwatched'"),
    ("settings", "daily_quota", "INTEGER NOT NULL DEFAULT 10000"),
    ("settings", "quota_reserve", "INTEGER NOT NULL DEFAULT 0"),
    ("settings", "hide_tour", "BOOLEAN NOT NULL DEFAULT 0"),
    ("settings", "hide_open_notice", "BOOLEAN NOT NULL DEFAULT 0"),
    ("settings", "hide_connect_notice", "BOOLEAN NOT NULL DEFAULT 0"),
    ("sync_run", "forced", "BOOLEAN NOT NULL DEFAULT 0"),
    ("sync_run", "quota_spent", "INTEGER NOT NULL DEFAULT 0"),
    ("sync_run", "stopped_on_quota", "BOOLEAN NOT NULL DEFAULT 0"),
    # Trigger boxes on the canvas. All nullable: every node that came before
    # them is a source, feed or filter, and none of these mean anything there.
    ("graph_node", "trigger_kind", "VARCHAR(10)"),
    ("graph_node", "every_minutes", "INTEGER"),
    ("graph_node", "cron", "VARCHAR(120)"),
    ("graph_node", "enabled", "BOOLEAN NOT NULL DEFAULT 1"),
    ("channel", "tags", "TEXT"),
    ("graph_node", "tag", "VARCHAR(40)"),
    ("graph_node", "duration_minutes", "INTEGER"),
    ("graph_node", "width", "INTEGER"),
    ("graph_node", "height", "INTEGER"),
    ("graph_node", "sort_by", "VARCHAR(16)"),
    ("graph_node", "sort_dir", "VARCHAR(4)"),
    # Counts, so a sort box can order by them. Backfilled as the details are
    # next fetched; NULL until then, which the ordering treats as unknown.
    ("video", "view_count", "INTEGER"),
    ("video", "like_count", "INTEGER"),
    ("graph_node", "last_fired_at", "DATETIME"),
    # Ownership. Nullable, so every existing row becomes the implicit
    # owner's — which is exactly what it was before accounts existed.
    ("settings", "owner_pk", "INTEGER REFERENCES user(id) ON DELETE CASCADE"),
    ("oauth_token", "owner_pk", "INTEGER REFERENCES user(id) ON DELETE CASCADE"),
    ("channel", "owner_pk", "INTEGER REFERENCES user(id) ON DELETE CASCADE"),
    ("playlist", "owner_pk", "INTEGER REFERENCES user(id) ON DELETE CASCADE"),
    ("video", "owner_pk", "INTEGER REFERENCES user(id) ON DELETE CASCADE"),
    ("quota_usage", "owner_pk", "INTEGER REFERENCES user(id) ON DELETE CASCADE"),
    ("sync_run", "owner_pk", "INTEGER REFERENCES user(id) ON DELETE CASCADE"),
    # Sources that are not YouTube. Every row that existed before these is
    # YouTube, which is what the default says: an upgrade must not quietly
    # turn a channel into something else. `link` is where an item from
    # elsewhere lives, since only YouTube's are addressed by an id.
    ("channel", "source_kind", "VARCHAR(12) NOT NULL DEFAULT 'youtube'"),
    ("channel", "source_url", "TEXT"),
    ("video", "link", "TEXT"),
    # Where else the same feed can be read, when the first place refuses us.
    ("channel", "mirror_url", "TEXT"),
    # Boxes a plugin put in the palette: which one, and what its fields say.
    ("graph_node", "plugin_ref", "VARCHAR(80)"),
    ("graph_node", "plugin_settings", "TEXT"),
    # Which kind of somewhere a source box is for. Nullable: every source box
    # that came before this was the one generic kind, and an empty one of
    # those can still be pointed at something already watched.
    ("graph_node", "source_kind", "VARCHAR(24)"),
    # Deposit and Withdraw boxes: which repository, and how much a withdrawal
    # takes. Nullable, because every box drawn before them is neither.
    ("graph_node", "repository", "VARCHAR(60)"),
    ("graph_node", "takes", "INTEGER"),
    # Which box a jigsaw piece is slotted under. Added without the foreign
    # key an ALTER cannot carry: the constraint is on the table SQLAlchemy
    # creates from scratch, and a column added to an existing one goes in
    # plain. Nothing reads it but the walk up a chain, which checks anyway.
    ("graph_node", "attached_to", "INTEGER"),
    # The two ends of an Alive piece's stretch of the day.
    ("graph_node", "alive_from", "VARCHAR(5)"),
    ("graph_node", "alive_to", "VARCHAR(5)"),
    # What the boxes on an item's way marked it with, and when a placement
    # made under an Expire box stops counting.
    ("video", "tags", "TEXT"),
    ("video", "view_seconds", "INTEGER"),
    ("video", "view_locked", "BOOLEAN NOT NULL DEFAULT 0"),
    ("placement", "expires_at", "DATETIME"),
    # A Filter box can narrow on a tag a Tag box put on.
    ("graph_node", "tagged", "VARCHAR(40)"),
    # What a Tag box marks whatever comes through it with.
    ("graph_node", "marks", "VARCHAR(40)"),
    # What a person granted each plugin. plugin_state may already exist from
    # before permissions did, so this is a column rather than part of the
    # table's creation.
    ("plugin_state", "granted", "TEXT"),
)

# run_event is a new table rather than new columns, so it needs no entry here:
# create_all makes it, and an install that predates it simply has no history
# from before it existed.


# Columns removed after the first release. An existing table still has them,
# and they are NOT NULL with no SQL default, so leaving them would break every
# insert once the model stops supplying a value.
_DROPPED_COLUMNS: tuple[tuple[str, str], ...] = (
    ("playlist", "default_target"),
    # From before feeds could be fanned out. They are NOT NULL with no SQL
    # default, so they were harmless only while `settings` held exactly one
    # row that already had them — the moment a second account needed a row of
    # its own, the insert failed and the app would not start.
    ("settings", "max_playlist_items"),
    ("settings", "playlist_id"),
    ("settings", "playlist_title"),
    # The tag node, and the Sources page that set what it matched on. A
    # source box names one source now, and the way to follow a kind of thing
    # is the plugin that understands it. Feed tags are a different feature
    # and are untouched.
    ("channel", "tags"),
    ("graph_node", "tag"),
)


def _feed_windows_become_pieces() -> None:
    """Turn a trigger wired to a feed into the pieces that say the same thing.

    A feed used to take a trigger on a second input to say when it could be
    read. That is a Reset and a Timer slotted under it now — when it opens,
    and how long for — so the wire is unpicked into the two pieces it was
    carrying rather than dropped along with what somebody set up.

    A pulse said "this long, this often" with no clock time to anchor it, and
    there is no cron that means the same. It becomes a Timer alone, which
    keeps the duration and leaves the feed open — the honest half of it,
    rather than a made-up hour nobody chose.
    """
    engine = get_engine()
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if not {"graph_node", "graph_edge"} <= tables:
        return
    if "attached_to" not in {c["name"] for c in inspector.get_columns("graph_node")}:
        return

    with engine.begin() as connection:
        windows = connection.execute(text("""
            SELECT e.id, t.id, t.owner_pk, s.trigger_kind, s.duration_minutes, s.cron
            FROM graph_edge e
            JOIN graph_node s ON s.id = e.source_pk AND s.kind = 'trigger'
            JOIN graph_node t ON t.id = e.target_pk AND t.kind = 'feed'
        """)).fetchall()
        for edge_pk, feed_pk, owner_pk, kind, minutes, cron in windows:
            made = connection.execute(
                text(
                    "INSERT INTO graph_node (owner_pk, kind, enabled, x, y, "
                    "attached_to, duration_minutes) "
                    "VALUES (:owner, 'timer', 1, 0, 0, :host, :minutes)"
                ),
                {"owner": owner_pk, "host": feed_pk, "minutes": minutes or 30},
            )
            if kind == "schedule" and cron:
                connection.execute(
                    text(
                        "INSERT INTO graph_node (owner_pk, kind, enabled, x, y, "
                        "attached_to, cron) VALUES (:owner, 'reset', 1, 0, 0, :host, :cron)"
                    ),
                    {"owner": owner_pk, "host": made.lastrowid, "cron": cron},
                )
            connection.execute(
                text("DELETE FROM graph_edge WHERE id = :pk"), {"pk": edge_pk}
            )
    if windows:
        log.info("turned %d feed window(s) into jigsaw pieces", len(windows))


def _wires_belong_to_boxes() -> None:
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


def _retire_tag_nodes() -> None:
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
        retiring = [
            row[0]
            for row in connection.execute(
                text("SELECT id FROM graph_node WHERE kind = 'source' AND tag IS NOT NULL")
            )
        ]
        if not retiring:
            return
        marks = ", ".join(str(int(one)) for one in retiring)
        connection.execute(
            text(f"DELETE FROM graph_edge WHERE source_pk IN ({marks}) OR target_pk IN ({marks})")
        )
        connection.execute(text(f"DELETE FROM graph_node WHERE id IN ({marks})"))
    log.info("removed %d tag node(s); source boxes name one source now", len(retiring))


def _drop_removed_columns() -> None:
    engine = get_engine()
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as connection:
        for table, column in _DROPPED_COLUMNS:
            if table not in tables:
                continue
            if column not in {c["name"] for c in inspector.get_columns(table)}:
                continue
            connection.execute(text(f"ALTER TABLE {table} DROP COLUMN {column}"))
            log.info("dropped unused column %s.%s", table, column)


def _add_missing_columns() -> None:
    engine = get_engine()
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as connection:
        for table, column, definition in _ADDED_COLUMNS:
            if table not in tables:
                continue
            existing = {c["name"] for c in inspector.get_columns(table)}
            if column in existing:
                continue
            connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))
            log.info("added column %s.%s to an existing database", table, column)


# Uniqueness that used to be global and is now per owner. Each was declared
# `unique=True, index=True`, so SQLite holds it as a plain index that can be
# swapped — no table rebuild for these three.
_REPLACED_INDEXES: tuple[tuple[str, str, str], ...] = (
    ("channel", "ix_channel_channel_id", "channel_id"),
    ("playlist", "ix_playlist_playlist_id", "playlist_id"),
    ("quota_usage", "ix_quota_usage_day", "day"),
)


def _scope_uniqueness_to_owners() -> None:
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


def _rebuild_video_uniqueness() -> None:
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


def _rename_local_feed_prefix() -> None:
    """An earlier build wrote generic feeds with a `local:` id. Same idea, and
    nothing else reads the old prefix, so bring them across."""
    engine = get_engine()
    if "playlist" not in set(inspect(engine).get_table_names()):
        return
    with engine.begin() as connection:
        changed = connection.execute(
            text(
                "UPDATE playlist SET playlist_id = 'generic:' || substr(playlist_id, 7)"
                " WHERE playlist_id LIKE 'local:%'"
            )
        ).rowcount
    if changed:
        log.info("renamed %d generic feed id(s) from the old prefix", changed)


def _migrate_single_playlist() -> None:
    """Carry a pre-fan-out database onto the playlist/placement tables.

    Older installs kept one playlist id in ``settings`` and one item id per
    video. Both become rows: a single Playlist that every channel feeds, and a
    Placement for every video already in it. Clearing ``settings.playlist_id``
    marks the migration done, so this is safe to run on every start.
    """
    engine = get_engine()
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if not {"settings", "playlist", "channel_playlist", "placement"} <= tables:
        return
    if "playlist_id" not in {c["name"] for c in inspector.get_columns("settings")}:
        return  # already created on the new shape

    with engine.begin() as connection:
        row = connection.execute(
            text("SELECT playlist_id, playlist_title, max_playlist_items FROM settings WHERE id = 1")
        ).first()
        if row is None or not row[0]:
            return
        if connection.execute(text("SELECT COUNT(*) FROM playlist")).scalar():
            return  # playlists already configured; nothing to carry over

        connection.execute(
            text(
                # Every NOT NULL column must be listed: a table created by
                # create_all has no SQL-side defaults, only Python ones.
                "INSERT INTO playlist"
                " (playlist_id, title, enabled, priority, max_items, max_per_run, added_at)"
                " VALUES (:pid, :title, 1, 0, :max_items, 0, :now)"
            ),
            {"pid": row[0], "title": row[1] or "", "max_items": row[2] or 0, "now": utcnow()},
        )
        playlist_pk = connection.execute(
            text("SELECT id FROM playlist WHERE playlist_id = :pid"), {"pid": row[0]}
        ).scalar()

        # Every existing channel fed that one playlist.
        connection.execute(
            text(
                "INSERT OR IGNORE INTO channel_playlist (channel_pk, playlist_pk)"
                " SELECT id, :playlist_pk FROM channel"
            ),
            {"playlist_pk": playlist_pk},
        )

        video_columns = {c["name"] for c in inspector.get_columns("video")}
        if "playlist_item_id" in video_columns:
            connection.execute(
                text(
                    "INSERT OR IGNORE INTO placement"
                    " (video_pk, playlist_pk, playlist_item_id, attempts, added_at)"
                    " SELECT id, :playlist_pk, playlist_item_id, 0, processed_at FROM video"
                    " WHERE playlist_item_id IS NOT NULL"
                ),
                {"playlist_pk": playlist_pk},
            )

        connection.execute(text("UPDATE settings SET playlist_id = NULL WHERE id = 1"))
        log.info("migrated the single target playlist %s onto the playlist tables", row[0])


def init_db() -> None:
    Base.metadata.create_all(get_engine())
    _add_missing_columns()
    _rebuild_video_uniqueness()
    _scope_uniqueness_to_owners()
    _rename_local_feed_prefix()
    _migrate_single_playlist()
    _retire_tag_nodes()
    _wires_belong_to_boxes()
    _feed_windows_become_pieces()
    # After the migrations above, not before: they read columns this drops,
    # and they are the last things that need them.
    _drop_removed_columns()

    # The admin account is the environment's, so it is reconciled on every
    # start rather than only when the database is first made. Imported here
    # rather than at the top: accounts reads the models this module defines.
    from .services import accounts

    # Items filed before anything looked at a feed's markup for pictures kept
    # the address in their words instead. Reading it back out needs no
    # network, and reaches items the feed has long since stopped listing.
    from .services import sync

    with session_scope() as session:
        accounts.ensure_admin(session)
        accounts.clear_expired(session)
        sync.repair_stored_pictures(session)


def get_settings(session: Session, owner: int | None = None) -> Settings:
    """This account's settings, made on first use.

    Every account keeps its own — the poll interval, the backfill, the quota
    and the Google credentials all belong to whoever set them. `owner=None` is
    the implicit account, which is what everything is while sign-in is off.
    """
    settings = session.scalar(
        select(Settings).where(
            Settings.owner_pk.is_(None) if owner is None else Settings.owner_pk == owner
        )
    )
    if settings is None:
        settings = Settings(owner_pk=owner)
        session.add(settings)
        session.flush()
    return settings


def get_token(session: Session, owner: int | None = None) -> OAuthToken | None:
    """This account's Google grant. Each connects their own."""
    return session.scalar(
        select(OAuthToken).where(
            OAuthToken.owner_pk.is_(None) if owner is None else OAuthToken.owner_pk == owner
        )
    )
