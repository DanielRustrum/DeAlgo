"""The sync engine: poll feeds, filter, and push new uploads into the playlist.

One run is a single pass over every enabled channel. It is deliberately
restartable — every decision is written to the database as it is made, so a
crash mid-run costs at most the videos still in flight, and nothing is ever
added twice.
"""

from __future__ import annotations

import datetime as dt
import html
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
    GraphNode,
    Placement,
    Playlist,
    RepositoryItem,
    Settings,
    SyncRun,
    Video,
    to_naive_utc,
    utcnow,
)
from ..sources import items, patience, syndication
from ..plugins import registry, site
from ..plugins.publisher import PublishError, Publisher, VideoDetails, cost_of
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
    #: Items put into a repository to wait for a Withdraw box. Counted apart
    #: from `added`: nothing has reached a feed, which is the whole point.
    deposited: int = 0
    #: Items a Withdraw box took back out and sent on.
    withdrawn: int = 0
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
    withdrawals: Collection[int] | None = None,
    token: int | None = None,
) -> SyncResult:
    """Run one account's sync pass. Returns at once if a pass is in flight.

    ``force`` polls every enabled channel regardless of its minimum gap. The
    scheduler never forces; this is for someone pressing the button.

    ``only`` narrows the pass to certain channels, by primary key. A trigger
    on the canvas is wired to some channels and not others, and this is how it
    says so. The publishing half still runs over everything, because what a
    new video is allowed into is a question about the whole graph.

    ``withdrawals`` narrows the pulling half the way ``only`` narrows the
    polling half: the Withdraw boxes one trigger is wired to, pulled whether
    or not their own gap has elapsed. Without it, whichever boxes their
    triggers say are due.

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
                    withdrawals=withdrawals,
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
    withdrawals: Collection[int] | None = None,
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
    elif youtube_feeds and quota_state.spendable < cost_of("add"):
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

    # Last, so a pull takes what this run brought as well as what was already
    # waiting. A run's job is to bring everything up to date, and holding
    # back what arrived a moment ago would be a rule with no reason behind it.
    _withdraw_what_is_due(
        session, result, owner, pen=pen,
        only=frozenset(withdrawals) if withdrawals is not None else None,
    )
    session.commit()

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


def _poll(channel: Channel, http: httpx.Client) -> items.Batch:
    """Read whatever kind of feed this source publishes.

    YouTube's own reader knows two things the general one cannot: which
    entries are Shorts, and the channel id the feed belongs to. Everything
    else is a feed like any other, and is read as one.
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

    Only the fields a plugin actually named: a kind with no opinion about
    Shorts leaves `is_short` false rather than having to say so, and one with
    no opinion about ids gets the hash every other source gets.
    """
    given = str(said.get("id") or "").strip()
    return items.Entry(
        id=given or _item_id(channel, item),
        title=item.title,
        published_at=item.published_at,
        thumbnail_url=item.thumbnail_url,
        is_short=said.get("is_short") is True,
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
            say.write(
                "nothing polls this — wire a trigger to it"
                if not plan.get(channel.id)
                else "not due yet, so it was left alone",
                about=channel.title,
            )
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

        # Some sources keep things their feed does not carry — YouTube's
        # community posts are the one shipped example. Whether this is such
        # a source is the plugin's to say, not a name checked here.
        if not channel.skip_posts and registry.current().has_extras(channel.source_kind):
            _discover_posts(
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


def repair_stored_pictures(session: Session) -> int:
    """Take the pictures out of items that were stored before we looked.

    Every item from a feed elsewhere was filed by a version that threw the
    markup away without reading it for pictures — so the address survived as
    words, which is why it was showing up as the first line of the post.

    It cannot be fixed by polling again: a feed lists its most recent couple
    of dozen items and no more, and most of what is in hand has long since
    fallen off the end of it. But nothing needs fetching. The address is in
    the text, and this reads it back out.

    Run once, at startup. `images` is written even when nothing is found, so
    a row that has been looked at is never looked at again — "we checked, it
    has none" is an answer worth recording.
    """
    # Anything never looked at, and anything still showing its workings: a
    # body that kept its escapes, or one that still leads with the address of
    # its own picture. All three converge after one pass, because the repair
    # removes exactly what selects them.
    waiting = list(
        session.scalars(
            select(Video).where(
                Video.kind == "link",
                or_(
                    Video.images.is_(None),
                    Video.body.like("%&amp;%"),
                    Video.body.like("%&#%"),
                    Video.body.like("http%"),
                ),
            )
        )
    )
    if not waiting:
        return 0

    repaired = 0
    for video in waiting:
        pictures = syndication.pictures_in(video.body or "")
        # Never throws away pictures a reading already found: this one looks
        # only at the words, and a feed names pictures the words do not.
        if pictures or video.images is None:
            video.images = json.dumps(pictures or video.image_list)
        # Tidied either way: a body stored before the words were unescaped
        # carries its "&#32;" into every reading of it, picture or no picture.
        video.body = _words_without(video.body or "", pictures) or None
        if not pictures:
            continue

        biggest = max(pictures, key=syndication.declared_width)
        if not video.thumbnail_url or syndication.declared_width(
            video.thumbnail_url
        ) < syndication.declared_width(biggest):
            video.thumbnail_url = biggest
        repaired += 1

    session.flush()
    log.info("read pictures back out of %d stored items", repaired)
    return repaired


def repair_stored_pictures_now() -> int:
    """The repair over a session of its own, for a caller that has none open.

    `init_db` already holds one and passes it in; everybody else just wants
    it done.
    """
    with session_scope() as session:
        return repair_stored_pictures(session)


def _words_without(body: str, pictures: list[str]) -> str:
    """The post's words, unescaped, with the pictures' addresses taken out.

    Splitting on whitespace and rejoining is what closes the gaps an escape
    leaves behind: "&#32;" unescapes to a space beside the ones already there.
    """
    wanted = set(pictures)
    kept = [word for word in html.unescape(body).split() if word not in wanted]
    return " ".join(kept).strip()


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
    channel: Channel,
    result: SyncResult,
    *,
    first_check: bool,
    backfill: int,
    owner: OwnerId = None,
) -> None:
    """Collect whatever a source keeps outside its feed.

    The plugin fetches and reads these, because the shape of a page with no
    feed behind it is the service's own and changes without notice. It is
    wrapped whole all the same: a source whose extras cannot be read still
    keeps everything its feed gave.

    The backfill rules are the feed's, so tracking a source does not drop a
    year of its writing into a feed on day one.
    """
    try:
        with site.acting_for(owner):
            posts = registry.current().posts(channel.source_kind, channel.channel_id)
        found = [post for post in (_as_post(row) for row in posts) if post.id]
    except Exception as exc:  # the page shape is not ours to rely on
        log.warning("could not read posts for %s: %s", channel.title, exc)
        return
    if not found:
        return
    here = set(
        session.scalars(
            owned(select(Video.video_id), Video, owner).where(
                Video.video_id.in_([post.id for post in found] or [""])
            )
        )
    )
    for index, post in enumerate(found):
        if post.id in here:
            continue
        beyond_backfill = first_check and index >= max(0, backfill)
        session.add(
            Video(
                owner_pk=owner,
                video_id=post.id,
                channel_pk=channel.id,
                kind="post",
                title=post.title,
                body=post.summary,
                images=json.dumps(list(post.images)) if post.images else None,
                # The first image is the post's face in the feed list.
                thumbnail_url=post.images[0] if post.images else None,
                published_at=to_naive_utc(post.published_at),
                status="ignored" if beyond_backfill else "pending",
                reason=TOO_OLD if beyond_backfill else None,
                processed_at=utcnow() if beyond_backfill else None,
            )
        )
        if not beyond_backfill:
            result.discovered += 1
    session.flush()


def _as_post(row: dict[str, object]) -> items.Entry:
    """One of a plugin's extras, as the same kind of thing a feed gives.

    A post has no title of its own — nothing it is called, only what it says
    — so it is given one from its first line. That is not the service's idea
    of anything; it is this list needing something to print.
    """
    text = str(row.get("text") or "")
    given = row.get("images")
    pictures = (
        tuple(str(url) for url in given if isinstance(url, str) and url)
        if isinstance(given, list)
        else ()
    )
    when = row.get("published_at")
    return items.Entry(
        id=str(row.get("id") or ""),
        title=_first_line(text) or ("(image post)" if pictures else ""),
        published_at=(
            dt.datetime.fromtimestamp(float(when), dt.timezone.utc)
            if isinstance(when, (int, float)) and not isinstance(when, bool)
            else None
        ),
        thumbnail_url=pictures[0] if pictures else None,
        kind="post",
        summary=text,
        images=pictures,
    )


def _first_line(text: str) -> str:
    """A one-line stand-in, for the places that list posts beside videos."""
    lines = text.strip().splitlines()
    first = lines[0] if lines else ""
    if len(first) <= 80:
        return first
    return first[:79].rsplit(" ", 1)[0] + "\u2026"


def _fill_missing_details(
    session: Session, client: Publisher, result: SyncResult, owner: OwnerId = None
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


def _plugin_refusal(video: Video, path: "graph.Route") -> filters.Decision | None:
    """Ask each plugin box on this path, and stop at the first no.

    The item is handed over as plain values, not as a database row: a plugin
    is given what it needs to judge and nothing it could write through.
    """
    if not path.checks:
        return None


    found = registry.current()
    item = {
        "title": video.title or "",
        "kind": video.kind,
        "words": video.body or "",
        "link": video.link or "",
        "duration": video.duration_sec or 0,
        "views": video.view_count or 0,
        "likes": video.like_count or 0,
        "is_short": video.is_short,
        "source": video.channel.source_kind if video.channel else "",
    }
    # Whose work this is, for the whole of the asking. A plugin reaching the
    # site through `dealgo` sees this account and no other, and outside a
    # block like this it sees nobody at all.
    with site.acting_for(path.channel.owner_pk):
        for node in path.checks:
            ref = node.plugin_ref or ""
            box = found.node(ref)
            if box is None:
                # Its plugin is switched off or gone. The box stays on the
                # canvas and stops narrowing anything, which is the same
                # thing a filter with no rules does.
                continue
            if not found.keeps(ref, item, _plugin_settings(node)):
                return filters.Decision(False, f"held by {node.title}")
    return None


def _plugin_settings(node: GraphNode) -> dict[str, str]:
    """What a plugin box's fields were set to, as plain strings."""
    if not node.plugin_settings:
        return {}
    try:
        loaded = json.loads(node.plugin_settings)
    except (TypeError, ValueError):
        return {}
    if not isinstance(loaded, dict):
        return {}
    return {str(key): str(value) for key, value in loaded.items()}


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
            _note_placed(placement.playlist_pk)
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
        _note_placed(placement.playlist_pk)
        result.added += 1
        session.flush()
    return False


def _publish(
    session: Session,
    client: Publisher,
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
        own_rules = graph.Route(
            channel=channel,
            playlist=paths[0].playlist,
            store=paths[0].store,
            filters=[],
        )
        if _decide(video, own_rules, detail, settings).accept:
            _note_left(channel.id)

        allowed: list[Playlist] = []
        stored: list[graph.Route] = []
        refusals: list[str] = []
        for path in paths:
            decision = _decide(video, path, detail, settings)
            _attribute(video, path, detail, settings)
            if not decision.accept:
                if decision.reason:
                    refusals.append(decision.reason)
            elif path.deposits:
                stored.append(path)
            elif path.playlist is not None:
                allowed.append(path.playlist)

        if not allowed and not stored:
            # Every path said no; the first reason is the one worth showing.
            why = refusals[0] if refusals else "filtered out"
            _reject(video, result, why)
            say.write(f"held back — {why}", about=video.title or video.video_id)
            continue

        # Into the repositories first: nothing is sent anywhere for these, so
        # a quota stop partway through the feeds cannot lose them.
        held = _deposit(session, video, stored, owner)
        if held:
            result.deposited += held

        going = sorted(p.title for p in allowed)
        waiting = sorted({path.store for path in stored})
        say.write(
            "goes to " + ", ".join(going + [f"the {name} repository" for name in waiting]),
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
    if not video.is_youtube and path.playlist is not None and not path.playlist.is_generic:
        return filters.Decision(False, WRONG_KIND_OF_FEED)

    # Plugin boxes, before the rules that cost anything to work out. Each is
    # somebody's Lua answering one question about one item, and a box that
    # says no ends the path there.
    refused = _plugin_refusal(video, path)
    if refused is not None:
        return refused

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


def withdraw(
    session: Session,
    node: GraphNode,
    result: SyncResult,
    owner: OwnerId = None,
    say: runlog.Pen | None = None,
) -> int:
    """Pull from one Withdraw box's repository and send what comes out onward.

    A Withdraw box stands where a source stands: it starts a path. What comes
    out of it has already been through whatever filtered it on the way in, so
    only the boxes between here and a feed get another say.

    Oldest first, so a repository behaves like the pile it looks like. What
    is taken is taken — the rows go, which is what makes it a withdrawal
    rather than a look.
    """
    name = graph.store_name(node.repository)
    if not name:
        return 0
    if not node.enabled:
        return 0

    most = node.takes or 0
    query = (
        owned(select(RepositoryItem), RepositoryItem, owner)
        .options(selectinload(RepositoryItem.video).selectinload(Video.channel))
        .where(RepositoryItem.name == name)
        .order_by(RepositoryItem.deposited_at, RepositoryItem.id)
    )
    if most > 0:
        query = query.limit(most)
    holding = list(session.scalars(query))
    if not holding:
        if say is not None:
            say.write(f"the {name} repository is empty", about=node.title)
        return 0

    settings = get_settings(session, owner)
    sent = 0
    held_back = 0
    for row in holding:
        video, channel = row.video, row.video.channel if row.video else None
        if video is None or channel is None:
            session.delete(row)   # the item is gone; the row is a leftover
            continue

        # Every box between here and a feed still gets a say. A filter wired
        # after a Withdraw is a filter on what comes out, and ignoring it
        # would make it a box that draws a wire and does nothing.
        allowed: list[Playlist] = []
        for path in graph.paths_from(session, node, channel, owner):
            if path.playlist is None or not path.playlist.enabled:
                continue
            if _decide(video, path, None, settings).accept:
                allowed.append(path.playlist)
        feeds = sorted(
            {one.id: one for one in allowed}.values(),
            key=lambda one: (one.priority, one.id),
        )

        # Taken either way. A withdrawal is a withdrawal: an item every path
        # turned away has been dealt with, and leaving it in would mean a
        # repository that fills up with things nothing will ever accept.
        session.delete(row)
        if not feeds:
            held_back += 1
            continue

        _place_locally(session, video, channel, result, {}, {}, feeds)
        sent += 1

    session.flush()
    result.withdrawn += sent
    if say is not None:
        said = f"took {sent} from the {name} repository"
        if held_back:
            said += f"; {held_back} filtered out on the way"
        if most > 0:
            said += f", leaving {waiting_in(session, name, owner)}"
        say.write(said, about=node.title)
    return sent


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


def withdraw_now(
    session: Session, boxes: Collection[int], owner: OwnerId = None
) -> str:
    """Pull from these Withdraw boxes at once, and say what came out.

    For a trigger somebody pressed that is wired to nothing but repositories.
    Pulling touches no network and spends no quota, so there is nothing worth
    starting a thread for — the answer is ready by the time the button lets
    go.
    """
    result = SyncResult()
    wanted = set(boxes)
    for node in nodes_of_kind(session, "withdraw", owner):
        if node.id not in wanted:
            continue
        withdraw(session, node, result, owner)
        node.last_fired_at = utcnow()
    session.flush()

    if result.withdrawn == 0:
        return "Nothing came through."
    return f"Took {result.withdrawn} out and sent {'it' if result.withdrawn == 1 else 'them'} on."


def nodes_of_kind(
    session: Session, kind: str, owner: OwnerId = None
) -> list[GraphNode]:
    """Every box of one kind on this account's canvas."""
    return [node for node in graph.nodes(session, owner) if node.kind == kind]


def _withdraw_what_is_due(
    session: Session,
    result: SyncResult,
    owner: OwnerId = None,
    *,
    pen: runlog.Pen | None = None,
    only: frozenset[int] | None = None,
) -> None:
    """Pull from every repository whose turn it has come round.

    `only` is the boxes one trigger was set off by hand for; without it,
    whichever boxes their own triggers say are due.
    """
    due = graph.due_withdrawals(session, owner)
    if only is not None:
        due = [node for node in due if node.id in only] if due else []
        # Pressed by hand, so its turn is now whatever its trigger would say.
        wanted = {node.id for node in due}
        for node in graph.nodes(session, owner):
            if node.id in only and node.kind == "withdraw" and node.id not in wanted:
                due.append(node)
    if not due:
        return

    for node in due:
        withdraw(session, node, result, owner, say=pen)
        node.last_fired_at = utcnow()
    session.flush()


def _deposit(
    session: Session,
    video: Video,
    paths: list[graph.Route],
    owner: OwnerId = None,
) -> int:
    """Put one item into every repository its paths end in.

    Once each. Two Deposit boxes carrying the same name are two ways into one
    pile, not two piles — and an item already waiting there is already
    waiting, so a second run does not double it up.
    """
    if not paths:
        return 0

    already = set(
        session.scalars(
            owned(select(RepositoryItem.name), RepositoryItem, owner).where(
                RepositoryItem.video_pk == video.id
            )
        )
    )
    put = 0
    for path in paths:
        if path.store in already:
            continue
        session.add(
            RepositoryItem(
                owner_pk=owner,
                name=path.store,
                video_pk=video.id,
                deposited_by=path.finish.id if path.finish is not None else None,
            )
        )
        already.add(path.store)
        put += 1
    if put:
        session.flush()
    return put


def waiting_in(session: Session, name: str, owner: OwnerId = None) -> int:
    """How many items a repository is holding."""
    wanted = graph.store_name(name)
    if not wanted:
        return 0
    return len(
        list(
            session.scalars(
                owned(select(RepositoryItem.id), RepositoryItem, owner).where(
                    RepositoryItem.name == wanted
                )
            )
        )
    )


def _reject(video: Video, result: SyncResult, reason: str) -> None:
    video.status = "skipped"
    video.reason = reason
    video.processed_at = utcnow()
    result.skipped += 1


# -- phase 3: keep the playlist to size -----------------------------------


def _prune(
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
