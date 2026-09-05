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
from urllib.parse import urlencode

import httpx
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from .. import __version__, scheduler
from ..config import CONFIG
from ..db import get_settings, get_token, init_db, session_scope
from ..models import Channel, Placement, Playlist, SyncRun, Video
from ..services import backup as backup_service
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
from ..youtube.api import YouTubeAPIError

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
async def lifespan(app: FastAPI):
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
TEMPLATES.env.filters["duration"] = format_duration


def _last_run_id() -> int:
    with session_scope() as session:
        return session.scalar(select(func.max(SyncRun.id))) or 0


def render(request: Request, template: str, context: dict) -> HTMLResponse:
    context = {
        "version": __version__,
        "asset_version": ASSET_VERSION,
        "ok_message": request.query_params.get("ok"),
        "error_message": request.query_params.get("err"),
        "sync_running": sync_service.is_running(),
        "last_run_id": _last_run_id(),
        **context,
    }
    return TEMPLATES.TemplateResponse(request, template, context)


def fragment(
    request: Request,
    template: str,
    context: dict,
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


def _quota_context(session) -> dict:
    state = quota_service.state(session)
    return {"quota": state, "quota_resets_in": quota_service.describe_reset()}


def _stats_context(session) -> dict:
    counts = dict(session.execute(select(Video.status, func.count(Video.id)).group_by(Video.status)).all())
    return {
        "counts": counts,
        # "added" means it reached the playlist at some point; this is what is
        # actually in there now, after pruning and watched-removals.
        "in_playlist": session.scalar(
            select(func.count(func.distinct(Placement.video_pk))).where(
                Placement.playlist_item_id.is_not(None)
            )
        )
        or 0,
        "watched_count": watched_service.count_watched(session),
        "removable_count": watched_service.count_removable(session),
        "enabled_channels": session.scalar(
            select(func.count(Channel.id)).where(Channel.enabled.is_(True))
        )
        or 0,
    }


def _activity_context(session) -> dict:
    return {
        "recent_runs": list(session.scalars(select(SyncRun).order_by(SyncRun.started_at.desc()).limit(8))),
        "recent_videos": list(
            session.scalars(
                select(Video)
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


def _channel_list_context(session, feed: str = "") -> dict:
    def counts_by_channel(*conditions) -> dict:
        return dict(
            session.execute(
                select(Video.channel_pk, func.count(Video.id))
                .where(*conditions)
                .group_by(Video.channel_pk)
            ).all()
        )

    channels = channel_service.list_channels(session)
    playlists = playlist_service.list_playlists(session)
    counts_by_feed = {p.id: sum(1 for c in channels if p in c.playlists) for p in playlists}
    unassigned = sum(1 for c in channels if not c.playlists)

    if feed == "none":
        channels = [c for c in channels if not c.playlists]
    elif feed.isdigit():
        wanted = int(feed)
        channels = [c for c in channels if any(p.id == wanted for p in c.playlists)]
    else:
        feed = ""

    return {
        "channels": channels,
        "pull_intervals": channel_service.PULL_INTERVALS,
        "feed": feed,
        "feed_playlists": playlists,
        "counts_by_feed": counts_by_feed,
        "unassigned_count": unassigned,
        "total_channels": session.scalar(select(func.count(Channel.id))) or 0,
        "pending_by_channel": counts_by_channel(Video.status == "pending"),
        "added_by_channel": dict(
            session.execute(
                select(Video.channel_pk, func.count(func.distinct(Placement.video_pk)))
                .join(Placement, Placement.video_pk == Video.id)
                .where(Placement.playlist_item_id.is_not(None))
                .group_by(Video.channel_pk)
            ).all()
        ),
    }


_ACCOUNT_PLAYLIST_TTL = 120.0
_account_playlists_cache: dict = {"at": 0.0, "items": [], "error": None}


def _account_playlists(session, *, refresh: bool = False) -> tuple[list, str | None]:
    """The playlists on the connected account, cached for a couple of minutes."""
    now = time.monotonic()
    fresh = now - _account_playlists_cache["at"] < _ACCOUNT_PLAYLIST_TTL
    if fresh and not refresh:
        return _account_playlists_cache["items"], _account_playlists_cache["error"]

    items: list = []
    error = None
    with _http_client() as http:
        client = build_client(session, http)
        if client.has_write_access:
            try:
                items = client.my_playlists()
            except YouTubeAPIError as exc:
                error = str(exc)
    _account_playlists_cache.update({"at": now, "items": items, "error": error})
    return items, error


def _forget_account_playlists() -> None:
    _account_playlists_cache["at"] = 0.0


def _playlist_context(session, open_pk: str = "", creating: bool = False) -> dict:
    """Everything the targets panel needs, including the account's own lists."""
    state = _connection_state(session)
    available: list = []
    error = None
    if state["connected"]:
        available, error = _account_playlists(session)
    known = {p.playlist_id for p in state["playlists"]}
    return {
        "state": state,
        "targets": state["playlists"],
        "counts": state["playlist_counts"],
        "available": [p for p in available if p.playlist_id not in known],
        "playlist_error": error,
        "all_channels": channel_service.list_channels(session),
        "open_playlist": int(open_pk) if str(open_pk).isdigit() else None,
        "creating": creating,
    }


def _connection_state(session) -> dict:
    token = get_token(session)
    return {
        "connected": token is not None,
        "account": token.account_title if token else None,
        "needs_reconnect": bool(token and token.refresh_error),
        "reconnect_reason": token.refresh_error if token else None,
        "has_client": has_client_credentials(session),
        "playlists": playlist_service.list_playlists(session),
        "playlist_counts": playlist_service.item_counts(session),
        "has_targets": bool(
            session.scalar(select(func.count(Playlist.id)).where(Playlist.enabled.is_(True)))
        ),
    }


# -- dashboard ------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    with session_scope() as session:
        context = {
            **_stats_context(session),
            **_activity_context(session),
            **_quota_context(session),
            "state": _connection_state(session),
            "settings": get_settings(session),
            "next_run": scheduler.next_run_time(),
        }
    return render(request, "dashboard.html", context)


@app.post("/sync")
def trigger_sync(request: Request, force: str = Form("")):
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
def partial_sync_status(request: Request, seen: int = 0):
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
def partial_stats(request: Request):
    with session_scope() as session:
        context = _stats_context(session)
    return fragment(request, "_stats.html", context)


@app.get("/partials/activity", response_class=HTMLResponse)
def partial_activity(request: Request):
    with session_scope() as session:
        context = _activity_context(session)
    return fragment(request, "_activity.html", context)


@app.get("/partials/feed-target", response_class=HTMLResponse)
def partial_feed_target(request: Request):
    with session_scope() as session:
        context = {
            **_stats_context(session),
            **_quota_context(session),
            "state": _connection_state(session),
            "settings": get_settings(session),
            "next_run": scheduler.next_run_time(),
        }
    return fragment(request, "_feed_target.html", context)


@app.get("/partials/channels", response_class=HTMLResponse)
def partial_channels(request: Request, feed: str = ""):
    with session_scope() as session:
        context = _channel_list_context(session, feed)
    return fragment(request, "_channel_list.html", context)


@app.get("/api/status")
def api_status():
    with session_scope() as session:
        run = session.scalar(select(SyncRun).order_by(SyncRun.started_at.desc()))
        counts = dict(
            session.execute(select(Video.status, func.count(Video.id)).group_by(Video.status)).all()
        )
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
def channels_page(request: Request, feed: str = "", open: str = "", new: str = ""):
    with session_scope() as session:
        context = {
            **_channel_list_context(session, feed),
            **_playlist_context(session, open, creating=new == "1"),
        }
    return render(request, "channels.html", context)


def _channel_list_response(
    request: Request, *, ok: str | None = None, err: str | None = None, feed: str = ""
):
    """Every channel mutation answers with the whole list, freshly counted."""
    if not is_htmx(request):
        target = f"/channels?feed={feed}" if feed else "/channels"
        return redirect(target, ok=ok, err=err)
    with session_scope() as session:
        context = _channel_list_context(session, feed)
    return fragment(request, "_channel_list.html", context, ok=ok, err=err)


@app.post("/channels/add")
def add_channel(request: Request, reference: str = Form("")):
    reference = reference.strip()
    if not reference:
        return _channel_list_response(request, err="Paste a channel URL, @handle, or UC… id.")
    with session_scope() as session, _http_client() as http:
        try:
            channel = channel_service.add_channel(session, reference, http)
        except channel_service.ChannelError as exc:
            return _channel_list_response(request, err=str(exc))
        title = channel.title
    return _channel_list_response(request, ok=f"Now watching {title}.")


@app.get("/channels/{channel_id}", response_class=HTMLResponse)
def channel_detail(request: Request, channel_id: int):
    with session_scope() as session:
        channel = session.scalar(
            select(Channel).options(selectinload(Channel.playlists)).where(Channel.id == channel_id)
        )
        if channel is None:
            return redirect("/channels", err="That channel is no longer being watched.")
        videos = list(
            session.scalars(
                select(Video)
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
            "settings": get_settings(session),
            "all_playlists": playlist_service.list_playlists(session),
            "pull_intervals": channel_service.PULL_INTERVALS,
            "channel_playlist_pks": {p.id for p in channel.playlists},
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
):
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
def toggle_channel(request: Request, channel_id: int, feed: str = Form("")):
    with session_scope() as session:
        channel = session.get(Channel, channel_id)
        if channel is None:
            return _channel_list_response(request, err="That channel is no longer being watched.", feed=feed)
        channel.enabled = not channel.enabled
        message = f"{channel.title} {'resumed' if channel.enabled else 'paused'}."
    return _channel_list_response(request, ok=message, feed=feed)


def _toggle_filter_response(
    request: Request, channel_id: int, feed: str, *, kind: str
):
    """One-click filter toggles, so they do not live only inside a save form."""
    with session_scope() as session:
        channel = session.get(Channel, channel_id)
        if channel is None:
            return _channel_list_response(
                request, err="That channel is no longer being watched.", feed=feed
            )
        if kind == "shorts":
            include = channel.skip_shorts  # flipping it on
            requeued = channel_service.set_shorts(session, channel, include=include)
            noun, plural = "Short", "Shorts"
        elif kind == "live":
            include = channel.skip_live
            requeued = channel_service.set_live(session, channel, include=include)
            noun, plural = "live stream or premiere", "live streams and premieres"
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
            message += " Nothing from this channel will be added now — all three are off."
    return _channel_list_response(request, ok=message, feed=feed)


@app.post("/channels/{channel_id}/shorts")
def toggle_channel_shorts(request: Request, channel_id: int, feed: str = Form("")):
    return _toggle_filter_response(request, channel_id, feed, kind="shorts")


@app.post("/channels/{channel_id}/live")
def toggle_channel_live(request: Request, channel_id: int, feed: str = Form("")):
    return _toggle_filter_response(request, channel_id, feed, kind="live")


@app.post("/channels/{channel_id}/videos")
def toggle_channel_videos(request: Request, channel_id: int, feed: str = Form("")):
    return _toggle_filter_response(request, channel_id, feed, kind="videos")


@app.post("/channels/{channel_id}/interval")
def set_channel_interval(
    request: Request, channel_id: int, minutes: str = Form("0"), feed: str = Form("")
):
    """The shortest gap between feed checks for one channel."""
    try:
        value = max(0, int(minutes))
    except ValueError:
        return _channel_list_response(request, err="That is not a number of minutes.", feed=feed)

    with session_scope() as session:
        channel = session.get(Channel, channel_id)
        if channel is None:
            return _channel_list_response(
                request, err="That channel is no longer being watched.", feed=feed
            )
        channel_service.set_pull_interval(session, channel, value)
        title = channel.title
        described = channel_service.describe_interval(value)
    return _channel_list_response(request, ok=f"Checking {title} {described}.", feed=feed)


@app.post("/channels/{channel_id}/move")
def move_channel(request: Request, channel_id: int, direction: str = Form("up"), feed: str = Form("")):
    with session_scope() as session:
        moved = ordering_service.move_channel(session, channel_id, direction)
    if not moved:
        return _channel_list_response(request, feed=feed)
    return _channel_list_response(request, feed=feed)


@app.post("/channels/{channel_id}/delete")
def remove_channel(request: Request, channel_id: int, feed: str = Form("")):
    with session_scope() as session:
        channel = session.get(Channel, channel_id)
        if channel is None:
            return _channel_list_response(request, err="That channel is no longer being watched.", feed=feed)
        title = channel.title
        channel_service.delete_channel(session, channel)
    return _channel_list_response(request, ok=f"Stopped watching {title}.", feed=feed)


# -- feed -----------------------------------------------------------------


def _feed_context(session, *, order: str, show: str, playlist: str) -> dict:
    """What is in each playlist right now, grouped and ready to watch."""
    order = "newest" if order == "newest" else "oldest"
    show = "all" if show == "all" else "unwatched"
    wanted = int(playlist) if playlist.isdigit() else None

    playlists = [p for p in playlist_service.list_playlists(session) if p.enabled or wanted]
    sections = []
    for target in playlists:
        if wanted and target.id != wanted:
            continue
        query = (
            select(Video)
            .join(Placement, Placement.video_pk == Video.id)
            .options(selectinload(Video.channel))
            .where(Placement.playlist_pk == target.id, Placement.playlist_item_id.is_not(None))
        )
        if show == "unwatched":
            query = query.where(Video.watched_at.is_(None))
        direction = Video.published_at.desc() if order == "newest" else Video.published_at.asc()
        videos = list(session.scalars(query.order_by(direction, Video.id.asc())))

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
        "order": order,
        "show": show,
        "playlist_filter": wanted,
        "all_playlists": playlist_service.list_playlists(session),
        "feed_query": urlencode({"order": order, "show": show, "playlist": playlist or ""}),
    }


@app.get("/feed", response_class=HTMLResponse)
def feed_page(request: Request, order: str = "oldest", show: str = "unwatched", playlist: str = ""):
    with session_scope() as session:
        context = _feed_context(session, order=order, show=show, playlist=playlist)
    return render(request, "feed.html", context)


@app.get("/partials/feed", response_class=HTMLResponse)
def partial_feed(request: Request, order: str = "oldest", show: str = "unwatched", playlist: str = ""):
    with session_scope() as session:
        context = _feed_context(session, order=order, show=show, playlist=playlist)
    return fragment(request, "_feed_sections.html", context)


def _watch_queue(session, *, order: str, playlist: str, start: int | None = None) -> list[dict]:
    """The unwatched videos to play through, flattened across playlists.

    Rebuilt from the database on every advance rather than trusted from the
    browser, so a queue left open overnight cannot resurrect a video that has
    since been watched or removed.
    """
    order = "newest" if order == "newest" else "oldest"
    wanted = int(playlist) if playlist.isdigit() else None
    direction = Video.published_at.desc() if order == "newest" else Video.published_at.asc()

    queue: list[dict] = []
    seen: set[int] = set()
    for target in playlist_service.list_playlists(session):
        if not target.enabled or (wanted and target.id != wanted):
            continue
        videos = session.scalars(
            select(Video)
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
            queue.append(
                {
                    "id": video.id,
                    "video_id": video.video_id,
                    "title": video.title or video.video_id,
                    "channel": video.channel.title,
                    "playlist": target.title,
                    "duration": format_duration(video.duration_sec),
                    "thumbnail": video.thumbnail_url,
                }
            )

    if start is not None:
        at = next((i for i, item in enumerate(queue) if item["id"] == start), None)
        if at is not None:
            queue = queue[at:]
        else:
            # Starting from something already watched: play it, then carry on.
            video = session.scalar(
                select(Video).options(selectinload(Video.channel)).where(Video.id == start)
            )
            if video is not None:
                queue.insert(
                    0,
                    {
                        "id": video.id,
                        "video_id": video.video_id,
                        "title": video.title or video.video_id,
                        "channel": video.channel.title,
                        "playlist": "",
                        "duration": format_duration(video.duration_sec),
                        "thumbnail": video.thumbnail_url,
                    },
                )
    return queue


@app.get("/watch", response_class=HTMLResponse)
def theater(request: Request, order: str = "oldest", playlist: str = "", start: str = ""):
    start_id = int(start) if start.isdigit() else None
    with session_scope() as session:
        queue = _watch_queue(session, order=order, playlist=playlist, start=start_id)
        context = {
            "queue": queue,
            "queue_json": json.dumps(queue),
            "order": "newest" if order == "newest" else "oldest",
            "playlist": playlist,
            "playlist_title": next(
                (p.title for p in playlist_service.list_playlists(session) if str(p.id) == playlist),
                None,
            ),
        }
    return render(request, "theater.html", context)


@app.post("/watch/{video_id}/finished")
def theater_finished(
    request: Request,
    video_id: int,
    order: str = Form("oldest"),
    playlist: str = Form(""),
    watched: str = Form("1"),
):
    """Called by the player when a video ends, or when someone skips."""
    with session_scope() as session:
        video = session.get(Video, video_id)
        if video is None:
            return JSONResponse({"error": "unknown video"}, status_code=404)
        if watched == "1":
            watched_service.mark_watched(session, [video_id])

    with session_scope() as session:
        queue = _watch_queue(session, order=order, playlist=playlist)
        # A skipped video stays unwatched, so drop it from this sitting only.
        queue = [item for item in queue if item["id"] != video_id]
    return JSONResponse({"next": queue[0] if queue else None, "remaining": len(queue)})


@app.get("/partials/player/{video_id}", response_class=HTMLResponse)
def partial_player(request: Request, video_id: int):
    """Swap a thumbnail for an embedded player, so watching stays on the page."""
    with session_scope() as session:
        video = session.get(Video, video_id)
        if video is None:
            return HTMLResponse("", status_code=404)
        context = {"video": video}
    return fragment(request, "_player.html", context)


# -- videos ---------------------------------------------------------------


@app.get("/videos", response_class=HTMLResponse)
def videos_page(request: Request, status: str = "", watched: str = "", channel: str = "", page: int = 1):
    page_size = 60
    page = max(1, page)
    with session_scope() as session:
        query = select(Video)
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
        counts = dict(
            session.execute(select(Video.status, func.count(Video.id)).group_by(Video.status)).all()
        )
        context = {
            "videos": videos,
            "counts": counts,
            "watched_count": watched_service.count_watched(session),
            "removable_count": watched_service.count_removable(session),
            "status": "" if watched == "1" else status,
            "watched": watched,
            "channel_filter": channel_pk,
            "channels": channel_service.list_channels(session),
            "page": page,
            "pages": max(1, -(-total // page_size)),
            "total": total,
        }
    return render(request, "videos.html", context)


def _video_row_response(
    request: Request,
    video_id: int,
    *,
    ok=None,
    err=None,
    back="/videos",
    watched_changed=False,
    view: str = "list",
):
    if not is_htmx(request):
        return redirect(back, ok=ok, err=err)
    # Panels that count watched videos listen for this and re-render themselves.
    headers = {"HX-Trigger": "dealgo:watched-changed"} if watched_changed else None
    template = "_feed_card.html" if view == "feed" else "_video_row.html"
    with session_scope() as session:
        video = session.scalar(
            select(Video)
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
def requeue_video(request: Request, video_id: int, back: str = Form("/videos")):
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
def mark_video_watched(request: Request, video_id: int, back: str = Form("/videos"), view: str = Form("list")):
    with session_scope() as session:
        video = session.get(Video, video_id)
        if video is None:
            return redirect(back, err="That video is no longer tracked.")
        watched_service.mark_watched(session, [video_id])
        title = video.title
    return _video_row_response(
        request, video_id, ok=f"Marked {title!r} watched.", back=back, watched_changed=True, view=view
    )


@app.post("/videos/{video_id}/unwatched")
def mark_video_unwatched(request: Request, video_id: int, back: str = Form("/videos"), view: str = Form("list")):
    with session_scope() as session:
        video = session.get(Video, video_id)
        if video is None:
            return redirect(back, err="That video is no longer tracked.")
        watched_service.mark_unwatched(session, [video_id])
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
def mark_all_watched(request: Request):
    with session_scope() as session:
        changed = watched_service.mark_all_in_playlist_watched(session)
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
def remove_watched(request: Request):
    """Clear watched videos out of the playlist, on the user's instruction."""
    with session_scope() as session:
        removable = watched_service.count_removable(session)
        connected = get_token(session) is not None
        feeds = list(session.scalars(select(Playlist).where(Playlist.enabled.is_(True))))
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
    threading.Thread(target=watched_service.remove_watched, args=("manual",), daemon=True).start()
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
def ignore_video(request: Request, video_id: int, back: str = Form("/videos")):
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
def settings_page(request: Request):
    with session_scope() as session:
        context = {
            **_quota_context(session),
            "state": _connection_state(session),
            "settings": get_settings(session),
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
    daily_quota: str = Form("10000"),
    quota_reserve: str = Form("0"),
    auto_sync: str = Form(""),
    client_id: str = Form(""),
    client_secret: str = Form(""),
    api_key: str = Form(""),
):
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
        settings.daily_quota = as_int(daily_quota, 10000)
        settings.quota_reserve = as_int(quota_reserve, 0)
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
    open_pk: str = "",
    creating: bool = False,
):
    if not is_htmx(request):
        params = {k: v for k, v in (("open", open_pk), ("new", "1" if creating else "")) if v}
        target = f"/channels?{urlencode(params)}" if params else "/channels"
        return redirect(target, ok=ok, err=err)
    with session_scope() as session:
        context = _playlist_context(session, open_pk, creating=creating)
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
):
    """Set up a feed in one step: the playlist, then what fills it."""
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
    enabled: str = Form(""),
):
    with session_scope() as session:
        playlist = session.get(Playlist, playlist_pk)
        if playlist is None:
            return _playlists_response(request, err="That playlist is no longer a target.")
        try:
            playlist_service.update(
                session,
                playlist,
                {"max_items": max_items, "max_per_run": max_per_run, "enabled": enabled},
            )
        except playlist_service.PlaylistError as exc:
            return _playlists_response(request, err=str(exc))
        title = playlist.title
    return _playlists_response(request, ok=f"Saved {title!r}.")


@app.post("/settings/playlists/{playlist_pk}/delete")
def delete_playlist(request: Request, playlist_pk: int):
    with session_scope() as session:
        playlist = session.get(Playlist, playlist_pk)
        if playlist is None:
            return _playlists_response(request, err="That playlist is no longer a target.")
        title = playlist.title
        playlist_service.remove(session, playlist)
    _forget_account_playlists()
    return _playlists_response(
        request, ok=f"Stopped feeding {title!r}. The playlist itself is untouched on YouTube."
    )


@app.post("/settings/playlists/{playlist_pk}/move")
def move_playlist(request: Request, playlist_pk: int, direction: str = Form("up")):
    with session_scope() as session:
        ordering_service.move_playlist(session, playlist_pk, direction)
    return _playlists_response(request)


@app.get("/partials/playlists", response_class=HTMLResponse)
def partial_playlists(request: Request, open: str = "", new: str = ""):
    with session_scope() as session:
        context = _playlist_context(session, open, creating=new == "1")
    return fragment(request, "_playlist_targets.html", context)


@app.post("/settings/playlists/{playlist_pk}/channels")
def set_feed_membership(
    request: Request,
    playlist_pk: int,
    channel_id: int = Form(...),
    include: str = Form("1"),
    open: str = Form(""),
):
    """Add or remove one channel from one feed, straight from the feed row."""
    with session_scope() as session:
        playlist = session.get(Playlist, playlist_pk)
        if playlist is None:
            return _playlists_response(request, err="That feed is no longer a target.", open_pk=open)
        try:
            title = playlist_service.set_membership(
                session, playlist, channel_id, include=include == "1"
            )
        except playlist_service.PlaylistError as exc:
            return _playlists_response(request, err=str(exc), open_pk=open)
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
    return _playlists_response(request, ok=message, open_pk=open)


# -- oauth ----------------------------------------------------------------


@app.get("/oauth/start")
def oauth_start(request: Request):
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
def oauth_callback(code: str = "", state: str = "", error: str = ""):
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

        store_token(session, token)
        client = build_client(session, http)
        try:
            account = client.my_channel_title()
        except YouTubeAPIError:
            account = None
        if account:
            store_token(session, token, account_title=account)
    return redirect("/settings", ok="Google account connected.")


@app.post("/oauth/disconnect")
def oauth_disconnect():
    with session_scope() as session, _http_client() as http:
        disconnect(session, http)
    return redirect("/settings", ok="Google account disconnected.")


@app.get("/settings/backup")
def download_backup(request: Request):
    """The setup, as a JSON file the browser saves."""
    with session_scope() as session:
        data = backup_service.build_export(session)
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
def restore_backup(request: Request, backup_file: UploadFile = File(...)):
    """Load a backup file back in, matching rows by their YouTube ids."""
    raw = backup_file.file.read()
    if len(raw) > 32 * 1024 * 1024:
        return redirect("/settings", err="That file is too large to be a De-Algo backup.")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return redirect("/settings", err="That file is not readable JSON.")

    with session_scope() as session:
        try:
            summary = backup_service.restore(session, payload)
        except backup_service.RestoreError as exc:
            return redirect("/settings", err=str(exc))
        message = summary.describe()
        if summary.skipped:
            message += f" {len(summary.skipped)} video(s) skipped: their channel was not in the file."

    scheduler.reschedule()
    return redirect("/settings", ok=message)


@app.get("/healthz")
def healthz():
    return {"status": "ok", "version": __version__, "syncing": sync_service.is_running()}
