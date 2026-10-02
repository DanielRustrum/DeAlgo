"""Expire boxes: when a placement stops counting, and taking it out when it does."""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ...models import (
    Placement,
    Playlist,
    Video,
    to_naive_utc,
    utcnow,
)
from ...plugins.publisher import Publisher, PublishError, cost_of
from .. import graph, quota, runlog
from ..scope import OwnerId, belongs_to
from .result import SyncResult

log = logging.getLogger(__name__)


def stamp_expiry(
    session: Session, video: Video, paths: list[graph.Route]
) -> None:
    """Say when a placement made under an Expire box stops counting.

    Per placement rather than per item: the same video down a path with an
    Expire box and a path without is two different answers, and only one of
    them has an end.

    Counted from now, which is when it reached the feed. Not from when it
    was published — everything that comes through gets the same stretch
    whatever its age, which is what a rolling feed means.
    """
    known = graph.pieces_of(session, video.owner_pk)
    # Queried rather than read off the relationship: the placements were
    # added a moment ago and `video.placements` has not been told.
    session.flush()
    placed = {
        one.playlist_pk: one
        for one in session.scalars(
            select(Placement).where(Placement.video_pk == video.id)
        )
    }
    for path in paths:
        if path.playlist is None:
            continue
        minutes = graph.stamped_life(path.stamps, known)
        placement = placed.get(path.playlist.id)
        if minutes is None or placement is None or placement.expires_at is not None:
            continue
        placement.expires_at = to_naive_utc(
            dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=minutes)
        )


def stamp_what_is_already_here(
    session: Session, owner: OwnerId = None
) -> int:
    """Put an end on what was already in a feed when an Expire box arrived.

    Wiring one up says something about the feed, not only about what happens
    to turn up next. Without this a box wired to a feed of eighty items
    changes nothing anybody can see until the eighty have been read.

    Counted from when each item arrived, which is what the Timer says — so
    something that has already overstayed is past its end the moment the
    rule appears, and the sweep takes it on the same run.
    """
    known = graph.pieces_of(session, owner)
    put = 0
    # Every path into a feed with an Expire box on it.
    for path in graph.routes(session, owner):
        if path.playlist is None:
            continue
        minutes = graph.stamped_life(path.stamps, known)
        if minutes is None:
            continue
        # What came down this path, is still in the feed, and has no end yet.
        waiting = session.scalars(
            select(Placement)
            .join(Video, Video.id == Placement.video_pk)
            .where(
                belongs_to(Video, owner),
                Video.channel_pk == path.channel.id,
                Placement.playlist_pk == path.playlist.id,
                Placement.expires_at.is_(None),
                Placement.removed_at.is_(None),
                Placement.playlist_item_id.is_not(None),
            )
        )
        for placement in waiting:
            began = placement.added_at or utcnow()
            placement.expires_at = began + dt.timedelta(minutes=minutes)
            put += 1
    if put:
        session.flush()
    return put


def sweep_expired(
    session: Session,
    client: Publisher,
    result: SyncResult,
    owner: OwnerId = None,
    say: runlog.Pen | None = None,
) -> None:
    """Take out what an Expire box said had had its time.

    Removed from the feed, not deleted: the item is still in the history and
    still in any other feed whose path said nothing about expiry.
    """
    due = list(
        session.scalars(
            # A placement has no owner of its own; it belongs to whoever
            # the video does, which is how every other query reaches one.
            select(Placement)
            .join(Video, Video.id == Placement.video_pk)
            .where(belongs_to(Video, owner))
            .join(Playlist, Playlist.id == Placement.playlist_pk)
            .options(selectinload(Placement.playlist), selectinload(Placement.video))
            .where(
                Placement.expires_at.is_not(None),
                Placement.expires_at <= utcnow(),
                Placement.removed_at.is_(None),
                Placement.playlist_item_id.is_not(None),
            )
        )
    )
    if not due:
        return

    gone = 0
    for placement in due:
        playlist = placement.playlist
        if not (playlist.is_generic or placement.is_local or not client.has_write_access):
            # A real playlist holds a real item, which has to be taken out of
            # it — and that costs quota like any other write.
            if not quota.can_afford(session, cost_of("remove"), owner=owner):
                result.messages.append("Quota ran out before the expired items were cleared.")
                break
            try:
                client.delete_playlist_item(placement.playlist_item_id or "")
            except PublishError as exc:
                if exc.is_quota_error:
                    quota.mark_exhausted(session, owner)
                    result.stopped_on_quota = True
                    break
                log.warning("could not clear an expired item: %s", exc)
                continue
        placement.playlist_item_id = None
        placement.removed_at = utcnow()
        placement.removal_reason = "its time in this feed ran out"
        gone += 1

    session.flush()
    result.pruned += gone
    if gone and say is not None:
        say.write(f"cleared {gone} whose time in a feed had run out")
