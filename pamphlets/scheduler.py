"""Background polling loop.

APScheduler runs the sync in a worker thread on the interval stored in the
database, and is re-scheduled whenever that setting changes.

The interval is a heartbeat, not the schedule. Each pass asks the trigger
boxes on the canvas which sources are due, and polls only those; a source
with no trigger wired is never polled by it.
"""

from __future__ import annotations

import datetime as dt
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .db import get_settings, session_scope
from .services.sync import run_for_everyone

log = logging.getLogger(__name__)

JOB_ID = "pamphlets-sync"

_scheduler: BackgroundScheduler | None = None


def _job() -> None:
    """One heartbeat: a scheduled run for every account in turn."""
    # Every account in turn: the schedule belongs to the site, the channels
    # and feeds it polls belong to whoever set them up.
    run_for_everyone(trigger="scheduled")


def start() -> BackgroundScheduler:
    """Start the scheduler, once, and apply the stored interval."""
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(timezone=dt.timezone.utc)
        _scheduler.start()
    reschedule()
    return _scheduler


def shutdown() -> None:
    """Stop the scheduler without waiting for a run in flight."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def reschedule() -> None:
    """Apply the interval currently stored in settings."""
    if _scheduler is None:
        return
    with session_scope() as session:
        settings = get_settings(session)
        auto = settings.auto_sync
        minutes = max(1, settings.poll_interval_minutes or 30)

    # Automatic sync off: drop the job if there is one.
    existing = _scheduler.get_job(JOB_ID)
    if not auto:
        if existing:
            _scheduler.remove_job(JOB_ID)
            log.info("automatic sync disabled")
        return

    # On: move the existing job to the new interval, or add it, first run in 20 seconds.
    trigger = IntervalTrigger(minutes=minutes, timezone=dt.timezone.utc)
    if existing:
        existing.reschedule(trigger=trigger)
    else:
        _scheduler.add_job(
            _job,
            trigger=trigger,
            id=JOB_ID,
            name="Pamphlets channel sync",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=300,
            next_run_time=dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=20),
        )
    log.info("automatic sync every %d minute(s)", minutes)


def next_run_time() -> dt.datetime | None:
    """When the next heartbeat is due, or None if automatic sync is off."""
    if _scheduler is None:
        return None
    job = _scheduler.get_job(JOB_ID)
    return job.next_run_time if job else None
