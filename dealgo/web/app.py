"""FastAPI application: the De-Algo GUI.

Server-rendered HTML so the container ships with no build step and the UI works
in any browser, which is the only GUI that makes sense inside Docker.
"""

from __future__ import annotations

import datetime as dt
import logging
import json
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
from sqlalchemy import func, select
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
    User,
    Channel,
    Placement,
    Playlist,
    SyncRun,
    Video,
    channel_playlist,
)
from ..services import accounts
from ..services.scope import OwnerId, belongs_to, owned
from ..services import backup as backup_service
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
from ..youtube import oauth
from . import guard
from ..youtube.api import PlaylistInfo, YouTubeAPIError

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


TEMPLATES.env.filters["ago"] = _ago
TEMPLATES.env.filters["stamp"] = _stamp
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
        "pull_intervals": channel_service.PULL_INTERVALS,
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
            except YouTubeAPIError as exc:
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


@app.post("/sync")
def trigger_sync(request: Request, force: str = Form("")) -> Response:
    forced = bool(force)
    already = sync_service.is_running()
    if not already:
        threading.Thread(
            target=sync_service.run_sync, args=("manual",), kwargs={"force": forced}, daemon=True
        ).start()

    if already:
        message = "A sync is already running."
    elif forced:
        message = "Forced sync started — every channel is being polled, minimum gaps ignored."
    else:
        message = "Sync started."

    if is_htmx(request):
        # Report it as running straight away: the worker thread may not have
        # taken the lock yet, and a button that flickers back to idle lies.
        return fragment(
            request,
            "_sync_controls.html",
            {"sync_running": True, "last_run_id": _last_run_id()},
            ok=message,
        )
    return redirect("/", ok=message)


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


@app.get("/partials/channels", response_class=HTMLResponse)
def partial_channels(request: Request, feed: str = "", track: str = "", q: str = "") -> HTMLResponse:
    owner = owner_of(request)
    with session_scope() as session:
        context = _channel_list_context(session, feed, tracking=track == "1", query=q, owner=owner)
    return fragment(request, "_channel_list.html", context)


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
        }
    return render(request, "channels.html", context)


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
    if not is_htmx(request):
        params = {
            k: v
            for k, v in (("feed", feed), ("q", query), ("track", "1" if tracking else ""))
            if v
        }
        target = f"/channels?{urlencode(params)}" if params else "/channels"
        return redirect(target, ok=ok, err=err)
    with session_scope() as session:
        context = _channel_list_context(session, feed, tracking=tracking, query=query, owner=owner)
    return fragment(request, "_channel_list.html", context, ok=ok, err=err)


@app.post("/channels/add")
def add_channel(
    request: Request,
    reference: str = Form(""),
    feeds: list[int] = Form(default=[]),
    backfill: str = Form(""),
    feed: str = Form(""),
) -> Response:
    owner = owner_of(request)
    reference = reference.strip()
    if not reference:
        # Keep the dialog up rather than dropping what they were doing.
        return _channel_list_response(
            request, err="Paste a channel URL, @handle, or UC… id.", feed=feed, tracking=True
        )

    with session_scope() as session, _http_client() as http:
        try:
            channel = channel_service.add_channel(
                session,
                reference,
                http,
                backfill_days=channel_service.parse_backfill(backfill),
                owner=owner,
            )
        except channel_service.ChannelError as exc:
            return _channel_list_response(request, err=str(exc), feed=feed, tracking=True)

        playlist_service.set_channel_targets(session, channel, feeds)
        title = channel.title
        watching = channel.enabled

    message = f"Now watching {title}."
    if not watching:
        message = f"Added {title}. It stays paused until a feed is linked."
    return _channel_list_response(request, ok=message, feed=feed)


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
            "pull_intervals": channel_service.PULL_INTERVALS,
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


@app.post("/channels/{channel_id}")
def save_channel(
    channel_id: int,
    title_include: str = Form(""),
    title_exclude: str = Form(""),
    min_duration_sec: str = Form(""),
    max_duration_sec: str = Form(""),
    max_per_run: str = Form(""),
    skip_shorts: str = Form(""),
    skip_live: str = Form(""),
    playlists: list[int] = Form(default=[]),
) -> RedirectResponse:
    with session_scope() as session:
        channel = session.get(Channel, channel_id)
        if channel is None:
            return redirect("/channels", err="That channel is no longer being watched.")
        playlist_service.set_channel_targets(session, channel, playlists)
        try:
            requeued = channel_service.update_filters(
                session,
                channel,
                {
                    "title_include": title_include,
                    "title_exclude": title_exclude,
                    "min_duration_sec": min_duration_sec,
                    "max_duration_sec": max_duration_sec,
                    "max_per_run": max_per_run,
                    "skip_shorts": skip_shorts,
                    "skip_live": skip_live,
                },
            )
        except channel_service.ChannelError as exc:
            return redirect(f"/channels/{channel_id}", err=str(exc))
    message = "Saved."
    if requeued:
        message += f" {requeued} previously skipped video{'s' if requeued != 1 else ''} queued."
    return redirect(f"/channels/{channel_id}", ok=message)


@app.post("/channels/{channel_id}/toggle")
def toggle_channel(request: Request, channel_id: int, feed: str = Form("")) -> Response:
    with session_scope() as session:
        channel = session.get(Channel, channel_id)
        if channel is None:
            return _channel_list_response(request, err="That channel is no longer being watched.", feed=feed)
        channel.enabled = not channel.enabled
        message = f"{channel.title} {'resumed' if channel.enabled else 'paused'}."
    return _channel_list_response(request, ok=message, feed=feed)


def _toggle_filter_response(
    request: Request, channel_id: int, feed: str, *, kind: str, back: str = ""
) -> Response:
    """One-click filter toggles, so they do not live only inside a save form."""
    with session_scope() as session:
        channel = session.get(Channel, channel_id)
        if channel is None:
            return _channel_list_response(
                request, err="That channel is no longer being watched.", feed=feed, back=back
            )
        if kind == "shorts":
            include = channel.skip_shorts  # flipping it on
            requeued = channel_service.set_shorts(session, channel, include=include)
            noun, plural = "Short", "Shorts"
        elif kind == "live":
            include = channel.skip_live
            requeued = channel_service.set_live(session, channel, include=include)
            noun, plural = "live stream or premiere", "live streams and premieres"
        elif kind == "posts":
            include = channel.skip_posts
            requeued = channel_service.set_posts(session, channel, include=include)
            noun, plural = "community post", "community posts"
        else:
            include = channel.skip_videos
            requeued = channel_service.set_videos(session, channel, include=include)
            noun, plural = "regular video", "regular videos"
        title = channel.title
        takes_nothing = channel.takes_nothing

    if include:
        message = f"Including {plural} from {title}."
        if requeued:
            message += (
                f" {requeued} previously skipped {noun if requeued == 1 else plural} queued."
            )
    else:
        message = f"Skipping {plural} from {title}. Anything already in a playlist stays put."
        if takes_nothing:
            message += " Nothing from this channel will be added now — every kind is off."
    return _channel_list_response(request, ok=message, feed=feed, back=back)


@app.post("/channels/{channel_id}/shorts")
def toggle_channel_shorts(
    request: Request, channel_id: int, feed: str = Form(""), back: str = Form("")
) -> Response:
    return _toggle_filter_response(request, channel_id, feed, kind="shorts", back=back)


@app.post("/channels/{channel_id}/live")
def toggle_channel_live(
    request: Request, channel_id: int, feed: str = Form(""), back: str = Form("")
) -> Response:
    return _toggle_filter_response(request, channel_id, feed, kind="live", back=back)


@app.post("/channels/{channel_id}/posts")
def toggle_channel_posts(
    request: Request, channel_id: int, feed: str = Form(""), back: str = Form("")
) -> Response:
    return _toggle_filter_response(request, channel_id, feed, kind="posts", back=back)


@app.post("/channels/{channel_id}/videos")
def toggle_channel_videos(
    request: Request, channel_id: int, feed: str = Form(""), back: str = Form("")
) -> Response:
    return _toggle_filter_response(request, channel_id, feed, kind="videos", back=back)


@app.post("/channels/{channel_id}/interval")
def set_channel_interval(
    request: Request,
    channel_id: int,
    minutes: str = Form("0"),
    feed: str = Form(""),
    back: str = Form(""),
) -> Response:
    """The shortest gap between feed checks for one channel."""
    try:
        value = max(0, int(minutes))
    except ValueError:
        return _channel_list_response(
            request, err="That is not a number of minutes.", feed=feed, back=back
        )

    with session_scope() as session:
        channel = session.get(Channel, channel_id)
        if channel is None:
            return _channel_list_response(
                request, err="That channel is no longer being watched.", feed=feed, back=back
            )
        channel_service.set_pull_interval(session, channel, value)
        title = channel.title
        described = channel_service.describe_interval(value)
    return _channel_list_response(
        request, ok=f"Checking {title} {described}.", feed=feed, back=back
    )


@app.post("/channels/{channel_id}/move")
def move_channel(request: Request, channel_id: int, direction: str = Form("up"), feed: str = Form("")) -> Response:
    with session_scope() as session:
        moved = ordering_service.move_channel(session, channel_id, direction)
    if not moved:
        return _channel_list_response(request, feed=feed)
    return _channel_list_response(request, feed=feed)


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
    session: Session, *, playlist: str = "", query: str = "", owner: OwnerId = None
) -> Context:
    """What is in each feed right now, each laid out the way that feed asks."""
    wanted = int(playlist) if playlist.isdigit() else None

    playlists = [p for p in playlist_service.list_playlists(session, owner) if p.enabled or wanted]
    terms = query.lower().split()
    if terms:
        # Name or tag, any order, partial words.
        playlists = [p for p in playlists if all(term in p.searchable for term in terms)]
    sections = []
    for target in playlists:
        if wanted and target.id != wanted:
            continue
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
        sections.append({"playlist": target, "videos": videos, "total": total})

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
        context = _feed_context(session, playlist=playlist, query=q, owner=owner)
    return render(request, "feed.html", context)


@app.get("/partials/feed", response_class=HTMLResponse)
def partial_feed(request: Request, playlist: str = "", q: str = "") -> HTMLResponse:
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
            context = _feed_context(session, playlist=playlist, query=q, owner=owner)
        return fragment(request, "_feed_sections.html", context)
    return redirect(f"/feed?{urlencode({'playlist': playlist, 'q': q})}")


def _focus_item(video: Video, playlist_title: str = "") -> Context:
    """One entry in the Focus queue, video or community post alike."""
    return {
        "id": video.id,
        "video_id": video.video_id,
        "kind": video.kind,
        "title": video.title or video.video_id,
        "channel": video.channel.title,
        "playlist": playlist_title,
        "duration": format_duration(video.duration_sec),
        "thumbnail": video.thumbnail_url,
        # Posts carry their whole content: there is no player to fetch it.
        "body": video.body or "",
        "images": video.image_list,
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
    if not is_htmx(request):
        target = "/channels?new=1" if creating else "/channels"
        return redirect(target, ok=ok, err=err)
    with session_scope() as session:
        context = _playlist_context(session, creating=creating, owner=owner)
    return fragment(request, "_playlist_targets.html", context, ok=ok, err=err)


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
            # Keep the dialog open with what they typed still on screen.
            return _playlists_response(request, err=str(exc), creating=True)
        title = playlist.title

    _forget_account_playlists()
    message = f"Now feeding {title!r}."
    if linked:
        message += f" {linked} channel{'s' if linked != 1 else ''} linked."
    return _playlists_response(request, ok=message)


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


@app.post("/settings/playlists/{playlist_pk}/move")
def move_playlist(
    request: Request, playlist_pk: int, direction: str = Form("up"), back: str = Form("")
) -> Response:
    with session_scope() as session:
        ordering_service.move_playlist(session, playlist_pk, direction)
    return _playlists_response(request, back=back)


@app.get("/partials/playlists", response_class=HTMLResponse)
def partial_playlists(request: Request, new: str = "") -> HTMLResponse:
    owner = owner_of(request)
    with session_scope() as session:
        context = _playlist_context(session, creating=new == "1", owner=owner)
    return fragment(request, "_playlist_targets.html", context)


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
            account = client.my_channel_title()
        except YouTubeAPIError:
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


# -- the admin's tab ------------------------------------------------------


def _admin_context(session: Session) -> Context:
    return {
        "users": accounts.list_users(session),
        "admin_user": CONFIG.admin_user,
        "session_days": CONFIG.session_days,
        "min_password": accounts.MIN_PASSWORD_LENGTH,
        "min_passphrase": migration.MIN_PASSPHRASE,
    }


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
