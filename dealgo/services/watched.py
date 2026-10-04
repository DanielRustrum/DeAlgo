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
from ..plugins.publisher import Publisher, PublishError, cost_of, names
from . import quota
from .connections import build_client
from .scope import OwnerId, belongs_to, owned
from .sync import Busy, playlist_lock

log = logging.getLogger(__name__)


@dataclass
class RemovalResult:
    """What a removal of watched items did, counted, and what to tell the person."""

    ok: bool = False
    started: bool = True
    removed: int = 0
    missing: int = 0
    failed: int = 0
    stopped_on_quota: bool = False
    messages: list[str] = field(default_factory=list)

    @property
    def message(self) -> str:
        """Every message, as one line."""
        return " ".join(self.messages)


def count_watched(session: Session, owner: OwnerId = None) -> int:
    """How many items the owner has marked watched."""
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
    """Mark the owner's items with these ids watched; returns how many changed."""
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
    """Clear the watched mark on these ids; returns how many changed."""
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
    """Take every watched item out of its feeds, recording it as a run."""
    result = RemovalResult()
    client = build_client(session, http, owner)

    why_not = _nothing_to_remove(session, client, owner)
    if why_not:
        result.messages.append(why_not)
        return result

    candidates = _watched_placements(session, owner)
    if not candidates:
        result.ok = True
        result.messages.append("No watched videos are in a playlist.")
        return result

    run = SyncRun(trigger=trigger, started_at=utcnow(), owner_pk=owner)
    session.add(run)
    session.commit()

    stranded = 0  # really on the service, and no account to delete them with
    for placement in candidates:
        outcome = _take_out(session, client, placement, result)
        if outcome == "stranded":
            stranded += 1
        elif outcome == "stop":
            break

    result.ok = result.failed == 0
    total = result.removed + result.missing
    result.messages.insert(0, _summary(result, total, stranded))

    run.finished_at = utcnow()
    run.ok = result.ok
    run.removed = total
    run.failed = result.failed
    run.stopped_on_quota = result.stopped_on_quota
    run.message = result.message
    session.commit()

    log.info("removed %d watched placements (%s)", total, trigger)
    return result


def clear_feed(playlist_pk: int, owner: OwnerId = None) -> RemovalResult:
    """Empty one feed: everything in it leaves it, watched or not.

    Taken out the way a watched item is — from the real playlist too, where
    the feed has one and there is an account to do it with — and the row is
    kept, so nothing cleared is put back by the next run. The items stay in
    the history, and in any other feed they are in.
    """
    try:
        with playlist_lock():
            with outgoing.client() as http, session_scope() as session:
                return _clear_feed(session, http, playlist_pk, owner)
    except Busy:
        return RemovalResult(
            ok=True, started=False, messages=["Another playlist operation is already running."]
        )
    except Exception as exc:  # pragma: no cover - last-resort guard
        log.exception("clearing a feed failed")
        return RemovalResult(ok=False, messages=[f"Clearing failed: {exc}"])


def _clear_feed(
    session: Session, http: httpx.Client, playlist_pk: int, owner: OwnerId
) -> RemovalResult:
    result = RemovalResult()
    target = session.scalar(owned(select(Playlist), Playlist, owner).where(Playlist.id == playlist_pk))
    if target is None:
        result.ok = False
        result.messages.append("That feed is not here.")
        return result
    held = list(
        session.scalars(
            select(Placement)
            .options(selectinload(Placement.video), selectinload(Placement.playlist))
            .where(Placement.playlist_pk == target.id, Placement.playlist_item_id.is_not(None))
        )
    )
    if not held:
        result.ok = True
        result.messages.append(f"“{target.title}” is already empty.")
        return result

    client = build_client(session, http, owner)
    stranded = 0
    for placement in held:
        outcome = _take_out(session, client, placement, result, _CLEARED)
        if outcome == "stranded":
            stranded += 1
        elif outcome == "stop":
            break
    session.commit()

    result.ok = result.failed == 0
    total = result.removed + result.missing
    said = f"Cleared {total} item{'s' if total != 1 else ''} from “{target.title}”."
    if result.failed:
        said += f" {result.failed} could not be taken out."
    if stranded:
        said += (
            f" {stranded} sit in its {names().publisher} playlist and need a connected account "
            "before they can be taken out."
        )
    result.messages.insert(0, said)
    log.info("cleared %d placements from feed %s", total, target.id)
    return result


def _nothing_to_remove(session: Session, client: Publisher, owner: OwnerId) -> str | None:
    """Why there is nothing to do at all, or None when there may be."""
    if not session.scalar(
        owned(select(func.count(Playlist.id)), Playlist, owner).where(Playlist.enabled.is_(True))
    ):
        return "No feeds are set up."
    if not client.has_write_access and not session.scalar(
        select(func.count(Placement.id))
        .join(Video, Video.id == Placement.video_pk)
        .where(belongs_to(Video, owner))
        .where(Video.watched_at.is_not(None), Placement.playlist_item_id.is_not(None))
    ):
        # An account is only needed for rows that really are on the service.
        # With nothing watched at all there is nothing to say but this.
        return f"No {names().service} account is connected."
    return None


def _watched_placements(session: Session, owner: OwnerId) -> list[Placement]:
    """Every watched item still in a feed, the longest-watched first."""
    return list(
        session.scalars(
            select(Placement)
            .options(selectinload(Placement.video), selectinload(Placement.playlist))
            .join(Video, Video.id == Placement.video_pk)
            .where(belongs_to(Video, owner))
            .where(Video.watched_at.is_not(None), Placement.playlist_item_id.is_not(None))
            .order_by(Video.watched_at.asc(), Placement.id.asc())
        )
    )


@dataclass(frozen=True)
class _Why:
    """What a removal records, for each way it can go."""

    local: str = "removed after watching"
    gone: str = "watched — already gone from the playlist"
    removed: str = "removed from the playlist after watching"


_WATCHED = _Why()
_CLEARED = _Why(
    local="cleared from the feed",
    gone="cleared — already gone from the playlist",
    removed="cleared from the feed and its playlist",
)


def _take_out(
    session: Session,
    client: Publisher,
    placement: Placement,
    result: RemovalResult,
    why: _Why = _WATCHED,
) -> str:
    """Take one item out of its feed: watched, or the feed being cleared.

    "stranded" when it is on the service with no account to remove it with,
    "stop" when the quota has run out, and "" otherwise.
    """
    title = placement.video.title

    if placement.is_local:
        # Nothing to delete anywhere — a generic feed, or one filled while
        # signed out — so forgetting the row is the whole removal.
        _clear(placement, why.local)
        result.removed += 1
        session.flush()
        return ""

    if not client.has_write_access:
        # A real playlist item, and no account to delete it with. Leave it
        # alone rather than losing the record of where it is.
        return "stranded"

    # Removal is charged the same 50 units as an insert; a manual removal
    # may dip into the reserve, which is what the reserve is for.
    if not quota.can_afford(session, cost_of("remove"), use_reserve=True):
        result.stopped_on_quota = True
        result.messages.append(
            f"Quota ran out; the rest can be removed after the reset {quota.describe_reset()}."
        )
        return "stop"
    item_id = placement.playlist_item_id
    if item_id is None:
        # The query asks for rows that have one; belt and braces for a
        # future caller that does not.
        return ""
    try:
        client.delete_playlist_item(item_id)
    except PublishError as exc:
        if exc.status == 404:
            # Already gone from the service's side; just reconcile our record.
            _clear(placement, why.gone)
            result.missing += 1
            session.flush()
            return ""
        if exc.is_quota_error:
            quota.mark_exhausted(session)
            result.stopped_on_quota = True
            result.messages.append(
                f"{names().publisher} says today's allowance is spent; the rest can be removed "
                "after the reset "
                f"{quota.describe_reset()}."
            )
            log.warning("quota exhausted while removing from a playlist")
            return "stop"
        result.failed += 1
        result.messages.append(f"Could not remove {title!r} from {placement.playlist.title!r}: {exc}")
        log.warning("could not remove playlist item for %s: %s", placement.video.video_id, exc)
        return ""

    _clear(placement, why.removed)
    result.removed += 1
    session.flush()
    return ""


def _summary(result: RemovalResult, total: int, stranded: int) -> str:
    """The line that opens the result: how many went, and what could not."""
    said = f"Removed {total} watched video{'s' if total != 1 else ''} from playlists."
    if result.failed:
        said += f" {result.failed} could not be removed."
    if stranded:
        said += (
            f" {stranded} sit in a {names().publisher} playlist and need a connected account "
            "before they can be taken out."
        )
    return said


def _clear(placement: Placement, reason: str) -> None:
    """Mark a placement removed, with why, keeping the row."""
    placement.playlist_item_id = None
    placement.removed_at = utcnow()
    placement.removal_reason = reason
