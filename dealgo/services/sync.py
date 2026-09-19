"""The sync engine: poll feeds, filter, and push new uploads into the playlist.

One run is a single pass over every enabled channel. It is deliberately
restartable — every decision is written to the database as it is made, so a
crash mid-run costs at most the videos still in flight, and nothing is ever
added twice.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import threading
from hashlib import sha1
from contextlib import contextmanager
from collections.abc import Collection, Iterator, Sequence
from dataclasses import dataclass, field, replace

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
    Settings,
    SyncRun,
    Video,
    to_naive_utc,
    utcnow,
)
from ..sources import patience, syndication
from ..youtube import community, feeds
from ..youtube.api import (
    QUOTA_COST_DELETE,
    QUOTA_COST_INSERT,
    VideoDetails,
    YouTubeAPIError,
    YouTubeClient,
)
from . import filters
from . import quota
from . import runlog
from .auth import build_client
from . import graph
from .scope import OwnerId, belongs_to, owned

# How many items each playlist or channel has taken so far this run.
Tally = dict[int, int]

log = logging.getLogger(__name__)

USER_AGENT = "De-Algo/0.1 (personal feed builder)"

# What an item from somewhere other than YouTube is addressed by, so an id
# from a feed can never be mistaken for a video id.
ITEM_PREFIX = "item-"

# Why an item from somewhere other than YouTube was turned away. Named rather
# than written twice: wiring the source to a feed that *can* hold it looks for
# exactly this, so the two must not drift apart.
WRONG_KIND_OF_FEED = "not a YouTube video, and that feed is a YouTube playlist"

# Why something the feed still lists was passed over on the first check. Named
# so that reaching back can find exactly what it set aside and nothing else.
TOO_OLD = "predates the backfill window"
HTTP_TIMEOUT = 30.0
MAX_INSERT_ATTEMPTS = 3

class Busy(RuntimeError):
    """Another playlist operation holds the lock."""


_run_lock = threading.Lock()


@contextmanager
def playlist_lock() -> Iterator[None]:
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
class RunProgress:
    """Where a run has got to, for anything watching it happen.

    Held in memory rather than in the database: it is worth nothing once the
    run is over, it changes many times a second, and a crash mid-run should
    leave no trace of it. What survives a run is the SyncRun row.
    """

    owner: OwnerId = None
    trigger: str = "manual"
    stage: str = "starting"
    #: The trigger box that set this off, when a person pressed one. The
    #: canvas lights it and the wire out of it, so the run reads as starting
    #: somewhere rather than as several boxes changing at once.
    fired_by: int | None = None
    #: The channel being polled right this moment.
    channel_pk: int | None = None
    #: The channels this run has finished with, and what each brought in.
    polled: dict[int, int] = field(default_factory=dict)
    #: The channels it could not read, and what went wrong. A poll that failed
    #: is not a poll that found nothing, and a canvas that drew them the same
    #: way sent people looking for a wiring fault that was not there.
    unreachable: dict[int, str] = field(default_factory=dict)
    #: How many items each feed has taken so far.
    placed: dict[int, int] = field(default_factory=dict)
    #: Items that got past each channel's own settings, by channel. What a
    #: channel found and what left it are different numbers, and the gap
    #: between them is the channel turning its own uploads away.
    left: dict[int, int] = field(default_factory=dict)
    #: Items each filter box let through and turned away, by graph node id.
    #: Kept per box rather than per run so the canvas can say where the flow
    #: stopped, which is the question a filter exists to answer.
    through: dict[int, int] = field(default_factory=dict)
    stopped: dict[int, int] = field(default_factory=dict)
    finished: bool = False
    #: Which run this is. A run is claimed before the thread that will carry
    #: it starts, so only the claimant may declare it over — otherwise a run
    #: that never got going would mark the one in flight finished.
    token: int = 0


_progress: RunProgress | None = None
_next_token = 0
_progress_lock = threading.Lock()


def progress() -> RunProgress | None:
    """A snapshot of the run in flight, or of the one that just ended."""
    with _progress_lock:
        if _progress is None:
            return None
        return replace(
            _progress,
            polled=dict(_progress.polled),
            placed=dict(_progress.placed),
            unreachable=dict(_progress.unreachable),
        )


def claim(owner: OwnerId, trigger: str, fired_by: int | None = None) -> int:
    """Say a run is about to begin, before the thread carrying it has started.

    The canvas asks where the run has got to the moment the button answers. A
    thread takes a little while to get going, and without this the answer
    would be about the *previous* run — which reads exactly like this one
    having finished instantly, with the last run's marks on the boxes.
    """
    global _progress, _next_token
    with _progress_lock:
        _next_token += 1
        _progress = RunProgress(
            owner=owner, trigger=trigger, fired_by=fired_by, token=_next_token
        )
        return _next_token


def _finish(token: int) -> None:
    """Declare a run over, if it is still the run in hand.

    Guarded by the token: a call that never took the lock must not mark
    somebody else's run finished on its way out.
    """
    with _progress_lock:
        if _progress is not None and _progress.token == token:
            _progress.finished = True
            _progress.stage = "done"
            _progress.channel_pk = None


def _note(**fields: object) -> None:
    """Move the run on. Silent when nothing is watching."""
    with _progress_lock:
        if _progress is None:
            return
        for name, value in fields.items():
            setattr(_progress, name, value)


def _note_polled(channel_pk: int, found: int) -> None:
    with _progress_lock:
        if _progress is None:
            return
        _progress.polled[channel_pk] = found
        _progress.channel_pk = None


def _note_unreachable(channel_pk: int, why: str) -> None:
    with _progress_lock:
        if _progress is None:
            return
        _progress.unreachable[channel_pk] = why
        _progress.channel_pk = None


def _note_left(channel_pk: int) -> None:
    with _progress_lock:
        if _progress is None:
            return
        _progress.left[channel_pk] = _progress.left.get(channel_pk, 0) + 1


def _note_filtered(node_pk: int, passed: bool) -> None:
    with _progress_lock:
        if _progress is None:
            return
        tally = _progress.through if passed else _progress.stopped
        tally[node_pk] = tally.get(node_pk, 0) + 1


def _note_placed(playlist_pk: int) -> None:
    with _progress_lock:
        if _progress is None:
            return
        _progress.placed[playlist_pk] = _progress.placed.get(playlist_pk, 0) + 1


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


def run_sync(
    trigger: str = "manual",
    *,
    force: bool = False,
    owner: OwnerId = None,
    only: Collection[int] | None = None,
    fired_by: int | None = None,
    reach_back: int | None = None,
    token: int | None = None,
) -> SyncResult:
    """Run one account's sync pass. Returns at once if a pass is in flight.

    ``force`` polls every enabled channel regardless of its minimum gap. The
    scheduler never forces; this is for someone pressing the button.

    ``only`` narrows the pass to certain channels, by primary key. A trigger
    on the canvas is wired to some channels and not others, and this is how it
    says so. The publishing half still runs over everything, because what a
    new video is allowed into is a question about the whole graph.

    ``fired_by`` is the trigger box somebody pressed, carried through so the
    canvas can light it while its run is going.

    ``reach_back`` is how many of the latest items to run through, rather than
    only what is new: it brings back what an earlier run passed over as too
    old, and takes that many of what each feed lists whatever their age. Zero
    means as far as each feed goes. None is an ordinary run.

    A feed carries its last dozen or two items and no more, so this reaches as
    far as that and no further — it is "catch me up on what is there", not a
    way to read an archive that was never published.

    One account at a time, because everything a pass depends on belongs to
    one: its channels, its feeds, its Google connection and its quota.
    """
    # Claimed here unless the caller claimed it already — which the canvas
    # does, so that what it draws is this run from the first moment it asks.
    mine = claim(owner, trigger, fired_by) if token is None else token
    try:
        with playlist_lock():
            with http_client() as http, session_scope() as session:
                return _run(
                    session, http, trigger, force=force, owner=owner, only=only,
                    fired_by=fired_by, reach_back=reach_back,
                )
    except Busy:
        return SyncResult(ok=True, started=False, messages=["A sync is already running."])
    except Exception as exc:  # pragma: no cover - last-resort guard for the scheduler
        log.exception("sync run failed")
        return SyncResult(ok=False, messages=[f"Sync failed: {exc}"])
    finally:
        # However it ended — done, refused the lock, or thrown out of — a run
        # that is over has to say so, or the canvas watches it for ever.
        _finish(mine)


def owners_with_channels(session: Session) -> list[OwnerId]:
    """Everyone who has something to sync, the implicit owner included."""
    return [
        row for row in session.scalars(select(Channel.owner_pk).distinct().order_by(Channel.owner_pk))
    ]


def run_for_everyone(trigger: str = "scheduled") -> list[SyncResult]:
    """One pass per account, in turn.

    Sequential on purpose: they share a SQLite file and the lock that guards
    playlist writes, and one account's YouTube quota has nothing to say about
    another's. The scheduler calls this; a person pressing Sync now syncs only
    their own.
    """
    with session_scope() as session:
        owners = owners_with_channels(session)

    results = []
    for owner in owners:
        results.append(run_sync(trigger, owner=owner))
    if not owners:
        results.append(run_sync(trigger))  # nothing tracked yet; still report
    return results


def _run(
    session: Session,
    http: httpx.Client,
    trigger: str,
    *,
    force: bool = False,
    owner: OwnerId = None,
    only: Collection[int] | None = None,
    fired_by: int | None = None,
    reach_back: int | None = None,
) -> SyncResult:
    settings = get_settings(session, owner)
    run = SyncRun(trigger=trigger, started_at=utcnow(), forced=force, owner_pk=owner)
    session.add(run)
    session.commit()

    result = SyncResult(forced=force)
    quota_before = quota.state(session, owner).used
    client = build_client(session, http, owner)

    pen = runlog.Pen(session, run.id, owner)
    pen.write(
        f"{run.how} — {'forced' if force else 'on its own terms'}"
        + (f", reaching back through the latest {reach_back}" if reach_back else "")
        + (f", set off by box {fired_by}" if fired_by is not None else "")
    )
    session.commit()

    _note(stage="polling")
    pen.at("polling")
    _discover(
        session, http, result, backfill=settings.initial_backfill, force=force, owner=owner,
        only=only, reach_back=reach_back, pen=pen,
    )
    _note(stage="sorting")
    pen.at("sorting")
    _fill_missing_details(session, client, result, owner)
    session.commit()
    _note(stage="filling")
    pen.at("filling")
    pen.at("filling")

    playlists = list(
        session.scalars(
            owned(select(Playlist), Playlist, owner)
            .where(Playlist.enabled.is_(True))
            .order_by(Playlist.priority, Playlist.id)
        )
    )
    quota_state = quota.state(session, owner)
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
        _publish(session, client, settings, result, owner, pen=pen)
        session.commit()
    elif youtube_feeds and quota_state.spendable < QUOTA_COST_INSERT:
        # Feeds cost nothing, so discovery already ran; only writing stops.
        result.stopped_on_quota = True
        result.messages.append(
            f"YouTube API quota is spent ({quota_state.used}/{quota_state.budget} units). "
            f"Queued videos will be added after it resets {quota.describe_reset()}."
        )
        log.info("skipping the insert phase: quota exhausted until %s", quota_state.resets_at)
        pen.warn(f"YouTube quota is spent ({quota_state.used}/{quota_state.budget} units).")
        _publish(session, client, settings, result, owner, pen=pen)
        session.commit()
    else:
        _publish(session, client, settings, result, owner, pen=pen)
        session.commit()
        _prune(session, client, playlists, result, owner)

    _note(stage="done", finished=True, channel_pk=None)
    pen.at("done")
    pen.write(
        f"Finished: looked at {result.channels_checked}, found {result.discovered}, "
        f"added {result.added}, held back {result.skipped}, failed {result.failed}."
    )
    runlog.prune(session, owner)
    run.finished_at = utcnow()
    run.ok = result.failed == 0 and all("failed" not in m.lower() for m in result.messages)
    run.channels_checked = result.channels_checked
    run.discovered = result.discovered
    run.added = result.added
    run.skipped = result.skipped
    run.failed = result.failed
    run.pruned = result.pruned
    run.quota_spent = max(0, quota.state(session, owner).used - quota_before)
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


def _poll(channel: Channel, http: httpx.Client) -> feeds.FeedResult:
    """Read whatever kind of feed this source publishes.

    YouTube's own reader knows two things the general one cannot: which
    entries are Shorts, and the channel id the feed belongs to. Everything
    else is a feed like any other, and is read as one.
    """
    if channel.is_youtube:
        return feeds.fetch_feed(channel.channel_id, http)

    found = _read_feed(channel, http)
    return feeds.FeedResult(
        channel_id=channel.channel_id,
        channel_title=found.title,
        entries=[
            feeds.FeedEntry(
                video_id=_item_id(channel, item),
                title=item.title,
                published_at=item.published_at,
                thumbnail_url=item.thumbnail_url,
                is_short=False,
                kind="link",
                link=item.link,
                summary=item.summary,
                images=tuple(item.images),
            )
            for item in found.items
        ],
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

    The trigger boxes wired to it have the last word, and any one of them
    saying yes is enough. Without one the channel's own minimum gap decides,
    which is how every setup worked before the canvas had triggers. A forced
    run never asks.
    """
    wired = plan.get(channel.id)
    if wired is None:
        return channel.is_due(now)
    return any(when.due(channel.last_checked_at, now) for when in wired)


def _discover(
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
    say = pen or runlog.Quiet()
    channels = list(
        session.scalars(
            owned(select(Channel), Channel, owner)
            .where(Channel.enabled.is_(True))
            .order_by(Channel.priority, Channel.id)
        )
    )
    plan = graph.polling_plan(session, owner)
    now = utcnow()
    for channel in channels:
        if only is not None and channel.id not in only:
            continue
        if not force and not _channel_due(channel, plan, now):
            # Its gap has not elapsed, or a pulse is the only thing that polls
            # it. Polling is free, so this is about how often the user wants to
            # hear from a channel, not about cost.
            result.channels_waiting += 1
            say.write("not due yet, so it was left alone", about=channel.title)
            continue
        _note(channel_pk=channel.id)
        try:
            feed = _poll(channel, http)
        except patience.RateLimited as held:
            # Not an error and not a failure: a host asked us to wait and we
            # did. Said out loud, because a source that quietly does nothing
            # for a minute is indistinguishable from one that is broken.
            why = f"waiting {round(held.seconds)}s — {held.host} limits how often it is asked"
            # On the channel too, so its page answers "why is this quiet?".
            # Cleared by the next poll that gets through, like any other.
            channel.last_error = why
            result.messages.append(f"{channel.title}: {why}.")
            _note_unreachable(channel.id, why)
            say.warn(why, about=channel.title)
            continue
        except httpx.HTTPError as exc:
            why = _why_unreachable(exc)
            channel.last_error = f"{why}: {exc}"
            result.messages.append(f"{channel.title}: {why}.")
            _note_unreachable(channel.id, why)
            say.bad(f"{why} ({channel.feed_url})", about=channel.title)
            log.warning("feed fetch failed for %s: %s", channel.channel_id, exc)
            continue
        except Exception as exc:  # malformed XML, etc.
            channel.last_error = f"feed unreadable: {exc}"
            result.messages.append(f"{channel.title}: feed unreadable.")
            _note_unreachable(channel.id, "feed unreadable")
            say.bad(f"what came back was not a feed: {exc}", about=channel.title)
            log.warning("feed parse failed for %s: %s", channel.channel_id, exc)
            continue

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
        known = set(
            session.scalars(
                owned(select(Video.video_id), Video, owner).where(
                    Video.video_id.in_([e.video_id for e in feed.entries] or [""])
                )
            )
        )

        # A channel can ask for a window of history instead of a count. The
        # feed only lists the newest ~15 uploads either way, so a long window
        # reaches as far as that and no further.
        cutoff = None
        if reach_back is not None:
            # Age stops deciding: how many were asked for is what decides.
            first_check = True
            backfill = reach_back or len(feed.entries)
        elif first_check and channel.backfill_days is not None:
            cutoff = now - dt.timedelta(days=max(0, channel.backfill_days))

        found = 0
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
                    owner_pk=owner,
                    video_id=entry.video_id,
                    channel_pk=channel.id,
                    title=entry.title,
                    published_at=to_naive_utc(entry.published_at),
                    thumbnail_url=entry.thumbnail_url,
                    is_short=entry.is_short,
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
                result.discovered += 1
                found += 1

        # Community posts are a YouTube idea; elsewhere the feed is all there is.
        if channel.is_youtube and not channel.skip_posts:
            _discover_posts(
                session, http, channel, result,
                first_check=first_check, backfill=backfill, owner=owner,
            )

        if not channel.title and feed.channel_title:
            channel.title = feed.channel_title
        say.write(
            f"read {len(feed.entries)} from the feed; {found} of them new"
            if found
            else f"read {len(feed.entries)} from the feed; nothing new",
            about=channel.title,
        )
        channel.last_checked_at = utcnow()
        channel.last_error = None
        result.channels_checked += 1
        _note_polled(channel.id, found)
        session.flush()


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


def _discover_posts(
    session: Session,
    http: httpx.Client,
    channel: Channel,
    result: SyncResult,
    *,
    first_check: bool,
    backfill: int,
    owner: OwnerId = None,
) -> None:
    """Collect a channel's community posts.

    Scraped, not fetched from an API — there is no API for these — so it is
    wrapped whole: a channel whose posts cannot be read still keeps its videos.
    The backfill rules are the video ones, so tracking a channel does not drop
    a year of its writing into a feed on day one.
    """
    try:
        posts = community.fetch_posts(channel.channel_id, http)
    except Exception as exc:  # the page shape is not ours to rely on
        log.warning("could not read posts for %s: %s", channel.title, exc)
        return
    if not posts:
        return

    known = set(
        session.scalars(
            owned(select(Video.video_id), Video, owner).where(
                Video.video_id.in_([p.post_id for p in posts] or [""])
            )
        )
    )
    for index, post in enumerate(posts):
        if post.post_id in known:
            continue
        beyond_backfill = first_check and index >= max(0, backfill)
        session.add(
            Video(
                owner_pk=owner,
                video_id=post.post_id,
                channel_pk=channel.id,
                kind="post",
                title=post.title,
                body=post.text,
                images=json.dumps(post.image_urls) if post.image_urls else None,
                # The first image is the post's face in the feed list.
                thumbnail_url=post.image_urls[0] if post.image_urls else None,
                published_at=to_naive_utc(post.published_at),
                status="ignored" if beyond_backfill else "pending",
                reason=TOO_OLD if beyond_backfill else None,
                processed_at=utcnow() if beyond_backfill else None,
            )
        )
        if not beyond_backfill:
            result.discovered += 1
    session.flush()


def _fill_missing_details(
    session: Session, client: YouTubeClient, result: SyncResult, owner: OwnerId = None
) -> None:
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
            owned(select(Channel), Channel, owner)
            .where(or_(Channel.thumbnail_url.is_(None), Channel.description.is_(None)))
            .order_by(Channel.id)
        )
    )
    if not missing or not quota.can_afford(session, 1, use_reserve=True, owner=owner):
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
        if path.playlist.enabled and path.playlist.is_generic:
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
    client: YouTubeClient,
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
            _note_placed(placement.playlist_pk)
            result.added += 1
            session.flush()
            continue

        if not quota.can_afford(session, QUOTA_COST_INSERT, owner=owner):
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
        _note_placed(placement.playlist_pk)
        result.added += 1
        session.flush()
    return False


def _publish(
    session: Session,
    client: YouTubeClient,
    settings: Settings,
    result: SyncResult,
    owner: OwnerId = None,
    pen: runlog.Pen | None = None,
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
        if path.playlist.enabled:
            routes_for.setdefault(path.channel.id, []).append(path)


    details = {}
    # Only a YouTube video has details to read; a post has none, and an item
    # from somewhere else is not YouTube's to answer for.
    clips = [v.video_id for v in pending if v.kind == "video"]
    if clips and client.can_read and quota.can_afford(session, 1, use_reserve=True, owner=owner):
        try:
            details = client.video_details(clips)
        except YouTubeAPIError as exc:
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

    _reorder(pending, routes_for)

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
        if detail is None and client.can_read and video.kind == "video":
            _reject(video, result, "video is unavailable (private, deleted, or region blocked)")
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
        own_rules = graph.Route(channel=channel, playlist=paths[0].playlist, filters=[])
        if _decide(video, own_rules, detail, settings).accept:
            _note_left(channel.id)

        allowed: list[Playlist] = []
        refusals: list[str] = []
        for path in paths:
            decision = _decide(video, path, detail, settings)
            _attribute(video, path, detail, settings)
            if decision.accept:
                allowed.append(path.playlist)
            elif decision.reason:
                refusals.append(decision.reason)

        if not allowed:
            # Every path said no; the first reason is the one worth showing.
            why = refusals[0] if refusals else "filtered out"
            _reject(video, result, why)
            say.write(f"held back — {why}", about=video.title or video.video_id)
            continue
        say.write(
            "goes to " + ", ".join(sorted(p.title for p in allowed)),
            about=video.title or video.video_id,
        )

        if video.is_post:
            _place_locally(
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

            if not quota.can_afford(session, QUOTA_COST_INSERT, owner=owner):
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


def _decide(
    video: Video, path: "graph.Route", detail: VideoDetails | None, settings: Settings
) -> filters.Decision:
    """Whether this video belongs in this feed, by this path's rules.

    The channel's own filters with every filter node on the path laid over
    them — which is what makes a filter node an override rather than a second
    set of settings to keep in step.
    """
    rules = path.effective()

    # The one thing that does not generalise. A YouTube playlist holds YouTube
    # videos and nothing else, so an item from anywhere else can only go into
    # a feed that lives inside De-Algo — said here, once, rather than failing
    # at the insert with whatever YouTube makes of it.
    if not video.is_youtube and not path.playlist.is_generic:
        return filters.Decision(False, WRONG_KIND_OF_FEED)

    if video.kind == "link":
        # Nothing to measure but its words: a feed entry has no duration and
        # is neither a Short nor a broadcast.
        return filters.evaluate_post(
            text=f"{video.title} {video.body or ''}",
            skip_posts=False,
            title_include=rules["title_include"],
            title_exclude=rules["title_exclude"],
        )

    if video.is_post:
        return filters.evaluate_post(
            text=video.body or video.title,
            skip_posts=bool(rules["skip_posts"]),
            title_include=rules["title_include"],
            title_exclude=rules["title_exclude"],
        )
    return filters.evaluate(
        title=video.title,
        duration_sec=video.duration_sec,
        live_state=detail.live_state if detail else None,
        is_short=video.is_short,
        title_include=rules["title_include"],
        title_exclude=rules["title_exclude"],
        min_duration_sec=rules["min_duration_sec"],
        max_duration_sec=rules["max_duration_sec"],
        skip_shorts=bool(rules["skip_shorts"]),
        skip_live=bool(rules["skip_live"]),
        skip_videos=bool(rules["skip_videos"]),
        shorts_max_seconds=settings.shorts_max_seconds,
    )


def _reorder(pending: list[Video], routes_for: dict[int, list["graph.Route"]]) -> None:
    """Put the batch in the order the sort boxes asked for.

    Insertion order is the order things appear in a feed, and this list is
    what the insert loop walks — so ordering it here is what a sort box does.

    One list, so one order. A video reached by two paths that sort
    differently is ordered by the first of them, which is the one nearest the
    top of the graph; two feeds that genuinely disagree need two batches, and
    that is a larger change than this earns. Videos with no sort box on their
    path keep the order they came in with, which is oldest first.
    """
    keyed = [
        (video, _sorter(video, routes_for.get(video.channel_pk or 0, [])))
        for video in pending
    ]
    if not any(key is not None for _, key in keyed):
        return

    # Sorted once, with the original position as the tie-break, so anything
    # the sort boxes say nothing about stays where it was.
    order = {video.id: position for position, video in enumerate(pending)}
    pending.sort(
        key=lambda video: (
            _sorter(video, routes_for.get(video.channel_pk or 0, [])) or (0, 0),
            order[video.id],
        )
    )


def _sorter(video: Video, paths: Sequence["graph.Route"]) -> tuple[int, float] | None:
    """Where this video belongs in the batch, as the first sort box sees it.

    The leading number is the box's own position, so videos under different
    sort boxes do not interleave: each box's batch stays together, in its own
    order, rather than being shuffled through another's.
    """
    for path in paths:
        box = path.order
        if box is None:
            continue
        rank = _sort_value(video, box.sort_by or graph.DEFAULT_SORT_BY)
        return (box.id, -rank if (box.sort_dir or "desc") == "desc" else rank)
    return None


def _sort_value(video: Video, key: str) -> float:
    """The number a batch is ordered by. Unknown counts sort last either way.

    A video whose details were never fetched has no view count, and guessing
    zero would put it top of an ascending sort — which reads as "this is the
    least watched" rather than "nobody asked YouTube yet".
    """
    if key == "duration":
        return float(video.duration_sec or 0)
    if key == "views":
        return float(video.view_count or 0)
    if key == "likes":
        return float(video.like_count or 0)
    if key == "title":
        # Alphabetical, as a number: the first few characters are enough to
        # order a batch, and it keeps every key the same shape.
        return -sum(ord(letter) / (256.0 ** index) for index, letter in enumerate((video.title or "").lower()[:8]))
    published = video.published_at
    return published.timestamp() if published is not None else 0.0


def _attribute(
    video: Video, path: "graph.Route", detail: VideoDetails | None, settings: Settings
) -> None:
    """Say which box on this path let the video through, and which stopped it.

    The decision for the path as a whole says yes or no; it does not say where
    the no happened. This walks the path a box at a time and asks the same
    question of each prefix, so the canvas can point at the box that is
    actually holding things up rather than at the path in general.
    """
    for index, node in enumerate(path.filters):
        so_far = graph.Route(
            channel=path.channel, playlist=path.playlist, filters=path.filters[: index + 1]
        )
        if _decide(video, so_far, detail, settings).accept:
            _note_filtered(node.id, passed=True)
        else:
            _note_filtered(node.id, passed=False)
            return  # it got no further, so the boxes after this one never saw it


def _place_locally(
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


def _prune(
    session: Session,
    client: YouTubeClient,
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
        except YouTubeAPIError as exc:
            result.messages.append(f"Could not read {playlist.title!r} for pruning: {exc}")
            continue

        overflow = len(items) - limit
        if overflow <= 0:
            continue

        # De-Algo appends oldest-first, so the front of the playlist is the oldest.
        for item in sorted(items, key=lambda i: i.position)[:overflow]:
            if not quota.can_afford(session, QUOTA_COST_DELETE, owner=owner):
                result.stopped_on_quota = True
                result.messages.append("Quota ran out before pruning finished.")
                return
            try:
                client.delete_playlist_item(item.item_id)
            except YouTubeAPIError as exc:
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
