"""What is happening: the run log, the sync status, the stats and the status API."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import func, select

from ...db import session_scope
from ...models import (
    SyncRun,
    Video,
)
from ...services import quota as quota_service
from ...services import runlog
from ...services import sync as sync_service
from ...services.scope import owned
from ..responses import fragment, newest_run_id, owner_of

if TYPE_CHECKING:
    pass
from ..contexts import stats_context

router = APIRouter()


#: What the filter offers, and what each name means. "By hand" covers every
#: way a person can start one; the clock is the only thing that is not a
#: person, so the split is the honest one rather than one name per button.
LOG_FILTERS: tuple[tuple[str, str], ...] = (
    ("all", "Everything"),
    ("hand", "Started by me"),
    ("clock", "On a schedule"),
    ("trouble", "Went wrong"),
)


@router.get("/partials/log", response_class=HTMLResponse)
def log_partial(request: Request, show: str = "") -> HTMLResponse:
    """The log, for the dialog on the canvas.

    A fragment rather than a page: it is read while looking at the canvas that
    caused it, and walking away from the drawing to read about it was the
    wrong way round. Fetched when the dialog opens, so a canvas nobody asks
    about costs nothing to draw.
    """
    owner = owner_of(request)
    wanted = show if show in {name for name, _ in LOG_FILTERS} else "all"

    with session_scope() as session:
        asking = owned(select(SyncRun), SyncRun, owner)
        if wanted == "hand":
            asking = asking.where(SyncRun.trigger.in_(SyncRun.BY_HAND))
        elif wanted == "clock":
            asking = asking.where(SyncRun.trigger.not_in(SyncRun.BY_HAND))
        elif wanted == "trouble":
            # A run still going has not failed yet, so it is not trouble.
            asking = asking.where(
                SyncRun.ok.is_(False), SyncRun.finished_at.is_not(None)
            )

        runs = list(session.scalars(asking.order_by(SyncRun.id.desc()).limit(60)))
        counts = runlog.counted(session, owner)
        # Read once for the runs on the page rather than per open <details>:
        # the page is server-rendered and every one of them may be opened.
        lines: dict[int, list[Any]] = {}
        for run in runs:
            if counts.get(run.id):
                lines[run.id] = runlog.lines_for(session, run.id, owner)

        context = {
            "runs": runs,
            "lines": lines,
            "counts": counts,
            "show": wanted,
            "filters": LOG_FILTERS,
            "runs_with_detail": runlog.RUNS_WITH_DETAIL,
        }
    return fragment(request, "_log.html", context)


@router.get("/partials/sync-status", response_class=HTMLResponse)
def partial_sync_status(request: Request, seen: int = 0) -> HTMLResponse:
    """Polled by the header. Announces a finished run so panels can refresh."""
    running = sync_service.is_running()
    last_run_id = newest_run_id()
    headers = {}
    if not running and last_run_id and last_run_id != seen:
        headers["HX-Trigger"] = "dealgo:sync-finished"
    return fragment(
        request,
        "_sync_controls.html",
        {"sync_running": running, "last_run_id": last_run_id},
        headers=headers,
    )


@router.get("/partials/stats", response_class=HTMLResponse)
def partial_stats(request: Request) -> HTMLResponse:
    """The counts row, redrawn after a run."""
    owner = owner_of(request)
    with session_scope() as session:
        context = stats_context(session, owner)
    return fragment(request, "_stats.html", context)


@router.get("/api/status")
def api_status(request: Request) -> JSONResponse:
    """The account's latest run and item counts, as JSON."""
    owner = owner_of(request)
    with session_scope() as session:
        run = session.scalar(
            owned(select(SyncRun), SyncRun, owner).order_by(SyncRun.started_at.desc())
        )
        counts: dict[str, int] = {
            status: held
            for status, held in session.execute(
                select(Video.status, func.count(Video.id)).group_by(Video.status)
            ).all()
        }
        quota_state = quota_service.state(session)
        payload = {
            "running": sync_service.is_running(),
            "counts": counts,
            "quota": {
                "used": quota_state.used,
                "budget": quota_state.budget,
                "remaining": quota_state.remaining,
                "exhausted": quota_state.exhausted,
                "resets_at": quota_state.resets_at.isoformat(),
            },
            "last_run": None
            if run is None
            else {
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "ok": run.ok,
                "added": run.added,
                "skipped": run.skipped,
                "failed": run.failed,
                "discovered": run.discovered,
                "message": run.message,
            },
        }
    return JSONResponse(payload)
