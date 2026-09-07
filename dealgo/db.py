"""Engine, session factory, and first-run schema creation."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import CONFIG
from .models import Base, OAuthToken, Settings, utcnow

log = logging.getLogger(__name__)

_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


def _connect_args(url: str) -> dict:
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
            def _set_sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - driver glue
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
    ("playlist", "priority", "INTEGER NOT NULL DEFAULT 0"),
    ("playlist", "max_per_run", "INTEGER NOT NULL DEFAULT 0"),
    ("playlist", "tags", "TEXT"),
    ("playlist", "view_order", "VARCHAR(8) NOT NULL DEFAULT 'oldest'"),
    ("playlist", "view_show", "VARCHAR(10) NOT NULL DEFAULT 'unwatched'"),
    ("settings", "daily_quota", "INTEGER NOT NULL DEFAULT 10000"),
    ("settings", "quota_reserve", "INTEGER NOT NULL DEFAULT 0"),
    ("settings", "hide_tour", "BOOLEAN NOT NULL DEFAULT 0"),
    ("sync_run", "forced", "BOOLEAN NOT NULL DEFAULT 0"),
    ("sync_run", "quota_spent", "INTEGER NOT NULL DEFAULT 0"),
    ("sync_run", "stopped_on_quota", "BOOLEAN NOT NULL DEFAULT 0"),
)


# Columns removed after the first release. An existing table still has them,
# and they are NOT NULL with no SQL default, so leaving them would break every
# insert once the model stops supplying a value.
_DROPPED_COLUMNS: tuple[tuple[str, str], ...] = (("playlist", "default_target"),)


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
    _drop_removed_columns()
    _rename_local_feed_prefix()
    _migrate_single_playlist()
    with session_scope() as session:
        if session.get(Settings, 1) is None:
            session.add(Settings(id=1))


def get_settings(session: Session) -> Settings:
    settings = session.get(Settings, 1)
    if settings is None:
        settings = Settings(id=1)
        session.add(settings)
        session.flush()
    return settings


def get_token(session: Session) -> OAuthToken | None:
    return session.get(OAuthToken, 1)
