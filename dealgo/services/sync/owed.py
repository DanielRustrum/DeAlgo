"""What earlier runs left unfinished, finished first.

Placements a quota stop or a cap left owing, and items that had nowhere to go
until a wire was drawn or a feed changed underneath one.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from ...models import (
    OFFLINE_ITEM_PREFIX,
    Channel,
    Placement,
    Playlist,
    Video,
    utcnow,
)
from ...plugins.publisher import Publisher, PublishError, cost_of
from .. import graph, quota
from ..scope import OwnerId, belongs_to, owned
from .progress import note_placed
from .reasons import WRONG_KIND_OF_FEED

if TYPE_CHECKING:
    from .result import SyncResult, Tally

from .placements import MAX_INSERT_ATTEMPTS, local_item_id

log = logging.getLogger(__name__)


def reconsider_routing(session: Session, result: SyncResult, owner: OwnerId = None) -> int:
    """Bring back items that only had nowhere to go.

    "Not a YouTube video, and that feed is a YouTube playlist" is a verdict
    about the *route*, not about the item — and routes change. A wire is
    redrawn, a second feed is added, or a YouTube playlist is turned into a
    feed that lives here, and suddenly the thing that was refused is welcome.

    Connecting a wire already brings these back, but that only catches one of
    the ways it can happen: nothing was reconnected when the feed on the end
    of an existing wire changed underneath it. So the question is asked again
    on every run, which is cheap and cannot go stale.

    Only where somewhere would now take them. Reviving them into the same
    refusal every run would be churn that reads as a feed doing something.
    """
    stranded = list(
        session.scalars(
            owned(select(Video), Video, owner).where(
                Video.status == "skipped", Video.reason == WRONG_KIND_OF_FEED
            )
        )
    )
    if not stranded:
        return 0

    # Which channels can now reach a feed that could hold such an item.
    welcomed: set[int] = set()
    for path in graph.routes(session, owner):
        # A repository holds anything, the way a feed inside De-Algo does:
        # nothing is being written to somebody else's service.
        if path.deposits:
            welcomed.add(path.channel.id)
        elif path.playlist is not None and path.playlist.enabled and path.playlist.is_generic:
            welcomed.add(path.channel.id)

    brought = 0
    for video in stranded:
        if video.channel_pk not in welcomed:
            continue
        video.status = "pending"
        video.reason = None
        video.attempts = 0
        video.processed_at = None
        brought += 1

    if brought:
        session.flush()
        result.messages.append(
            f"{brought} item{'s' if brought != 1 else ''} had nowhere to go before, "
            "and now do."
        )
    return brought


def retry_deferred(
    session: Session,
    client: Publisher,
    result: SyncResult,
    added_per_playlist: Tally,
    owner: OwnerId = None,
) -> bool:
    """Finish placements an earlier run started but could not complete.

    A row with no item id, never removed and not out of attempts is one a past
    run meant to insert and could not — quota ran out mid-video, or the call
    failed. Playlists assigned to a channel *after* a video was handled have no
    such row, which is what stops a new playlist backfilling years of history.

    Returns True if quota ran out again, so the caller stops there.
    """
    open_placements = _owed(session, owner)

    for index, placement in enumerate(open_placements):
        already_local = placement.is_offline
        cap = placement.playlist.max_per_run or 0
        if cap and added_per_playlist.get(placement.playlist_pk, 0) >= cap:
            continue  # this playlist has had its fill for the run

        if placement.playlist.is_generic or not client.has_write_access:
            if already_local:
                continue  # readable in De-Algo already; nothing more to do here
            _pay(session, placement, local_item_id(placement.video, placement.playlist),
                 added_per_playlist, result)
            continue

        if not quota.can_afford(session, cost_of("add"), owner=owner):
            result.stopped_on_quota = True
            result.messages.append(
                f"YouTube API quota is spent; {len(open_placements) - index} playlist insertion(s) "
                f"wait for the reset {quota.describe_reset()}."
            )
            return True
        try:
            item_id = client.insert_playlist_item(
                placement.playlist.playlist_id, placement.video.video_id
            )
        except PublishError as exc:
            if exc.is_quota_error:
                quota.mark_exhausted(session, owner)
                result.stopped_on_quota = True
                result.messages.append(
                    f"YouTube refused further writes: the daily quota is gone. Queued videos "
                    f"resume after the reset {quota.describe_reset()}."
                )
                return True
            placement.attempts += 1
            placement.error = str(exc)
            log.warning("retry failed for %s: %s", placement.video.video_id, exc)
            session.flush()
            continue

        _pay(session, placement, item_id, added_per_playlist, result)
    return False


def _owed(session: Session, owner: OwnerId) -> list[Placement]:
    """Every placement still owed, in the order they are paid."""
    return list(
        session.scalars(
            select(Placement)
            .options(selectinload(Placement.video), selectinload(Placement.playlist))
            .join(Video, Video.id == Placement.video_pk)
            .where(belongs_to(Video, owner))
            .join(Channel, Channel.id == Video.channel_pk)
            .join(Playlist, Playlist.id == Placement.playlist_pk)
            .where(
                or_(
                    Placement.playlist_item_id.is_(None),
                    # Filled locally while signed out: still owed to YouTube.
                    Placement.playlist_item_id.startswith(OFFLINE_ITEM_PREFIX),
                ),
                Placement.removed_at.is_(None),
                Placement.attempts < MAX_INSERT_ATTEMPTS,
                Playlist.enabled.is_(True),
            )
            .order_by(Channel.priority, Playlist.priority, Video.published_at, Placement.id)
        )
    )


def _pay(
    session: Session,
    placement: Placement,
    item_id: str,
    added_per_playlist: Tally,
    result: SyncResult,
) -> None:
    """An owed placement filled, here or on YouTube, and counted."""
    placement.playlist_item_id = item_id
    placement.error = None
    placement.added_at = utcnow()
    added_per_playlist[placement.playlist_pk] = (
        added_per_playlist.get(placement.playlist_pk, 0) + 1
    )
    note_placed(placement.playlist_pk)
    result.added += 1
    session.flush()
