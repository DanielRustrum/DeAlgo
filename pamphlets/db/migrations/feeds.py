"""Feeds from before there could be several, or before their ids had today's prefix."""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text

from ...models import utcnow
from ..engine import get_engine

log = logging.getLogger(__name__)


def rename_local_feed_prefix() -> None:
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


def migrate_single_playlist() -> None:
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
