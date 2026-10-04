"""The Feed page: every feed's latest, and how each is shown."""

from __future__ import annotations

import datetime as dt
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ...db import session_scope
from ...models import (
    GraphNode,
    Placement,
    Playlist,
    Video,
    utcnow,
)
from ...services import graph as graph_service
from ...services import playlists as playlist_service
from ...services import watched as watched_service
from ...services.scope import OwnerId, owned
from ..contexts import feed_window_words
from ..responses import fragment, is_htmx, owner_of, redirect, render
from ..templates import Context

router = APIRouter()


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
    sections = [
        _section(session, target, owner, windows.get(target.id, []), now=now, sitting=sitting)
        for target in playlists
        if not wanted or target.id == wanted
    ]

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


def _section(
    session: Session,
    target: Playlist,
    owner: OwnerId,
    opens: list[GraphNode],
    *,
    now: dt.datetime,
    sitting: bool,
) -> Context:
    """One feed's part of the page: what is in it, or why it is shut."""
    # A feed with a Reset slotted under it is only read while that window is
    # open. Shown as shut rather than hidden: a feed that vanished would read
    # as a feed that had gone.
    if opens:
        state = graph_service.window_state(opens, now)
        if not state.open:
            return {
                "playlist": target,
                "videos": [],
                "total": 0,
                "shut": feed_window_words(opens),
                "opens_at": state.opens_at,
                "expiring": {},
            }
        if sitting:
            graph_service.begin_sitting(session, state, now)
    return {
        "playlist": target,
        "videos": _shown(session, target, owner),
        "total": _held(session, target),
        "shut": [],
        "opens_at": None,
        "expiring": _expiring(session, target),
    }


def _shown(session: Session, target: Playlist, owner: OwnerId) -> list[Video]:
    """What the feed shows, in the order it asks for."""
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
    return list(session.scalars(statement.order_by(direction, Video.id.asc())))


def _held(session: Session, target: Playlist) -> int:
    """How many the feed holds, watched or not."""
    return (
        session.scalar(
            select(func.count(Placement.id)).where(
                Placement.playlist_pk == target.id, Placement.playlist_item_id.is_not(None)
            )
        )
        or 0
    )


def _expiring(session: Session, target: Playlist) -> dict[int, dt.datetime]:
    """When an Expire box takes each item out of *this* feed.

    Per feed rather than per item: the same video in two feeds may have two
    different answers, and the one that matters here is this one's.
    """
    return {
        video_pk: when
        for video_pk, when in session.execute(
            select(Placement.video_pk, Placement.expires_at).where(
                Placement.playlist_pk == target.id,
                Placement.expires_at.is_not(None),
                Placement.removed_at.is_(None),
            )
        )
    }


@router.get("/feed", response_class=HTMLResponse)
def feed_page(request: Request, playlist: str = "", q: str = "") -> HTMLResponse:
    """The Feed page. Opening it starts a reading window's sitting."""
    owner = owner_of(request)
    with session_scope() as session:
        context = _feed_context(session, playlist=playlist, query=q, owner=owner, sitting=True)
    return render(request, "feed.html", context)


@router.get("/partials/feed", response_class=HTMLResponse)
def partial_feed(request: Request, playlist: str = "", q: str = "") -> HTMLResponse:
    """The sections again after a sync landed. Not a sitting: nobody arrived,
    the page they were already on caught up."""
    owner = owner_of(request)
    with session_scope() as session:
        context = _feed_context(session, playlist=playlist, query=q, owner=owner)
    return fragment(request, "_feed_sections.html", context)


@router.post("/feeds/{playlist_pk}/view")
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


@router.post("/feeds/{playlist_pk}/clear")
def clear_feed(
    request: Request, playlist_pk: int, playlist: str = Form(""), q: str = Form("")
) -> Response:
    """Empty one feed, from the button on its section."""
    owner = owner_of(request)
    result = watched_service.clear_feed(playlist_pk, owner)
    ok, err = (result.message, None) if result.ok else (None, result.message)
    if is_htmx(request):
        with session_scope() as session:
            context = _feed_context(session, playlist=playlist, query=q, owner=owner)
        return fragment(request, "_feed_sections.html", context, ok=ok, err=err)
    return redirect(f"/feed?{urlencode({'playlist': playlist, 'q': q})}", ok=ok, err=err)
