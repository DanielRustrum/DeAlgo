"""Focus mode: one item at a time."""

from __future__ import annotations

import json

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ... import sources
from ...db import get_settings, session_scope
from ...models import (
    Placement,
    Video,
)
from ...services import playlists as playlist_service
from ...services import watched as watched_service
from ...services.filters import format_duration
from ...services.scope import OwnerId, owned
from ..responses import owner_of, redirect, render
from ..templates import Context

router = APIRouter()


def _focus_item(video: Video, playlist_title: str = "") -> Context:
    """One entry in the Focus queue: a video, a community post, or an item
    from a feed somewhere else. The last two are read rather than played, and
    differ only in what the link out is called."""
    described = sources.describe(video.channel.source_kind)
    return {
        "id": video.id,
        "video_id": video.video_id,
        "kind": video.kind,
        # Which built-in player plays it, as its source's plugin chose: "" for
        # anything read rather than played.
        "player": described.player if video.kind == "video" else "",
        # Where it came from, said the way a person would say it, so the page
        # can offer "Open it on Reddit" without knowing the list of kinds.
        "source": described.label,
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
        # What a Decay box on its way here said. Null means the account's own
        # setting, which is what everything that never met one uses.
        "seconds": video.view_seconds,
        # And whether a Lock under that box said the time cannot be held.
        "locked": video.view_locked,
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


@router.get("/focus", response_class=HTMLResponse)
def focus(request: Request, order: str = "oldest", playlist: str = "", start: str = "") -> HTMLResponse:
    """Focus mode: the queue of unwatched items, one at a time."""
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


@router.get("/watch")
def watch_moved(order: str = "oldest", playlist: str = "", start: str = "") -> RedirectResponse:
    """Theater mode's old address. Links and bookmarks outlive renames."""
    return redirect(f"/focus?order={order}&playlist={playlist}&start={start}")


# How much of the queue travels back with each advance. Enough to fill the
# "up next" list without shipping a thousand-video feed on every click.
UPCOMING_SHOWN = 40


@router.post("/focus/{video_id}/finished")
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
