"""Carrying an existing install onto the multi-playlist schema.

These run against a database put back into the pre-fan-out shape — one playlist
id in ``settings``, one item id per video — which is what an install created
before this change actually looks like on disk.
"""

from __future__ import annotations

from sqlalchemy import select, text

from pamphlets.db import get_settings
from pamphlets.models import Channel, Placement, Playlist, Video


def make_legacy(db) -> None:
    """Rewind a fresh database to the single-playlist shape and fill it."""
    # Settings rows are made on demand now, one per account, so an old install
    # is reproduced by making the implicit owner's first.
    with db.session_scope() as session:
        get_settings(session)

    engine = db.get_engine()
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM placement"))
        connection.execute(text("DELETE FROM channel_playlist"))
        connection.execute(text("DELETE FROM playlist"))
        # A fresh test database is built from the current models, so put the
        # dropped columns back to reproduce what an older install has on disk.
        for statement in (
            "ALTER TABLE settings ADD COLUMN playlist_id VARCHAR(64)",
            "ALTER TABLE settings ADD COLUMN playlist_title VARCHAR(255)",
            "ALTER TABLE settings ADD COLUMN max_playlist_items INTEGER DEFAULT 0",
            "ALTER TABLE video ADD COLUMN playlist_item_id VARCHAR(128)",
        ):
            connection.execute(text(statement))
        connection.execute(
            text("UPDATE settings SET playlist_id = 'PL_old', playlist_title = 'Old Feed',"
                 " max_playlist_items = 40 WHERE id = 1")
        )

    with db.session_scope() as session:
        channel = Channel(channel_id="UCaaaaaaaaaaaaaaaaaaaaaa", title="Old Channel")
        session.add(channel)
        session.flush()
        for index, item in enumerate(["item-a", "item-b", None]):
            video = Video(
                video_id=f"old{index}",
                channel_pk=channel.id,
                title=f"Old video {index}",
                status="added" if item else "skipped",
            )
            session.add(video)
            session.flush()
            if item:
                session.execute(
                    text("UPDATE video SET playlist_item_id = :item WHERE id = :id"),
                    {"item": item, "id": video.id},
                )


def test_the_old_target_becomes_a_playlist_row(db):
    make_legacy(db)
    db.init_db()

    with db.session_scope() as session:
        playlist = session.scalar(select(Playlist))
        assert playlist.playlist_id == "PL_old"
        assert playlist.title == "Old Feed"
        assert playlist.max_items == 40  # the global cap becomes this playlist's cap
        assert playlist.enabled is True


def test_existing_channels_keep_feeding_it(db):
    make_legacy(db)
    db.init_db()

    with db.session_scope() as session:
        channel = session.scalar(select(Channel))
        assert [p.playlist_id for p in channel.playlists] == ["PL_old"]


def test_videos_already_in_the_playlist_become_placements(db):
    make_legacy(db)
    db.init_db()

    with db.session_scope() as session:
        placements = {
            session.get(Video, p.video_pk).video_id: p.playlist_item_id
            for p in session.scalars(select(Placement))
        }
    # Only the two that were actually in the playlist; the skipped one is not.
    assert placements == {"old0": "item-a", "old1": "item-b"}


def test_migrating_twice_changes_nothing(db):
    make_legacy(db)
    db.init_db()
    db.init_db()

    with db.session_scope() as session:
        assert session.scalar(select(Playlist).order_by(Playlist.id)) is not None
        assert len(list(session.scalars(select(Playlist)))) == 1
        assert len(list(session.scalars(select(Placement)))) == 2


def test_an_install_that_never_set_a_playlist_migrates_to_nothing(db):
    with db.session_scope() as session:
        session.add(Channel(channel_id="UCbbbbbbbbbbbbbbbbbbbbbb", title="No target"))
    db.init_db()

    with db.session_scope() as session:
        assert list(session.scalars(select(Playlist))) == []
