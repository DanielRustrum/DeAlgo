"""FastAPI application: the De-Algo GUI.

Server-rendered HTML so the container ships with no build step and the UI works
in any browser, which is the only GUI that makes sense inside Docker.
"""

from __future__ import annotations

import datetime as dt
import logging
import json
import re
import secrets
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote, urlencode

import httpx
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from .. import __version__, scheduler
from starlette.concurrency import run_in_threadpool

from ..config import CONFIG
from ..db import get_settings, get_token, init_db, session_scope
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from typing import Any
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from ..models import (
    GENERIC_PLAYLIST_PREFIX,
    GraphNode,
    User,
    Channel,
    Placement,
    Playlist,
    SyncRun,
    Video,
    channel_playlist,
    utcnow,
)
from .. import sources
from ..plugins import permissions, registry
from ..services import accounts
from ..services.scope import OwnerId, belongs_to, owned
from ..services import backup as backup_service
from ..services import graph as graph_service
from ..services import runlog
from ..services import migration
from ..services import channels as channel_service
from ..services import ordering as ordering_service
from ..services import playlists as playlist_service
from ..services import quota as quota_service
from ..services import sync as sync_service
from ..services import watched as watched_service
from ..services.auth import (
    build_client,
    client_credentials,
    disconnect,
    has_client_credentials,
    store_token,
)
from ..services.filters import format_duration
from ..plugins.publisher import PlaylistInfo, PublishError
from ..services import oauth
from . import guard

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def _asset_version() -> str:
    """Newest mtime across the static files, so a rebuild busts browser caches.

    Without this a redeploy keeps serving the stylesheet the browser already
    has, and a fixed layout still looks broken until someone hard-reloads.
    """
    static = BASE_DIR / "static"
    try:
        newest = max(path.stat().st_mtime for path in static.iterdir() if path.is_file())
    except (OSError, ValueError):  # pragma: no cover - no static dir at all
        return __version__
    return f"{int(newest):x}"


ASSET_VERSION = _asset_version()

# OAuth state tokens live in memory: the flow completes in seconds, and a
# restart mid-flow should invalidate it anyway.
_oauth_states: dict[str, float] = {}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logging.basicConfig(
        level=CONFIG.log_level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    init_db()
    scheduler.start()
    log.info("De-Algo %s ready on %s", __version__, CONFIG.public_url)
    try:
        yield
    finally:
        scheduler.shutdown()


app = FastAPI(title="De-Algo", version=__version__, lifespan=lifespan)


# Starlette hands the next handler in untyped; naming the shape here keeps
# the middleware itself honest about what it returns.
Handler = Callable[[Request], Awaitable[Response]]


@app.middleware("http")
async def require_account(request: Request, call_next: Handler) -> Response:
    """Decide who this is, before any route runs.

    Middleware rather than a dependency on each route: there are sixty of
    them, and one that forgets its dependency is a hole nobody notices. Here
    the default is deny, and the exceptions are a list in guard.py.
    """
    path = request.url.path
    request.state.identity = None

    if not CONFIG.auth_enabled:
        # No admin configured: the app behaves as it did before there were
        # accounts, and says so on every page.
        return await call_next(request)

    token = request.cookies.get(accounts.SESSION_COOKIE)

    if guard.is_public(path):
        # Public means "no account required", not "do not look". The login
        # page has to know it is being read by someone already signed in, or
        # it offers the form again and looks as though signing in failed.
        # Skipped for assets, which would otherwise cost a query apiece.
        if token and not path.startswith("/static/"):
            request.state.identity = await run_in_threadpool(_identify, token)
        return await call_next(request)

    identity = await run_in_threadpool(_identify, token)

    if identity is None:
        return _ask_to_sign_in(request)
    if guard.needs_admin(path) and not identity.is_admin:
        return _refuse(request)

    request.state.identity = identity
    return await call_next(request)


def _identify(token: str | None) -> accounts.Identity | None:
    with session_scope() as session:
        user = accounts.identify(session, token)
        if user is None:
            return None
        return accounts.Identity(username=user.username, is_admin=user.is_admin, user_pk=user.id)


def _ask_to_sign_in(request: Request) -> Response:
    """Send them to the login page, and back here afterwards.

    An htmx request is answered with the header htmx understands: a plain
    redirect would be followed by the XHR and the login page swapped into
    whatever panel asked.
    """
    target = request.url.path
    if request.url.query:
        target = f"{target}?{request.url.query}"
    destination = f"/login?next={quote(target, safe='/?=&')}"
    if is_htmx(request):
        return Response(status_code=401, headers={"HX-Redirect": destination})
    return RedirectResponse(destination, status_code=303)


def _refuse(request: Request) -> Response:
    message = "That part of De-Algo belongs to the admin account."
    if is_htmx(request):
        return Response(message, status_code=403)
    return RedirectResponse(f"/?err={quote(message)}", status_code=303)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


# -- template helpers -----------------------------------------------------


def _ago(value: dt.datetime | None) -> str:
    if value is None:
        return "never"
    delta = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - value.replace(tzinfo=None)
    seconds = int(delta.total_seconds())
    if seconds < 0:
        seconds = abs(seconds)
        suffix = "from now"
    else:
        suffix = "ago"
    for limit, unit, size in ((60, "second", 1), (3600, "minute", 60), (86400, "hour", 3600)):
        if seconds < limit:
            count = max(1, seconds // size)
            return f"{count} {unit}{'s' if count != 1 else ''} {suffix}"
    days = seconds // 86400
    if days < 30:
        return f"{days} day{'s' if days != 1 else ''} {suffix}"
    return value.strftime("%d %b %Y")


def _stamp(value: dt.datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M UTC") if value else "—"


def _clock(value: dt.datetime | None) -> str:
    """Just the time of day, for lines that are all from the same run."""
    return value.strftime("%H:%M:%S") if value else "—"


TEMPLATES.env.globals["source_label"] = lambda kind: sources.describe(kind).label
TEMPLATES.env.filters["ago"] = _ago
TEMPLATES.env.filters["stamp"] = _stamp
TEMPLATES.env.filters["clock"] = _clock
# What a template is handed. Jinja takes anything, so this says only that the
# keys are names — the value types are the templates' business.
Context = dict[str, Any]

TEMPLATES.env.filters["duration"] = format_duration
# Bound late: the function is defined further down, and the template calls it
# with the owner the page belongs to.
TEMPLATES.env.globals["youtube_offline"] = lambda owner=None: _youtube_offline(owner)


def _last_run_id() -> int:
    with session_scope() as session:
        return session.scalar(select(func.max(SyncRun.id))) or 0


def _tour_progress(session: Session, owner: OwnerId = None) -> Context:
    """What the tour can already tick off, so it guides rather than lectures."""
    feeds = list(session.scalars(owned(select(Playlist), Playlist, owner)))
    return {
        "has_feed": bool(feeds),
        "has_youtube_feed": any(not feed.is_generic for feed in feeds),
        "has_channel": bool(session.scalar(owned(select(func.count(Channel.id)), Channel, owner))),
        "linked": bool(
            session.scalar(
                select(func.count()).select_from(channel_playlist)
            )
        ),
        "connected": get_token(session, owner) is not None,
        "synced": bool(session.scalar(owned(select(func.count(SyncRun.id)), SyncRun, owner))),
        "watched_any": watched_service.count_watched(session, owner) > 0,
    }


def _notices() -> Context:
    """Which standing notices this instance still wants to see.

    One read for all of them, since every page render asks. Each is stored as
    "hide", so an unticked checkbox — which sends nothing at all — means show.
    """
    with session_scope() as session:
        settings = get_settings(session)
        return {
            "show_tour": not settings.hide_tour,
            "show_open_notice": not settings.hide_open_notice,
            "show_connect_notice": not settings.hide_connect_notice,
        }


def owner_of(request: Request) -> OwnerId:
    """Whose data this request is about.

    None is the implicit owner — which is everyone, while sign-in is off. With
    accounts on it is the signed-in one, and never anybody else's: there is no
    route that reads another account's channels or feeds.
    """
    identity = getattr(request.state, "identity", None)
    return identity.user_pk if identity else None


def render(request: Request, template: str, context: Context) -> HTMLResponse:
    context = {
        "version": __version__,
        "asset_version": ASSET_VERSION,
        "ok_message": request.query_params.get("ok"),
        "error_message": request.query_params.get("err"),
        "sync_running": sync_service.is_running(),
        "last_run_id": _last_run_id(),
        **_notices(),
        "identity": getattr(request.state, "identity", None),
        "auth_enabled": CONFIG.auth_enabled,
        "weak_admin_password": CONFIG.admin_password_weak,
        **context,
    }
    return TEMPLATES.TemplateResponse(request, template, context)


def fragment(
    request: Request,
    template: str,
    context: Context,
    *,
    ok: str | None = None,
    err: str | None = None,
    headers: dict[str, str] | None = None,
) -> HTMLResponse:
    """Render one piece of a page, with the flash area swapped out of band."""
    body = TEMPLATES.get_template(template).render({"request": request, **context})
    if ok or err:
        body += TEMPLATES.get_template("_flash.html").render(
            {"request": request, "ok_message": ok, "error_message": err, "oob": True}
        )
    return HTMLResponse(body, headers=headers)


def is_htmx(request: Request) -> bool:
    return request.headers.get("hx-request") == "true"


def redirect(path: str, *, ok: str | None = None, err: str | None = None) -> RedirectResponse:
    params = {k: v for k, v in (("ok", ok), ("err", err)) if v}
    url = f"{path}?{urlencode(params)}" if params else path
    return RedirectResponse(url, status_code=303)


def _http_client() -> httpx.Client:
    return httpx.Client(
        timeout=sync_service.HTTP_TIMEOUT,
        headers={"User-Agent": sync_service.USER_AGENT},
        follow_redirects=True,
    )


def _quota_context(session: Session) -> Context:
    state = quota_service.state(session)
    return {"quota": state, "quota_resets_in": quota_service.describe_reset()}


def _stats_context(session: Session, owner: OwnerId = None) -> Context:
    counts: dict[str, int] = {
        status: held
        for status, held in session.execute(
            owned(select(Video.status, func.count(Video.id)), Video, owner).group_by(Video.status)
        ).all()
    }
    return {
        "counts": counts,
        # "added" means it reached the playlist at some point; this is what is
        # actually in there now, after pruning and watched-removals.
        "in_playlist": session.scalar(
            select(func.count(func.distinct(Placement.video_pk)))
            .join(Video, Video.id == Placement.video_pk)
            .where(Placement.playlist_item_id.is_not(None), belongs_to(Video, owner))
        )
        or 0,
        "watched_count": watched_service.count_watched(session, owner),
        "removable_count": watched_service.count_removable(session, owner),
        "enabled_channels": session.scalar(
            owned(select(func.count(Channel.id)), Channel, owner).where(Channel.enabled.is_(True))
        )
        or 0,
    }


def _activity_context(session: Session, owner: OwnerId = None) -> Context:
    return {
        "recent_runs": list(session.scalars(owned(select(SyncRun), SyncRun, owner).order_by(SyncRun.started_at.desc()).limit(8))),
        "recent_videos": list(
            session.scalars(
                owned(select(Video), Video, owner)
                .options(
                    selectinload(Video.channel),
                    selectinload(Video.placements).selectinload(Placement.playlist),
                )
                .where(Video.status.in_(("added", "pending", "failed")))
                .order_by(Video.discovered_at.desc())
                .limit(12)
            )
        ),
    }


def _matching_channels(channels: Sequence[Channel], query: str) -> list[Channel]:
    """Every word must appear somewhere, in any order — partial words count."""
    terms = query.lower().split()
    if not terms:
        return list(channels)
    return [
        channel
        for channel in channels
        if all(
            term
            in " ".join(filter(None, [channel.title, channel.handle, channel.channel_id])).lower()
            for term in terms
        )
    ]


def _matching_feeds(playlists: Sequence[Playlist], query: str) -> list[Playlist]:
    terms = query.lower().split()
    if not terms:
        return list(playlists)
    return [p for p in playlists if all(term in (p.title or "").lower() for term in terms)]


def _channel_list_context(
    session: Session,
    feed: str = "",
    tracking: bool = False,
    query: str = "",
    *,
    owner: OwnerId = None,
) -> Context:
    def counts_by_channel(*conditions: ColumnElement[bool]) -> dict[int, int]:
        return {
            channel_pk: held
            for channel_pk, held in session.execute(
                select(Video.channel_pk, func.count(Video.id))
                .where(*conditions)
                .group_by(Video.channel_pk)
            ).all()
        }

    channels = channel_service.list_channels(session, owner)
    playlists = playlist_service.list_playlists(session, owner)
    counts_by_feed = {p.id: sum(1 for c in channels if p in c.playlists) for p in playlists}
    unassigned = sum(1 for c in channels if not c.playlists)

    if feed == "none":
        channels = [c for c in channels if not c.playlists]
    elif feed.isdigit():
        wanted = int(feed)
        channels = [c for c in channels if any(p.id == wanted for p in c.playlists)]
    else:
        feed = ""

    # Each word has to appear somewhere, in any order: "greene daniel" finds
    # "Daniel Greene", and a partial word still matches.
    terms = query.lower().split()
    if terms:
        def matches(channel: Channel) -> bool:
            haystack = " ".join(
                filter(None, [channel.title, channel.handle, channel.channel_id])
            ).lower()
            return all(term in haystack for term in terms)

        channels = [c for c in channels if matches(c)]

    return {
        "channels": channels,
        "tracking": tracking,
        "query": query,
        "all_feeds": playlists,
        "backfill_choices": channel_service.BACKFILL_CHOICES,
        "feed": feed,
        "feed_playlists": playlists,
        "counts_by_feed": counts_by_feed,
        "unassigned_count": unassigned,
        "total_channels": session.scalar(owned(select(func.count(Channel.id)), Channel, owner)) or 0,
        "pending_by_channel": counts_by_channel(Video.status == "pending"),
        "added_by_channel": {
            channel_pk: held
            for channel_pk, held in session.execute(
                select(Video.channel_pk, func.count(func.distinct(Placement.video_pk)))
                .join(Placement, Placement.video_pk == Video.id)
                .where(Placement.playlist_item_id.is_not(None))
                .group_by(Video.channel_pk)
            ).all()
        },
    }


_ACCOUNT_PLAYLIST_TTL = 120.0
_account_playlists_cache: dict[str, Any] = {"at": 0.0, "items": [], "error": None}


def _account_playlists(
    session: Session, *, refresh: bool = False, owner: OwnerId = None
) -> tuple[list[PlaylistInfo], str | None]:
    """The playlists on the connected account, cached for a couple of minutes."""
    now = time.monotonic()
    fresh = now - _account_playlists_cache["at"] < _ACCOUNT_PLAYLIST_TTL
    if fresh and not refresh:
        return _account_playlists_cache["items"], _account_playlists_cache["error"]

    items: list[PlaylistInfo] = []
    error: str | None = None
    with _http_client() as http:
        client = build_client(session, http, owner)
        if client.has_write_access:
            try:
                items = client.my_playlists()
            except PublishError as exc:
                error = str(exc)
    _account_playlists_cache.update({"at": now, "items": items, "error": error})
    return items, error


def _forget_account_playlists() -> None:
    _account_playlists_cache["at"] = 0.0


def _playlist_context(
    session: Session, creating: bool = False, *, owner: OwnerId = None
) -> Context:
    """Everything the targets panel needs, including the account's own lists."""
    state = _connection_state(session)
    available: list[PlaylistInfo] = []
    error: str | None = None
    if state["connected"]:
        available, error = _account_playlists(session, owner=owner)
    known = {p.playlist_id for p in state["playlists"]}
    return {
        "state": state,
        "targets": state["playlists"],
        "counts": state["playlist_counts"],
        "available": [p for p in available if p.playlist_id not in known],
        "playlist_error": error,
        "all_channels": channel_service.list_channels(session, owner),
        "creating": creating,
    }


def _youtube_offline(owner: OwnerId = None) -> Context | None:
    """The state where Google is not available: no usable account, but feeds
    that point at a YouTube playlist.

    Registered as a template global rather than threaded through every context,
    because the htmx fragments render outside `render()` and need it too.
    """
    with session_scope() as session:
        token = get_token(session, owner)
        if token is not None and not token.refresh_error:
            return None
        feeds = session.scalar(
            owned(select(func.count(Playlist.id)), Playlist, owner).where(
                Playlist.enabled.is_(True),
                Playlist.playlist_id.not_like(f"{GENERIC_PLAYLIST_PREFIX}%"),
            )
        )
        if not feeds:
            return None
        return {"feeds": feeds, "stale": token is not None}


def _connection_state(session: Session, owner: OwnerId = None) -> Context:
    token = get_token(session, owner)
    return {
        "connected": token is not None,
        "account": token.account_title if token else None,
        "needs_reconnect": bool(token and token.refresh_error),
        "reconnect_reason": token.refresh_error if token else None,
        "has_client": has_client_credentials(session, owner),
        "playlists": playlist_service.list_playlists(session, owner),
        "playlist_counts": playlist_service.item_counts(session, owner),
        "has_targets": bool(
            session.scalar(
                owned(select(func.count(Playlist.id)), Playlist, owner).where(
                    Playlist.enabled.is_(True)
                )
            )
        ),
    }


# -- dashboard ------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    owner = owner_of(request)
    with session_scope() as session:
        context = {
            **_stats_context(session, owner),
            **_activity_context(session, owner),
            **_quota_context(session),
            "state": _connection_state(session, owner),
            "settings": get_settings(session, owner),
            "next_run": scheduler.next_run_time(),
        }
    return render(request, "dashboard.html", context)


# There is no "sync everything now" route any more. A run is started from a
# trigger box on the canvas, which polls what it is wired to and nothing else
# — and a header button that ignored every wire drawn there was a second,
# contradictory answer to "when does this get polled". The scheduler still
# runs the graph's own schedules, and the CLI still has `dealgo sync`.


# -- the log ---------------------------------------------------------------
#
# Which runs, started how, and what each of them did on the way.

#: What the filter offers, and what each name means. "By hand" covers every
#: way a person can start one; the clock is the only thing that is not a
#: person, so the split is the honest one rather than one name per button.
LOG_FILTERS: tuple[tuple[str, str], ...] = (
    ("all", "Everything"),
    ("hand", "Started by me"),
    ("clock", "On a schedule"),
    ("trouble", "Went wrong"),
)


@app.get("/partials/log", response_class=HTMLResponse)
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


@app.get("/partials/sync-status", response_class=HTMLResponse)
def partial_sync_status(request: Request, seen: int = 0) -> HTMLResponse:
    """Polled by the header. Announces a finished run so panels can refresh."""
    running = sync_service.is_running()
    last_run_id = _last_run_id()
    headers = {}
    if not running and last_run_id and last_run_id != seen:
        headers["HX-Trigger"] = "dealgo:sync-finished"
    return fragment(
        request,
        "_sync_controls.html",
        {"sync_running": running, "last_run_id": last_run_id},
        headers=headers,
    )


@app.get("/partials/stats", response_class=HTMLResponse)
def partial_stats(request: Request) -> HTMLResponse:
    owner = owner_of(request)
    with session_scope() as session:
        context = _stats_context(session, owner)
    return fragment(request, "_stats.html", context)


@app.get("/partials/activity", response_class=HTMLResponse)
def partial_activity(request: Request) -> HTMLResponse:
    owner = owner_of(request)
    with session_scope() as session:
        context = _activity_context(session, owner)
    return fragment(request, "_activity.html", context)


@app.get("/partials/dashboard", response_class=HTMLResponse)
def partial_dashboard(request: Request) -> HTMLResponse:
    owner = owner_of(request)
    with session_scope() as session:
        context = {
            **_stats_context(session, owner),
            **_quota_context(session),
            "state": _connection_state(session, owner),
            "settings": get_settings(session, owner),
            "next_run": scheduler.next_run_time(),
        }
    return fragment(request, "_dashboard_state.html", context)


@app.get("/api/status")
def api_status(request: Request) -> JSONResponse:
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


# -- sources --------------------------------------------------------------
#
# What this account watches, and the labels it groups them by. Separate from
# the canvas on purpose: this is the list of what is available, the canvas is
# what is done with it.


# -- channels -------------------------------------------------------------


@app.get("/channels", response_class=HTMLResponse)
def channels_page(
    request: Request, feed: str = "", new: str = "", track: str = "", q: str = ""
) -> HTMLResponse:
    owner = owner_of(request)
    with session_scope() as session:
        context = {
            **_channel_list_context(session, feed, tracking=track == "1", query=q, owner=owner),
            **_playlist_context(session, creating=new == "1", owner=owner),
            "plugin_nodes": _palette_plugins(),
        }
    return render(request, "channels.html", context)


def _palette_plugins() -> list[Context]:
    """What the plugins put in the palette, grouped by the plugin offering it.

    A plugin's source box comes first in its own group, because that is the
    box somebody is looking for: there is no generic Channel box any more,
    and the way to watch a subreddit is to drag out the Subreddit box.

    In the order the registry read them, so the palette is the same on every
    visit. A plugin offering nothing is left out entirely rather than shown
    as an empty heading, which would be a question about nothing.
    """
    found = registry.current()
    grouped: dict[str, list[Context]] = {}
    for kind in found.source_kinds():
        grouped.setdefault(kind.plugin, []).append(
            {
                "palette": "source",
                "ref": kind.kind,
                "label": kind.noun or kind.label,
                "blurb": kind.blurb or f"One {kind.label} source.",
                "swatch": "source",
            }
        )
    for node in found.node_kinds():
        grouped.setdefault(node.plugin, []).append(
            {
                "palette": "plugin",
                "ref": node.ref,
                "label": node.label,
                "blurb": node.blurb,
                "swatch": "plugin",
            }
        )
    return [{"plugin": plugin, "nodes": nodes} for plugin, nodes in grouped.items()]
def _channel_list_response(
    request: Request,
    *,
    ok: str | None = None,
    err: str | None = None,
    feed: str = "",
    tracking: bool = False,
    back: str = "",
    query: str = "",
) -> Response:
    """Every channel mutation answers with the whole list, freshly counted."""
    owner = owner_of(request)
    if back:
        # A channel's own page posts plainly and returns to itself.
        return redirect(back, ok=ok, err=err)
    # The canvas is the only view of this now, and it reloads itself.
    return redirect("/channels", ok=ok, err=err)


@app.get("/channels/{channel_id}", response_class=HTMLResponse)
def channel_detail(request: Request, channel_id: int, q: str = "") -> Response:
    owner = owner_of(request)
    with session_scope() as session:
        channel = session.scalar(
            owned(select(Channel), Channel, owner)
            .options(selectinload(Channel.playlists))
            .where(Channel.id == channel_id)
        )
        if channel is None:
            return redirect("/channels", err="That channel is no longer being watched.")
        videos = list(
            session.scalars(
                owned(select(Video), Video, owner)
                .options(
                    selectinload(Video.channel),
                    selectinload(Video.placements).selectinload(Placement.playlist),
                )
                .where(Video.channel_pk == channel_id)
                .order_by(Video.published_at.desc())
                .limit(50)
            )
        )
        context = {
            "channel": channel,
            "videos": videos,
            "settings": get_settings(session, owner),
            "all_playlists": _matching_feeds(playlist_service.list_playlists(session, owner), q),
            "query": q,
                "channel_playlist_pks": {p.id for p in channel.playlists},
            "placed": session.scalar(
                select(func.count(func.distinct(Placement.video_pk)))
                .join(Video, Video.id == Placement.video_pk)
                .where(Video.channel_pk == channel_id, Placement.playlist_item_id.is_not(None))
            )
            or 0,
            "pending": session.scalar(
                select(func.count(Video.id)).where(
                    Video.channel_pk == channel_id, Video.status == "pending"
                )
            )
            or 0,
        }
    return render(request, "channel_detail.html", context)


@app.post("/channels/{channel_id}/delete")
def remove_channel(request: Request, channel_id: int, feed: str = Form("")) -> Response:
    with session_scope() as session:
        channel = session.get(Channel, channel_id)
        if channel is None:
            return _channel_list_response(request, err="That channel is no longer being watched.", feed=feed)
        title = channel.title
        channel_service.delete_channel(session, channel)
    return _channel_list_response(request, ok=f"Stopped watching {title}.", feed=feed)


# -- feed -----------------------------------------------------------------


def _feed_context(
    session: Session,
    *,
    playlist: str = "",
    query: str = "",
    owner: OwnerId = None,
    sitting: bool = False,
) -> Context:
    """What is in each feed right now, each laid out the way that feed asks.

    ``sitting`` says whether somebody actually came to the feed. A pulse on a
    feed's second input gives a stretch of reading that starts when you sit
    down, so arriving is what starts it — and a background refresh must not,
    or a sync landing overnight would spend the day's reading before anyone
    was awake to do it.
    """
    wanted = int(playlist) if playlist.isdigit() else None

    playlists = [p for p in playlist_service.list_playlists(session, owner) if p.enabled or wanted]
    terms = query.lower().split()
    if terms:
        # Name or tag, any order, partial words.
        playlists = [p for p in playlists if all(term in p.searchable for term in terms)]
    windows = graph_service.consumption(session, owner)
    now = utcnow()

    sections = []
    for target in playlists:
        if wanted and target.id != wanted:
            continue

        # A feed with a Reset slotted under it is only read while that window
        # is open. Shown as shut rather than hidden: a feed that vanished
        # would read as a feed that had gone.
        opens = windows.get(target.id, [])
        if opens:
            state = graph_service.window_state(opens, now)
            if not state.open:
                sections.append(
                    {
                        "playlist": target,
                        "videos": [],
                        "total": 0,
                        "shut": _window_words(opens),
                        "opens_at": state.opens_at,
                    }
                )
                continue
            if sitting:
                graph_service.begin_sitting(session, state, now)
        # Not `query`: that name is the search text on this function.
        statement = (
            owned(select(Video), Video, owner)
            .join(Placement, Placement.video_pk == Video.id)
            .options(selectinload(Video.channel))
            .where(Placement.playlist_pk == target.id, Placement.playlist_item_id.is_not(None))
        )
        if target.view_show != "all":
            statement = statement.where(Video.watched_at.is_(None))
        direction = (
            Video.published_at.desc() if target.view_order == "newest"
            else Video.published_at.asc()
        )
        videos = list(session.scalars(statement.order_by(direction, Video.id.asc())))

        total = (
            session.scalar(
                select(func.count(Placement.id)).where(
                    Placement.playlist_pk == target.id, Placement.playlist_item_id.is_not(None)
                )
            )
            or 0
        )
        sections.append(
            {"playlist": target, "videos": videos, "total": total, "shut": [], "opens_at": None}
        )

    return {
        "sections": sections,
        "playlist_filter": wanted,
        # Named, so a page showing one feed can say which — an unexplained
        # single section looks like the other feeds have gone.
        "filtered_feed": next((p for p in playlist_service.list_playlists(session, owner)
                               if p.id == wanted), None) if wanted else None,
        "query": query,
        "all_playlists": playlist_service.list_playlists(session, owner),
        "feed_query": urlencode({"playlist": playlist or "", "q": query or ""}),
    }


@app.get("/feed", response_class=HTMLResponse)
def feed_page(request: Request, playlist: str = "", q: str = "") -> HTMLResponse:
    owner = owner_of(request)
    with session_scope() as session:
        context = _feed_context(session, playlist=playlist, query=q, owner=owner, sitting=True)
    return render(request, "feed.html", context)


@app.get("/partials/feed", response_class=HTMLResponse)
def partial_feed(request: Request, playlist: str = "", q: str = "") -> HTMLResponse:
    """The sections again after a sync landed. Not a sitting: nobody arrived,
    the page they were already on caught up."""
    owner = owner_of(request)
    with session_scope() as session:
        context = _feed_context(session, playlist=playlist, query=q, owner=owner)
    return fragment(request, "_feed_sections.html", context)


@app.post("/feeds/{playlist_pk}/view")
def set_feed_view(
    request: Request,
    playlist_pk: int,
    order: str = Form(""),
    show: str = Form(""),
    playlist: str = Form(""),
    q: str = Form(""),
) -> Response:
    """Each feed is laid out its own way, and remembers it."""
    owner = owner_of(request)
    with session_scope() as session:
        target = session.get(Playlist, playlist_pk)
        if target is None:
            return redirect("/feed", err="That feed is no longer a target.")
        playlist_service.set_view(session, target, order=order, show=show)

    if is_htmx(request):
        with session_scope() as session:
            # Changing how a feed is laid out is somebody looking at it.
            context = _feed_context(
                session, playlist=playlist, query=q, owner=owner, sitting=True
            )
        return fragment(request, "_feed_sections.html", context)
    return redirect(f"/feed?{urlencode({'playlist': playlist, 'q': q})}")


def _focus_item(video: Video, playlist_title: str = "") -> Context:
    """One entry in the Focus queue: a video, a community post, or an item
    from a feed somewhere else. The last two are read rather than played, and
    differ only in what the link out is called."""
    return {
        "id": video.id,
        "video_id": video.video_id,
        "kind": video.kind,
        # Where it came from, said the way a person would say it, so the page
        # can offer "Open it on Reddit" without knowing the list of kinds.
        "source": sources.describe(video.channel.source_kind).label,
        "title": video.title or video.video_id,
        "channel": video.channel.title,
        "playlist": playlist_title,
        "duration": format_duration(video.duration_sec),
        "thumbnail": video.thumbnail_url,
        # Posts carry their whole content: there is no player to fetch it.
        "body": video.body or "",
        # Not `image_list`: a feed that names one picture and carries no
        # others still has a picture to show.
        "images": video.pictures,
        "url": video.url,
    }


def _focus_queue(
    session: Session, *, order: str, playlist: str, start: int | None = None, owner: OwnerId = None
) -> list[Context]:
    """The unwatched items to go through, flattened across playlists.

    Rebuilt from the database on every advance rather than trusted from the
    browser, so a queue left open overnight cannot resurrect a video that has
    since been watched or removed.
    """
    order = "newest" if order == "newest" else "oldest"
    wanted = int(playlist) if playlist.isdigit() else None
    direction = Video.published_at.desc() if order == "newest" else Video.published_at.asc()

    queue: list[Context] = []
    seen: set[int] = set()
    for target in playlist_service.list_playlists(session, owner):
        if not target.enabled or (wanted and target.id != wanted):
            continue
        videos = session.scalars(
            owned(select(Video), Video, owner)
            .join(Placement, Placement.video_pk == Video.id)
            .options(selectinload(Video.channel))
            .where(
                Placement.playlist_pk == target.id,
                Placement.playlist_item_id.is_not(None),
                Video.watched_at.is_(None),
            )
            .order_by(direction, Video.id.asc())
        )
        for video in videos:
            if video.id in seen:  # a video in two playlists plays once
                continue
            seen.add(video.id)
            queue.append(_focus_item(video, target.title))

    if start is not None:
        at = next((i for i, item in enumerate(queue) if item["id"] == start), None)
        if at is not None:
            queue = queue[at:]
        else:
            # Starting from something already watched: play it, then carry on.
            opened_on = session.scalar(
                owned(select(Video), Video, owner).options(selectinload(Video.channel)).where(Video.id == start)
            )
            if opened_on is not None:
                queue.insert(0, _focus_item(opened_on))
    return queue


@app.get("/focus", response_class=HTMLResponse)
def focus(request: Request, order: str = "oldest", playlist: str = "", start: str = "") -> HTMLResponse:
    owner = owner_of(request)
    start_id = int(start) if start.isdigit() else None
    with session_scope() as session:
        queue = _focus_queue(session, order=order, playlist=playlist, start=start_id, owner=owner)
        context = {
            "queue": queue,
            "queue_json": json.dumps(queue),
            "order": "newest" if order == "newest" else "oldest",
            "playlist": playlist,
            # A post never ends by itself, so reading time is what moves it on.
            "post_seconds": get_settings(session, owner).post_seconds,
            "playlist_title": next(
                (p.title for p in playlist_service.list_playlists(session, owner) if str(p.id) == playlist),
                None,
            ),
        }
    return render(request, "focus.html", context)


@app.get("/watch")
def watch_moved(order: str = "oldest", playlist: str = "", start: str = "") -> RedirectResponse:
    """Theater mode's old address. Links and bookmarks outlive renames."""
    return redirect(f"/focus?order={order}&playlist={playlist}&start={start}")


# How much of the queue travels back with each advance. Enough to fill the
# "up next" list without shipping a thousand-video feed on every click.
UPCOMING_SHOWN = 40


@app.post("/focus/{video_id}/finished")
def focus_finished(
    request: Request,
    video_id: int,
    order: str = Form("oldest"),
    playlist: str = Form(""),
    watched: str = Form("1"),
    skipped: str = Form(""),
) -> JSONResponse:
    """Called by the player when a video ends, or when someone skips.

    The queue is rebuilt from the database rather than trusted from the
    browser, so a tab left open overnight cannot resurrect something watched
    or removed since — but it is rebuilt *from where the sitting is*, not from
    the top. Position comes from the item just finished, which is why the
    queue is read before it is marked watched: once watched it drops out of
    the queue, and there is no longer a place in it to carry on from.
    """
    owner = owner_of(request)
    with session_scope() as session:
        video = session.get(Video, video_id)
        if video is None:
            return JSONResponse({"error": "unknown video"}, status_code=404)

        queue = _focus_queue(session, order=order, playlist=playlist, start=video_id, owner=owner)
        # Everything after the one just finished — the sitting carries on
        # rather than starting again.
        rest = queue[1:] if queue and queue[0]["id"] == video_id else queue

        # Skipping means "not this sitting", so those stay out for the rest of
        # it. They are still unwatched, and come back in the next one.
        passed_over = {int(part) for part in skipped.split(",") if part.strip().isdigit()}
        passed_over.add(video_id)
        rest = [item for item in rest if item["id"] not in passed_over]

        if watched == "1":
            watched_service.mark_watched(session, [video_id], owner)

    return JSONResponse(
        {
            "next": rest[0] if rest else None,
            "remaining": len(rest),
            # The list the page shows, rebuilt from the same queue the next
            # item came from, so the two cannot drift apart.
            "upcoming": rest[1 : 1 + UPCOMING_SHOWN],
        }
    )


# -- videos ---------------------------------------------------------------


@app.get("/videos", response_class=HTMLResponse)
def videos_page(
    request: Request,
    status: str = "",
    watched: str = "",
    channel: str = "",
    page: int = 1,
    q: str = "",
) -> HTMLResponse:
    owner = owner_of(request)
    page_size = 60
    page = max(1, page)
    with session_scope() as session:
        query = owned(select(Video), Video, owner)
        terms = q.split()
        if terms:
            # Each word must appear in the title, the channel name or the id —
            # in any order, and a partial word counts.
            query = query.join(Channel, Channel.id == Video.channel_pk)
            for term in terms:
                like = f"%{term}%"
                query = query.where(
                    Video.title.ilike(like)
                    | Channel.title.ilike(like)
                    | Video.video_id.ilike(like)
                )
        if watched == "1":
            query = query.where(Video.watched_at.is_not(None))
        elif status in Video.STATUSES:
            query = query.where(Video.status == status)
        channel_pk = int(channel) if channel.isdigit() else None
        if channel_pk:
            query = query.where(Video.channel_pk == channel_pk)
        total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
        videos = list(
            session.scalars(
                query.options(
                    selectinload(Video.channel),
                    selectinload(Video.placements).selectinload(Placement.playlist),
                )
                .order_by(Video.published_at.desc(), Video.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        counts: dict[str, int] = {
            status: held
            for status, held in session.execute(
                select(Video.status, func.count(Video.id)).group_by(Video.status)
            ).all()
        }
        context = {
            "videos": videos,
            "counts": counts,
            "watched_count": watched_service.count_watched(session, owner),
            "removable_count": watched_service.count_removable(session, owner),
            "status": "" if watched == "1" else status,
            "watched": watched,
            "query": q,
            "channel_filter": channel_pk,
            "channels": channel_service.list_channels(session, owner),
            "page": page,
            "pages": max(1, -(-total // page_size)),
            "total": total,
        }
    return render(request, "videos.html", context)


def _video_row_response(
    request: Request,
    video_id: int,
    *,
    ok: str | None = None,
    err: str | None = None,
    back: str = "/videos",
    watched_changed: bool = False,
    view: str = "list",
) -> Response:
    if not is_htmx(request):
        return redirect(back, ok=ok, err=err)
    # Panels that count watched videos listen for this and re-render themselves.
    headers = {"HX-Trigger": "dealgo:watched-changed"} if watched_changed else None
    template = "_feed_card.html" if view == "feed" else "_video_row.html"
    owner = owner_of(request)
    with session_scope() as session:
        video = session.scalar(
            owned(select(Video), Video, owner)
            .options(
                selectinload(Video.channel),
                selectinload(Video.placements).selectinload(Placement.playlist),
            )
            .where(Video.id == video_id)
        )
        if video is None:
            return fragment(request, "_empty.html", {}, err=err or "That video is no longer tracked.")
        return fragment(request, template, {"video": video}, ok=ok, err=err, headers=headers)


@app.post("/videos/{video_id}/requeue")
def requeue_video(request: Request, video_id: int, back: str = Form("/videos")) -> Response:
    with session_scope() as session:
        video = session.get(Video, video_id)
        if video is None:
            return redirect(back, err="That video is no longer tracked.")
        if video.status == "added":
            return _video_row_response(request, video_id, err="That video is already in the playlist.", back=back)
        video.status = "pending"
        video.reason = None
        video.attempts = 0
        video.processed_at = None
        title = video.title
    return _video_row_response(request, video_id, ok=f"Queued {title!r} for the next sync.", back=back)


@app.post("/videos/{video_id}/watched")
def mark_video_watched(request: Request, video_id: int, back: str = Form("/videos"), view: str = Form("list")) -> Response:
    owner = owner_of(request)
    with session_scope() as session:
        video = session.get(Video, video_id)
        if video is None:
            return redirect(back, err="That video is no longer tracked.")
        watched_service.mark_watched(session, [video_id], owner)
        title = video.title
    return _video_row_response(
        request, video_id, ok=f"Marked {title!r} watched.", back=back, watched_changed=True, view=view
    )


@app.post("/videos/{video_id}/unwatched")
def mark_video_unwatched(request: Request, video_id: int, back: str = Form("/videos"), view: str = Form("list")) -> Response:
    owner = owner_of(request)
    with session_scope() as session:
        video = session.get(Video, video_id)
        if video is None:
            return redirect(back, err="That video is no longer tracked.")
        watched_service.mark_unwatched(session, [video_id], owner)
        title = video.title
    return _video_row_response(
        request,
        video_id,
        ok=f"{title!r} is no longer marked watched.",
        back=back,
        watched_changed=True,
        view=view,
    )


@app.post("/playlist/mark-all-watched")
def mark_all_watched(request: Request) -> Response:
    owner = owner_of(request)
    with session_scope() as session:
        changed = watched_service.mark_all_in_playlist_watched(session, owner)
    message = (
        f"Marked {changed} video{'s' if changed != 1 else ''} watched."
        if changed
        else "Nothing in the playlist is unwatched."
    )
    if is_htmx(request):
        return fragment(
            request,
            "_sync_controls.html",
            {"sync_running": sync_service.is_running(), "last_run_id": _last_run_id()},
            ok=message,
            headers={"HX-Trigger": "dealgo:watched-changed"},
        )
    return redirect("/videos?watched=1", ok=message)


@app.post("/playlist/remove-watched")
def remove_watched(request: Request) -> Response:
    """Clear watched videos out of the playlist, on the user's instruction."""
    owner = owner_of(request)
    with session_scope() as session:
        removable = watched_service.count_removable(session, owner)
        connected = get_token(session, owner) is not None
        feeds = list(
            session.scalars(
                owned(select(Playlist), Playlist, owner).where(Playlist.enabled.is_(True))
            )
        )
        blocker = None
        if not feeds:
            blocker = "No feeds are set up."
        elif not connected and all(not feed.is_generic for feed in feeds):
            # Local feeds need no account; YouTube ones do.
            blocker = "Connect a Google account before removing videos from the playlist."

    # Checked here, not just in the worker: promising a removal that cannot
    # happen would leave the failure invisible in a background thread.
    if blocker:
        if is_htmx(request):
            return fragment(
                request,
                "_sync_controls.html",
                {"sync_running": sync_service.is_running(), "last_run_id": _last_run_id()},
                err=blocker,
            )
        return redirect("/videos?watched=1", err=blocker)

    if not removable:
        message = "No watched videos are in the playlist."
        if is_htmx(request):
            return fragment(
                request,
                "_sync_controls.html",
                {"sync_running": sync_service.is_running(), "last_run_id": _last_run_id()},
                ok=message,
            )
        return redirect("/videos?watched=1", ok=message)

    # Each removal is a round trip to YouTube, so it runs in the background and
    # reports itself through the run log like a sync does.
    threading.Thread(
        target=watched_service.remove_watched, args=("manual", owner), daemon=True
    ).start()
    message = f"Removing {removable} watched video{'s' if removable != 1 else ''} from the playlist…"
    if is_htmx(request):
        return fragment(
            request,
            "_sync_controls.html",
            {"sync_running": True, "last_run_id": _last_run_id()},
            ok=message,
        )
    return redirect("/videos?watched=1", ok=message)


@app.post("/videos/{video_id}/ignore")
def ignore_video(request: Request, video_id: int, back: str = Form("/videos")) -> Response:
    with session_scope() as session:
        video = session.get(Video, video_id)
        if video is None:
            return redirect(back, err="That video is no longer tracked.")
        video.status = "ignored"
        video.reason = "ignored by hand"
        title = video.title
    return _video_row_response(request, video_id, ok=f"Ignoring {title!r}.", back=back)


# -- settings -------------------------------------------------------------


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request) -> HTMLResponse:
    owner = owner_of(request)
    with session_scope() as session:
        context = {
            **_quota_context(session),
            "state": _connection_state(session, owner),
            "settings": get_settings(session, owner),
            "env_client_id": bool(CONFIG.client_id),
            "env_client_secret": bool(CONFIG.client_secret),
            "env_api_key": bool(CONFIG.api_key),
            "redirect_uri": CONFIG.redirect_uri,
            "next_run": scheduler.next_run_time(),
            # Feeds backed by a real YouTube playlist are made here: the
            # canvas makes the ones that live inside De-Algo.
            **_playlist_context(session, owner=owner),
        }
    return render(request, "settings.html", context)


@app.post("/settings")
def save_settings(
    poll_interval_minutes: str = Form("30"),
    initial_backfill: str = Form("3"),
    shorts_max_seconds: str = Form("60"),
    post_seconds: str = Form("30"),
    daily_quota: str = Form("10000"),
    quota_reserve: str = Form("0"),
    hide_tour: str = Form(""),
    hide_open_notice: str = Form(""),
    hide_connect_notice: str = Form(""),
    auto_sync: str = Form(""),
    client_id: str = Form(""),
    client_secret: str = Form(""),
    api_key: str = Form(""),
) -> RedirectResponse:
    def as_int(raw: str, default: int, minimum: int = 0) -> int:
        try:
            return max(minimum, int(raw.strip()))
        except (ValueError, AttributeError):
            return default

    with session_scope() as session:
        settings = get_settings(session)
        settings.poll_interval_minutes = as_int(poll_interval_minutes, 30, minimum=1)
        settings.initial_backfill = as_int(initial_backfill, 3)
        settings.shorts_max_seconds = as_int(shorts_max_seconds, 60)
        # A post that flicks past in a second or two cannot be read, so the
        # floor is a real one rather than zero.
        settings.post_seconds = as_int(post_seconds, 30, minimum=3)
        settings.daily_quota = as_int(daily_quota, 10000)
        settings.quota_reserve = as_int(quota_reserve, 0)
        settings.hide_tour = bool(hide_tour)
        settings.hide_open_notice = bool(hide_open_notice)
        settings.hide_connect_notice = bool(hide_connect_notice)
        settings.auto_sync = bool(auto_sync)
        settings.client_id = client_id.strip() or None
        settings.client_secret = client_secret.strip() or None
        settings.api_key = api_key.strip() or None
    scheduler.reschedule()
    return redirect("/settings", ok="Settings saved.")


def _playlists_response(
    request: Request,
    *,
    ok: str | None = None,
    err: str | None = None,
    creating: bool = False,
    back: str = "",
) -> Response:
    owner = owner_of(request)
    if back:
        # The detail page posts plainly and returns to itself.
        return redirect(back, ok=ok, err=err)
    return redirect("/channels", ok=ok, err=err)


@app.post("/settings/feeds/new")
def create_feed(
    request: Request,
    source: str = Form("new"),
    new_title: str = Form(""),
    generic_title: str = Form(""),
    privacy: str = Form("private"),
    playlist_id: str = Form(""),
    channels: list[int] = Form(default=[]),
) -> Response:
    """Set up a feed in one step: the playlist, then what fills it."""
    owner = owner_of(request)
    with session_scope() as session, _http_client() as http:
        try:
            playlist, linked = playlist_service.set_up_feed(
                session,
                http,
                source=source,
                title=generic_title if source == "generic" else new_title,
                privacy=privacy,
                playlist_id=playlist_id,
                channel_pks=channels,
                owner=owner,
            )
        except playlist_service.PlaylistError as exc:
            return redirect("/settings", err=str(exc))
        title = playlist.title

    _forget_account_playlists()
    message = f"Now feeding {title!r}. It is on the Configuration canvas."
    if linked:
        message += f" {linked} channel{'s' if linked != 1 else ''} linked."
    return redirect("/settings", ok=message)


@app.post("/settings/playlists/{playlist_pk}")
def save_playlist(
    request: Request,
    playlist_pk: int,
    max_items: str = Form("0"),
    max_per_run: str = Form("0"),
    back: str = Form(""),
) -> Response:
    with session_scope() as session:
        playlist = session.get(Playlist, playlist_pk)
        if playlist is None:
            return _playlists_response(request, err="That playlist is no longer a target.", back=back)
        try:
            playlist_service.update(
                session,
                playlist,
                {"max_items": max_items, "max_per_run": max_per_run},
            )
        except playlist_service.PlaylistError as exc:
            return _playlists_response(request, err=str(exc), back=back)
        title = playlist.title
    return _playlists_response(request, ok=f"Saved {title!r}.", back=back)


@app.get("/feeds/{playlist_pk}", response_class=HTMLResponse)
def feed_detail(request: Request, playlist_pk: int, rename: str = "", q: str = "") -> Response:
    """Everything about one feed, off the list that only needs to be scannable."""
    owner = owner_of(request)
    with session_scope() as session:
        playlist = session.scalar(
            owned(select(Playlist), Playlist, owner)
            .options(selectinload(Playlist.channels))
            .where(Playlist.id == playlist_pk)
        )
        if playlist is None:
            return redirect("/channels", err="That feed is no longer a target.")

        videos = list(
            session.scalars(
                owned(select(Video), Video, owner)
                .join(Placement, Placement.video_pk == Video.id)
                .options(
                    selectinload(Video.channel),
                    selectinload(Video.placements).selectinload(Placement.playlist),
                )
                .where(Placement.playlist_pk == playlist_pk, Placement.playlist_item_id.is_not(None))
                .order_by(Video.published_at.desc())
                .limit(50)
            )
        )
        order = [p.id for p in playlist_service.list_playlists(session, owner)]
        context = {
            "playlist": playlist,
            "videos": videos,
            "held": playlist_service.item_counts(session, owner).get(playlist_pk, 0),
            "all_channels": _matching_channels(channel_service.list_channels(session, owner), q),
            "query": q,
            "position": order.index(playlist_pk) + 1 if playlist_pk in order else None,
            "total_feeds": len(order),
            "renaming": playlist_pk if rename == "1" else None,
            "state": _connection_state(session, owner),
        }
    return render(request, "feed_detail.html", context)


@app.post("/settings/playlists/{playlist_pk}/tags")
def set_playlist_tags(request: Request, playlist_pk: int, tags: str = Form(""), back: str = Form("")) -> Response:
    """Free-form labels, searchable on the Feed page."""
    with session_scope() as session:
        playlist = session.get(Playlist, playlist_pk)
        if playlist is None:
            return _playlists_response(request, err="That feed is no longer a target.", back=back)
        applied = playlist_service.set_tags(session, playlist, tags)
        title = playlist.title

    message = (
        f"{title} tagged {', '.join(applied)}." if applied else f"Cleared the tags on {title}."
    )
    return _playlists_response(request, ok=message, back=back)


@app.post("/settings/playlists/{playlist_pk}/filling")
def toggle_playlist_filling(request: Request, playlist_pk: int, back: str = Form("")) -> Response:
    """Pause or resume a feed without disturbing what is already in it."""
    with session_scope() as session:
        playlist = session.get(Playlist, playlist_pk)
        if playlist is None:
            return _playlists_response(request, err="That feed is no longer a target.", back=back)
        playlist_service.set_enabled(session, playlist, enabled=not playlist.enabled)
        title, filling = playlist.title, playlist.enabled

    message = (
        f"Filling {title} again." if filling
        else f"Paused {title}. Nothing already in it is removed."
    )
    return _playlists_response(request, ok=message, back=back)


@app.post("/settings/playlists/{playlist_pk}/rename")
def rename_playlist(
    request: Request, playlist_pk: int, title: str = Form(""), back: str = Form("")
) -> Response:
    """Retitle a feed, and the playlist behind it where there is one."""
    with session_scope() as session, _http_client() as http:
        playlist = session.get(Playlist, playlist_pk)
        if playlist is None:
            return _playlists_response(request, err="That feed is no longer a target.", back=back)
        try:
            on_youtube = playlist_service.rename(session, playlist, title, http)
        except playlist_service.PlaylistError as exc:
            # The local rename may well have gone through; say so either way.
            return _playlists_response(request, err=str(exc), back=back)
        new_title = playlist.title

    _forget_account_playlists()
    message = f"Renamed to {new_title!r}."
    if on_youtube:
        message += " The YouTube playlist was renamed too."
    return _playlists_response(request, ok=message, back=back)


@app.post("/settings/playlists/{playlist_pk}/unlink")
def unlink_playlist(request: Request, playlist_pk: int, back: str = Form("")) -> Response:
    """Keep the feed, drop the YouTube playlist behind it."""
    with session_scope() as session:
        playlist = session.get(Playlist, playlist_pk)
        if playlist is None:
            return _playlists_response(request, err="That feed is no longer a target.", back=back)
        try:
            playlist_service.unlink(session, playlist)
        except playlist_service.PlaylistError as exc:
            return _playlists_response(request, err=str(exc), back=back)
        title = playlist.title

    _forget_account_playlists()
    return _playlists_response(
        request,
        ok=f"{title} is now a generic feed. Its YouTube playlist and videos are untouched.",
        back=back,
    )


@app.post("/settings/playlists/{playlist_pk}/delete")
def delete_playlist(request: Request, playlist_pk: int, back: str = Form("")) -> Response:
    with session_scope() as session:
        playlist = session.get(Playlist, playlist_pk)
        if playlist is None:
            return _playlists_response(request, err="That playlist is no longer a target.", back=back)
        title = playlist.title
        playlist_service.remove(session, playlist)
    _forget_account_playlists()
    return _playlists_response(request, ok=f"Stopped feeding {title!r}. The playlist itself is untouched on YouTube."
    , back=back)


@app.post("/settings/playlists/{playlist_pk}/channels")
def set_feed_membership(
    request: Request,
    playlist_pk: int,
    channel_id: int = Form(...),
    include: str = Form("1"),
    back: str = Form(""),
) -> Response:
    """Add or remove one channel from one feed, straight from the feed row."""
    with session_scope() as session:
        playlist = session.get(Playlist, playlist_pk)
        if playlist is None:
            return _playlists_response(request, err="That feed is no longer a target.", back=back)
        try:
            title = playlist_service.set_membership(
                session, playlist, channel_id, include=include == "1"
            )
        except playlist_service.PlaylistError as exc:
            return _playlists_response(request, err=str(exc), back=back)
        feed_title = playlist.title
        channel = session.get(Channel, channel_id)
        resumed = include == "1" and channel is not None and channel.enabled
        stranded = include != "1" and channel is not None and channel.awaiting_feed

    verb = "now feeds" if include == "1" else "no longer feeds"
    message = f"{title} {verb} {feed_title}."
    if resumed and include == "1":
        message += " It was waiting for a feed, so watching has started."
    elif stranded:
        message += " It feeds nothing now, so it is paused until you link one."
    return _playlists_response(request, ok=message, back=back)


# -- oauth ----------------------------------------------------------------


@app.get("/oauth/start")
def oauth_start(request: Request) -> Response:
    with session_scope() as session:
        client_id, client_secret = client_credentials(session)
    if not (client_id and client_secret):
        return redirect("/settings", err="Add a Google OAuth client id and secret first.")

    state = secrets.token_urlsafe(24)
    _oauth_states[state] = dt.datetime.now(dt.timezone.utc).timestamp()
    url = oauth.build_authorization_url(client_id, CONFIG.redirect_uri, state)
    if is_htmx(request):
        # An XHR cannot follow a redirect to another origin, so hand the URL
        # back and let htmx navigate the whole window to it.
        return Response(status_code=200, headers={"HX-Redirect": url})
    return RedirectResponse(url, status_code=303)


@app.get("/oauth/callback")
def oauth_callback(
    request: Request, code: str = "", state: str = "", error: str = ""
) -> RedirectResponse:
    # Google sends the browser back here, so the session cookie says which
    # account the grant belongs to.
    owner = owner_of(request)
    if error:
        explanations = {
            "access_denied": (
                "Google refused the request. Either you declined it, or this account is not on the "
                "OAuth client's test-user list while the consent screen is still in Testing."
            ),
            "redirect_uri_mismatch": (
                f"The OAuth client has no redirect URI matching {CONFIG.redirect_uri} — add it "
                "exactly, including the scheme and port."
            ),
        }
        return redirect("/settings", err=explanations.get(error, f"Google returned an error: {error}"))
    if not code:
        return redirect("/settings", err="Google did not return an authorization code.")

    issued = _oauth_states.pop(state, None)
    now = dt.datetime.now(dt.timezone.utc).timestamp()
    # Drop anything stale so the dict cannot grow without bound.
    for key, value in list(_oauth_states.items()):
        if now - value > 600:
            _oauth_states.pop(key, None)
    if issued is None or now - issued > 600:
        return redirect("/settings", err="That sign-in link expired. Try connecting again.")

    with session_scope() as session, _http_client() as http:
        client_id, client_secret = client_credentials(session)
        try:
            token = oauth.exchange_code(
                code=code,
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri=CONFIG.redirect_uri,
                client=http,
            )
        except oauth.OAuthError as exc:
            return redirect("/settings", err=f"Could not complete sign-in: {exc}")

        store_token(session, token, owner=owner)
        client = build_client(session, http)
        try:
            account = client.account_name()
        except PublishError:
            account = None
        if account:
            store_token(session, token, account_title=account, owner=owner)
    return redirect("/settings", ok="Google account connected.")


@app.post("/oauth/disconnect")
def oauth_disconnect() -> RedirectResponse:
    with session_scope() as session, _http_client() as http:
        disconnect(session, http)
    return redirect("/settings", ok="Google account disconnected.")


@app.get("/settings/backup")
def download_backup(request: Request) -> Response:
    """The setup, as a JSON file the browser saves."""
    owner = owner_of(request)
    with session_scope() as session:
        data = backup_service.build_export(session, owner)
    body = json.dumps(data, indent=2, ensure_ascii=False)
    return Response(
        content=body,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{backup_service.filename()}"',
            "Content-Length": str(len(body.encode("utf-8"))),
        },
    )


@app.post("/settings/restore")
def restore_backup(request: Request, backup_file: UploadFile = File(...)) -> RedirectResponse:
    """Load a backup file back in, matching rows by their YouTube ids."""
    owner = owner_of(request)
    raw = backup_file.file.read()
    if len(raw) > 32 * 1024 * 1024:
        return redirect("/settings", err="That file is too large to be a De-Algo backup.")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return redirect("/settings", err="That file is not readable JSON.")

    with session_scope() as session:
        try:
            summary = backup_service.restore(session, payload, owner)
        except backup_service.RestoreError as exc:
            return redirect("/settings", err=str(exc))
        message = summary.describe()
        if summary.skipped:
            message += f" {len(summary.skipped)} video(s) skipped: their channel was not in the file."

    scheduler.reschedule()
    return redirect("/settings", ok=message)


@app.get("/tour", response_class=HTMLResponse)
def tour(request: Request, step: int = 1) -> HTMLResponse:
    """A guided walk from an empty install to a daily habit."""
    owner = owner_of(request)
    with session_scope() as session:
        progress = _tour_progress(session, owner)
        context = {"progress": progress, "step": step}
    return render(request, "tour.html", context)


# -- signing in -----------------------------------------------------------


def _set_session_cookie(response: Response, request: Request, token: str) -> None:
    """Http-only so no script can read it, Lax so it does not ride along with
    a cross-site form post, Secure wherever the connection can carry it."""
    response.set_cookie(
        accounts.SESSION_COOKIE,
        token,
        max_age=CONFIG.session_days * 24 * 60 * 60,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "") -> Response:
    if not CONFIG.auth_enabled:
        return redirect("/")
    if getattr(request.state, "identity", None) is not None:
        return redirect(guard.safe_next(next))
    return render(request, "login.html", {"next": guard.safe_next(next)})


@app.post("/login")
def sign_in(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    next: str = Form(""),
) -> Response:
    if not CONFIG.auth_enabled:
        return redirect("/")

    destination = guard.safe_next(next)
    with session_scope() as session:
        try:
            user = accounts.authenticate(session, username, password)
        except accounts.AccountError as exc:
            log.info("failed sign-in for %r", username.strip()[:64])
            return render(
                request,
                "login.html",
                {"next": destination, "username": username, "error_message": str(exc)},
            )
        token = accounts.start_session(
            session, user, agent=request.headers.get("user-agent", "")
        )

    response = redirect(destination, ok=f"Signed in as {username.strip().lower()}.")
    _set_session_cookie(response, request, token)
    return response


@app.post("/logout")
def sign_out(request: Request) -> Response:
    with session_scope() as session:
        accounts.end_session(session, request.cookies.get(accounts.SESSION_COOKIE))
    response = redirect("/login", ok="Signed out.")
    response.delete_cookie(accounts.SESSION_COOKIE, path="/")
    return response


@app.get("/logout")
def sign_out_link(request: Request) -> Response:
    """So the menu can offer it as a plain link with no JavaScript."""
    return sign_out(request)


# -- the canvas -----------------------------------------------------------


def _graph_payload(session: Session, owner: OwnerId) -> Context:
    """The whole canvas as JSON: what the browser draws from."""
    nodes, _ = graph_service.load(session, owner)
    plan = graph_service.polling_plan(session, owner)
    facts = _channel_facts(session, owner)
    windows = graph_service.consumption(session, owner)
    opening = {node.id for wired in windows.values() for node in wired}
    # What each empty source box is waiting to be told, worked out once per
    # node because the title and the form both want it.
    asking = {
        node.id: _asks_for(node) for node in nodes if node.kind == "source"
    }
    # The same, for the two ends of a repository: the count is wanted on the
    # box and in its panel, and counting it twice per box would be two
    # queries each for one answer.
    stores = {
        node.id: _store_facts(session, node, owner)
        for node in nodes
        if node.kind in ("deposit", "withdraw")
    }
    return {
        "nodes": [
            {
                "id": node.id,
                "kind": node.kind,
                # An empty source box is named after the kind it was dragged
                # out as — "New Subreddit". Said here rather than on the model
                # because the pretty name is the plugin's and the model must
                # be readable without asking which plugins are loaded.
                "title": _box_title(node, asking.get(node.id)),
                "x": node.x,
                "y": node.y,
                "detail": (
                    f"/channels/{node.channel_pk}" if node.kind == "source" and node.channel_pk
                    else f"/feeds/{node.playlist_pk}" if node.kind == "feed" and node.playlist_pk
                    else None
                ),
                "note": _node_note(node, opening, stores.get(node.id)),
                "enabled": _is_on(node),
                "size": (
                    None
                    if node.kind != "group"
                    else {
                        "width": node.width or graph_service.GROUP_SIZE[0],
                        "height": node.height or graph_service.GROUP_SIZE[1],
                    }
                ),
                "polled": _how_polled(node, plan) if node.kind == "source" else None,
                "plugin": _plugin_facts(node) if node.kind == "plugin" else None,
                "channel": facts.get(node.channel_pk or 0) if node.kind == "source" else None,
                # Which kind of somewhere an empty box is for, and what to
                # type into it. Sent per box rather than looked up in the
                # browser, because the palette is the only other place that
                # knows and a second copy would be a second thing to keep up.
                "asks": asking.get(node.id) if node.kind == "source" else None,
                "store": stores.get(node.id),
                # A jigsaw piece: what it is slotted under, and what it says.
                # Drawn under its host rather than at its own position, so the
                # canvas needs to know which box that is.
                "piece": (
                    {
                        "under": node.attached_to,
                        "minutes": node.duration_minutes or graph_service.DEFAULT_DURATION_MINUTES,
                        "cron": node.cron or graph_service.DEFAULT_CRON,
                        "from": graph_service.clock_time(node.alive_from),
                        "to": graph_service.clock_time(node.alive_to),
                    }
                    if node.kind in graph_service.JIGSAW
                    else None
                ),
                "feed": (
                    _feed_facts(node, windows.get(node.playlist_pk or 0, []))
                    if node.kind == "feed"
                    else None
                ),
                "overrides": {name: value for name, value in node.overrides.items()},
                "sort": (
                    None
                    if node.kind != "sort"
                    else {
                        "by": node.sort_by or graph_service.DEFAULT_SORT_BY,
                        "desc": (node.sort_dir or "desc") == "desc",
                        # Each key carries its own two ends, so the canvas
                        # can say "Longest first" rather than "Most first".
                        "keys": [
                            {"name": name, "label": label, "first": first, "last": last}
                            for name, label, first, last in graph_service.SORT_KEYS
                        ],
                    }
                ),
                "trigger": (
                    None
                    if node.kind != "trigger"
                    else {
                        "kind": node.trigger_kind or "pulse",
                        "every_minutes": node.every_minutes,
                        # The same gap said as an amount and a unit, so the
                        # canvas can offer "2 hours" rather than "120".
                        "every": _every_parts(node),
                        "cron": node.cron,
                        "next": _next_firing(node),
                        "duration": node.duration_minutes,
                        # A trigger wired to a feed opens a window rather than
                        # setting something off, and is asked different things.
                        "opens": node.id in opening,
                        "last_fired": node.last_fired_at.isoformat() if node.last_fired_at else None,
                    }
                ),
            }
            for node in nodes
        ],
        "wires": graph_service.wires(session, owner),
        # What is already watched, for a source node to be pointed at rather
        # than told again. Sent once for the whole canvas: every empty source
        # node offers the same list, narrowed in the browser to its own kind.
        "sources": [
            {
                "id": channel.id,
                "title": channel.title or channel.channel_id,
                "kind": channel.source_kind,
            }
            for channel in channel_service.list_channels(session, owner)
        ],
    }


def _box_title(node: GraphNode, asks: Context | None) -> str:
    """What a box calls itself on the canvas."""
    if asks is None or not asks.get("label"):
        return node.title
    return f"New {asks['label']}"


def _store_facts(session: Session, node: GraphNode, owner: OwnerId) -> Context:
    """What a Deposit or Withdraw box is about, and how full it is.

    The count is the useful fact on both: on a Deposit it says how much has
    piled up, and on a Withdraw it says how much the next pull would find.
    """
    name = graph_service.store_name(node.repository)
    return {
        "name": name,
        "waiting": sync_service.waiting_in(session, name, owner) if name else 0,
        # Withdraw boxes only. 0 means everything waiting.
        "takes": node.takes or 0,
        "pulls": node.kind == "withdraw",
    }


def _asks_for(node: GraphNode) -> Context | None:
    """What an empty source box is for, and what to type into it.

    None for a tag box and for one that already has its channel: neither is
    asking anything. A box from before sources had kinds has no kind to
    report, and the canvas offers it the one thing that still makes sense —
    something already being watched.
    """
    if node.channel_pk:
        return None
    wanted = (node.source_kind or "").strip()
    if not wanted:
        return {"kind": "", "label": "", "source": "", "example": "", "known": False}
    known = sources.describe(wanted)
    return {
        "kind": wanted,
        "label": known.noun or known.label,
        # The short one, for the word above the title on the box. A filled
        # box reads the same thing off its channel.
        "source": known.label,
        "example": known.example,
        # False when the plugin that offered this kind has been switched off
        # or removed, which is worth saying rather than drawing an empty box
        # that refuses everything typed into it.
        "known": any(one.name == wanted for one in sources.all_kinds()),
    }


def _every_parts(node: GraphNode) -> Context:
    """A pulse's gap as an amount, a unit, and the units it could be said in."""
    amount, unit = graph_service.split_every(
        node.every_minutes or graph_service.DEFAULT_EVERY_MINUTES
    )
    return {
        "amount": amount,
        "unit": unit,
        "units": [
            {"name": name, "label": label} for name, _, label in graph_service.EVERY_UNITS
        ],
    }


def _next_firing(node: GraphNode) -> str | None:
    """When a schedule next comes round, so the box can be checked at a glance.

    A cron expression is easy to get subtly wrong, and the honest way to show
    what one means is to say when it would actually go off.
    """
    if node.trigger_kind != "schedule":
        return None
    try:
        trigger = graph_service.cron_trigger(node.cron or graph_service.DEFAULT_CRON)
    except graph_service.GraphError:
        return None
    when = trigger.get_next_fire_time(None, dt.datetime.now(dt.timezone.utc))
    return when.isoformat() if when is not None else None


def _sort_words(node: GraphNode) -> str:
    """What a sort box does, in the words that belong to what it sorts by."""
    return graph_service.sort_words(
        node.sort_by or graph_service.DEFAULT_SORT_BY,
        (node.sort_dir or "desc") == "desc",
    )


def _is_on(node: GraphNode) -> bool:
    """Whether this box is doing anything.

    A source or feed box answers for the channel or playlist behind it, since
    that is where the rest of the app reads it from. A filter or trigger box
    stands for nothing else, so it answers for itself.
    """
    if node.kind == "source":
        return node.channel.enabled if node.channel is not None else False
    if node.kind == "feed":
        return node.playlist.enabled if node.playlist is not None else False
    return node.enabled


def _feed_facts(node: GraphNode, windows: list[GraphNode]) -> Context | None:
    """How a feed fills: whether it is taking anything, and how much.

    The same two things its own page calls Filling. Read off the box's own
    playlist rather than counted, so there is no query per feed.
    """
    playlist = node.playlist
    if playlist is None:
        return None
    return {
        "enabled": playlist.enabled,
        "max_items": playlist.max_items,
        "max_per_run": playlist.max_per_run,
        "generic": playlist.is_generic,
        # When it may be read. Empty means always, which is what a feed with
        # no pieces slotted under it has always been.
        "windows": _window_words(windows),
        "open": graph_service.is_open(windows, utcnow()),
    }


def _window_words(pieces: list[GraphNode]) -> list[str]:
    """What the pieces under a feed say about when it can be read.

    The Timer is a modifier rather than a line of its own: it says how long a
    Reset's window lasts, so it is read into the Reset's sentence and only
    speaks for itself when there is no Reset to speak for.
    """
    resets = [one for one in pieces if one.kind == "reset"]
    timers = [one for one in pieces if one.kind == "timer"]
    window = (
        max(1, timers[0].duration_minutes or graph_service.DEFAULT_DURATION_MINUTES)
        if timers
        else graph_service.DEFAULT_DURATION_MINUTES
    )
    said = [graph_service.piece_words(one) for one in timers[:1]]
    said += [graph_service.piece_words(one, window) for one in resets]
    # Last, because it is a condition on the rest rather than another way in.
    said += [
        graph_service.piece_words(one)
        for one in pieces
        if one.kind == "alive" and graph_service.piece_words(one) != "any time of day"
    ]
    return said


def _channel_facts(session: Session, owner: OwnerId) -> dict[int, Context]:
    """What each channel does, for the box that stands for it.

    What it takes, when it was last looked at, and how much it has placed.
    Not what it fills: the wires out of the box already say that, and saying
    it twice invites the two to disagree. Counted for every channel at once
    rather than per box, which would be one pair of queries per box.
    """
    def tally(*conditions: ColumnElement[bool]) -> dict[int, int]:
        rows = session.execute(
            owned(select(Video.channel_pk, func.count(Video.id)), Video, owner)
            .where(*conditions)
            .group_by(Video.channel_pk)
        )
        return {channel_pk: held for channel_pk, held in rows if channel_pk is not None}

    placed = tally(Video.status == "added")
    pending = tally(Video.status == "pending")

    channels = session.scalars(owned(select(Channel), Channel, owner))
    return {
        channel.id: {
            # What kind of somewhere it is. The four switches below are
            # YouTube's own distinctions, so a source elsewhere sends them
            # rather than pretending they mean something there.
            "source": sources.describe(channel.source_kind).label,
            "youtube": channel.is_youtube,
            "feed_url": channel.feed_url,
            "mirror": channel.mirror_url,
            # What to paste, for the kinds where somebody is known to publish
            # the same feed. A field you have to go and research is a field
            # nobody fills in.
            "mirror_hint": sources.suggest_mirror(channel.source_kind, channel.channel_id),
            "takes": {
                "videos": not channel.skip_videos,
                "shorts": not channel.skip_shorts,
                "live": not channel.skip_live,
                "posts": not channel.skip_posts,
            },
            # When it is next looked at is the trigger's business, and the
            # channel's own gap only applies while none is wired — so the box
            # says when it last happened and leaves the rest to `polled`.
            "enabled": channel.enabled,
            "checked": _instant(channel.last_checked_at),
            "placed": placed.get(channel.id, 0),
            "pending": pending.get(channel.id, 0),
        }
        for channel in channels
    }


def _instant(when: dt.datetime | None) -> str | None:
    """Naive UTC in the database becomes an instant the browser can read.

    Not the ``stamp`` filter above, which formats for a page; this is for the
    canvas, which does its own formatting on the reader's own clock.
    """
    return None if when is None else when.replace(tzinfo=dt.timezone.utc).isoformat()


def _how_polled(node: GraphNode, plan: dict[int, list[graph_service.When]]) -> str:
    """What decides when this channel is polled, in a sentence.

    Worth spelling out on the box rather than leaving to be inferred from the
    wires: a channel with nothing wired to it and one with a trigger wired
    look much the same on a canvas and are polled on different clocks.
    """
    wired = None if node.channel_pk is None else plan.get(node.channel_pk)
    if not wired:
        return "Nothing polls this. Wire a trigger into it, or it just sits here."
    return "Polled by " + _join_clauses([_when_clause(when) for when in wired]) + "."


def _when_clause(when: graph_service.When) -> str:
    if when.kind == "schedule":
        return f"a schedule on “{when.cron or graph_service.DEFAULT_CRON}”"
    gap = when.every_minutes or graph_service.DEFAULT_EVERY_MINUTES
    return f"a pulse every {graph_service.every_words(gap)}"


def _join_clauses(parts: list[str]) -> str:
    if len(parts) <= 2:
        return " and ".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]





def _plugin_facts(node: GraphNode) -> Context | None:
    """What a plugin box is, and what its fields are set to.

    None when the plugin is switched off or gone: the box stays drawn and
    stops narrowing anything, and the canvas says which plugin it is waiting
    for rather than showing an empty form.
    """
    ref = node.plugin_ref or ""
    box = registry.current().node(ref)
    was = sync_service._plugin_settings(node)
    if box is None:
        plugin_id = ref.split(":", 1)[0] if ":" in ref else ref
        return {"ref": ref, "missing": plugin_id or "a plugin", "fields": [], "blurb": ""}
    return {
        "ref": ref,
        "missing": None,
        "blurb": box.blurb,
        "plugin": box.plugin,
        "fields": [
            {
                "name": one.name,
                "label": one.label,
                "type": one.type,
                "value": was.get(one.name, one.default),
                "placeholder": one.placeholder,
            }
            for one in box.fields
        ],
    }


def _node_note(
    node: GraphNode,
    opening: set[int] | None = None,
    store: Context | None = None,
) -> str:
    """The line under the title: what this box is, in a few words."""
    if node.kind == "group":
        return "drag it to move everything in it"
    if node.kind == "plugin":
        box = registry.current().node(node.plugin_ref or "")
        if box is None:
            return "its plugin is switched off — it narrows nothing"
        return box.blurb or f"from {box.plugin}"
    if node.kind in graph_service.JIGSAW:
        if node.attached_to is None:
            return "drop it on a box to slot it in"
        return graph_service.piece_words(node)
    if node.kind in ("deposit", "withdraw"):
        name = str((store or {}).get("name") or "")
        if not name:
            return "open it and give it a name"
        held = int((store or {}).get("waiting") or 0)
        if node.kind == "deposit":
            return f"{held} waiting in {name}"
        how = "all of it" if not node.takes else f"{node.takes} at a time"
        return f"pulls {how} from {name}"
    if node.kind == "sort":
        return _sort_words(node)
    if node.kind == "trigger":
        # Wired to a feed it opens a window, which is a different sentence
        # from the one about setting a channel off.
        if opening is not None and node.id in opening:
            return graph_service.window_words(node)
        if node.trigger_kind == "schedule":
            return node.cron or graph_service.DEFAULT_CRON
        every = node.every_minutes or graph_service.DEFAULT_EVERY_MINUTES
        return f"every {graph_service.every_words(every)}"
    if node.kind == "source":
        channel = node.channel
        if channel is None:
            return "open it and say where to watch"
        if not channel.is_youtube:
            # Nowhere else splits what it publishes into four kinds, so the
            # line says where it comes from, which is the useful fact instead.
            return f"everything from {sources.describe(channel.source_kind).label}"
        takes = [
            word
            for word, off in (("videos", channel.skip_videos), ("shorts", channel.skip_shorts),
                              ("live", channel.skip_live), ("posts", channel.skip_posts))
            if not off
        ]
        return "takes " + (", ".join(takes) if takes else "nothing")
    if node.kind == "feed":
        playlist = node.playlist
        if playlist is None:
            return "feed is gone"
        return "generic" if playlist.is_generic else "YouTube playlist"
    count = len(node.overrides)
    return f"{count} rule{'s' if count != 1 else ''}" if count else "passes everything"


@app.get("/api/graph")
def graph_state(request: Request) -> JSONResponse:
    owner = owner_of(request)
    with session_scope() as session:
        return JSONResponse(_graph_payload(session, owner))


@app.post("/graph/nodes/{node_pk}/move")
def graph_move(
    request: Request,
    node_pk: int,
    x: int = Form(0),
    y: int = Form(0),
    carries: str = Form(""),
) -> JSONResponse:
    """Where a node was dragged to.

    ``carries`` says this is a group, which moves everything it surrounds by
    the same amount — one call rather than one per node inside it, so a group
    of ten cannot half-move.
    """
    owner = owner_of(request)
    with session_scope() as session:
        if carries == "1":
            try:
                went = graph_service.move_group(session, node_pk, x, y, owner)
            except graph_service.GraphError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)
            return JSONResponse({"moved": True, "carried": len(went)})
        moved = graph_service.move(session, node_pk, x, y, owner)
    return JSONResponse({"moved": moved})


@app.post("/graph/connect")
def graph_connect(
    request: Request, source: int = Form(...), target: int = Form(...)
) -> JSONResponse:
    owner = owner_of(request)
    with session_scope() as session:
        nodes = {node.id: node for node in graph_service.nodes(session, owner)}
        first, second = nodes.get(source), nodes.get(target)
        if first is None or second is None:
            return JSONResponse({"error": "That node is no longer there."}, status_code=404)
        try:
            graph_service.connect(session, first, second, owner)
        except graph_service.GraphError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(_graph_payload(session, owner))


@app.post("/graph/disconnect")
def graph_disconnect(request: Request, wire: str = Form(...)) -> JSONResponse:
    """Take out one wire. There is only one kind of wire now."""
    owner = owner_of(request)
    with session_scope() as session:
        kind, _, rest = wire.partition(":")
        if kind == "edge" and rest.isdigit():
            graph_service.disconnect(session, int(rest), owner)
        return JSONResponse(_graph_payload(session, owner))


@app.post("/graph/nodes")
def graph_add_node(
    request: Request,
    kind: str = Form(...),
    title: str = Form(""),
    plugin_node: str = Form(""),
    source_kind: str = Form(""),
    attach_to: str = Form(""),
    x: int = Form(0),
    y: int = Form(0),
) -> JSONResponse:
    """Put a new box on the canvas wherever it was dropped.

    Every kind comes through here, because every kind is dragged out of the
    same palette. A channel box arrives empty and is told which channel it is
    afterwards; a feed box makes its feed at once, since a name is all one
    needs.
    """
    owner = owner_of(request)
    with session_scope() as session:
        if kind == "source":
            wanted = source_kind.strip()
            if not wanted or wanted not in {known.name for known in sources.all_kinds()}:
                return JSONResponse(
                    {"error": "There is no source of that kind. Its plugin may be off."},
                    status_code=400,
                )
            graph_service.add_source(session, owner, source_kind=wanted, x=x, y=y)
        elif kind == "feed":
            try:
                playlist = playlist_service.create_generic(
                    session, title.strip() or "New feed", owner
                )
            except playlist_service.PlaylistError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)
            graph_service.add_feed(session, playlist, owner, x=x, y=y)
        elif kind == "filter":
            graph_service.add_filter(session, owner, label=title.strip() or "Filter", x=x, y=y)
        elif kind == "sort":
            graph_service.add_sort(session, owner, label=title.strip(), x=x, y=y)
        elif kind == "plugin":
            box = registry.current().node(plugin_node.strip())
            if box is None:
                return JSONResponse(
                    {"error": "That box's plugin is not loaded."}, status_code=400
                )
            graph_service.add_plugin_node(
                session,
                owner,
                ref=box.ref,
                label=title.strip() or box.label,
                settings={f.name: f.default for f in box.fields if f.default},
                x=x,
                y=y,
            )
        elif kind in graph_service.JIGSAW:
            # Slotted under whatever it was dropped on. Without a host it is
            # a piece lying on the canvas, which is a thing you can pick up
            # and put somewhere rather than a thing that was refused.
            host = (
                session.scalar(
                    owned(select(GraphNode), GraphNode, owner).where(
                        GraphNode.id == int(attach_to)
                    )
                )
                if attach_to.strip().isdigit()
                else None
            )
            try:
                graph_service.add_piece(session, owner, kind=kind, host=host, x=x, y=y)
            except graph_service.GraphError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)
        elif kind in ("deposit", "withdraw"):
            graph_service.add_store(
                session, owner, kind=kind, repository=title.strip(), x=x, y=y
            )
        elif kind == "group":
            graph_service.add_group(session, owner, label=title.strip(), x=x, y=y)
        elif kind in graph_service.TRIGGER_KINDS:
            graph_service.add_trigger(
                session, owner, trigger_kind=kind, label=title.strip(), x=x, y=y
            )
        else:
            return JSONResponse({"error": f"There is no {kind} node."}, status_code=400)
        return JSONResponse(_graph_payload(session, owner))


@app.post("/graph/nodes/{node_pk}/attach")
def graph_attach(request: Request, node_pk: int, under: str = Form("")) -> JSONResponse:
    """Slot a piece that is already on the canvas into a box, or take it out.

    The other way a piece gets slotted in. Dragging one out of the palette
    onto a slot is the first; this is for the one already lying there, which
    otherwise could only be deleted and dragged out again.
    """
    owner = owner_of(request)
    with session_scope() as session:
        piece = session.scalar(
            owned(select(GraphNode), GraphNode, owner).where(GraphNode.id == node_pk)
        )
        if piece is None:
            return JSONResponse({"error": "That node is not here."}, status_code=404)

        wanted = under.strip()
        if not wanted:
            graph_service.detach(session, piece)
            return JSONResponse(_graph_payload(session, owner))

        host = session.scalar(
            owned(select(GraphNode), GraphNode, owner).where(GraphNode.id == int(wanted))
            if wanted.isdigit()
            else select(GraphNode).where(GraphNode.id == -1)
        )
        if host is None:
            return JSONResponse({"error": "That box is not here."}, status_code=404)
        try:
            graph_service.attach(session, piece, host, owner)
        except graph_service.GraphError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(_graph_payload(session, owner))


@app.post("/graph/nodes/{node_pk}/resize")
def graph_resize(
    request: Request, node_pk: int, width: int = Form(0), height: int = Form(0)
) -> JSONResponse:
    owner = owner_of(request)
    with session_scope() as session:
        return JSONResponse({"resized": graph_service.resize(session, node_pk, width, height, owner)})


@app.get("/graph/nodes/{node_pk}/export")
def graph_export_group(request: Request, node_pk: int) -> Response:
    """A group as a file to hand somebody else."""
    owner = owner_of(request)
    with session_scope() as session:
        try:
            packed = graph_service.export_group(session, node_pk, owner)
        except graph_service.GraphError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

    name = re.sub(r"[^A-Za-z0-9]+", "-", str(packed["name"])).strip("-").lower() or "group"
    return Response(
        content=json.dumps(packed, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="de-algo-{name}.json"'},
    )


@app.post("/graph/groups")
async def graph_import_group(
    request: Request, file: UploadFile = File(...), x: int = Form(40), y: int = Form(40)
) -> JSONResponse:
    """Load a group somebody else exported. Nothing existing is changed."""
    owner = owner_of(request)
    raw = await file.read()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JSONResponse({"error": "That file is not readable JSON."}, status_code=400)

    with session_scope() as session:
        try:
            graph_service.import_group(session, payload, owner, x=x, y=y)
        except graph_service.GraphError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(_graph_payload(session, owner))


@app.post("/graph/nodes/{node_pk}/fire")
def graph_fire(request: Request, node_pk: int) -> JSONResponse:
    """Press a trigger: poll the channels it is wired to, and only those.

    Forced, because pressing it is the whole schedule — a gap that has not
    elapsed is not a reason to ignore somebody's finger. It runs in a thread
    like every other sync, so the answer comes back before the polling does.
    """
    return _set_off(request, node_pk, reach_back=None)


@app.post("/graph/nodes/{node_pk}/backfill")
def graph_backfill(request: Request, node_pk: int, count: str = Form("")) -> JSONResponse:
    """The same, running through the latest ``count`` posts of each source.

    A poll takes what is new. This takes that many whatever their age, and
    brings back what an earlier run passed over for being older than the
    backfill window allowed — which is what somebody means by "catch me up".

    An unreadable count means as far as the feeds go, which is the most the
    button could ever have done and so cannot surprise anybody.
    """
    wanted = count.strip()
    return _set_off(request, node_pk, reach_back=int(wanted) if wanted.isdigit() else 0)


def _set_off(request: Request, node_pk: int, *, reach_back: int | None) -> JSONResponse:
    """Set a trigger off by hand, polling only what it is wired to."""
    owner = owner_of(request)
    with session_scope() as session:
        try:
            targets = graph_service.pulse_targets(session, node_pk, owner)
        except graph_service.GraphError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        node = session.scalar(
            owned(select(GraphNode), GraphNode, owner).where(GraphNode.id == node_pk)
        )
        # A trigger may be wired to sources, to Withdraw boxes, or to both.
        # Pulling needs no network and no quota, so it happens here rather
        # than in the thread — and a trigger wired only to a Withdraw box has
        # something to do without a sync running at all.
        pulling = (
            graph_service.wired_withdrawals(session, node, owner) if node is not None else []
        )
        if not targets and not pulling:
            return JSONResponse(
                {"error": "Nothing is wired to that trigger yet."}, status_code=400
            )

        if node is not None:
            node.last_fired_at = utcnow()
        session.flush()
        payload = _graph_payload(session, owner)
        pulled = [one.id for one in pulling]

    if sync_service.is_running():
        return JSONResponse({**payload, "said": "A sync is already running."})

    # Claimed here rather than in the thread: the canvas asks where the run
    # has got to as soon as this answers, and a thread takes a moment to get
    # going. Without the claim it would be told about the previous run, which
    # reads as this one having finished instantly.
    trigger = "pulse" if reach_back is None else "backfill"
    if not targets:
        # Nothing to poll, so nothing to run in a thread: pull now and answer
        # with what came out.
        with session_scope() as session:
            said = sync_service.withdraw_now(session, pulled, owner)
            payload = _graph_payload(session, owner)
        return JSONResponse({**payload, "said": said})

    token = sync_service.claim(owner, trigger, node_pk)
    threading.Thread(
        target=sync_service.run_sync,
        args=(trigger,),
        kwargs={
            "force": True,
            "owner": owner,
            "only": frozenset(targets),
            "fired_by": node_pk,
            "reach_back": reach_back,
            "withdrawals": pulled,
            "token": token,
        },
        daemon=True,
    ).start()
    where = f"{len(targets)} channel{'s' if len(targets) != 1 else ''}"
    if reach_back is None:
        said = f"Polling {where}…"
    elif reach_back > 0:
        said = f"Reaching back through the latest {reach_back} of {where}…"
    else:
        said = f"Reaching back as far as {where} still list…"
    return JSONResponse({**payload, "said": said})


@app.get("/api/graph/run")
def graph_run_state(request: Request) -> JSONResponse:
    """Where the run in flight has got to, said in boxes rather than rows.

    The canvas asks for this while something is running, so the drawing can
    show the work moving through it instead of going still for a minute and
    then changing all at once.

    It reports on the boxes that exist rather than drawing any: this is asked
    for once a second, and a GET that writes to the database is a poor thing
    to run on a timer.
    """
    owner = owner_of(request)
    state = sync_service.progress()
    running = sync_service.is_running()
    if state is None or (state.owner != owner and state.owner is not None):
        return JSONResponse({"running": running, "stage": None, "nodes": {}})

    with session_scope() as session:
        marks = _run_marks(session, state, owner)

    return JSONResponse(
        {
            # A claimed run counts as running even before its thread has taken
            # the lock, so the canvas follows it from the first moment rather
            # than deciding on its first look that it was already over. Whose
            # run it is was settled above.
            "running": running or not state.finished,
            "stage": state.stage,
            "trigger": state.trigger,
            "nodes": marks,
        }
    )


@app.get("/graph/nodes/{node_pk}/test")
def graph_try(request: Request, node_pk: int) -> JSONResponse:
    """What this trigger's run would do, without doing it.

    Asked of a trigger because a trigger is what starts a run: it already
    knows which channels it sets off, and those are the ones worth asking
    about. The boxes are marked exactly as a real run marks them, so the
    drawing says the same thing either way — the difference is that nothing
    is written and nothing reaches YouTube.
    """
    owner = owner_of(request)
    with session_scope() as session:
        node = session.scalar(
            owned(select(GraphNode), GraphNode, owner).where(GraphNode.id == node_pk)
        )
        if node is None or node.kind != "trigger":
            return JSONResponse({"error": "That node is not a trigger."}, status_code=400)

        reaches = graph_service.wired_channels(session, node, owner)
        # The other half of what a trigger can set off. A trigger wired only
        # to a Withdraw box has plenty to say about what a run would do, and
        # asking only about channels answered that it had nothing.
        pulls = [one.id for one in graph_service.wired_withdrawals(session, node, owner)]
        if not reaches and not pulls:
            return JSONResponse(
                {"error": "Nothing is wired to that trigger yet."}, status_code=400
            )

        trial = graph_service.try_it(
            session, get_settings(session, owner), owner,
            channels=reaches, pulls=pulls,
        )
        boxes = {entry.id: entry for entry in graph_service.nodes(session, owner)}

        # Every box the trial touched carries its own share of it, so each can
        # answer for itself rather than sending the reader back to the trigger.
        touched = set(trial.through) | set(trial.held)
        marks = {
            str(node_id): _mark(
                len(trial.through.get(node_id, [])), len(trial.held.get(node_id, []))
            )
            for node_id in touched
        }
        items: dict[str, Context] = {
            str(node_id): {
                "through": [_judged(item) for item in trial.through.get(node_id, [])],
                "held": [
                    {**_judged(item), "box": boxes[node_id].title if node_id in boxes else ""}
                    for item in trial.held.get(node_id, [])
                ],
            }
            for node_id in touched
        }

        # The trigger that was asked answers for the whole of it.
        items[str(node.id)] = {
            "through": [
                _judged(item)
                for node_id, landing in trial.through.items()
                if node_id in boxes and boxes[node_id].kind == "feed"
                for item in landing
            ],
            "held": [
                {**_judged(item), "box": boxes[node_id].title if node_id in boxes else ""}
                for node_id, holding in trial.held.items()
                for item in holding
            ],
        }
        # The trigger answers for the whole of it: what arrived at a feed,
        # and what was stopped anywhere along the way. Counting the channels
        # it reaches said nothing at all about a trigger wired to a Withdraw
        # box, which reaches none.
        mine = items[str(node.id)]
        landed, stopped = len(mine["through"]), len(mine["held"])
        marks.setdefault(
            str(node.id), _mark(landed or len(reaches), stopped)
        )

        _log_the_trial(session, node, trial, boxes, owner)

        return JSONResponse({"trigger": node.title, "nodes": marks, "items": items})


def _log_the_trial(
    session: Session,
    node: GraphNode,
    trial: graph_service.Trial,
    boxes: dict[int, GraphNode],
    owner: OwnerId,
) -> None:
    """Write a trial into the log like any other run.

    A trial writes nothing to a feed and sends nothing to YouTube, and that is
    the whole point of it — but "I pressed Test and it said nothing useful" is
    a thing that happens, and it is answered by the same log that answers it
    for a real run. The row says it wrote nothing, so nobody reads it as one.
    """
    run = SyncRun(
        owner_pk=owner,
        trigger="test",
        started_at=utcnow(),
        finished_at=utcnow(),
        forced=False,
        ok=True,
    )
    session.add(run)
    session.flush()

    pen = runlog.Pen(session, run.id, owner)
    pen.at("trial")
    pen.write(f"Test of {node.title} — nothing was written and nothing was sent.")

    landed = held = 0
    for node_id, through in sorted(trial.through.items()):
        box = boxes.get(node_id)
        if box is None or box.kind != "feed":
            continue
        landed += len(through)
        pen.write(f"{len(through)} would land here", about=box.title)
    for node_id, holding in sorted(trial.held.items()):
        box = boxes.get(node_id)
        held += len(holding)
        for item in holding:
            pen.write(
                f"would be held — {item.reason or 'filtered out'}",
                about=f"{box.title if box else '?'} · {item.title}",
                level="warn",
            )

    run.discovered = landed + held
    run.added = landed
    run.skipped = held
    run.message = f"Trial: {landed} would land, {held} would be held back."
    runlog.prune(session, owner)


@app.get("/graph/nodes/{node_pk}/filtered")
def graph_filter_report(request: Request, node_pk: int) -> JSONResponse:
    """What this filter box lets through, and what it holds back."""
    owner = owner_of(request)
    with session_scope() as session:
        try:
            through, held = graph_service.filter_report(
                session, node_pk, get_settings(session, owner), owner
            )
        except graph_service.GraphError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(
            {
                "through": [_judged(item) for item in through],
                "held": [_judged(item) for item in held],
            }
        )


def _run_marks(
    session: Session, state: sync_service.RunProgress, owner: OwnerId
) -> dict[str, Context]:
    """What the run did at each box it actually reached.

    Reached means something arrived, not that a wire leads there. A channel
    that found nothing sends nothing on, so the boxes after it took no part in
    the run and are left unmarked — which is how the drawing says the flow
    stopped at the channel.
    """
    boxes = graph_service.nodes(session, owner)
    set_off = _trigger_targets(session, boxes, owner)
    # Which channels each source node stands for: one for a channel node, and
    # however many carry the tag for a tag node.
    stands_for = {
        node.id: [channel.id for channel in graph_service.channels_of(session, node, owner)]
        for node in boxes
        if node.kind == "source"
    }

    marks: dict[str, Context] = {}
    for node in boxes:
        mark = _mark_for(node, state, set_off.get(node.id, []), stands_for.get(node.id, []))
        if mark is not None:
            marks[str(node.id)] = mark

    # Whatever is happening this second outranks whatever came before it.
    for node_id, channels in stands_for.items():
        if state.channel_pk is not None and state.channel_pk in channels:
            marks[str(node_id)] = _busy()
    if state.fired_by is not None and not state.finished:
        marks[str(state.fired_by)] = _busy()
    return marks


def _trigger_targets(
    session: Session, boxes: list[GraphNode], owner: OwnerId
) -> dict[int, list[int]]:
    """The channels each trigger box is wired to, by trigger node id."""
    by_id = {node.id: node for node in boxes}
    wired: dict[int, list[int]] = {}
    for edge in graph_service.edges(session, owner):
        start, end = by_id.get(edge.source_pk), by_id.get(edge.target_pk)
        if start is None or end is None or start.kind != "trigger":
            continue
        if end.kind == "source":
            # A tag node is several channels, and a trigger on it sets off all
            # of them.
            for channel in graph_service.channels_of(session, end, owner):
                wired.setdefault(start.id, []).append(channel.id)
    return wired


def _busy() -> Context:
    # The same shape as a finished mark, so the canvas reads one kind of thing.
    return {"state": "busy", "count": 0, "stopped": 0, "ends": False, "trouble": None}


def _mark_for(
    node: GraphNode,
    state: sync_service.RunProgress,
    targets: list[int],
    stands_for: list[int],
) -> Context | None:
    """One box's share of the run, or None if nothing of the run got to it.

    ``count`` is what left the box and ``stopped`` is what it held. A box that
    held things and passed none on is where the flow ended, and says so.
    """
    if node.kind == "trigger":
        if node.id != state.fired_by:
            return None
        # Its own channels, not the run's: a trigger wired to a channel that
        # is switched off set nothing off, however busy the rest of the run
        # was, and saying "nothing new" would credit it with a look it never
        # took.
        reached = [channel_pk for channel_pk in targets if channel_pk in state.polled]
        if reached:
            return _mark(len(reached), 0)
        # It went, and could not get in. That is a different thing from a
        # trigger that never set off, and the two used to read the same.
        failed = [why for pk, why in state.unreachable.items() if pk in targets]
        if failed:
            return _mark(0, 0, ends=True, trouble=_one_voice(failed))
        return _mark(0, 0, ends=True)

    if node.kind == "source":
        # Every channel it stands for, added up: a tag node is one box over
        # several channels, and reports what all of them did.
        polled = [channel_pk for channel_pk in stands_for if channel_pk in state.polled]
        if not polled:
            failed = [why for pk, why in state.unreachable.items() if pk in stands_for]
            if failed:
                return _mark(0, 0, ends=True, trouble=_one_voice(failed))
            return None
        found = sum(state.polled.get(channel_pk, 0) for channel_pk in polled)
        left = sum(state.left.get(channel_pk, 0) for channel_pk in polled)
        return _mark(left, max(0, found - left))

    if node.kind == "filter":
        passed = state.through.get(node.id, 0)
        held = state.stopped.get(node.id, 0)
        # Nothing came either way: the flow never got this far.
        return _mark(passed, held) if passed or held else None

    taken = state.placed.get(node.playlist_pk or 0, 0)
    return _mark(taken, 0) if taken else None


def _one_voice(reasons: list[str]) -> str:
    """One line for however many channels failed the same way."""
    first = reasons[0]
    rest = len(reasons) - 1
    return first if rest == 0 else f"{first} (and {rest} more like it)"


def _mark(
    count: int, stopped: int, *, ends: bool | None = None, trouble: str | None = None
) -> Context:
    """One box's answer. ``ends`` is worked out unless a box knows better.

    A filter knows it ended the flow because it held things back. A trigger
    knows because nothing it is wired to was polled, and it has nothing to
    hold — so it says so rather than being read as having found nothing.

    ``trouble`` is why it could not look at all, which is a third thing again:
    not "nothing was there" and not "this is where it stopped", but "it went
    and could not get in".
    """
    stopping = (count == 0 and stopped > 0) if ends is None else ends
    return {
        "state": "done",
        "count": count,
        "stopped": stopped,
        "ends": stopping,
        "trouble": trouble,
    }


def _judged(item: graph_service.Judged) -> Context:
    return {
        "id": item.video_pk,
        "title": item.title,
        "kind": item.kind,
        "reason": item.reason,
    }


@app.post("/graph/nodes/{node_pk}/delete")
def graph_remove(request: Request, node_pk: int) -> JSONResponse:
    owner = owner_of(request)
    with session_scope() as session:
        try:
            gone = graph_service.remove(session, node_pk, owner)
        except graph_service.GraphError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        if not gone:
            return JSONResponse({"error": "That node is not here."}, status_code=404)
        return JSONResponse(_graph_payload(session, owner))


@app.post("/graph/nodes/{node_pk}")
async def graph_save_node(
    request: Request,
    node_pk: int,
    label: str = Form(""),
    handle: str = Form(""),
    source_pk: str = Form(""),
    backfill: str = Form(""),
    # An unticked checkbox is not submitted at all, so "off" and "this form
    # never showed the switch" arrive looking identical. This marker is what
    # tells them apart: only a form that says it carried the switches may
    # turn any of them off. One marker for every kind of box, because every
    # kind of box has the same switch on it.
    box_form: str = Form(""),
    active: str = Form(""),
    max_items: str = Form(""),
    feed_max_per_run: str = Form(""),
    takes_videos: str = Form(""),
    takes_shorts: str = Form(""),
    takes_live: str = Form(""),
    takes_posts: str = Form(""),
    mirror_url: str = Form(""),
    every_minutes: str = Form(""),
    cron: str = Form(""),
    every_unit: str = Form(""),
    duration_minutes: str = Form(""),
    sort_by: str = Form(""),
    sort_dir: str = Form(""),
    skip_videos: str = Form(""),
    skip_shorts: str = Form(""),
    skip_live: str = Form(""),
    skip_posts: str = Form(""),
    title_include: str = Form(""),
    title_exclude: str = Form(""),
    min_duration_sec: str = Form(""),
    max_duration_sec: str = Form(""),
    max_per_run: str = Form(""),
    repository: str = Form(""),
    takes_how_many: str = Form(""),
    alive_from: str = Form(""),
    alive_to: str = Form(""),
) -> JSONResponse:
    """Save what a box says about itself.

    One route for every kind, because the canvas has one way to open a box and
    one Save in it. What each kind carries differs; what they share is a name.
    """
    owner = owner_of(request)
    with session_scope() as session:
        node = session.scalar(
            owned(select(GraphNode), GraphNode, owner).where(GraphNode.id == node_pk)
        )
        if node is None:
            return JSONResponse({"error": "That node is not here."}, status_code=404)

        if node.kind == "source" and source_pk.strip().isdigit():
            # Pointed at something already watched, rather than told again.
            answer = _attach_watched(session, node, int(source_pk), owner)
            if answer is not None:
                return answer
        elif node.kind == "source" and handle.strip():
            answer = _attach_channel(session, node, handle.strip(), backfill, owner)
            if answer is not None:
                return answer

        graph_service.rename(session, node.id, label, owner)

        if box_form == "1":
            _switch(node, on=active == "1")

        if node.kind == "feed" and node.playlist is not None and box_form == "1":
            _save_feed(node.playlist, max_items=max_items, max_per_run=feed_max_per_run)
        elif node.kind == "source" and node.channel is not None and box_form == "1":
            answer = _save_channel(
                session,
                node.channel,
                takes={
                    "videos": takes_videos, "shorts": takes_shorts,
                    "live": takes_live, "posts": takes_posts,
                },
                mirror_url=mirror_url,
            )
            if answer is not None:
                return answer
        elif node.kind == "sort":
            try:
                node.sort_by = graph_service.check_sort_key(sort_by or graph_service.DEFAULT_SORT_BY)
            except graph_service.GraphError as exc:
                return JSONResponse({"error": str(exc)}, status_code=400)
            node.sort_dir = "asc" if sort_dir == "asc" else "desc"
        elif node.kind in graph_service.JIGSAW:
            if node.kind == "alive":
                begins = graph_service.clock_time(alive_from)
                ends = graph_service.clock_time(alive_to)
                if (alive_from.strip() and not begins) or (alive_to.strip() and not ends):
                    return JSONResponse(
                        {"error": "Write the times as HH:MM, on a 24-hour clock."},
                        status_code=400,
                    )
                node.alive_from, node.alive_to = begins or None, ends or None
            elif node.kind == "timer":
                wanted = duration_minutes.strip()
                node.duration_minutes = (
                    int(wanted) if wanted.isdigit() and int(wanted) > 0 else None
                )
            else:
                try:
                    graph_service.cron_trigger(cron.strip() or graph_service.DEFAULT_CRON)
                except graph_service.GraphError as exc:
                    return JSONResponse({"error": str(exc)}, status_code=400)
                node.cron = cron.strip() or graph_service.DEFAULT_CRON
        elif node.kind in ("deposit", "withdraw"):
            # The name is what joins the two ends. Filed the way the walk
            # files it, so a name typed two ways is still one repository.
            node.repository = graph_service.store_name(repository) or None
            if node.kind == "withdraw":
                wanted = takes_how_many.strip()
                # Empty, or nothing that reads as a number, means everything
                # waiting — which is what the field says it means and the
                # least surprising answer to an unreadable one.
                node.takes = int(wanted) if wanted.isdigit() and int(wanted) > 0 else None
        elif node.kind == "plugin":
            await _save_plugin_box(request, node)
        elif node.kind == "trigger":
            answer = _save_trigger(node, every_minutes, every_unit, cron, duration_minutes)
            if answer is not None:
                return answer
        elif node.kind == "filter":
            _save_filter_rules(
                node,
                switches={
                    "skip_videos": skip_videos, "skip_shorts": skip_shorts,
                    "skip_live": skip_live, "skip_posts": skip_posts,
                },
                text={"title_include": title_include, "title_exclude": title_exclude},
                numbers={
                    "min_duration_sec": min_duration_sec, "max_duration_sec": max_duration_sec,
                    "max_per_run": max_per_run,
                },
            )

        session.flush()
        return JSONResponse(_graph_payload(session, owner))


def _attach_channel(
    session: Session, node: GraphNode, wanted: str, backfill: str, owner: OwnerId
) -> JSONResponse | None:
    """Tell an empty channel box which channel it is. None means it worked."""
    if node.channel is not None:
        return None  # already named; the rename below is all that was meant

    # A channel already being watched is attached rather than refused: two
    # nodes for one channel is a way of wiring it down two paths that filter
    # differently, and is worth being able to draw.
    already = _channel_already_here(session, wanted, owner)
    if already is not None:
        graph_service.attach_channel(session, node, already, owner)
        return None

    with sync_service.http_client() as http:
        try:
            # Within the kind this box was dragged out as, so what is typed
            # is read the way somebody typing into that box meant it: "python"
            # in a Subreddit box is r/python and nothing else.
            channel = channel_service.add_source(
                session,
                wanted,
                http,
                backfill_days=channel_service.parse_backfill(backfill),
                within=node.source_kind or "",
                owner=owner,
            )
        except channel_service.ChannelError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
    graph_service.attach_channel(session, node, channel, owner)
    return None


def _switch(node: GraphNode, *, on: bool) -> None:
    """Turn a box on or off, wherever that box keeps the answer."""
    if node.kind == "source" and node.channel is not None:
        node.channel.enabled = on
    elif node.kind == "feed" and node.playlist is not None:
        node.playlist.enabled = on
    else:
        node.enabled = on


def _save_feed(playlist: Playlist, *, max_items: str, max_per_run: str) -> None:
    """How much this feed takes.

    Both limits count from zero meaning no limit, so an unreadable answer
    becomes no limit rather than a limit of nothing — which would quietly stop
    the feed filling at all.
    """
    for name, raw in (("max_items", max_items), ("max_per_run", max_per_run)):
        wanted = raw.strip()
        setattr(playlist, name, int(wanted) if wanted.isdigit() else 0)


def _save_channel(
    session: Session,
    channel: Channel,
    *,
    takes: dict[str, str],
    mirror_url: str = "",
) -> JSONResponse | None:
    """What kinds the channel takes.

    Not what it filters: narrowing by title or length is a filter box's job,
    and offering it here as well would be two places to look for one answer.

    Through the same services the channel's own page uses, not by setting the
    columns: turning something back on brings back what was skipped for that
    reason, and writing ``skip_shorts = False`` here would quietly lose that.
    Each is only called when the answer actually changed, so saving the box
    without touching a switch requeues nothing.

    Only reached for a form that said it carried these fields, so an unticked
    box here really does mean off.
    """
    switches = (
        ("videos", channel.skip_videos, channel_service.set_videos),
        ("shorts", channel.skip_shorts, channel_service.set_shorts),
        ("live", channel.skip_live, channel_service.set_live),
        ("posts", channel.skip_posts, channel_service.set_posts),
    )
    for name, skipping, apply in switches:
        wanted = takes[name] == "1"
        if wanted is skipping:  # it was off and is wanted on, or the reverse
            apply(session, channel, include=wanted)

    wanted_mirror = mirror_url.strip()
    if wanted_mirror and not wanted_mirror.lower().startswith(("http://", "https://")):
        return JSONResponse(
            {"error": "A mirror is a web address — it should start with https://."},
            status_code=400,
        )
    channel.mirror_url = wanted_mirror or None

    session.flush()
    return None


def _attach_watched(
    session: Session, node: GraphNode, channel_pk: int, owner: OwnerId
) -> JSONResponse | None:
    """Point an empty channel node at a source already being watched."""
    if node.channel is not None:
        return None
    channel = session.scalar(
        owned(select(Channel), Channel, owner).where(Channel.id == channel_pk)
    )
    if channel is None:
        return JSONResponse({"error": "That source is not here."}, status_code=400)
    graph_service.attach_channel(session, node, channel, owner)
    return None


def _channel_already_here(session: Session, wanted: str, owner: OwnerId) -> Channel | None:
    """A channel this account already watches, by whatever was typed.

    Matched without asking YouTube: an id or a handle already on record is
    enough, and a lookup would cost a request to tell us what we know.
    """
    typed = wanted.strip()
    found = session.scalar(
        owned(select(Channel), Channel, owner).where(
            or_(
                Channel.channel_id == typed,
                func.lower(Channel.handle) == typed.lower(),
                func.lower(Channel.title) == typed.lower(),
            )
        )
    )
    if found is not None:
        return found

    # A source elsewhere is filed under the short name its kind reduces to, so
    # a pasted URL and the r/ name that means the same thing find one row. A
    # YouTube handle is the exception: nothing here can turn one into a
    # channel id, so there is no key to look up and the caller resolves it.
    try:
        said = sources.resolve(typed)
    except sources.UnknownSource:
        return None
    if said.needs_host:
        return None
    key = said.key
    return session.scalar(
        owned(select(Channel), Channel, owner).where(Channel.channel_id == key)
    )


async def _save_plugin_box(request: Request, node: GraphNode) -> None:
    """Keep whatever a plugin box's own fields were set to.

    Read straight off the form rather than through named parameters, because
    the host does not know the names: they are the plugin's to declare, and a
    parameter per field is not something a plugin can ask for.

    Only fields the plugin still declares are kept. A box whose plugin has
    dropped a field should not carry it for ever in a column nobody reads.
    """
    box = registry.current().node(node.plugin_ref or "")
    if box is None:
        return  # its plugin is off; there is nothing to save it against

    sent = await request.form()
    kept: dict[str, str] = {}
    for one in box.fields:
        value = sent.get(f"plugin_{one.name}")
        kept[one.name] = str(value).strip() if isinstance(value, str) else one.default
    node.plugin_settings = json.dumps(kept) if kept else None


def _save_trigger(
    node: GraphNode, every_minutes: str, every_unit: str, cron: str, duration: str
) -> JSONResponse | None:
    wanted_window = duration.strip()
    if wanted_window.isdigit() and int(wanted_window) > 0:
        node.duration_minutes = int(wanted_window)
    elif wanted_window != "":
        node.duration_minutes = graph_service.DEFAULT_DURATION_MINUTES

    if node.trigger_kind == "schedule":
        try:
            node.cron = graph_service.check_cron(cron)
        except graph_service.GraphError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return None
    wanted = every_minutes.strip()
    # The number is in whatever unit was chosen beside it; minutes is what is
    # stored, and what an older form with no unit at all meant. Zero is a real
    # answer — "every run there is" — rather than a missing one, so it is kept
    # instead of being replaced by the default.
    if wanted.isdigit():
        node.every_minutes = graph_service.every_minutes_from(
            int(wanted), every_unit or "minutes"
        )
    else:
        node.every_minutes = graph_service.DEFAULT_EVERY_MINUTES
    return None


def _save_filter_rules(
    node: GraphNode,
    *,
    switches: dict[str, str],
    text: dict[str, str],
    numbers: dict[str, str],
) -> None:
    """A filter's every field is three-valued: "" means leave it to the channel.

    Which is why blanks are stored as NULL rather than as zero or false — that
    is the whole difference between a filter box and a second copy of the
    channel's settings.
    """
    for name, raw in switches.items():
        setattr(node, name, None if raw.strip() == "" else raw.strip() == "1")
    for name, raw in text.items():
        setattr(node, name, raw.strip() or None)
    for name, raw in numbers.items():
        value = raw.strip()
        setattr(node, name, int(value) if value.isdigit() else None)


# -- the admin's tab ------------------------------------------------------


def _admin_context(session: Session) -> Context:
    return {
        "users": accounts.list_users(session),
        "admin_user": CONFIG.admin_user,
        "session_days": CONFIG.session_days,
        "min_password": accounts.MIN_PASSWORD_LENGTH,
        "min_passphrase": migration.MIN_PASSPHRASE,
        **_plugin_tally(),
    }


def _plugin_tally() -> Context:
    """Enough about the plugins for the Admin page to point at them, and to
    say when one is not loading rather than leaving it to be noticed."""
    found = registry.current()
    return {"plugin_count": len(found.working), "plugin_trouble": len(found.broken)}


@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request) -> HTMLResponse:
    # Reachable by address even with accounts switched off, where an empty
    # list of them would explain nothing. Say what would turn it on instead.
    if not CONFIG.auth_enabled:
        return render(
            request,
            "admin.html",
            {
                "users": [],
                "admin_user": "",
                "session_days": CONFIG.session_days,
                "min_password": accounts.MIN_PASSWORD_LENGTH,
                "min_passphrase": migration.MIN_PASSPHRASE,
                **_plugin_tally(),
            },
        )
    with session_scope() as session:
        context = _admin_context(session)
    return render(request, "admin.html", context)


@app.post("/admin/accounts")
def add_account(
    request: Request, username: str = Form(""), password: str = Form("")
) -> Response:
    with session_scope() as session:
        try:
            accounts.create_user(session, username, password)
        except accounts.AccountError as exc:
            return redirect("/admin", err=str(exc))
    return redirect("/admin", ok=f"Account {username.strip().lower()} created.")


# -- plugins ---------------------------------------------------------------
#
# Under Admin because adding one is adding code to this install, which is not
# a per-account thing however many accounts there are.

#: What a plugin file may weigh. A source plugin is a page or two of Lua; a
#: megabyte of it is somebody uploading the wrong thing.
MOST_PLUGIN_BYTES = 256 * 1024

#: Shown on the page, so the shape is learnable without leaving it.
PLUGIN_EXAMPLE = """-- What you return is configuration. It says what this plugin is and what
-- it offers; nothing in it does anything by itself.
--
-- Anything it *does* to the site goes through `dealgo`, which it is handed
-- rather than importing — and which answers nothing it was not granted.

return {
  id = "example",  name = "Example",  version = "1.0.0",  api = 1,

  -- Asked for by name, with a reason somebody can weigh. Untick any of them
  -- and this still loads; it just finds that capability missing.
  permissions = {
    { name = "read", why = "To suggest a tag based on what you already watch." },
  },

  sources = {
    {
      kind = "example",
      label = "Example",
      example = "what somebody would type",
      playlistable = false,

      recognise = function(reference)
        local name = string.match(reference, "^example/(%w+)$")
        if not name then return nil end
        return {
          key   = "example/" .. name,
          feed  = "https://example.com/" .. name .. "/feed",
          title = name,
        }
      end,
    },
  },

  nodes = {
    {
      kind = "already-watched",
      label = "Not already watched",
      blurb = "Holds anything from a source you are watching twice.",
      keep = function(item)
        -- `dealgo` is always there. Without the read permission it simply
        -- answers with nothing, so this does no harm either way — and
        -- `dealgo.permissions()` is how a plugin finds out which it is.
        for _, source in ipairs(dealgo.sources()) do
          if source.title == item.title then return false end
        end
        return true
      end,
    },
  },
}"""


@app.get("/admin/plugins", response_class=HTMLResponse)
def plugins_page(request: Request) -> HTMLResponse:
    return _plugins_view(request)


def _plugins_view(request: Request, pending: Context | None = None) -> HTMLResponse:
    """The page, optionally with a plugin waiting to be agreed to."""
    found = registry.current()
    mine = registry.folder()
    leaning = _sources_per_kind()
    return render(
        request,
        "plugins.html",
        {
            "plugins": [
                {
                    "id": plugin.id,
                    "title": plugin.title,
                    "version": plugin.version,
                    "ok": plugin.ok,
                    "loaded": plugin.loaded,
                    "paused": plugin.paused,
                    "trouble": plugin.trouble,
                    "sources": plugin.sources,
                    "wants": plugin.wants,
                    "granted": plugin.granted,
                    "wanting": plugin.wanting,
                    "path": plugin.path,
                    "replaces": plugin.replaces,
                    # Only a plugin of one's own can be removed from here.
                    # A shipped one comes back with the next start anyway,
                    # so a Remove button on it would be a lie — pausing is
                    # how you turn one of those off.
                    "mine": plugin.path.parent == mine,
                    # How much is leaning on it, so switching one off is a
                    # decision rather than a discovery.
                    "leaning": sum(leaning.get(k.kind, 0) for k in plugin.sources),
                }
                for plugin in found.plugins
            ],
            "folder": mine,
            "example": PLUGIN_EXAMPLE,
            "pending": pending,
            "known_permissions": permissions.KNOWN,
        },
    )


def _sources_per_kind() -> dict[str, int]:
    """How many watched sources each kind accounts for, across every account.

    Install-wide, because a plugin is: switching one off reaches everybody,
    and the admin deciding that should be able to see the whole cost.
    """
    with session_scope() as session:
        rows = session.execute(
            select(Channel.source_kind, func.count(Channel.id)).group_by(Channel.source_kind)
        )
        return {kind: count for kind, count in rows}


@app.post("/admin/plugins/{plugin_id}/pause")
def pause_plugin(request: Request, plugin_id: str, on: str = Form("")) -> Response:
    """Switch a plugin off, or back on.

    The only way to turn off one that ships in the image, and gentler than
    removing one of your own: nothing is deleted, and what it offered comes
    back the moment it is switched on again.
    """
    if not set(plugin_id) <= registry.PLAIN:
        return redirect("/admin/plugins", err="That is not a plugin here.")
    found = next((p for p in registry.current().plugins if p.id == plugin_id), None)
    if found is None:
        return redirect("/admin/plugins", err="That is not a plugin here.")

    wanted = on == "1"
    registry.set_paused(plugin_id, paused=not wanted)
    if wanted:
        return redirect("/admin/plugins", ok=f"{found.title} switched on.")
    return redirect(
        "/admin/plugins",
        ok=f"{found.title} switched off. What it recognised is no longer recognised; "
        "sources already being watched keep their own feed address and carry on.",
    )


@app.get("/admin/plugins/{plugin_id}/source", response_class=HTMLResponse)
def plugin_source(request: Request, plugin_id: str) -> Response:
    """Read a plugin's Lua.

    A plugin is code that runs here, so being able to read it without leaving
    the page is the least this owes anybody.
    """
    if not set(plugin_id) <= registry.PLAIN:
        return redirect("/admin/plugins", err="That is not a plugin here.")
    found = next((p for p in registry.current().plugins if p.id == plugin_id), None)
    if found is None:
        return redirect("/admin/plugins", err="That is not a plugin here.")
    try:
        text = found.path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return redirect("/admin/plugins", err=f"Could not be read: {exc}")
    return render(
        request,
        "plugin_source.html",
        {"plugin": found, "source": text},
    )


@app.post("/admin/plugins")
async def add_plugin(request: Request, file: UploadFile = File(...)) -> Response:
    """Take a .lua file into the plugins folder.

    Adding a plugin is adding code that runs in this process. It is walled
    off — no files, no network, no credentials — but it reads every reference
    anybody adds, so this is deliberately an admin-only door and says so on
    the page rather than pretending it is an ordinary upload.
    """
    given = (file.filename or "").strip()
    # Refused rather than quietly reduced to its last part. Stripping a
    # "../" would be safe and would also mean somebody's file landing under a
    # name they did not choose, which is a worse thing to be surprised by
    # than an error.
    if not given or given != Path(given).name:
        return redirect("/admin/plugins", err="Give it a plain filename, with no path in it.")
    name = given
    if not name.endswith(".lua"):
        return redirect("/admin/plugins", err="A plugin is a .lua file.")
    stem = name[: -len(".lua")]
    if not stem or not set(stem) <= registry.PLAIN:
        return redirect(
            "/admin/plugins",
            err="Name it with letters, numbers, dashes or underscores — it becomes its id.",
        )

    body = await file.read(MOST_PLUGIN_BYTES + 1)
    if len(body) > MOST_PLUGIN_BYTES:
        return redirect("/admin/plugins", err="That file is far too big to be a plugin.")
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return redirect("/admin/plugins", err="That file is not text.")

    # Read it before keeping it, with nothing granted. A plugin that will not
    # load is a plugin nobody wants in the folder, and saying so now beats a
    # broken row later.
    checked = registry.judge(stem, text)
    if checked.trouble:
        return redirect("/admin/plugins", err=f"{name}: {checked.trouble}")

    # Nothing is written yet. What it asks for is put to somebody first, and
    # the file lands only once they have said yes — so a plugin nobody agreed
    # to is never on disk at all.
    return _plugins_view(request, pending={"name": name, "source": text, "plugin": checked})


@app.post("/admin/plugins/confirm")
async def confirm_plugin(
    request: Request, name: str = Form(""), source: str = Form("")
) -> Response:
    """Keep a plugin, with exactly the permissions that were ticked.

    Read again rather than trusted from the form: what is judged has to be
    what lands, and the only thing carried across is the file itself.
    """
    stem = name[: -len(".lua")] if name.endswith(".lua") else ""
    if not stem or not set(stem) <= registry.PLAIN or len(source) > MOST_PLUGIN_BYTES:
        return redirect("/admin/plugins", err="That was not a plugin this page offered.")

    checked = registry.judge(stem, source)
    if checked.trouble:
        return redirect("/admin/plugins", err=f"{name}: {checked.trouble}")

    sent = await request.form()
    # Only what it asked for: a tick for something it never wanted cannot
    # grant it, whatever the form says.
    wanted = {want.name for want in checked.wants if want.known}
    granting = frozenset(name for name in wanted if sent.get(f"grant_{name}") == "1")

    folder = registry.folder()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{stem}.lua").write_text(source, encoding="utf-8")
    except OSError as exc:  # pragma: no cover - a full or unwritable volume
        return redirect("/admin/plugins", err=f"Could not be saved: {exc}")

    registry.set_granted(stem, granting)
    said = f"{checked.title} added"
    if granting:
        labels = ", ".join(sorted(permissions.describe(n).label.lower() for n in granting))
        said += f", allowed to {labels}"
    elif checked.wants:
        said += ", with none of what it asked for"
    return redirect("/admin/plugins", ok=said + ".")


@app.post("/admin/plugins/{plugin_id}/permissions")
async def set_plugin_permissions(request: Request, plugin_id: str) -> Response:
    """Change what a plugin already here is allowed to do."""
    if not set(plugin_id) <= registry.PLAIN:
        return redirect("/admin/plugins", err="That is not a plugin here.")
    found = next((p for p in registry.current().plugins if p.id == plugin_id), None)
    if found is None:
        return redirect("/admin/plugins", err="That is not a plugin here.")

    sent = await request.form()
    wanted = {want.name for want in found.wants if want.known}
    granting = frozenset(name for name in wanted if sent.get(f"grant_{name}") == "1")
    registry.set_granted(plugin_id, granting)

    gained = granting - found.granted
    lost = found.granted - granting
    if not gained and not lost:
        return redirect("/admin/plugins", ok=f"{found.title} is unchanged.")
    return redirect(
        "/admin/plugins",
        ok=f"{found.title} now has {len(granting)} of the "
        f"{len(wanted)} thing{'s' if len(wanted) != 1 else ''} it asked for.",
    )


@app.post("/admin/plugins/reload")
def reload_plugins(request: Request) -> Response:
    """Read the folder again, for a file put there by hand."""
    found = registry.reload()
    broken = len(found.broken)
    said = f"{len(found.working)} plugin{'s' if len(found.working) != 1 else ''} loaded"
    if broken:
        said += f", {broken} not"
    return redirect("/admin/plugins", ok=said + ".")


@app.post("/admin/plugins/{plugin_id}/remove")
def remove_plugin(request: Request, plugin_id: str) -> Response:
    """Take one of your own out of the folder.

    Only your own: a shipped plugin lives in the image and would come back on
    the next start, so a button offering to remove one would be a lie.
    """
    if not set(plugin_id) <= registry.PLAIN:
        return redirect("/admin/plugins", err="That is not a plugin here.")
    path = registry.folder() / f"{plugin_id}.lua"
    if not path.is_file():
        return redirect("/admin/plugins", err="That is not a plugin you added.")
    path.unlink()
    registry.reload()
    return redirect("/admin/plugins", ok=f"{plugin_id} removed.")


@app.post("/admin/accounts/{user_pk}/password")
def reset_account_password(request: Request, user_pk: int, password: str = Form("")) -> Response:
    with session_scope() as session:
        user = session.get(User, user_pk)
        if user is None:
            return redirect("/admin", err="That account no longer exists.")
        if user.is_admin:
            return redirect(
                "/admin",
                err="The admin password comes from DEALGO_ADMIN_PASSWORD; change it there.",
            )
        try:
            accounts.set_password(session, user, password)
        except accounts.AccountError as exc:
            return redirect("/admin", err=str(exc))
        name = user.username
    return redirect("/admin", ok=f"New password set for {name}. Their other sessions ended.")


@app.post("/admin/accounts/{user_pk}/enabled")
def set_account_enabled(request: Request, user_pk: int) -> Response:
    with session_scope() as session:
        user = session.get(User, user_pk)
        if user is None:
            return redirect("/admin", err="That account no longer exists.")
        if user.is_admin:
            return redirect("/admin", err="The admin account cannot switch itself off.")
        accounts.set_enabled(session, user, enabled=not user.enabled)
        name, now_on = user.username, user.enabled
    word = "can sign in again" if now_on else "is switched off, and signed out everywhere"
    return redirect("/admin", ok=f"{name} {word}.")


@app.post("/admin/accounts/{user_pk}/delete")
def remove_account(request: Request, user_pk: int) -> Response:
    with session_scope() as session:
        user = session.get(User, user_pk)
        if user is None:
            return redirect("/admin", err="That account no longer exists.")
        name = user.username
        try:
            accounts.delete_user(session, user)
        except accounts.AccountError as exc:
            return redirect("/admin", err=str(exc))
    return redirect("/admin", ok=f"Account {name} deleted.")


@app.post("/admin/accounts/{user_pk}/sessions")
def end_account_sessions(request: Request, user_pk: int) -> Response:
    with session_scope() as session:
        user = session.get(User, user_pk)
        if user is None:
            return redirect("/admin", err="That account no longer exists.")
        accounts.revoke_all(session, user)
        name = user.username
    return redirect("/admin", ok=f"{name} has been signed out everywhere.")


@app.post("/admin/backup")
def download_site_backup(request: Request, passphrase: str = Form("")) -> Response:
    """The whole instance, encrypted, for standing it up somewhere else.

    A POST rather than a link, because it needs the passphrase — and because a
    file holding every account's credentials should not be one click from a
    bookmark.
    """
    owner = owner_of(request)
    try:
        migration.check_passphrase(passphrase)
        with session_scope() as session:
            blob = migration.build_site_export(session, passphrase)
    except migration.MigrationError as exc:
        return redirect("/admin", err=str(exc))

    return Response(
        blob,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{migration.filename()}"'},
    )


@app.post("/admin/restore")
def restore_site_backup(
    request: Request, passphrase: str = Form(""), backup_file: UploadFile = File(...)
) -> Response:
    owner = owner_of(request)
    blob = backup_file.file.read()
    if not blob:
        return redirect("/admin", err="Choose a site backup to load.")
    try:
        with session_scope() as session:
            summary = migration.restore_site(session, blob, passphrase)
    except migration.MigrationError as exc:
        return redirect("/admin", err=str(exc))
    except Exception as exc:  # a file that opened but did not make sense
        log.exception("site restore failed")
        return redirect("/admin", err=f"That backup opened but could not be applied: {exc}")

    message = (
        f"Restored {summary.accounts} new account(s), {summary.feeds} feed(s) and "
        f"{summary.channels} channel(s)."
    )
    if summary.notes:
        message += " " + " ".join(summary.notes)
    return redirect("/admin", ok=message)


@app.post("/admin/sessions/prune")
def prune_sessions(request: Request) -> Response:
    with session_scope() as session:
        cleared = accounts.clear_expired(session)
    return redirect("/admin", ok=f"Cleared {cleared} expired session(s).")


# -- installing as an app -------------------------------------------------


@app.get("/sw.js")
def service_worker() -> Response:
    """The service worker, served from the root.

    Scope is decided by where a worker is served from, so this cannot live
    under /static: a worker fetched from /static/sw.js could only control
    /static. Never cached by the browser, or a new one could not replace it.
    """
    worker = BASE_DIR / "static" / "sw.js"
    if not worker.exists():  # pragma: no cover - only if the build was skipped
        return Response("", status_code=404)
    return Response(
        worker.read_text(),
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"},
    )


@app.get("/manifest.webmanifest")
def web_manifest() -> Response:
    """Served from the root so its scope covers the whole site."""
    manifest = BASE_DIR / "static" / "manifest.webmanifest"
    return Response(
        manifest.read_text(),
        media_type="application/manifest+json",
        headers={"Cache-Control": "max-age=3600"},
    )


@app.get("/offline", response_class=HTMLResponse)
def offline(request: Request) -> HTMLResponse:
    """What the worker shows for a page that has never been loaded.

    Precached on install, so it is there exactly when nothing else is.
    """
    return render(request, "offline.html", {})


@app.get("/healthz")
def healthz() -> dict[str, object]:
    return {"status": "ok", "version": __version__, "syncing": sync_service.is_running()}
