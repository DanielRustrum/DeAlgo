"""The sync engine: poll feeds, filter, and push new uploads into the playlist.

One run is a single pass over every enabled channel. It is deliberately
restartable — every decision is written to the database as it is made, so a
crash mid-run costs at most the videos still in flight, and nothing is ever
added twice.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field

import httpx
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload
from sqlalchemy.orm import Session

from ..db import get_settings, session_scope
from ..models import (
    GENERIC_ITEM_PREFIX,
    OFFLINE_ITEM_PREFIX,
    Channel,
    Placement,
    Playlist,
    SyncRun,
    Video,
    to_naive_utc,
    utcnow,
)
from ..youtube import feeds
from ..youtube.api import QUOTA_COST_DELETE, QUOTA_COST_INSERT, YouTubeAPIError, YouTubeClient
from . import filters
from . import quota
from .auth import build_client

log = logging.getLogger(__name__)

USER_AGENT = "De-Algo/0.1 (personal YouTube playlist builder)"
HTTP_TIMEOUT = 30.0
MAX_INSERT_ATTEMPTS = 3

class Busy(RuntimeError):
    """Another playlist operation holds the lock."""


_run_lock = threading.Lock()


@contextmanager
def playlist_lock():
    """Serialize everything that writes to the playlist.

    A sync inserting while a removal pass deletes would race over the same
    items, so the two take turns rather than overlapping.
    """
    if not _run_lock.acquire(blocking=False):
        raise Busy("Another playlist operation is already running.")
    try:
        yield
    finally:
        _run_lock.release()


@dataclass
class SyncResult:
    ok: bool = False
    started: bool = True
    forced: bool = False
    channels_checked: int = 0
    channels_waiting: int = 0
    discovered: int = 0
    added: int = 0
    skipped: int = 0
    failed: int = 0
    pruned: int = 0
    quota_spent: int = 0
    stopped_on_quota: bool = False
    messages: list[str] = field(default_factory=list)

    @property
    def message(self) -> str:
        return " ".join(self.messages)


def is_running() -> bool:
    return _run_lock.locked()


def http_client() -> httpx.Client:
    return httpx.Client(timeout=HTTP_TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True)


def run_sync(trigger: str = "manual", *, force: bool = False) -> SyncResult:
    """Run one sync pass. Returns immediately if another pass is in flight.

    ``force`` polls every enabled channel regardless of its minimum gap. The
    scheduler never forces; this is for someone pressing the button.
    """
    try:
        with playlist_lock():
            with http_client() as http, session_scope() as session:
                return _run(session, http, trigger, force=force)
    except Busy:
        return SyncResult(ok=True, started=False, messages=["A sync is already running."])
    except Exception as exc:  # pragma: no cover - last-resort guard for the scheduler
        log.exception("sync run failed")
        return SyncResult(ok=False, messages=[f"Sync failed: {exc}"])


def _run(session: Session, http: httpx.Client, trigger: str, *, force: bool = False) -> SyncResult:
    settings = get_settings(session)
    run = SyncRun(trigger=trigger, started_at=utcnow(), forced=force)
    session.add(run)
    session.commit()

    result = SyncResult(forced=force)
    quota_before = quota.state(session).used
    client = build_client(session, http)

    _discover(session, http, result, backfill=settings.initial_backfill, force=force)
    _fill_missing_details(session, client, result)
    session.commit()

    playlists = list(
        session.scalars(
            select(Playlist).where(Playlist.enabled.is_(True)).order_by(Playlist.priority, Playlist.id)
        )
    )
    quota_state = quota.state(session)
    # Feeds that live only in De-Algo need neither an account nor quota, so a
    # missing sign-in holds back the YouTube ones without stopping the run.
    youtube_feeds = [playlist for playlist in playlists if not playlist.is_generic]
    if not playlists:
        result.messages.append("No feeds are set up — new videos are queued in Pending.")
    elif youtube_feeds and not client.has_write_access:
        # Not an error: the app is usable without Google. The feeds still fill,
        # they just fill inside De-Algo until an account is connected.
        result.messages.append(
            f"No Google account connected — {len(youtube_feeds)} YouTube feed(s) are collecting "
            "inside De-Algo. Nothing is written to YouTube until you connect one."
        )
        _publish(session, client, settings, result)
        session.commit()
    elif youtube_feeds and quota_state.spendable < QUOTA_COST_INSERT:
        # Feeds cost nothing, so discovery already ran; only writing stops.
        result.stopped_on_quota = True
        result.messages.append(
            f"YouTube API quota is spent ({quota_state.used}/{quota_state.budget} units). "
            f"Queued videos will be added after it resets {quota.describe_reset()}."
        )
        log.info("skipping the insert phase: quota exhausted until %s", quota_state.resets_at)
        _publish(session, client, settings, result)
        session.commit()
    else:
        _publish(session, client, settings, result)
        session.commit()
        _prune(session, client, playlists, result)

    run.finished_at = utcnow()
    run.ok = result.failed == 0 and all("failed" not in m.lower() for m in result.messages)
    run.channels_checked = result.channels_checked
    run.discovered = result.discovered
    run.added = result.added
    run.skipped = result.skipped
    run.failed = result.failed
    run.pruned = result.pruned
    run.quota_spent = max(0, quota.state(session).used - quota_before)
    run.stopped_on_quota = result.stopped_on_quota
    result.quota_spent = run.quota_spent
    run.message = result.message or None
    result.ok = run.ok
    session.commit()

    log.info(
        "sync (%s): %d channels (%d waiting), %d new, %d added, %d skipped, %d failed",
        trigger,
        result.channels_checked,
        result.channels_waiting,
        result.discovered,
        result.added,
        result.skipped,
        result.failed,
    )
    return result


# -- phase 1: discovery ---------------------------------------------------


def _discover(
    session: Session, http: httpx.Client, result: SyncResult, *, backfill: int, force: bool = False
) -> None:
    channels = list(
        session.scalars(
            select(Channel).where(Channel.enabled.is_(True)).order_by(Channel.priority, Channel.id)
        )
    )
    now = utcnow()
    for channel in channels:
        if not force and not channel.is_due(now):
            # Its minimum gap has not elapsed. Polling is free, so this is about
            # how often the user wants to hear from a channel, not about cost.
            result.channels_waiting += 1
            continue
        try:
            feed = feeds.fetch_feed(channel.channel_id, http)
        except httpx.HTTPError as exc:
            channel.last_error = f"feed unreachable: {exc}"
            result.messages.append(f"{channel.title}: feed unreachable.")
            log.warning("feed fetch failed for %s: %s", channel.channel_id, exc)
            continue
        except Exception as exc:  # malformed XML, etc.
            channel.last_error = f"feed unreadable: {exc}"
            log.warning("feed parse failed for %s: %s", channel.channel_id, exc)
            continue

        first_check = channel.last_checked_at is None
        known = set(
            session.scalars(
                select(Video.video_id).where(Video.video_id.in_([e.video_id for e in feed.entries] or [""]))
            )
        )

        # A channel can ask for a window of history instead of a count. The
        # feed only lists the newest ~15 uploads either way, so a long window
        # reaches as far as that and no further.
        cutoff = None
        if first_check and channel.backfill_days is not None:
            cutoff = now - dt.timedelta(days=max(0, channel.backfill_days))

        for index, entry in enumerate(feed.entries):
            if entry.video_id in known:
                continue
            if cutoff is not None:
                published = to_naive_utc(entry.published_at)
                beyond_backfill = published is None or published < cutoff
            else:
                beyond_backfill = first_check and index >= max(0, backfill)
            session.add(
                Video(
                    video_id=entry.video_id,
                    channel_pk=channel.id,
                    title=entry.title,
                    published_at=to_naive_utc(entry.published_at),
                    thumbnail_url=entry.thumbnail_url,
                    is_short=entry.is_short,
                    status="ignored" if beyond_backfill else "pending",
                    reason="predates the backfill window" if beyond_backfill else None,
                    processed_at=utcnow() if beyond_backfill else None,
                )
            )
            if not beyond_backfill:
                result.discovered += 1

        if not channel.title and feed.channel_title:
            channel.title = feed.channel_title
        channel.last_checked_at = utcnow()
        channel.last_error = None
        result.channels_checked += 1
        session.flush()


def _fill_missing_details(session: Session, client: YouTubeClient, result: SyncResult) -> None:
    """Fetch avatars, handles and about text for channels added by bare id.

    The Atom feed gives a title and nothing else, so a channel added by its
    UC… id has no picture. Fifty of them cost one quota unit, and it only
    happens once per channel. A NULL description also counts as missing, so
    channels tracked before there was such a column get filled in too.
    """
    if not client.can_read:
        return
    missing = list(
        session.scalars(
            select(Channel)
            .where(or_(Channel.thumbnail_url.is_(None), Channel.description.is_(None)))
            .order_by(Channel.id)
        )
    )
    if not missing or not quota.can_afford(session, 1, use_reserve=True):
        return

    try:
        found = client.get_channels([channel.channel_id for channel in missing])
    except Exception as exc:
        # Cosmetic enrichment: whatever goes wrong here, the videos still matter.
        log.warning("could not look up channel details: %s", exc)
        return

    for channel in missing:
        info = found.get(channel.channel_id)
        if info is None:
            continue
        channel.thumbnail_url = info.thumbnail_url
        channel.handle = channel.handle or info.handle
        # "" is a real answer here — the channel simply has no about text —
        # so store it rather than leaving NULL and asking again next run.
        channel.description = info.description or ""
        if info.title:
            channel.title = channel.title or info.title
    session.flush()


# -- phase 2: filter and insert -------------------------------------------


def _retry_deferred(
    session: Session, client: YouTubeClient, result: SyncResult, added_per_playlist: dict
) -> bool:
    """Finish placements an earlier run started but could not complete.

    A row with no item id, never removed and not out of attempts is one a past
    run meant to insert and could not — quota ran out mid-video, or the call
    failed. Playlists assigned to a channel *after* a video was handled have no
    such row, which is what stops a new playlist backfilling years of history.

    Returns True if quota ran out again, so the caller stops there.
    """
    open_placements = list(
        session.scalars(
            select(Placement)
            .options(selectinload(Placement.video), selectinload(Placement.playlist))
            .join(Video, Video.id == Placement.video_pk)
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

    for index, placement in enumerate(open_placements):
        already_local = placement.is_offline
        cap = placement.playlist.max_per_run or 0
        if cap and added_per_playlist.get(placement.playlist_pk, 0) >= cap:
            continue  # this playlist has had its fill for the run

        if placement.playlist.is_generic or not client.has_write_access:
            if already_local:
                continue  # readable in De-Algo already; nothing more to do here
            placement.playlist_item_id = _local_item_id(placement.video, placement.playlist)
            placement.error = None
            placement.added_at = utcnow()
            added_per_playlist[placement.playlist_pk] = (
                added_per_playlist.get(placement.playlist_pk, 0) + 1
            )
            result.added += 1
            session.flush()
            continue

        if not quota.can_afford(session, QUOTA_COST_INSERT):
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
        except YouTubeAPIError as exc:
            if exc.is_quota_error:
                quota.mark_exhausted(session)
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

        placement.playlist_item_id = item_id
        placement.error = None
        placement.added_at = utcnow()
        added_per_playlist[placement.playlist_pk] = (
            added_per_playlist.get(placement.playlist_pk, 0) + 1
        )
        result.added += 1
        session.flush()
    return False


def _publish(session: Session, client: YouTubeClient, settings, result: SyncResult) -> None:
    added_per_playlist: dict[int, int] = {}
    if _retry_deferred(session, client, result, added_per_playlist):
        return

    # Channel priority decides who gets in first when the budget is short;
    # within a channel it stays chronological, so playlists read in order.
    # With every channel left at the default priority this is exactly
    # chronological, which is what it was before priorities existed.
    pending = list(
        session.scalars(
            select(Video)
            .join(Channel, Channel.id == Video.channel_pk)
            .options(selectinload(Video.placements), selectinload(Video.channel).selectinload(Channel.playlists))
            .where(Video.status == "pending")
            .order_by(Channel.priority.asc(), Video.published_at.asc(), Video.id.asc())
        )
    )
    if not pending:
        return

    details = {}
    if client.can_read and quota.can_afford(session, 1, use_reserve=True):
        try:
            details = client.video_details([v.video_id for v in pending])
        except YouTubeAPIError as exc:
            log.warning("could not load video details: %s", exc)
            result.messages.append("Video details unavailable; duration filters were not applied.")

    # Read each target playlist once, so videos already in it (added by hand, or
    # by a previous install) are adopted rather than inserted twice.
    existing: dict[int, dict[str, str]] = {}
    unreadable: set[int] = set()

    def playlist_contents(playlist: Playlist) -> dict[str, str] | None:
        if playlist.is_generic:
            return {}  # nothing outside De-Algo to reconcile against
        if playlist.id in existing:
            return existing[playlist.id]
        if playlist.id in unreadable:
            return None
        try:
            items = client.playlist_items(playlist.playlist_id)
        except YouTubeAPIError as exc:
            unreadable.add(playlist.id)
            playlist.last_error = str(exc)
            result.messages.append(f"Could not read {playlist.title!r}: {exc}")
            return None
        playlist.last_error = None
        existing[playlist.id] = {item.video_id: item.item_id for item in items}
        return existing[playlist.id]

    added_per_channel: dict[int, int] = {}
    quota_exhausted = False

    for video in pending:
        if quota_exhausted:
            break
        channel = video.channel
        detail = details.get(video.video_id)
        if detail is not None:
            video.duration_sec = detail.duration_sec
            if detail.title:
                video.title = detail.title

        if detail is None and client.can_read:
            _reject(video, result, "video is unavailable (private, deleted, or region blocked)")
            continue

        decision = filters.evaluate(
            title=video.title,
            duration_sec=video.duration_sec,
            live_state=detail.live_state if detail else None,
            is_short=video.is_short,
            title_include=channel.title_include,
            title_exclude=channel.title_exclude,
            min_duration_sec=channel.min_duration_sec,
            max_duration_sec=channel.max_duration_sec,
            skip_shorts=channel.skip_shorts,
            skip_live=channel.skip_live,
            skip_videos=channel.skip_videos,
            shorts_max_seconds=settings.shorts_max_seconds,
        )
        if not decision.accept:
            _reject(video, result, decision.reason or "filtered out")
            continue

        targets = sorted(channel.targets, key=lambda p: (p.priority, p.id))
        if not targets:
            # Stays pending: assigning a playlist later picks it up.
            continue

        cap = channel.max_per_run or 0
        if cap and added_per_channel.get(channel.id, 0) >= cap:
            continue

        placed = {p.playlist_pk: p for p in video.placements}
        landed = False
        deferred = 0
        errors = 0
        for playlist in targets:
            if playlist.id in placed:
                landed = landed or placed[playlist.id].playlist_item_id is not None
                continue

            local = playlist.is_generic or not client.has_write_access
            if local:
                # No API call, no quota: the placement is the whole act. With
                # no account that goes for every feed, so the app keeps working
                # and the videos are readable in De-Algo either way.
                cap = playlist.max_per_run or 0
                if cap and added_per_playlist.get(playlist.id, 0) >= cap:
                    session.add(Placement(video_pk=video.id, playlist_pk=playlist.id))
                    deferred += 1
                    session.flush()
                    continue
                placement = Placement(
                    video_pk=video.id,
                    playlist_pk=playlist.id,
                    playlist_item_id=_local_item_id(video, playlist),
                    added_at=utcnow(),
                )
                session.add(placement)
                placed[playlist.id] = placement
                added_per_playlist[playlist.id] = added_per_playlist.get(playlist.id, 0) + 1
                landed = True
                result.added += 1
                session.flush()
                continue

            cap = playlist.max_per_run or 0
            if cap and added_per_playlist.get(playlist.id, 0) >= cap:
                # Record what this playlist still owes so the next run finishes
                # it, exactly as a quota stop does.
                session.add(Placement(video_pk=video.id, playlist_pk=playlist.id))
                deferred += 1
                session.flush()
                continue

            contents = playlist_contents(playlist)
            if contents is None:
                continue

            if video.video_id in contents:
                session.add(
                    Placement(
                        video_pk=video.id,
                        playlist_pk=playlist.id,
                        playlist_item_id=contents[video.video_id],
                        added_at=utcnow(),
                        removal_reason=None,
                    )
                )
                landed = True
                continue

            if not quota.can_afford(session, QUOTA_COST_INSERT):
                # Stop cleanly on our own ledger rather than being refused, and
                # leave a marker for every playlist this video still owes so the
                # next run finishes the job instead of forgetting it.
                deferred += _defer(session, video, targets, placed)
                result.stopped_on_quota = True
                result.messages.append(
                    f"YouTube API quota is spent; {_still_queued(session)} video(s) wait for the "
                    f"reset {quota.describe_reset()}."
                )
                log.info("insert budget reached, pausing until quota resets")
                quota_exhausted = True
                break

            try:
                item_id = client.insert_playlist_item(playlist.playlist_id, video.video_id)
            except YouTubeAPIError as exc:
                if exc.is_quota_error:
                    quota.mark_exhausted(session)
                    deferred += _defer(session, video, targets, placed)
                    result.stopped_on_quota = True
                    result.messages.append(
                        f"YouTube refused further writes: the daily quota is gone. Queued videos "
                        f"resume after the reset {quota.describe_reset()}."
                    )
                    log.warning("quota exhausted, stopping insert phase")
                    quota_exhausted = True
                    break
                errors += 1
                placement = Placement(
                    video_pk=video.id,
                    playlist_pk=playlist.id,
                    attempts=1,
                    error=str(exc),
                )
                session.add(placement)
                log.warning(
                    "insert failed for %s into %s: %s", video.video_id, playlist.title, exc
                )
                continue

            placement = Placement(
                video_pk=video.id,
                playlist_pk=playlist.id,
                playlist_item_id=item_id,
                added_at=utcnow(),
            )
            session.add(placement)
            placed[playlist.id] = placement
            contents[video.video_id] = item_id
            added_per_playlist[playlist.id] = added_per_playlist.get(playlist.id, 0) + 1
            landed = True
            result.added += 1

        session.flush()
        if landed:
            video.status = "added"
            video.reason = None
            video.processed_at = utcnow()
            added_per_channel[channel.id] = added_per_channel.get(channel.id, 0) + 1
        elif deferred and not errors:
            # Held back by a cap or by quota, not broken: it stays pending and
            # the placements it owes are filled on a later run.
            pass
        else:
            video.attempts += 1
            failures = [p.error for p in video.placements if p.error]
            video.reason = failures[0] if failures else video.reason
            if video.attempts >= MAX_INSERT_ATTEMPTS:
                video.status = "failed"
                video.processed_at = utcnow()
                result.failed += 1
        session.flush()


def _defer(session: Session, video: Video, targets, placed: dict) -> int:
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


def _local_item_id(video: Video, playlist: Playlist) -> str:
    """A stand-in for the YouTube item id, so a local placement reads as filled.

    A generic feed is local for good. A YouTube feed filled while signed out is
    local for now, and says so, so a run with an account can finish the job.
    """
    prefix = GENERIC_ITEM_PREFIX if playlist.is_generic else OFFLINE_ITEM_PREFIX
    return f"{prefix}{playlist.id}-{video.id}"


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
    for placement in held[: max(0, len(held) - limit)]:
        placement.playlist_item_id = None
        placement.removed_at = utcnow()
        placement.removal_reason = "removed to stay under the size cap"
        result.pruned += 1
    session.flush()


def _still_queued(session: Session) -> int:
    return session.scalar(select(func.count(Video.id)).where(Video.status == "pending")) or 0


def _reject(video: Video, result: SyncResult, reason: str) -> None:
    video.status = "skipped"
    video.reason = reason
    video.processed_at = utcnow()
    result.skipped += 1


# -- phase 3: keep the playlist to size -----------------------------------


def _prune(session: Session, client: YouTubeClient, playlists, result: SyncResult) -> None:
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
        except YouTubeAPIError as exc:
            result.messages.append(f"Could not read {playlist.title!r} for pruning: {exc}")
            continue

        overflow = len(items) - limit
        if overflow <= 0:
            continue

        # De-Algo appends oldest-first, so the front of the playlist is the oldest.
        for item in sorted(items, key=lambda i: i.position)[:overflow]:
            if not quota.can_afford(session, QUOTA_COST_DELETE):
                result.stopped_on_quota = True
                result.messages.append("Quota ran out before pruning finished.")
                return
            try:
                client.delete_playlist_item(item.item_id)
            except YouTubeAPIError as exc:
                if exc.is_quota_error:
                    quota.mark_exhausted(session)
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
