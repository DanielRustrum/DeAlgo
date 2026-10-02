"""Phase two: putting each waiting item into every feed its paths say it belongs in."""

from __future__ import annotations

import logging
from collections.abc import Collection, Sequence
from typing import TYPE_CHECKING

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from ...models import (
    GENERIC_ITEM_PREFIX,
    OFFLINE_ITEM_PREFIX,
    Channel,
    Placement,
    Playlist,
    Settings,
    Video,
    utcnow,
)
from ...plugins.publisher import Publisher, PublishError, cost_of
from .. import graph, quota, runlog
from ..scope import OwnerId, belongs_to, owned
from .deciding import attribute, decide, reject
from .expiry import stamp_expiry
from .ordering import reorder
from .progress import note_left, note_placed
from .reasons import WRONG_KIND_OF_FEED
from .repositories import deposit
from .stamps import apply_stamps

if TYPE_CHECKING:
    from .result import SyncResult, Tally

log = logging.getLogger(__name__)


MAX_INSERT_ATTEMPTS = 3


def _reconsider_routing(session: Session, result: SyncResult, owner: OwnerId = None) -> int:
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


def _retry_deferred(
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
    open_placements = list(
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
            note_placed(placement.playlist_pk)
            result.added += 1
            session.flush()
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

        placement.playlist_item_id = item_id
        placement.error = None
        placement.added_at = utcnow()
        added_per_playlist[placement.playlist_pk] = (
            added_per_playlist.get(placement.playlist_pk, 0) + 1
        )
        note_placed(placement.playlist_pk)
        result.added += 1
        session.flush()
    return False


def publish(
    session: Session,
    client: Publisher,
    settings: Settings,
    result: SyncResult,
    owner: OwnerId = None,
    pen: runlog.Pen | None = None,
    sources: Collection[int] | None = None,
) -> None:
    say = pen or runlog.Quiet()
    added_per_playlist: dict[int, int] = {}
    if _retry_deferred(session, client, result, added_per_playlist, owner):
        return

    brought = _reconsider_routing(session, result, owner)
    if brought:
        say.write(f"{brought} item(s) had nowhere to go before, and now do")

    # Channel priority decides who gets in first when the budget is short;
    # within a channel it stays chronological, so playlists read in order.
    # With every channel left at the default priority this is exactly
    # chronological, which is what it was before priorities existed.
    pending = list(
        session.scalars(
            owned(select(Video), Video, owner)
            .join(Channel, Channel.id == Video.channel_pk)
            .options(selectinload(Video.placements), selectinload(Video.channel).selectinload(Channel.playlists))
            .where(Video.status == "pending")
            .order_by(Channel.priority.asc(), Video.published_at.asc(), Video.id.asc())
        )
    )
    if not pending:
        say.write("nothing was waiting to be filed")
        return
    say.write(f"{len(pending)} waiting to be filed")

    # Read once: walking the graph per video would be the same answer many
    # times over.
    routes_for: dict[int, list[graph.Route]] = {}
    for path in graph.routes(session, owner):
        # Set off from a trigger, this run belongs to the boxes that trigger
        # is wired to. A channel drawn twice is one channel and two boxes,
        # each starting a path of its own, and only one of them was asked to
        # run — the other waits for whatever sets it off.
        if sources is not None and (path.source is None or path.source.id not in sources):
            continue
        # A path into a repository has no feed to be switched off; whether it
        # is live is the Deposit box's own switch, which the walk checked.
        if path.deposits or (path.playlist is not None and path.playlist.enabled):
            routes_for.setdefault(path.channel.id, []).append(path)


    details = {}
    # Only a YouTube video has details to read; a post has none, and an item
    # from somewhere else is not YouTube's to answer for.
    clips = [v.video_id for v in pending if v.kind == "video"]
    if clips and client.can_read and quota.can_afford(session, 1, use_reserve=True, owner=owner):
        try:
            details = client.video_details(clips)
        except PublishError as exc:
            log.warning("could not load video details: %s", exc)
            result.messages.append("Video details unavailable; duration filters were not applied.")

    # What YouTube said goes onto the videos before anything reads it: a sort
    # box orders by duration and by counts, and those arrive here. Left until
    # the loop below, the first run of a new batch would sort it by nothing.
    for video in pending:
        arrived = details.get(video.video_id)
        if arrived is None:
            continue
        video.duration_sec = arrived.duration_sec
        video.view_count = arrived.view_count
        video.like_count = arrived.like_count
        if arrived.title:
            video.title = arrived.title

    reorder(pending, routes_for)

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
        except PublishError as exc:
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
        if detail is None and client.can_read and video.kind == "video":
            reject(video, result, "video is unavailable (private, deleted, or region blocked)")
            continue

        # One decision per path, not one per video: the same channel can reach
        # two feeds through filters that disagree, and a video turned away at
        # one of them still belongs in the other.
        paths = routes_for.get(channel.id, [])
        if not paths:
            # Stays pending: wiring it to a feed later picks it up.
            continue

        # What the channel itself thinks of this one, before any filter box
        # has a say. That is what "left the channel" means, and it is the
        # difference between a quiet channel and one turning its own uploads
        # away.
        own_rules = graph.Route(
            channel=channel,
            playlist=paths[0].playlist,
            store=paths[0].store,
            filters=[],
        )
        if decide(video, own_rules, detail, settings).accept:
            note_left(channel.id)

        allowed: list[Playlist] = []
        taking: list[graph.Route] = []
        stored: list[graph.Route] = []
        refusals: list[str] = []
        for path in paths:
            decision = decide(video, path, detail, settings)
            attribute(video, path, detail, settings)
            if not decision.accept:
                if decision.reason:
                    refusals.append(decision.reason)
            elif path.deposits:
                stored.append(path)
            elif path.playlist is not None:
                allowed.append(path.playlist)
                taking.append(path)

        # What the boxes on the paths that took it said about it. Done for
        # the item as a whole rather than per feed: a tag is a property of
        # the thing, and how long you get with it is a property of reading
        # it, neither of which is a fact about one feed.
        apply_stamps(session, video, taking + stored, owner)

        if not allowed and not stored:
            # Every path said no; the first reason is the one worth showing.
            why = refusals[0] if refusals else "filtered out"
            reject(video, result, why)
            say.write(f"held back — {why}", about=video.title or video.video_id)
            continue

        # Into the repositories first: nothing is sent anywhere for these, so
        # a quota stop partway through the feeds cannot lose them.
        held = deposit(session, video, stored, owner)
        if held:
            result.deposited += held

        going = sorted(p.title for p in allowed)
        waiting = sorted({path.store for path in stored})
        say.write(
            "goes to " + ", ".join(going + [f"the {name} repository" for name in waiting]),
            about=video.title or video.video_id,
        )

        if video.is_post:
            place_locally(
                session, video, channel, result, added_per_playlist, added_per_channel, allowed
            )
            continue

        # De-duplicated, and in fill order: two paths may end at one feed.
        targets = sorted({p.id: p for p in allowed}.values(), key=lambda p: (p.priority, p.id))

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

            if not quota.can_afford(session, cost_of("add"), owner=owner):
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
            except PublishError as exc:
                if exc.is_quota_error:
                    quota.mark_exhausted(session, owner)
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

        stamp_expiry(session, video, taking)

        session.flush()
        if landed or (held and not allowed):
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


def place_locally(
    session: Session,
    video: Video,
    channel: Channel,
    result: SyncResult,
    added_per_playlist: Tally,
    added_per_channel: Tally,
    targets: Sequence[Playlist] | None = None,
) -> None:
    """Put a community post into each of its channel's feeds.

    Posts never reach YouTube — there is no playlist that takes them — so this
    is the whole act: no API call, no quota, no deferral. What is left over
    after a cap is simply picked up by the next run, like anything else.
    """
    reachable = list(targets) if targets is not None else channel.targets
    ordered = sorted({p.id: p for p in reachable}.values(), key=lambda p: (p.priority, p.id))
    if not ordered:
        return  # stays pending until the channel is wired to a feed

    cap = channel.max_per_run or 0
    if cap and added_per_channel.get(channel.id, 0) >= cap:
        return

    placed = {p.playlist_pk for p in video.placements}
    landed = False
    for playlist in ordered:
        if playlist.id in placed:
            continue
        limit = playlist.max_per_run or 0
        if limit and added_per_playlist.get(playlist.id, 0) >= limit:
            continue
        session.add(
            Placement(
                video_pk=video.id,
                playlist_pk=playlist.id,
                playlist_item_id=_local_item_id(video, playlist),
                added_at=utcnow(),
            )
        )
        added_per_playlist[playlist.id] = added_per_playlist.get(playlist.id, 0) + 1
        landed = True
        result.added += 1

    session.flush()
    if landed:
        video.status = "added"
        video.reason = None
        video.processed_at = utcnow()
        added_per_channel[channel.id] = added_per_channel.get(channel.id, 0) + 1
        session.flush()


def _defer(
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


def _local_item_id(video: Video, playlist: Playlist) -> str:
    """A stand-in for the YouTube item id, so a local placement reads as filled.

    A generic feed is local for good. A YouTube feed filled while signed out is
    local for now, and says so, so a run with an account can finish the job.
    """
    # A post is local for good: nothing on YouTube can hold one, so it must
    # never be marked as owed to a playlist the way a signed-out video is.
    local_for_good = playlist.is_generic or video.is_post
    prefix = GENERIC_ITEM_PREFIX if local_for_good else OFFLINE_ITEM_PREFIX
    return f"{prefix}{playlist.id}-{video.id}"


def _still_queued(session: Session) -> int:
    return session.scalar(select(func.count(Video.id)).where(Video.status == "pending")) or 0
