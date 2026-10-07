"""The feeds an account has, and how much is in each."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ...models import Placement, Playlist
from ..scope import OwnerId, belongs_to, owned


class PlaylistError(RuntimeError):
    """A feed could not be made or changed; the message says why."""

    pass


def list_playlists(session: Session, owner: OwnerId = None) -> list[Playlist]:
    """The account's feeds in fill order, with their sources loaded."""
    return list(
        session.scalars(
            owned(select(Playlist), Playlist, owner)
            .options(selectinload(Playlist.channels))
            .order_by(Playlist.priority.asc(), Playlist.id.asc())
        )
    )


def enabled_playlists(session: Session, owner: OwnerId = None) -> list[Playlist]:
    """The account's switched-on feeds, in fill order."""
    return list(
        session.scalars(
            owned(select(Playlist), Playlist, owner)
            .where(Playlist.enabled.is_(True))
            .order_by(Playlist.priority, Playlist.id)
        )
    )


def item_counts(session: Session, owner: OwnerId = None) -> dict[int, int]:
    """How many videos each playlist currently holds, as Pamphlets sees it."""
    return {
        playlist_pk: held
        for playlist_pk, held in session.execute(
            select(Placement.playlist_pk, func.count(Placement.id))
            .join(Playlist, Playlist.id == Placement.playlist_pk)
            .where(Placement.playlist_item_id.is_not(None), belongs_to(Playlist, owner))
            .group_by(Placement.playlist_pk)
        ).all()
    }
