"""Phase three: keeping each feed to its size."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import (
    Placement,
    Playlist,
    Video,
    utcnow,
)
from ...plugins.publisher import Publisher, PublishError, cost_of
from .. import quota
from ..scope import OwnerId
from .result import SyncResult


def _prune_generic(session: Session, playlist: Playlist, limit: int, result: SyncResult) -> None:
    """Trim a local feed the same way, but by forgetting rows rather than calls."""
    held = list(
        session.scalars(
            select(Placement)
            .join(Video, Video.id == Placement.video_pk)
            .where(Placement.playlist_pk == playlist.id, Placement.playlist_item_id.is_not(None))
            .order_by(Video.published_at.asc(), Placement.id.asc())
        )
    )
    # Oldest first: everything beyond the cap is taken out, its row kept.
    for placement in held[: max(0, len(held) - limit)]:
        placement.playlist_item_id = None
        placement.removed_at = utcnow()
        placement.removal_reason = "removed to stay under the size cap"
        result.pruned += 1
    session.flush()


def prune(
    session: Session,
    client: Publisher,
    playlists: Sequence[Playlist],
    result: SyncResult,
    owner: OwnerId = None,
) -> None:
    """Trim each playlist back to its own size cap."""
    for playlist in playlists:
        limit = playlist.max_items or 0
        if limit <= 0:
            continue

        if playlist.is_generic or not client.has_write_access:
            # Signed out, the only copy of the feed is the local one, so that
            # is what the size cap applies to.
            _prune_generic(session, playlist, limit, result)
            continue

        try:
            items = client.playlist_items(playlist.playlist_id)
        except PublishError as exc:
            result.messages.append(f"Could not read {playlist.title!r} for pruning: {exc}")
            continue

        overflow = len(items) - limit
        if overflow <= 0:
            continue

        # De-Algo appends oldest-first, so the front of the playlist is the oldest.
        for item in sorted(items, key=lambda i: i.position)[:overflow]:
            if not quota.can_afford(session, cost_of("remove"), owner=owner):
                result.stopped_on_quota = True
                result.messages.append("Quota ran out before pruning finished.")
                return
            try:
                client.delete_playlist_item(item.item_id)
            except PublishError as exc:
                if exc.is_quota_error:
                    quota.mark_exhausted(session, owner)
                    result.stopped_on_quota = True
                    return
                result.messages.append(f"Could not prune an item from {playlist.title!r}: {exc}")
                break
            placement = session.scalar(
                select(Placement).where(
                    Placement.playlist_pk == playlist.id, Placement.playlist_item_id == item.item_id
                )
            )
            if placement is not None:
                placement.playlist_item_id = None
                placement.removed_at = utcnow()
                placement.removal_reason = "removed to stay under the size cap"
            result.pruned += 1
        session.commit()
