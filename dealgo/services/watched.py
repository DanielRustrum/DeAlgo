"""Marking videos as watched, and clearing them out of the playlist.

YouTube exposes no watch history to applications — the ``watchHistory``
playlist has returned nothing since 2016 — so "watched" is state De-Algo keeps
on the user's say-so, either from the UI or the CLI.

Removal never deletes the video's record. That record is what stops the next
sync from noticing the upload again and putting it straight back.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .. import outgoing
from ..db import session_scope
from ..models import Placement, Playlist, SyncRun, Video, utcnow
from ..plugins.publisher import PublishError, cost_of
from . import quota
from .auth import build_client
from .scope import OwnerId, belongs_to, owned
from .sync import Busy, playlist_lock

log = logging.getLogger(__name__)


@dataclass
class RemovalResult:
    ok: bool = False
    started: bool = True
    removed: int = 0
    missing: int = 0
    failed: int = 0
    stopped_on_quota: bool = False
    messages: list[str] = field(default_factory=list)

    @property
    def message(self) -> str:
        return " ".join(self.messages)


def count_watched(session: Session, owner: OwnerId = None) -> int:
    return (
        session.scalar(
            owned(select(func.count(Video.id)), Video, owner).where(
                Video.watched_at.is_not(None)
            )
        )
        or 0
    )


def count_removable(session: Session, owner: OwnerId = None) -> int:
    """Placements of watched videos that are still in a playlist.

    Counted per placement, not per video: one watched video sitting in three
    playlists is three deletions.
    """
    return (
        session.scalar(
            select(func.count(Placement.id))
            .join(Video, Video.id == Placement.video_pk)
            .where(belongs_to(Video, owner))
            .where(Video.watched_at.is_not(None), Placement.playlist_item_id.is_not(None))
        )
        or 0
    )


def mark_watched(session: Session, video_ids: list[int], owner: OwnerId = None) -> int:
    # Scoped as well as keyed: an id from another account is not this one's to
    # mark, however it arrived.
    videos = list(
        session.scalars(owned(select(Video), Video, owner).where(Video.id.in_(video_ids)))
    )
    now = utcnow()
    changed = 0
    for video in videos:
        if video.watched_at is None:
            video.watched_at = now
            changed += 1
    return changed


def mark_unwatched(session: Session, video_ids: list[int], owner: OwnerId = None) -> int:
    videos = list(
        session.scalars(owned(select(Video), Video, owner).where(Video.id.in_(video_ids)))
    )
    changed = 0
    for video in videos:
        if video.watched_at is not None:
            video.watched_at = None
            changed += 1
    return changed


def mark_all_in_playlist_watched(session: Session, owner: OwnerId = None) -> int:
    """Mark everything currently in the playlist as watched."""
    videos = list(
        session.scalars(
            owned(select(Video), Video, owner)
            .join(Placement, Placement.video_pk == Video.id)
            .where(Placement.playlist_item_id.is_not(None), Video.watched_at.is_(None))
            .distinct()
        )
    )
    now = utcnow()
    for video in videos:
        video.watched_at = now
    return len(videos)


def remove_watched(trigger: str = "manual", owner: OwnerId = None) -> RemovalResult:
    """Delete every watched video from the playlist. Runs only when asked."""
    try:
        with playlist_lock():
            with outgoing.client() as http, session_scope() as session:
                return _remove(session, http, trigger, owner)
    except Busy:
        return RemovalResult(
            ok=True, started=False, messages=["Another playlist operation is already running."]
        )
    except Exception as exc:  # pragma: no cover - last-resort guard
        log.exception("removing watched videos failed")
        return RemovalResult(ok=False, messages=[f"Removal failed: {exc}"])


def _remove(
    session: Session, http: httpx.Client, trigger: str, owner: OwnerId = None
) -> RemovalResult:
    result = RemovalResult()
    client = build_client(session, http, owner)

    if not session.scalar(
        owned(select(func.count(Playlist.id)), Playlist, owner).where(Playlist.enabled.is_(True))
    ):
        result.messages.append("No feeds are set up.")
        return result
    if not client.has_write_access and not session.scalar(
        select(func.count(Placement.id))
        .join(Video, Video.id == Placement.video_pk)
        .where(belongs_to(Video, owner))
        .where(Video.watched_at.is_not(None), Placement.playlist_item_id.is_not(None))
    ):
        # An account is only needed for rows that really are on YouTube. With
        # nothing watched at all there is nothing to say but this.
        result.messages.append("No Google account is connected.")
        return result

    candidates = list(
        session.scalars(
            select(Placement)
            .options(selectinload(Placement.video), selectinload(Placement.playlist))
            .join(Video, Video.id == Placement.video_pk)
            .where(belongs_to(Video, owner))
            .where(Video.watched_at.is_not(None), Placement.playlist_item_id.is_not(None))
            .order_by(Video.watched_at.asc(), Placement.id.asc())
        )
    )
    if not candidates:
        result.ok = True
        result.messages.append("No watched videos are in a playlist.")
        return result

    run = SyncRun(trigger=trigger, started_at=utcnow(), owner_pk=owner)
    session.add(run)
    session.commit()

    stranded = 0  # really on YouTube, and no account to delete them with

    for placement in candidates:
        title = placement.video.title

        if placement.is_local:
            # Nothing to delete anywhere — a generic feed, or one filled while
            # signed out — so forgetting the row is the whole removal.
            _clear(placement, "removed after watching")
            result.removed += 1
            session.flush()
            continue

        if not client.has_write_access:
            # A real playlist item, and no account to delete it with. Leave it
            # alone rather than losing the record of where it is.
            stranded += 1
            continue

        # Removal is charged the same 50 units as an insert; a manual removal
        # may dip into the reserve, which is what the reserve is for.
        if not quota.can_afford(session, cost_of("remove"), use_reserve=True):
            result.stopped_on_quota = True
            result.messages.append(
                f"Quota ran out; the rest can be removed after the reset {quota.describe_reset()}."
            )
            break
        item_id = placement.playlist_item_id
        if item_id is None:
            # The query asks for rows that have one; belt and braces for a
            # future caller that does not.
            continue
        try:
            client.delete_playlist_item(item_id)
        except PublishError as exc:
            if exc.status == 404 or exc.reason == "playlistItemNotFound":
                # Already gone from YouTube's side; just reconcile our record.
                _clear(placement, "watched — already gone from the playlist")
                result.missing += 1
                session.flush()
                continue
            if exc.is_quota_error:
                quota.mark_exhausted(session)
                result.stopped_on_quota = True
                result.messages.append(
                    f"YouTube says the daily quota is gone; the rest can be removed after the reset "
                    f"{quota.describe_reset()}."
                )
                log.warning("quota exhausted while removing watched videos")
                break
            result.failed += 1
            result.messages.append(f"Could not remove {title!r} from {placement.playlist.title!r}: {exc}")
            log.warning("could not remove playlist item for %s: %s", placement.video.video_id, exc)
            continue

        _clear(placement, "removed from the playlist after watching")
        result.removed += 1
        session.flush()

    result.ok = result.failed == 0
    total = result.removed + result.missing
    summary = f"Removed {total} watched video{'s' if total != 1 else ''} from playlists."
    if result.failed:
        summary += f" {result.failed} could not be removed."
    if stranded:
        summary += (
            f" {stranded} sit in a YouTube playlist and need a connected account "
            "before they can be taken out."
        )
    result.messages.insert(0, summary)

    run.finished_at = utcnow()
    run.ok = result.ok
    run.removed = total
    run.failed = result.failed
    run.stopped_on_quota = result.stopped_on_quota
    run.message = result.message
    session.commit()

    log.info("removed %d watched placements (%s)", total, trigger)
    return result


def _clear(placement: Placement, reason: str) -> None:
    placement.playlist_item_id = None
    placement.removed_at = utcnow()
    placement.removal_reason = reason
