"""Phase one: reading each source that is due, and keeping what is new."""

from __future__ import annotations

import datetime as dt
import json
import logging
from collections.abc import Collection
from hashlib import sha1

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import (
    Channel,
    Video,
    to_naive_utc,
    utcnow,
)
from ...plugins import registry
from ...sources import items, patience, syndication
from .. import graph, runlog
from ..scope import OwnerId, owned
from .posts import discover_posts
from .progress import note, note_polled, note_unreachable
from .reasons import TOO_OLD
from .result import SyncResult

log = logging.getLogger(__name__)


# What an item from somewhere other than YouTube is addressed by, so an id
# from a feed can never be mistaken for a video id.
ITEM_PREFIX = "item-"


def _poll(channel: Channel, http: httpx.Client) -> items.Batch:
    """Read whatever kind of feed this source publishes.

    Its plugin's `refine` adds what only it knows about each entry — the id
    to file it under, a hint about what it is. Everything else is a feed
    like any other, and is read as one.
    """

    found = _read_feed(channel, http)
    known = registry.current()
    return items.Batch(
        key=channel.channel_id,
        title=found.title,
        entries=[
            _as_entry(channel, item, known.refine(channel.source_kind, _shown(item)))
            for item in found.items
        ],
    )


def _shown(item: syndication.Item) -> dict[str, object]:
    """One entry as a plugin sees it: what the feed said, and nothing else."""
    return {
        "guid": item.guid,
        "title": item.title,
        "link": item.link or "",
        "summary": item.summary or "",
    }


def _as_entry(
    channel: Channel, item: syndication.Item, said: dict[str, object]
) -> items.Entry:
    """What the feed gave, with what its plugin knows laid over the top.

    Only the fields a plugin actually named: a kind with nothing to say about
    an item leaves its `hint` empty rather than having to say so, and one with
    no opinion about ids gets the hash every other source gets.
    """
    given = str(said.get("id") or "").strip()
    return items.Entry(
        id=given or _item_id(channel, item),
        title=item.title,
        published_at=item.published_at,
        thumbnail_url=item.thumbnail_url,
        hint=str(said.get("hint") or "")[:16],
        kind=str(said.get("kind") or "link"),
        link=item.link,
        summary=item.summary,
        images=tuple(item.images),
    )


def _read_feed(channel: Channel, http: httpx.Client) -> syndication.Feed:
    """The source's own feed, or its mirror when the source will not have us.

    Tried in that order and never the other way round: the mirror is somebody
    else's copy, a step further from the truth and a service we do not run. It
    earns its place only when the first answer is "not now".

    A mirror that also refuses is not worth a second complaint — the original
    refusal is the one worth reporting, so that is the one that is raised.
    """
    try:
        return syndication.fetch(channel.feed_url, http)
    except (patience.RateLimited, httpx.HTTPStatusError) as refused:
        mirror = (channel.mirror_url or "").strip()
        if not mirror or not _is_a_refusal(refused):
            raise
        log.info("%s refused us; trying its mirror", channel.channel_id)
        try:
            return syndication.fetch(mirror, http)
        except Exception:  # refused, unreachable, or not a feed at all
            raise refused from None


def _is_a_refusal(exc: Exception) -> bool:
    """Whether this is "not now" rather than "not here".

    A mirror routes around a host that will not have us. It cannot help with a
    feed that has genuinely gone, and trying it on a 404 would only hide a
    source that needs fixing.
    """
    if isinstance(exc, patience.RateLimited):
        return True
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return status in patience.REFUSALS


def _item_id(channel: Channel, item: syndication.Item) -> str:
    """An id for an item that has no video id.

    The feed's own guid, hashed under a prefix so it fits the column and can
    never be mistaken for a video id. The source is part of what is hashed, so
    two feeds that happen to publish the same guid stay apart.
    """
    made = sha1(f"{channel.channel_id}|{item.guid}".encode()).hexdigest()[:24]
    return f"{ITEM_PREFIX}{made}"


def _channel_due(
    channel: Channel, plan: dict[int, list[graph.When]], now: dt.datetime
) -> bool:
    """Whether this channel wants polling now.

    The trigger boxes wired to it decide, and any one of them saying yes is
    enough. With none wired, nothing polls it: a trigger is how a run starts,
    and a source quietly fetched on a schedule drawn nowhere is a source
    filling feeds for reasons the canvas cannot explain.

    A forced run never asks — pressing a button is the whole schedule.
    """
    wired = plan.get(channel.id)
    if not wired:
        return False
    return any(when.due(channel.last_checked_at, now) for when in wired)


def discover(
    session: Session,
    http: httpx.Client,
    result: SyncResult,
    *,
    backfill: int,
    force: bool = False,
    owner: OwnerId = None,
    only: Collection[int] | None = None,
    reach_back: int | None = None,
    pen: runlog.Pen | None = None,
) -> None:
    """Poll every source that is due, and keep what is new in each."""
    say = pen or runlog.Quiet()
    plan = graph.polling_plan(session, owner)
    now = utcnow()
    for channel in _enabled(session, owner):
        if only is not None and channel.id not in only:
            continue
        if not force and not _channel_due(channel, plan, now):
            # Its gap has not elapsed, or a pulse is the only thing that polls
            # it. Polling is free, so this is about how often the user wants to
            # hear from a channel, not about cost.
            result.channels_waiting += 1
            say.write(
                "nothing polls this — wire a trigger to it"
                if not plan.get(channel.id)
                else "not due yet, so it was left alone",
                about=channel.title,
            )
            continue
        note(channel_pk=channel.id)
        feed = _read_or_say_why(channel, http, result, say)
        if feed is None:
            continue
        _take_in(
            session, channel, feed, result, say,
            owner=owner, backfill=backfill, reach_back=reach_back, now=now,
        )


def _enabled(session: Session, owner: OwnerId) -> list[Channel]:
    """The account's switched-on sources, in fill order."""
    return list(
        session.scalars(
            owned(select(Channel), Channel, owner)
            .where(Channel.enabled.is_(True))
            .order_by(Channel.priority, Channel.id)
        )
    )


def _read_or_say_why(
    channel: Channel, http: httpx.Client, result: SyncResult, say: runlog.Pen | runlog.Quiet
) -> items.Batch | None:
    """The source's feed, or nothing — with why said on the source and in the log."""
    try:
        return _poll(channel, http)
    except patience.RateLimited as held:
        # Not an error and not a failure: a host asked us to wait and we
        # did. Said out loud, because a source that quietly does nothing
        # for a minute is indistinguishable from one that is broken.
        why = f"waiting {round(held.seconds)}s — {held.host} limits how often it is asked"
        # On the channel too, so its page answers "why is this quiet?".
        # Cleared by the next poll that gets through, like any other.
        channel.last_error = why
        result.messages.append(f"{channel.title}: {why}.")
        note_unreachable(channel.id, why)
        say.warn(why, about=channel.title)
    except httpx.HTTPError as exc:
        why = _why_unreachable(exc)
        channel.last_error = f"{why}: {exc}"
        result.messages.append(f"{channel.title}: {why}.")
        note_unreachable(channel.id, why)
        say.bad(f"{why} ({channel.feed_url})", about=channel.title)
        log.warning("feed fetch failed for %s: %s", channel.channel_id, exc)
    except Exception as exc:  # malformed XML, etc.
        channel.last_error = f"feed unreadable: {exc}"
        result.messages.append(f"{channel.title}: feed unreadable.")
        note_unreachable(channel.id, "feed unreadable")
        say.bad(f"what came back was not a feed: {exc}", about=channel.title)
        log.warning("feed parse failed for %s: %s", channel.channel_id, exc)
    return None


def _take_in(
    session: Session,
    channel: Channel,
    feed: items.Batch,
    result: SyncResult,
    say: runlog.Pen | runlog.Quiet,
    *,
    owner: OwnerId,
    backfill: int,
    reach_back: int | None,
    now: dt.datetime,
) -> None:
    """Everything one feed's reading leads to, and the source marked as checked."""
    if reach_back is not None:
        # What was passed over as too old is exactly what is being asked
        # for, so that many of them come back.
        revived = _unignore(session, channel, owner, limit=reach_back)
        result.discovered += revived
        if revived:
            say.write(
                f"brought back {revived} that an earlier run thought too old",
                about=channel.title,
            )

    first_check = channel.last_checked_at is None
    cutoff = None
    if reach_back is not None:
        # Age stops deciding: how many were asked for is what decides.
        first_check = True
        backfill = reach_back or len(feed.entries)
    elif first_check and channel.backfill_days is not None:
        # A channel can ask for a window of history instead of a count. The
        # feed only lists the newest ~15 uploads either way, so a long window
        # reaches as far as that and no further.
        cutoff = now - dt.timedelta(days=max(0, channel.backfill_days))

    found, filled = _keep_what_is_new(
        session, channel, feed, owner,
        first_check=first_check, backfill=backfill, cutoff=cutoff,
    )
    result.discovered += found

    # Some sources keep things their feed does not carry — YouTube's
    # community posts are the one shipped example. Whether this is such
    # a source is the plugin's to say, and whether they are still wanted is
    # whether every kind it marks as an extra is left out.
    if channel.wants_extras and registry.current().has_extras(channel.source_kind):
        discover_posts(
            session, channel, result,
            first_check=first_check, backfill=backfill, owner=owner,
        )

    if filled:
        say.write(
            f"filled in a picture for {filled} already here", about=channel.title
        )
    if not channel.title and feed.title:
        channel.title = feed.title
    say.write(
        f"read {len(feed.entries)} from the feed; {found} of them new"
        if found
        else f"read {len(feed.entries)} from the feed; nothing new",
        about=channel.title,
    )
    channel.last_checked_at = utcnow()
    channel.last_error = None
    result.channels_checked += 1
    note_polled(channel.id, found)
    session.flush()


def _keep_what_is_new(
    session: Session,
    channel: Channel,
    feed: items.Batch,
    owner: OwnerId,
    *,
    first_check: bool,
    backfill: int,
    cutoff: dt.datetime | None,
) -> tuple[int, int]:
    """Store each entry not seen before; refresh the ones that were.

    Returns how many were new and inside the backfill, and how many already
    here had something filled in.
    """
    # The rows themselves rather than their ids: an entry we have seen
    # before may still be carrying something we did not know how to read
    # when we first stored it.
    already = {
        video.video_id: video
        for video in session.scalars(
            owned(select(Video), Video, owner).where(
                Video.video_id.in_([e.id for e in feed.entries] or [""])
            )
        )
    }

    found = 0
    filled = 0
    for index, entry in enumerate(feed.entries):
        seen = already.get(entry.id)
        if seen is not None:
            filled += _freshen(seen, entry)
            continue
        if cutoff is not None:
            published = to_naive_utc(entry.published_at)
            beyond_backfill = published is None or published < cutoff
        else:
            beyond_backfill = first_check and index >= max(0, backfill)
        session.add(
            Video(
                owner_pk=owner,
                video_id=entry.id,
                channel_pk=channel.id,
                title=entry.title,
                published_at=to_naive_utc(entry.published_at),
                thumbnail_url=entry.thumbnail_url,
                hint=entry.hint or None,
                kind=entry.kind,
                link=entry.link,
                body=entry.summary,
                images=json.dumps(list(entry.images)) if entry.images else None,
                status="ignored" if beyond_backfill else "pending",
                reason=TOO_OLD if beyond_backfill else None,
                processed_at=utcnow() if beyond_backfill else None,
            )
        )
        if not beyond_backfill:
            found += 1
    return found, filled


def _why_unreachable(exc: httpx.HTTPError) -> str:
    """What went wrong, in words that say what to do about it.

    Being rate limited and being blocked are not the same as a feed that has
    gone, and neither is a channel id that was wrong from the start — telling
    them apart is the difference between waiting and going to look.
    """
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status == 429:
        wait = patience.wait_for(str(getattr(getattr(exc, "response", None), "url", "")))
        if wait > 0:
            return f"asked too often — waiting {round(wait)}s before trying again"
        return "asked too often — it is rate limiting us"
    if status in (401, 403):
        return "refused us"
    if status == 404:
        return "no feed there any more"
    if status is not None and status >= 500:
        return "its server is having trouble"
    return "feed unreachable"


def _freshen(video: Video, entry: items.Entry) -> int:
    """Fill in what we did not know how to read the first time.

    A feed is re-read every poll and keeps saying the same things about the
    same items, so an entry already stored is a second chance at anything we
    have since learned to take from it — pictures, most of all, which were
    being thrown away before there was anywhere to put them.

    The feed's current answer wins, rather than only filling a blank. Nothing
    in the app lets a person write any of these fields, so what is on the row
    came from an earlier reading of this same entry — and an earlier reading
    is exactly what is being corrected. A row stored before the words were
    unescaped keeps its "&#32;" for ever under a fill-only rule.

    Never replaces something with nothing, though: a parse that comes back
    empty is a reason to keep what we have, not to throw it away.
    """
    gained = 0
    fresh = json.dumps(list(entry.images)) if entry.images else None

    if entry.thumbnail_url and video.thumbnail_url != entry.thumbnail_url:
        video.thumbnail_url = entry.thumbnail_url
        gained = 1
    if fresh and video.images != fresh:
        video.images = fresh
        gained = 1
    if entry.summary and video.body != entry.summary:
        video.body = entry.summary
    if entry.link and video.link != entry.link:
        video.link = entry.link
    return gained


def _unignore(
    session: Session, channel: Channel, owner: OwnerId = None, *, limit: int = 0
) -> int:
    """Bring back what an earlier run set aside for being older than wanted.

    The newest ``limit`` of them, or all of them when that is zero — the same
    count the caller asked for of the feed itself, so "the latest 25" means
    the same thing on both halves of what a backfill looks at.

    Only that: something skipped by a filter was a decision about the thing
    itself and reaching further back is no argument against it. This undoes
    one judgement — "before your time" — which is the one being revisited.
    """
    asking = (
        owned(select(Video), Video, owner)
        .where(
            Video.channel_pk == channel.id,
            Video.status == "ignored",
            Video.reason == TOO_OLD,
        )
        .order_by(Video.published_at.desc().nullslast(), Video.id.desc())
    )
    if limit > 0:
        asking = asking.limit(limit)
    stranded = list(session.scalars(asking))
    for video in stranded:
        video.status = "pending"
        video.reason = None
        video.attempts = 0
        video.processed_at = None
    session.flush()
    return len(stranded)
