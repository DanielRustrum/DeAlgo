"""One run for one account, phase by phase; and one for each account in turn."""

from __future__ import annotations

import logging
from collections.abc import Collection

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ... import outgoing
from ...db import get_settings, session_scope
from ...models import (
    Channel,
    Playlist,
    Settings,
    SyncRun,
    utcnow,
)
from ...plugins.publisher import Publisher, cost_of
from .. import quota, runlog
from ..auth import build_client
from ..scope import OwnerId, owned
from .details import fill_missing_details
from .expiry import stamp_what_is_already_here, sweep_expired
from .filing import publish
from .lock import Busy, playlist_lock
from .polling import discover
from .progress import claim, finish, note
from .pruning import prune
from .result import SyncResult
from .withdrawing import withdraw_what_is_due

log = logging.getLogger(__name__)


def run_sync(
    trigger: str = "manual",
    *,
    force: bool = False,
    owner: OwnerId = None,
    only: Collection[int] | None = None,
    sources: Collection[int] | None = None,
    fired_by: int | None = None,
    reach_back: int | None = None,
    withdrawals: Collection[int] | None = None,
    token: int | None = None,
) -> SyncResult:
    """Run one account's sync pass. Returns at once if a pass is in flight.

    ``force`` polls every enabled channel regardless of its minimum gap. The
    scheduler never forces; this is for someone pressing the button.

    ``only`` narrows the polling half to certain channels, by primary key. A
    trigger on the canvas is wired to some channels and not others, and this
    is how it says so.

    ``sources`` narrows the publishing half to certain source *boxes*, which
    is a different question with a different answer: a channel drawn twice is
    one channel and two boxes, wired down two paths that filter differently,
    and a trigger reaches one of them. Without it the publishing half runs
    over the whole graph, which is what a scheduled pass wants — it is
    standing in for every trigger at once.

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
            with outgoing.client() as http, session_scope() as session:
                return _run(
                    session, http, trigger, force=force, owner=owner, only=only,
                    sources=sources, fired_by=fired_by, reach_back=reach_back,
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
        finish(mine)


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
    sources: Collection[int] | None = None,
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

    note(stage="polling")
    pen.at("polling")
    discover(
        session, http, result, backfill=settings.initial_backfill, force=force, owner=owner,
        only=only, reach_back=reach_back, pen=pen,
    )
    note(stage="sorting")
    pen.at("sorting")
    fill_missing_details(session, client, result, owner)
    session.commit()
    note(stage="filling")
    pen.at("filling")
    _fill(session, client, settings, result, owner, pen, sources)
    _keep_feeds_current(session, client, result, owner, pen, withdrawals)
    session.commit()

    note(stage="done", finished=True, channel_pk=None)
    pen.at("done")
    pen.write(
        f"Finished: looked at {result.channels_checked}, found {result.discovered}, "
        f"added {result.added}, held back {result.skipped}, failed {result.failed}."
    )
    runlog.prune(session, owner)
    _record(run, result, quota_spent=max(0, quota.state(session, owner).used - quota_before))
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


def _fill(
    session: Session,
    client: Publisher,
    settings: Settings,
    result: SyncResult,
    owner: OwnerId,
    pen: runlog.Pen,
    sources: Collection[int] | None,
) -> None:
    """File what is waiting into the feeds — as much of it as can be, today."""
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
        publish(session, client, settings, result, owner, pen=pen, sources=sources)
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
        publish(session, client, settings, result, owner, pen=pen, sources=sources)
        session.commit()
    else:
        publish(session, client, settings, result, owner, pen=pen, sources=sources)
        session.commit()
        prune(session, client, playlists, result, owner)


def _keep_feeds_current(
    session: Session,
    client: Publisher,
    result: SyncResult,
    owner: OwnerId,
    pen: runlog.Pen,
    withdrawals: Collection[int] | None,
) -> None:
    """What has had its time goes; what a repository is due to release comes out."""
    # An Expire box wired up says something about the feed, not only about
    # what turns up next, so anything already in one gets its end worked out
    # before the sweep rather than waiting to be read first.
    marked = stamp_what_is_already_here(session, owner)
    if marked:
        pen.write(f"worked out when {marked} already here will leave")

    # Whatever an Expire box said had had its time, taken out of the feed it
    # was in. After the filling, so something that arrived with no time left
    # on it goes in the same run it came in.
    sweep_expired(session, client, result, owner, say=pen)

    # Last, so a pull takes what this run brought as well as what was already
    # waiting. A run's job is to bring everything up to date, and holding
    # back what arrived a moment ago would be a rule with no reason behind it.
    withdraw_what_is_due(
        session, result, owner, pen=pen,
        only=frozenset(withdrawals) if withdrawals is not None else None,
    )


def _record(run: SyncRun, result: SyncResult, *, quota_spent: int) -> None:
    """Write what the run came to onto its row, and onto the result."""
    run.finished_at = utcnow()
    run.ok = result.failed == 0 and all("failed" not in m.lower() for m in result.messages)
    run.channels_checked = result.channels_checked
    run.discovered = result.discovered
    run.added = result.added
    run.skipped = result.skipped
    run.failed = result.failed
    run.pruned = result.pruned
    run.quota_spent = quota_spent
    run.stopped_on_quota = result.stopped_on_quota
    result.quota_spent = run.quota_spent
    run.message = result.message or None
    result.ok = run.ok
