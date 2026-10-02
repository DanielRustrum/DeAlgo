"""The raw list of every item, and what can be done to one."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from ...db import get_token, session_scope
from ...models import (
    Channel,
    Placement,
    Playlist,
    Video,
)
from ...services import channels as channel_service
from ...services import sync as sync_service
from ...services import watched as watched_service
from ...services.scope import owned
from ..responses import fragment, is_htmx, newest_run_id, owner_of, redirect, render

if TYPE_CHECKING:
    pass

router = APIRouter()


@router.get("/videos", response_class=HTMLResponse)
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


@router.post("/videos/{video_id}/requeue")
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


@router.post("/videos/{video_id}/watched")
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


@router.post("/videos/{video_id}/unwatched")
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


@router.post("/playlist/mark-all-watched")
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
            {"sync_running": sync_service.is_running(), "last_run_id": newest_run_id()},
            ok=message,
            headers={"HX-Trigger": "dealgo:watched-changed"},
        )
    return redirect("/videos?watched=1", ok=message)


@router.post("/playlist/remove-watched")
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
                {"sync_running": sync_service.is_running(), "last_run_id": newest_run_id()},
                err=blocker,
            )
        return redirect("/videos?watched=1", err=blocker)

    if not removable:
        message = "No watched videos are in the playlist."
        if is_htmx(request):
            return fragment(
                request,
                "_sync_controls.html",
                {"sync_running": sync_service.is_running(), "last_run_id": newest_run_id()},
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
            {"sync_running": True, "last_run_id": newest_run_id()},
            ok=message,
        )
    return redirect("/videos?watched=1", ok=message)


@router.post("/videos/{video_id}/ignore")
def ignore_video(request: Request, video_id: int, back: str = Form("/videos")) -> Response:
    with session_scope() as session:
        video = session.get(Video, video_id)
        if video is None:
            return redirect(back, err="That video is no longer tracked.")
        video.status = "ignored"
        video.reason = "ignored by hand"
        title = video.title
    return _video_row_response(request, video_id, ok=f"Ignoring {title!r}.", back=back)
