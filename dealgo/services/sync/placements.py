"""Writing placement rows: one owed for later, and the id a placement made here carries."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...models import (
    GENERIC_ITEM_PREFIX,
    OFFLINE_ITEM_PREFIX,
    Placement,
    Playlist,
    Video,
)

if TYPE_CHECKING:
    pass


log = logging.getLogger(__name__)


MAX_INSERT_ATTEMPTS = 3


def defer(
    session: Session, video: Video, targets: Sequence[Playlist], placed: dict[int, Placement]
) -> int:
    """Record the playlists this video was meant to reach but did not."""
    known = set(placed) | {p.playlist_pk for p in video.placements}
    created = 0
    for playlist in targets:
        if playlist.id in known:
            continue
        session.add(Placement(video_pk=video.id, playlist_pk=playlist.id))
        known.add(playlist.id)
        created += 1
    session.flush()
    return created


def local_item_id(video: Video, playlist: Playlist) -> str:
    """A stand-in for the YouTube item id, so a local placement reads as filled.

    A generic feed is local for good. A YouTube feed filled while signed out is
    local for now, and says so, so a run with an account can finish the job.
    """
    # A post is local for good: nothing on YouTube can hold one, so it must
    # never be marked as owed to a playlist the way a signed-out video is.
    local_for_good = playlist.is_generic or video.is_post
    prefix = GENERIC_ITEM_PREFIX if local_for_good else OFFLINE_ITEM_PREFIX
    return f"{prefix}{playlist.id}-{video.id}"


def still_queued(session: Session) -> int:
    return session.scalar(select(func.count(Video.id)).where(Video.status == "pending")) or 0
